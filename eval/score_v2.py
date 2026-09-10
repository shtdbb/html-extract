#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
score_v2.py — 离线库 HTML 结构化提取 · 评测器 v2（冻结版）

唯一实现依据：eval_spec_v2.md（与本文件绑定冻结，见规范 §9）。
算术与 eval/handcheck_draft.py 验算稿一致；13 场景 46 断言由
eval/test_score_v2.py 覆盖。

用法：
    python score_v2.py --pred predictions.jsonl --gold gold.json --out scores.json

输入格式
--------
gold.json：{"pages": [记录]}（顶层直接是列表也可）。每页记录：
    id                页面 id（与 pred 对齐的键）
    dataset           数据集名（dev / test / ispras_en ...），缺省 "unknown"
    site              站点名，缺省 "unknown"
    route             路由层（fixed / generic），缺省取 site
    content_structure single / multi_article / photo_set / live_blog / list_page ...
    page_condition    ok / empty_shell / anti_bot_suspected / truncated
    title             字符串 | null
    authors           列表 | null
    publish_time / update_time / 任意 *_time：
                      {"value": "YYYY-MM-DD hh:mm:ss（XX 占位）", "utc_offset": "+08:00"|null}
                      或纯字符串（视为 value，utc_offset=null）；null = 该字段不存在
    content_text      字符串 | null

predictions.jsonl：每行一条 {"id": ..., 同名字段...}。
    - 缺页（gold 有、pred 无该行）按崩溃处理：文章页四字段全计 0 入分母；
      应拒识页视为"未返回实质内容"，计正确拒识。
    - 行解析异常不吞：计入 pred_parse_errors 并在输出中上报。
    - 显式拒识：{"id": ..., "rejected": true} 或四字段全空。

输出 scores.json：overall + by_dataset / by_site / by_route /
by_content_structure 五组视图；每组含主指标（title_exact / authors_f1 /
各时间字段 score / content_f1 / rejection_accuracy）与全部诊断指标
（title_sim / lcs_f1 / dup_ratio / num_f1 / para_ratio / 时区三态 /
time_confusion / false_fill_rate / miss_rate / correct_empty 计数）。
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

# ===========================================================================
# §2 通用规范化
# ===========================================================================

def norm_text(s):
    """norm_text(s) = 删除全部空白字符( casefold( NFKC(s) ) )"""
    s = unicodedata.normalize("NFKC", s).casefold()
    return "".join(s.split())


# ===========================================================================
# §5/§3 字符 3-gram 多重集（content 主指标 & title_sim 共用）
# ===========================================================================

def trigram_multiset(s):
    """字符 3-gram 多重集；长度 <3 的文本退化为全串单元素集合。"""
    if len(s) < 3:
        return Counter({s}) if s else Counter()
    return Counter(s[i:i + 3] for i in range(len(s) - 2))


def multiset_prf(pred_ms, gold_ms):
    """多重集 P/R/F1：交集大小 = 各 gram 计数的 min 之和。"""
    common = sum((pred_ms & gold_ms).values())
    tp, tg = sum(pred_ms.values()), sum(gold_ms.values())
    p = common / tp if tp else 0.0
    r = common / tg if tg else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def content_f1(pred, gold):
    """§6.1 content 主指标：规范化后字符 3-gram 多重集 F1，返回 (P, R, F1)。"""
    return multiset_prf(trigram_multiset(norm_text(pred)),
                        trigram_multiset(norm_text(gold)))


# ===========================================================================
# §6.2 content 诊断指标
# ===========================================================================

def lcs_f1(pred, gold):
    """顺序敏感诊断：字符级 LCS（SequenceMatcher matching_blocks 之和）的 F1。"""
    a, b = norm_text(pred), norm_text(gold)
    m = SequenceMatcher(None, a, b, autojunk=False)
    common = sum(blk.size for blk in m.get_matching_blocks())
    if not a and not b:
        return None  # 双端皆空
    return 2 * common / (len(a) + len(b)) if (len(a) + len(b)) else 0.0


def dup_ratio(pred):
    """重复诊断：pred 3-gram 多重集中重复出现的比例 = (总数-去重数)/总数。"""
    ms = trigram_multiset(norm_text(pred))
    total = sum(ms.values())
    if total == 0:
        return 0.0
    return (total - len(ms)) / total


def num_f1(pred, gold):
    """关键数字保真诊断：数字串（\\d+(\\.\\d+)?）多重集 F1；双端均无数字为 None。"""
    np_ = Counter(re.findall(r"\d+(?:\.\d+)?", norm_text(pred)))
    ng = Counter(re.findall(r"\d+(?:\.\d+)?", norm_text(gold)))
    if not np_ and not ng:
        return None
    return multiset_prf(np_, ng)[2]


def para_ratio(pred, gold):
    """段落结构诊断：段落数之比 min/max（段落 = 1 个以上换行切分）；双端皆 0 段为 None。"""
    def npara(s):
        return len([x for x in re.split(r"\n+", s.strip()) if x.strip()])
    a, b = npara(pred), npara(gold)
    if a == 0 and b == 0:
        return None
    if a == 0 or b == 0:
        return 0.0
    return min(a, b) / max(a, b)


# ===========================================================================
# §4 authors
# ===========================================================================

AUTHOR_PREFIXES = ["记者", "通讯员", "作者", "执笔", "by"]


def norm_author(name):
    """作者名归一化：NFKC+casefold、剥角色括号、剥署名前缀（可叠加）、去全部空白。"""
    a = unicodedata.normalize("NFKC", name).casefold()
    a = re.sub(r"[（(][^）)]*[）)]", "", a)      # 角色括号：张三（摄影）→ 张三
    a = "".join(a.split())
    changed = True
    while changed:                                # 前缀可叠加：记者通讯员张三
        changed = False
        for p in AUTHOR_PREFIXES:
            if a.startswith(p) and len(a) > len(p):
                a = a[len(p):]
                changed = True
    return a


def authors_f1(pred_list, gold_list):
    """作者集合 F1，返回 (f1, P, R)；双端皆空返回 (None, None, None)。"""
    ps = {norm_author(x) for x in (pred_list or []) if norm_author(x)}
    gs = {norm_author(x) for x in (gold_list or []) if norm_author(x)}
    if not ps and not gs:
        return None, None, None                  # correct_empty
    if not ps or not gs:
        return 0.0, 0.0, 0.0                     # 误填或漏提
    common = len(ps & gs)
    if common == 0:
        return 0.0, 0.0, 0.0                     # 两集合不相交：F1=0（D-001 修复除零崩溃）
    p, r = common / len(ps), common / len(gs)
    return 2 * p * r / (p + r), p, r


# ===========================================================================
# §5 time
# ===========================================================================

_TIME_COMPONENTS = [(0, 4), (5, 7), (8, 10), (11, 13), (14, 16), (17, 19)]
_TIME_NAMES = ["year", "month", "day", "hour", "minute", "second"]


def _pad19(s):
    return (s or "").ljust(19, "X")


def time_score(pred, gold):
    """
    §5.1 按 gold 的精度比较：gold 中凡含 X 的分量不参与；参与分量全部相等
    记 1，任一不等记 0。gold 尾部整体缺失等同全 XX。pred 为 None 计 0。
    gold 无任何已知分量时返回 None（该页不进分母，计 gold_all_xx）。
    """
    if pred is None:
        return 0.0
    g, p = _pad19(gold), _pad19(pred)
    known = [i for i, (a, b) in enumerate(_TIME_COMPONENTS) if "X" not in g[a:b]]
    if not known:
        return None
    for i in known:
        a, b = _TIME_COMPONENTS[i]
        if p[a:b] != g[a:b]:
            return 0.0
    return 1.0


def time_confusion(pred_publish, gold_update):
    """§5.2 pred 某时间字段值等于 gold 的另一时间字段值 → 类型混淆。"""
    if not pred_publish or not gold_update:
        return False
    p, g = _pad19(pred_publish), _pad19(gold_update)
    return p[:19] == g[:19] or p[:len(gold_update.rstrip("X"))] == \
        gold_update.rstrip("X")


def tz_status(pred_offset, gold_offset):
    """§5.2 时区单独三态统计：match / missing / mismatch；gold 无时区记 gold_absent。"""
    if gold_offset is None:
        return "gold_absent"
    if pred_offset is None:
        return "missing"
    return "match" if pred_offset == gold_offset else "mismatch"


# ===========================================================================
# §3 title
# ===========================================================================

def title_exact(pred, gold):
    """§3 主指标：norm_text 精确匹配 0/1；pred 为 None（漏提/崩溃）记 0。"""
    if pred is None:
        return 0
    return 1 if norm_text(pred) == norm_text(gold) else 0


def title_sim(pred, gold):
    """§3 诊断：规范化后字符 3-gram 多重集 F1（定义同 §6.1）。"""
    if pred is None:
        return 0.0
    return content_f1(pred, gold)[2]


# ===========================================================================
# 逐页评分
# ===========================================================================

def _is_empty(v):
    """空值语义（§1.6）：None / 空串 / 空列表 皆为空。"""
    if v is None:
        return True
    if isinstance(v, str) and v == "":
        return True
    if isinstance(v, (list, tuple, dict)) and len(v) == 0:
        return True
    return False


def _time_parts(rec, field):
    """从一条记录中取时间字段的 (value, utc_offset)；兼容 dict / 纯字符串 / null。"""
    v = rec.get(field)
    if isinstance(v, dict):
        return v.get("value"), v.get("utc_offset")
    if isinstance(v, str):
        return v, None
    return None, None


def discover_time_fields(gold_pages):
    """时间字段 = gold 中出现的所有 *_time 键（§5：多时间字段分别维护、独立评分）。"""
    fields = set()
    for g in gold_pages:
        for k in g:
            if k.endswith("_time"):
                fields.add(k)
    return sorted(fields)


def should_reject(gold_rec):
    """§7：content_structure 非 single，或 page_condition 非 ok → 应拒识页。"""
    return (gold_rec.get("content_structure") != "single"
            or gold_rec.get("page_condition", "ok") != "ok")


def pred_is_empty_record(pred_rec, time_fields):
    """§7 拒识判定：空记录 = 四字段全空 / 显式拒识标记 / 记录缺失。"""
    if pred_rec is None:
        return True
    if pred_rec.get("rejected") is True:
        return True
    keys = ["title", "authors", "content_text"] + list(time_fields)
    return all(_is_empty(pred_rec.get(k)) for k in keys)


def score_title(pred, gold):
    """返回 (score_or_None, sim_or_None, tag)。tag ∈ ok/correct_empty/false_fill/miss。"""
    g, p = gold.get("title"), (pred or {}).get("title")
    if _is_empty(g) and _is_empty(p):
        return None, None, "correct_empty"
    if _is_empty(g):
        return 0.0, None, "false_fill"
    if _is_empty(p):
        return 0.0, 0.0, "miss"
    return float(title_exact(p, g)), title_sim(p, g), "ok"


def score_authors(pred, gold):
    """返回 (f1_or_None, tag)。"""
    g, p = gold.get("authors"), (pred or {}).get("authors")
    f, _, _ = authors_f1(p if isinstance(p, list) else ([] if _is_empty(p) else [p]),
                         g if isinstance(g, list) else ([] if _is_empty(g) else [g]))
    if f is None:
        return None, "correct_empty"
    if _is_empty(g):
        return 0.0, "false_fill"
    if _is_empty(p):
        return 0.0, "miss"
    return f, "ok"


def score_time_field(pred, gold, field, other_gold_values):
    """
    单个时间字段逐页评分。
    返回 dict：score(None=不进分母) / tag / confusion / tz。
    """
    g_val, g_off = _time_parts(gold, field)
    p_val, p_off = _time_parts(pred or {}, field)
    out = {"score": None, "tag": None, "confusion": False, "tz": None}
    if _is_empty(g_val) and _is_empty(p_val):
        out["tag"] = "correct_empty"
        return out
    if _is_empty(g_val):
        out.update(score=0.0, tag="false_fill")
        return out
    if _is_empty(p_val):
        out.update(score=0.0, tag="miss")
    else:
        s = time_score(p_val, g_val)
        if s is None:                      # gold 无已知分量：不进分母，单独登记
            out["tag"] = "gold_all_xx"
            return out
        out.update(score=s, tag="ok")
    # 类型混淆：pred 值等于该页 gold 的其他时间字段值（§5.2）
    for ov in other_gold_values:
        if time_confusion(p_val, ov):
            out["confusion"] = True
            break
    out["tz"] = tz_status(p_off, g_off)
    return out


def score_content(pred, gold):
    """返回 (f1_or_None, tag, diagnostics_dict)。"""
    g, p = gold.get("content_text"), (pred or {}).get("content_text")
    diag = {"lcs_f1": None, "dup_ratio": None, "num_f1": None, "para_ratio": None}
    if _is_empty(g) and _is_empty(p):
        return None, "correct_empty", diag
    if _is_empty(g):
        diag["dup_ratio"] = dup_ratio(p)
        return 0.0, "false_fill", diag
    if _is_empty(p):
        return 0.0, "miss", diag
    f = content_f1(p, g)[2]
    diag.update(lcs_f1=lcs_f1(p, g), dup_ratio=dup_ratio(p),
                num_f1=num_f1(p, g), para_ratio=para_ratio(p, g))
    return f, "ok", diag


def score_page(pred, gold, time_fields):
    """
    逐页评分（§1.1）。应拒识页只评拒识；文章页评四字段。
    返回该页的完整分明细。
    """
    page = {"id": gold.get("id"), "rejection": None}
    if should_reject(gold):
        page["rejection"] = {
            "should": True,
            "correct": pred_is_empty_record(pred, time_fields),
        }
        return page
    page["rejection"] = {"should": False, "correct": None}

    s, sim, tag = score_title(pred, gold)
    page["title"] = {"score": s, "sim": sim, "tag": tag}

    f, tag = score_authors(pred, gold)
    page["authors"] = {"score": f, "tag": tag}

    page["time"] = {}
    for tf in time_fields:
        others = []
        for of in time_fields:
            if of == tf:
                continue
            ov, _ = _time_parts(gold, of)
            if not _is_empty(ov):
                others.append(ov)
        page["time"][tf] = score_time_field(pred, gold, tf, others)

    f, tag, diag = score_content(pred, gold)
    page["content"] = {"score": f, "tag": tag, **diag}
    return page


# ===========================================================================
# 聚合（§1.1 宏平均 + §1.2 分组报告）
# ===========================================================================

def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def new_group():
    return {
        "n_pages": 0, "n_scored": 0,
        "title": {"scores": [], "sims": [], "correct_empty": 0,
                  "false_fill": 0, "miss": 0},
        "authors": {"scores": [], "correct_empty": 0, "false_fill": 0,
                    "miss": 0, "gold_empty_pages": 0, "gold_present_pages": 0},
        "time": {},
        "content": {"scores": [], "lcs_f1": [], "dup_ratio": [], "num_f1": [],
                    "para_ratio": [], "correct_empty": 0, "false_fill": 0,
                    "miss": 0},
        "rejection": {"n": 0, "correct": 0, "badcases": []},
    }


def _time_group(g, tf):
    return g["time"].setdefault(tf, {
        "scores": [], "confusion": 0, "correct_empty": 0, "false_fill": 0,
        "miss": 0, "gold_all_xx": 0,
        "tz": {"match": 0, "missing": 0, "mismatch": 0, "gold_absent": 0}})


def group_add(g, page):
    g["n_pages"] += 1
    rej = page["rejection"]
    if rej["should"]:
        g["rejection"]["n"] += 1
        if rej["correct"]:
            g["rejection"]["correct"] += 1
        else:
            g["rejection"]["badcases"].append(page["id"])
        return
    g["n_scored"] += 1

    t = page["title"]
    if t["tag"] == "correct_empty":
        g["title"]["correct_empty"] += 1
    else:
        g["title"]["scores"].append(t["score"])
        if t["sim"] is not None:
            g["title"]["sims"].append(t["sim"])
        if t["tag"] in ("false_fill", "miss"):
            g["title"][t["tag"]] += 1

    a = page["authors"]
    if a["tag"] == "correct_empty":
        g["authors"]["correct_empty"] += 1
        g["authors"]["gold_empty_pages"] += 1
    else:
        g["authors"]["scores"].append(a["score"])
        if a["tag"] == "false_fill":
            g["authors"]["false_fill"] += 1
            g["authors"]["gold_empty_pages"] += 1
        elif a["tag"] == "miss":
            g["authors"]["miss"] += 1
            g["authors"]["gold_present_pages"] += 1
        else:
            g["authors"]["gold_present_pages"] += 1

    for tf, r in page["time"].items():
        tg = _time_group(g, tf)
        if r["tag"] in ("correct_empty", "gold_all_xx"):
            tg[r["tag"]] += 1
            if r["tz"]:
                tg["tz"][r["tz"]] += 1
            continue
        tg["scores"].append(r["score"])
        if r["tag"] in ("false_fill", "miss"):
            tg[r["tag"]] += 1
        if r["confusion"]:
            tg["confusion"] += 1
        if r["tz"]:
            tg["tz"][r["tz"]] += 1

    c = page["content"]
    if c["tag"] == "correct_empty":
        g["content"]["correct_empty"] += 1
    else:
        g["content"]["scores"].append(c["score"])
        if c["tag"] in ("false_fill", "miss"):
            g["content"][c["tag"]] += 1
        for k in ("lcs_f1", "dup_ratio", "num_f1", "para_ratio"):
            if c.get(k) is not None:
                g["content"][k].append(c[k])


def finalize_group(g):
    """把累积器结算为对外报告结构：主指标平铺 + 明细嵌套。"""
    out = {"n_pages": g["n_pages"], "n_scored": g["n_scored"]}

    t = g["title"]
    out["title_exact"] = _mean(t["scores"])
    out["title_sim"] = _mean(t["sims"])
    out["title_detail"] = {
        "n": len(t["scores"]), "correct_empty": t["correct_empty"],
        "false_fill": t["false_fill"], "miss": t["miss"]}

    a = g["authors"]
    out["authors_f1"] = _mean(a["scores"])
    out["authors_false_fill_rate"] = (
        a["false_fill"] / a["gold_empty_pages"] if a["gold_empty_pages"] else None)
    out["authors_miss_rate"] = (
        a["miss"] / a["gold_present_pages"] if a["gold_present_pages"] else None)
    out["authors_detail"] = {
        "n": len(a["scores"]), "correct_empty": a["correct_empty"],
        "false_fill": a["false_fill"], "miss": a["miss"],
        "gold_empty_pages": a["gold_empty_pages"],
        "gold_present_pages": a["gold_present_pages"]}

    out["time"] = {}
    for tf, tg in g["time"].items():
        out["time"][tf] = {
            "score": _mean(tg["scores"]), "n": len(tg["scores"]),
            "confusion": tg["confusion"], "correct_empty": tg["correct_empty"],
            "false_fill": tg["false_fill"], "miss": tg["miss"],
            "gold_all_xx": tg["gold_all_xx"], "tz": dict(tg["tz"]),
            "false_fill_rate": (tg["false_fill"] /
                                (tg["false_fill"] + tg["correct_empty"])
                                if (tg["false_fill"] + tg["correct_empty"]) else None),
        }
        out[f"{tf}_score"] = out["time"][tf]["score"]  # 主指标平铺

    c = g["content"]
    out["content_f1"] = _mean(c["scores"])
    for k in ("lcs_f1", "dup_ratio", "num_f1", "para_ratio"):
        out[k] = _mean(c[k])
    out["content_detail"] = {
        "n": len(c["scores"]), "correct_empty": c["correct_empty"],
        "false_fill": c["false_fill"], "miss": c["miss"]}

    r = g["rejection"]
    out["rejection_accuracy"] = r["correct"] / r["n"] if r["n"] else None
    out["rejection_detail"] = {"n": r["n"], "correct": r["correct"],
                               "badcases": r["badcases"]}
    return out


def group_key(gold_rec):
    """§1.2 分组维度：数据集 / 站点 / 路由层 / 页面类型。"""
    return {
        "by_dataset": gold_rec.get("dataset") or "unknown",
        "by_site": gold_rec.get("site") or "unknown",
        "by_route": gold_rec.get("route") or gold_rec.get("site") or "unknown",
        "by_content_structure": gold_rec.get("content_structure") or "unknown",
    }


# ===========================================================================
# IO 与入口
# ===========================================================================

def load_gold(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    pages = data["pages"] if isinstance(data, dict) else data
    return pages


def load_pred(path):
    """读 pred JSONL。解析异常不吞：计数上报；缺页由调用方按崩溃计 0。"""
    preds, errors = {}, []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append({"line": lineno, "error": str(e)})
                continue
            if not isinstance(rec, dict) or "id" not in rec:
                errors.append({"line": lineno, "error": "record missing 'id'"})
                continue
            preds[rec["id"]] = rec
    return preds, errors


def run(pred_path, gold_path):
    gold_pages = load_gold(gold_path)
    preds, pred_errors = load_pred(pred_path)
    time_fields = discover_time_fields(gold_pages)

    groups = {"overall": new_group()}
    per_page = []
    for grec in gold_pages:
        prec = preds.get(grec.get("id"))   # 缺页 → None → 各字段计 0
        page = score_page(prec, grec, time_fields)
        per_page.append(page)
        buckets = [groups["overall"]]
        for dim, val in group_key(grec).items():
            buckets.append(groups.setdefault(dim, {}).setdefault(val, new_group()))
        for b in buckets:
            group_add(b, page)

    out = {
        "version": "v2",
        "spec": "eval_spec_v2.md（冻结）",
        "n_pages": len(gold_pages),
        "pred_parse_errors": pred_errors,
        "time_fields": time_fields,
        "overall": finalize_group(groups["overall"]),
    }
    for dim in ("by_dataset", "by_site", "by_route", "by_content_structure"):
        out[dim] = {k: finalize_group(v) for k, v in
                    sorted(groups.get(dim, {}).items())}
    out["pages"] = per_page
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="离线库 HTML 结构化提取评测器 v2（冻结）")
    ap.add_argument("--pred", required=True, help="predictions.jsonl")
    ap.add_argument("--gold", required=True, help="gold.json")
    ap.add_argument("--out", required=True, help="scores.json 输出路径")
    ap.add_argument("--no-pages", action="store_true",
                    help="不输出逐页明细（预留测试集纪律：只出聚合分）")
    args = ap.parse_args(argv)

    result = run(args.pred, args.gold)
    if args.no_pages:
        result.pop("pages", None)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    o = result["overall"]
    print(f"页数 {result['n_pages']}（参评字段评分 {o['n_scored']}，"
          f"应拒识 {o['rejection_detail']['n']}）")
    print(f"title_exact={o['title_exact']}  authors_f1={o['authors_f1']}  "
          f"content_f1={o['content_f1']}  "
          f"rejection={o['rejection_accuracy']}")
    for tf, tg in o["time"].items():
        print(f"{tf}={tg['score']}  confusion={tg['confusion']}  tz={tg['tz']}")
    if result["pred_parse_errors"]:
        print(f"警告：pred 有 {len(result['pred_parse_errors'])} 行解析异常（已上报，未吞）")
    print(f"已写出 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
