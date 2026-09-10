#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
score_zyte.py — B 组口径评分器：对齐 ISPRAS 论文（arXiv:2502.02167 §VII-A，Zyte 方法论）

口径（按任务书与会话记录 §436 的界定）：
  title / text : 词 4-gram 袋（multiset）F1。词 = 小写后按非字母数字切分的 token。
                 gold 有值而 pred 缺失 → F1=0（计入分母）；gold 缺失 → 该页不进分母。
  authors      : 集合 F1，仅 lower + strip（不剥前缀/括号）。gold 无作者标注的页不进分母。
  date         : gold 的 publish/update 值按"已知分量逐位比较"（沿用 v2 的 XX 语义，
                 论文口径的核心差异：gold 有值而预测缺失计 0 不跳过——本实现同样如此；
                 gold 缺失 → 不进分母，pred 有值也不惩罚（论文口径不含 false_fill 惩罚，
                 与我方 v2 不同，差异记入报告）。

用法：
  venv/bin/python external/score_zyte.py --pred external/ispras_pred.jsonl \
      --gold external/ispras_gold_en.json --out external/ispras_scores_zyte.json
"""
import argparse
import json
import re
import sys
from collections import Counter

sys.path.insert(0, str(__file__.rsplit("/", 2)[0] + "/eval"))
from score_v2 import _is_empty, _time_parts, load_gold, load_pred  # noqa: E402


def word_tokens(s):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def ngram_bag(tokens, n=4):
    if len(tokens) < n:
        return Counter({" ".join(tokens)}) if tokens else Counter()
    return Counter(" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1))


def bag_f1(pred, gold):
    p_ms, g_ms = ngram_bag(word_tokens(pred)), ngram_bag(word_tokens(gold))
    common = sum((p_ms & g_ms).values())
    tp, tg = sum(p_ms.values()), sum(g_ms.values())
    if not tg:
        return None
    if not tp:
        return 0.0
    p, r = common / tp, common / tg
    return 2 * p * r / (p + r) if (p + r) else 0.0


def authors_f1_zyte(pred_list, gold_list):
    ps = {a.lower().strip() for a in (pred_list or []) if a and a.strip()}
    gs = {a.lower().strip() for a in (gold_list or []) if a and a.strip()}
    if not gs:
        return None
    if not ps:
        return 0.0
    common = len(ps & gs)
    if not common:
        return 0.0
    p, r = common / len(ps), common / len(gs)
    return 2 * p * r / (p + r)


def date_score_zyte(pred_val, gold_val):
    """gold 有值：pred 缺失→0；按 gold 已知分量逐位等值（XX 分量不比）。gold 缺失→None。"""
    if _is_empty(gold_val):
        return None
    if _is_empty(pred_val):
        return 0.0
    comps = [(0, 4), (5, 7), (8, 10), (11, 13), (14, 16), (17, 19)]
    g = gold_val.ljust(19, "X")
    p = pred_val.ljust(19, "X")
    for a, b in comps:
        if "X" not in g[a:b] and p[a:b] != g[a:b]:
            return 0.0
    return 1.0


def date_score_day(pred_val, gold_val):
    """敏感性变体：天粒度等值（YYYY-MM-DD），gold/pred 缺失处理同上。"""
    if _is_empty(gold_val):
        return None
    if _is_empty(pred_val):
        return 0.0
    return 1.0 if pred_val[:10] == gold_val[:10] else 0.0


def run(pred_path, gold_path):
    gold_pages = load_gold(gold_path)
    preds, pred_errors = load_pred(pred_path)
    agg = {k: [] for k in ("title", "text", "authors", "publish_date", "update_date",
                           "date_union", "date_union_day")}
    per_page = []
    for g in gold_pages:
        p = preds.get(g["id"]) or {}
        row = {"id": g["id"], "site": g.get("site")}
        f = bag_f1(p.get("title"), g.get("title"))
        row["title"] = f
        if f is not None:
            agg["title"].append(f)
        f = bag_f1(p.get("content_text"), g.get("content_text"))
        row["text"] = f
        if f is not None:
            agg["text"].append(f)
        f = authors_f1_zyte(p.get("authors"), g.get("authors"))
        row["authors"] = f
        if f is not None:
            agg["authors"].append(f)
        pub_pv, _ = _time_parts(p, "publish_time")
        upd_pv, _ = _time_parts(p, "update_time")
        pub_gv, _ = _time_parts(g, "publish_time")
        upd_gv, _ = _time_parts(g, "update_time")
        for pv, gv, key in ((pub_pv, pub_gv, "publish_date"),
                            (upd_pv, upd_gv, "update_date")):
            f = date_score_zyte(pv, gv)
            row[key] = f
            if f is not None:
                agg[key].append(f)
        # 论文只有单一 Date 属性：publish/update 合一（pred 任一字段命中即取该分）
        if not (_is_empty(pub_gv) and _is_empty(upd_gv)):
            cand = []
            for pv, gv in ((pub_pv, pub_gv), (upd_pv, upd_gv),
                           (pub_pv, upd_gv), (upd_pv, pub_gv)):
                if not _is_empty(gv):
                    cand.append((date_score_zyte(pv, gv), date_score_day(pv, gv)))
            f_full = max(c[0] for c in cand)
            f_day = max(c[1] for c in cand)
            row["date_union"] = f_full
            row["date_union_day"] = f_day
            agg["date_union"].append(f_full)
            agg["date_union_day"].append(f_day)
        per_page.append(row)
    summary = {k: {"f1": (sum(v) / len(v) if v else None), "n": len(v)}
               for k, v in agg.items()}
    return {"version": "zyte-paper (B组)",
            "spec": "arXiv:2502.02167 §VII-A：title/text 词 4-gram 袋 F1；authors 集合 F1；date 缺失计 0",
            "n_pages": len(gold_pages),
            "pred_parse_errors": pred_errors,
            "summary": summary, "pages": per_page}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    res = run(args.pred, args.gold)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v["f1"] for k, v in res["summary"].items()}, indent=1))
    print(f"n: {json.dumps({k: v['n'] for k, v in res['summary'].items()})}")
    print(f"已写出 {args.out}")


if __name__ == "__main__":
    main()
