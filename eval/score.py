#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
score.py — 离线库 HTML 结构化提取 · 评测器 v1（历史口径，仅用于对照）

口径来源：会话记录《会话1-离线库字段提取计划.txt》§"各字段浮点指标的口径定义"
A 组（我方 score.py 冻结指标）。v2 冻结后，本版本仅作历史对照，不再修订。

与 v2 的三处系统性差异（详见 eval/README.md）：
    1. title   规范化（NFKC + 去全部空白 + 小写）精确匹配 0/1 —— 无 title_sim 诊断
    2. content 规范化后字符级 F1，用 difflib.SequenceMatcher 的 matching_blocks
               公共长度算 P/R/F1 —— 而非 3-gram 多重集
    3. time    天粒度等值（各取 YYYY-MM-DD 比较）；任一端缺失该页**跳过不计**
               —— v2 是缺失计 0 且按 gold 精度逐分量比较

其余：authors 集合 F1（只剥角色括号，不剥"记者/By"前缀）；逐页评分 → 宏平均；
按数据集 / 站点 / 路由层 / 页面类型分组输出；非文章页评拒识准确率。

用法：
    python score.py --pred predictions.jsonl --gold gold.json --out scores_v1.json
输入输出文件格式与 score_v2.py 相同。
"""

import argparse
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher

from score_v2 import (_is_empty, _time_parts, discover_time_fields, group_key,
                      load_gold, load_pred, pred_is_empty_record, should_reject)


# ---------------------------------------------------------------------------
# v1 规范化与指标
# ---------------------------------------------------------------------------

def norm_text_v1(s):
    """v1 规范化：NFKC + 小写 + 去全部空白（v1 原文为"小写"，非 casefold）。"""
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(s.split())


def title_score_v1(pred, gold):
    """v1 title：规范化精确匹配 0/1。gold 为空 → None（该页跳过）；pred 空 → 0。"""
    if _is_empty(gold):
        return None
    if _is_empty(pred):
        return 0.0
    return 1.0 if norm_text_v1(pred) == norm_text_v1(gold) else 0.0


def norm_author_v1(name):
    """v1 作者归一化：NFKC + 小写 + 剥角色括号 + 去全部空白（不剥署名前缀）。"""
    a = unicodedata.normalize("NFKC", name).lower()
    a = re.sub(r"[（(][^）)]*[）)]", "", a)
    return "".join(a.split())


def authors_f1_v1(pred_list, gold_list):
    """v1 authors：剥角色括号后的集合 F1。双端皆空 → None（跳过）。"""
    ps = {norm_author_v1(x) for x in (pred_list or []) if norm_author_v1(x)}
    gs = {norm_author_v1(x) for x in (gold_list or []) if norm_author_v1(x)}
    if not ps and not gs:
        return None
    if not ps or not gs:
        return 0.0
    common = len(ps & gs)
    p, r = common / len(ps), common / len(gs)
    return 2 * p * r / (p + r) if (p + r) else 0.0


def _day(s):
    """取天粒度 'YYYY-MM-DD'；无法取到返回 None。"""
    if not s or len(s) < 10 or "X" in s[:10]:
        return None
    return s[:10]


def time_score_v1(pred_value, gold_value):
    """v1 time：天粒度等值；任一端缺失（含日期分量含 XX）该页跳过（None）。"""
    gd, pd_ = _day(gold_value), _day(pred_value)
    if gd is None or pd_ is None:
        return None
    return 1.0 if gd == pd_ else 0.0


def content_f1_v1(pred, gold):
    """v1 content：规范化后字符级 F1，公共长度 = SequenceMatcher matching_blocks 之和。"""
    a, b = norm_text_v1(pred), norm_text_v1(gold)
    if not b:
        return None                      # gold 空 → 跳过
    if not a:
        return 0.0
    m = SequenceMatcher(None, a, b, autojunk=False)
    common = sum(blk.size for blk in m.get_matching_blocks())
    p, r = common / len(a), common / len(b)
    return 2 * p * r / (p + r) if (p + r) else 0.0


# ---------------------------------------------------------------------------
# 逐页评分与聚合
# ---------------------------------------------------------------------------

def score_page_v1(pred, gold, time_fields):
    page = {"id": gold.get("id"), "rejection": None}
    if should_reject(gold):
        page["rejection"] = {"should": True,
                             "correct": pred_is_empty_record(pred, time_fields)}
        return page
    page["rejection"] = {"should": False, "correct": None}
    pred = pred or {}
    page["title"] = title_score_v1(pred.get("title"), gold.get("title"))
    page["authors"] = authors_f1_v1(
        pred.get("authors") if isinstance(pred.get("authors"), list) else None,
        gold.get("authors") if isinstance(gold.get("authors"), list) else None)
    page["time"] = {}
    for tf in time_fields:
        pv, _ = _time_parts(pred, tf)
        gv, _ = _time_parts(gold, tf)
        page["time"][tf] = time_score_v1(pv, gv)
    page["content"] = content_f1_v1(pred.get("content_text") or "",
                                    gold.get("content_text") or "")
    return page


def new_group_v1():
    return {"n_pages": 0, "n_scored": 0, "title": [], "authors": [],
            "time": {}, "content": [],
            "rejection": {"n": 0, "correct": 0, "badcases": []}}


def group_add_v1(g, page, time_fields):
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
    for k in ("title", "authors", "content"):
        if page[k] is not None:
            g[k].append(page[k])
    for tf in time_fields:
        v = page["time"].get(tf)
        if v is not None:                # v1：time 缺失跳过不计
            g["time"].setdefault(tf, []).append(v)


def finalize_group_v1(g):
    def mean(xs):
        return sum(xs) / len(xs) if xs else None
    out = {"n_pages": g["n_pages"], "n_scored": g["n_scored"],
           "title": mean(g["title"]), "authors": mean(g["authors"]),
           "content": mean(g["content"]),
           "title_n": len(g["title"]), "authors_n": len(g["authors"]),
           "content_n": len(g["content"])}
    for tf, xs in g["time"].items():
        out[f"{tf}"] = mean(xs)
        out[f"{tf}_n"] = len(xs)
    r = g["rejection"]
    out["rejection_accuracy"] = r["correct"] / r["n"] if r["n"] else None
    out["rejection_detail"] = r
    return out


def run(pred_path, gold_path):
    gold_pages = load_gold(gold_path)
    preds, pred_errors = load_pred(pred_path)
    time_fields = discover_time_fields(gold_pages)

    groups = {"overall": new_group_v1()}
    per_page = []
    for grec in gold_pages:
        page = score_page_v1(preds.get(grec.get("id")), grec, time_fields)
        per_page.append(page)
        buckets = [groups["overall"]]
        for dim, val in group_key(grec).items():
            buckets.append(groups.setdefault(dim, {}).setdefault(val, new_group_v1()))
        for b in buckets:
            group_add_v1(b, page, time_fields)

    out = {
        "version": "v1（历史口径，仅对照用）",
        "n_pages": len(gold_pages),
        "pred_parse_errors": pred_errors,
        "time_fields": time_fields,
        "overall": finalize_group_v1(groups["overall"]),
        "pages": per_page,
    }
    for dim in ("by_dataset", "by_site", "by_route", "by_content_structure"):
        out[dim] = {k: finalize_group_v1(v) for k, v in
                    sorted(groups.get(dim, {}).items())}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="评测器 v1（历史口径，仅对照用）")
    ap.add_argument("--pred", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    result = run(args.pred, args.gold)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    o = result["overall"]
    print(f"页数 {result['n_pages']}（参评 {o['n_scored']}）  "
          f"title={o['title']}  authors={o['authors']}  content={o['content']}  "
          f"rejection={o['rejection_accuracy']}")
    for tf in result["time_fields"]:
        print(f"{tf}={o.get(tf)}（n={o.get(tf + '_n')}，缺失页已跳过）")
    print(f"已写出 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
