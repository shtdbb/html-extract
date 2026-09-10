#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all_eval.py — 批量评测驱动：对照臂 dev 双口径 + test 终测聚合 + 汇总。

执行内容（全部真实运行，日志落 results/run_logs/）：
  1. readability 对照臂：dev 全量提取 → score.py + score_v2.py 双口径；
  2. test 终测（只此一次）：extract.py(v4) 与 readability 各跑 test 集，
     score_v2.py --no-pages 只出聚合分 → results/test_final_scores.json；
  3. negative 4 页负例检查（不在 gold 内，单独核对拒识行为）；
  4. 汇总 results/v2_scores_all.json：v1~v4 + readability 各臂的
     overall + by_route(fixed/generic) 主指标与全部诊断指标（v2 口径），
     并附 v1 口径主指标对照。

用法：venv/bin/python scripts/run_all_eval.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "venv" / "bin" / "python"
LOGS = ROOT / "results" / "run_logs"
LOGS.mkdir(parents=True, exist_ok=True)


def run(cmd, logname):
    log = LOGS / logname
    with open(log, "w") as f:
        p = subprocess.run([str(PY)] + [str(c) for c in cmd],
                           cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        print(f"FAIL {logname}", file=sys.stderr)
        sys.exit(1)
    print(f"ok   {logname}")


def main():
    # ---- 0. test 评分 gold（dataset/route 派生字段；原 gold 不改） ----
    gt = json.load(open(ROOT / "gold" / "gold_test.json"))
    for r in gt:
        r["dataset"] = "test"
        r["route"] = "test"
    json.dump(gt, open(ROOT / "results" / "test_gold.json", "w"),
              ensure_ascii=False, indent=1)

    # ---- 1. readability dev ----
    run(["run_readability.py", "--groups", "fixed,generic,negative",
         "--out", "results/readability_pred_dev.jsonl"], "readability_extract_dev.log")
    run(["eval/score.py", "--pred", "results/readability_pred_dev.jsonl",
         "--gold", "results/dev_gold.json",
         "--out", "results/readability_scores_v1.json"], "readability_score_v1.log")
    run(["eval/score_v2.py", "--pred", "results/readability_pred_dev.jsonl",
         "--gold", "results/dev_gold.json",
         "--out", "results/readability_scores_v2.json"], "readability_score_v2.log")

    # ---- 2. test 终测（聚合分） ----
    run(["extract.py", "--groups", "test",
         "--out", "results/v4_pred_test.jsonl"], "v4_extract_test.log")
    run(["run_readability.py", "--groups", "test",
         "--out", "results/readability_pred_test.jsonl"], "readability_extract_test.log")
    run(["eval/score_v2.py", "--pred", "results/v4_pred_test.jsonl",
         "--gold", "results/test_gold.json", "--no-pages",
         "--out", "results/test_v4_scores.json"], "test_v4_score.log")
    run(["eval/score_v2.py", "--pred", "results/readability_pred_test.jsonl",
         "--gold", "results/test_gold.json", "--no-pages",
         "--out", "results/test_readability_scores.json"], "test_readability_score.log")
    test_final = {
        "note": "预留测试集终测：仅此一次运行，只出聚合分（--no-pages），不做逐页错误分析",
        "gold": "gold/gold_test.json（28 页，含 8 应拒识页）",
        "v4_baseline": json.load(open(ROOT / "results" / "test_v4_scores.json")),
        "readability_control": json.load(open(ROOT / "results" / "test_readability_scores.json")),
    }
    json.dump(test_final, open(ROOT / "results" / "test_final_scores.json", "w"),
              ensure_ascii=False, indent=2)
    print("ok   results/test_final_scores.json")

    # ---- 3. negative 4 页负例检查 ----
    neg_ids = ["people_list__01", "sohu_list__01", "sina_list__01", "chinanews_list__01"]
    neg_check = {"note": "negative 4 页不在 gold 内（会话1遗留的未标注缺口），"
                         "不参与评分；此处单独核对拒识行为。",
                 "expect": "全部返回空记录/rejected（均为频道列表页）"}
    for arm, path in [("v4", "results/v4_pred_dev.jsonl"),
                      ("readability", "results/readability_pred_dev.jsonl")]:
        preds = {json.loads(l)["id"]: json.loads(l)
                 for l in open(ROOT / path)}
        rows = []
        for nid in neg_ids:
            r = preds.get(nid, {})
            empty = all(not r.get(k) for k in
                        ("title", "authors", "content_text", "publish_time"))
            rows.append({"id": nid, "rejected": bool(r.get("rejected")),
                         "empty_record": empty,
                         "route": r.get("route"),
                         "correct_refusal": bool(r.get("rejected")) or empty})
        neg_check[arm] = rows
    json.dump(neg_check, open(ROOT / "results" / "negative_check.json", "w"),
              ensure_ascii=False, indent=2)
    print("ok   results/negative_check.json")

    # ---- 4. 汇总 v2_scores_all.json ----
    MAIN = ["title_exact", "authors_f1", "publish_time_score",
            "update_time_score", "content_f1", "rejection_accuracy"]
    DIAG = ["title_sim", "lcs_f1", "dup_ratio", "num_f1", "para_ratio",
            "authors_false_fill_rate", "authors_miss_rate"]

    def flatten(scores_v2, scores_v1):
        ov = scores_v2["overall"]
        out = {"overall": {}, "by_route": {}}
        for k in MAIN + DIAG:
            if ov.get(k) is not None:
                out["overall"][k] = ov[k]
        for tf, tg in ov.get("time", {}).items():
            out["overall"][f"{tf}_tz"] = tg["tz"]
            out["overall"][f"{tf}_confusion"] = tg["confusion"]
            out["overall"][f"{tf}_false_fill"] = tg["false_fill"]
            out["overall"][f"{tf}_miss"] = tg["miss"]
        out["overall"]["title_detail"] = ov["title_detail"]
        out["overall"]["authors_detail"] = ov["authors_detail"]
        out["overall"]["content_detail"] = ov["content_detail"]
        out["overall"]["rejection_detail"] = ov["rejection_detail"]
        for rt, g in scores_v2.get("by_route", {}).items():
            out["by_route"][rt] = {k: g.get(k) for k in MAIN + DIAG
                                   if g.get(k) is not None}
            for tf, tg in g.get("time", {}).items():
                out["by_route"][rt][f"{tf}_tz"] = tg["tz"]
                out["by_route"][rt][f"{tf}_confusion"] = tg["confusion"]
        # v1 口径主指标
        v1ov = scores_v1.get("overall", scores_v1)
        out["scorer_v1_overall"] = {k: v1ov.get(k) for k in
                                    ("title", "authors", "content",
                                     "publish_time", "update_time", "rejection")
                                    if v1ov.get(k) is not None}
        return out

    arms = {}
    for arm in ["v1", "v2", "v3", "v4", "readability"]:
        s2 = json.load(open(ROOT / f"results/{arm}_scores_v2.json"))
        s1 = json.load(open(ROOT / f"results/{arm}_scores_v1.json"))
        arms[arm] = flatten(s2, s1)
    summary = {
        "note": "dev（fixed 30 + generic 55，拒识页互斥分母）全量汇总；"
                "v2 口径为主（eval_spec_v2 冻结），v1 口径仅对照。",
        "gold": "results/dev_gold.json（= gold_fixed + gold_generic + dataset/route 派生字段）",
        "arms": arms,
    }
    json.dump(summary, open(ROOT / "results" / "v2_scores_all.json", "w"),
              ensure_ascii=False, indent=2)
    print("ok   results/v2_scores_all.json")


if __name__ == "__main__":
    main()
