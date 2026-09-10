#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_iteration.py — 自进化迭代闭环的单轮运行器。

闭环一环：提取（含耗时/内存/成本埋点）→ v2 冻结口径评分 → 负例核对
→ loop/metrics_history.jsonl 追加一条版本记录（git 提交哈希绑定）。

用法：
  venv/bin/python loop/run_iteration.py --extractor extract.py --version v5 \
      --note "v5: 埋点基线（策略同 v4）"

  # 模型臂（提取器内部自行调用模型并暴露 get_model_stats()）：
  venv/bin/python loop/run_iteration.py --extractor extract.py --version v10 \
      --note "v10: +模型兜底臂"

纪律：本运行器只跑 dev（fixed,generic,negative）+ 可选 ISPRAS，
绝不触碰 test 集（test 终测由最终交付阶段单独一次性运行）。
"""
import argparse
import importlib.util
import json
import platform
import resource
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from loop import layer_timer  # noqa: E402

NEG_IDS = ["people_list__01", "sohu_list__01", "sina_list__01",
           "chinanews_list__01"]
HISTORY = ROOT / "loop" / "metrics_history.jsonl"

MAIN_KEYS = ["title_exact", "authors_f1", "content_f1", "rejection_accuracy"]
DIAG_KEYS = ["title_sim", "lcs_f1", "dup_ratio", "num_f1", "para_ratio",
             "authors_false_fill_rate", "authors_miss_rate"]


def git_head():
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return commit, bool(dirty)
    except Exception:  # noqa: BLE001
        return None, None


def hw_info():
    try:
        chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                              capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        chip = platform.processor() or "unknown"
    return {"chip": chip, "ram_gb": 64, "accelerator": "Apple Silicon (统一内存, 无独立显存)"}


def load_extractor(path: str):
    spec = importlib.util.spec_from_file_location("extractor_mod", ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def compact_scores(scores: dict):
    ov = scores["overall"]
    out = {"overall": {}, "by_route": {}}
    for k in MAIN_KEYS + DIAG_KEYS:
        if ov.get(k) is not None:
            out["overall"][k] = round(ov[k], 4)
    for tf, tg in ov.get("time", {}).items():
        out["overall"][f"{tf}_score"] = round(tg["score"], 4)
        out["overall"][f"{tf}_false_fill"] = tg["false_fill"]
        out["overall"][f"{tf}_miss"] = tg["miss"]
        out["overall"][f"{tf}_tz"] = tg["tz"]
    for k in ("title_detail", "authors_detail", "content_detail",
              "rejection_detail"):
        if ov.get(k) is not None:
            out["overall"][k] = ov[k]
    for rt, g in scores.get("by_route", {}).items():
        row = {k: round(g[k], 4) for k in MAIN_KEYS + DIAG_KEYS
               if g.get(k) is not None}
        for tf, tg in g.get("time", {}).items():
            row[f"{tf}_score"] = round(tg["score"], 4)
        row["n_pages"] = g.get("n_pages")
        out["by_route"][rt] = row
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", default="extract.py")
    ap.add_argument("--version", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--index", default="dataset_index.jsonl")
    ap.add_argument("--groups", default="fixed,generic,negative")
    ap.add_argument("--gold", default="results/dev_gold.json")
    ap.add_argument("--pred", default=None)
    ap.add_argument("--scores", default=None)
    ap.add_argument("--no-score", action="store_true",
                    help="只跑提取与计时（如 ISPRAS 前先试跑）")
    args = ap.parse_args()

    pred_path = args.pred or f"results/{args.version}_pred_dev.jsonl"
    scores_path = args.scores or f"results/{args.version}_scores_v2.json"
    commit, dirty = git_head()

    mod = load_extractor(args.extractor)
    groups = set(args.groups.split(","))
    rows = [json.loads(l) for l in open(ROOT / args.index, encoding="utf-8")
            if json.loads(l)["group"] in groups]

    layer_timer.reset()
    t0 = time.perf_counter()
    page_times = []
    n_written = 0
    with open(ROOT / pred_path, "w", encoding="utf-8") as f:
        for r in rows:
            raw = (ROOT / r["path"]).read_bytes()
            p0 = time.perf_counter()
            rec = {"id": r["id"], **mod.extract_page(raw, r["site"])}
            page_times.append(time.perf_counter() - p0)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_written += 1
    wall = time.perf_counter() - t0
    peak_rss_mb = resource.getrusage(
        resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)  # macOS: bytes

    layers = layer_timer.report()
    model_stats = (mod.get_model_stats() if hasattr(mod, "get_model_stats")
                   else None)

    # ---- 评分（v2 冻结口径，子进程调用冻结评分器） ----
    scores = None
    if not args.no_score:
        p = subprocess.run(
            [str(ROOT / "venv" / "bin" / "python"),
             str(ROOT / "eval" / "score_v2.py"),
             "--pred", pred_path, "--gold", args.gold,
             "--out", scores_path],
            cwd=ROOT, capture_output=True, text=True)
        if p.returncode != 0:
            print(p.stdout, p.stderr, file=sys.stderr)
            sys.exit(1)
        scores = json.load(open(ROOT / scores_path))

    # ---- 负例核对（4 页频道列表页，期望拒识/空记录） ----
    neg = None
    if "negative" in groups:
        preds = {json.loads(l)["id"]: json.loads(l)
                 for l in open(ROOT / pred_path)}
        rows_neg = []
        for nid in NEG_IDS:
            r = preds.get(nid, {})
            empty = all(not r.get(k) for k in
                        ("title", "authors", "content_text", "publish_time"))
            rows_neg.append({"id": nid, "rejected": bool(r.get("rejected")),
                             "correct_refusal": bool(r.get("rejected")) or empty})
        neg = {"n_correct": sum(x["correct_refusal"] for x in rows_neg),
               "n_total": len(rows_neg), "rows": rows_neg}

    timing = {
        "wall_seconds": round(wall, 3),
        "n_pages": n_written,
        "pages_per_min": round(n_written / wall * 60, 1) if wall else None,
        "page_time_ms_mean": round(sum(page_times) / len(page_times) * 1000, 2),
        "page_time_ms_max": round(max(page_times) * 1000, 2),
        "layers": layers,
        "peak_rss_mb": round(peak_rss_mb, 1),
    }
    cost = {
        "rule_pages_per_min": None,  # 由 layers 估算（非模型页）
        "model_pages_per_min": None,
        "model": model_stats,
        "note": "规则/通用库=CPU 本地零边际成本；模型=本地 ollama（开源模型，"
                "推理零 API 费用，成本为时延与统一内存占用）",
    }
    if model_stats:
        mt = model_stats.get("total_seconds", 0)
        if model_stats.get("n_pages") and mt:
            cost["model_pages_per_min"] = round(
                model_stats["n_pages"] / mt * 60, 2)
    rule_seconds = wall - ((model_stats or {}).get("total_seconds") or 0)
    n_rule_pages = n_written - ((model_stats or {}).get("n_pages") or 0)
    if n_rule_pages and rule_seconds:
        cost["rule_pages_per_min"] = round(n_rule_pages / rule_seconds * 60, 1)

    record = {
        "version": args.version,
        "note": args.note,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": {"commit": commit, "dirty_at_run": dirty,
                "extractor": args.extractor},
        "hardware": hw_info(),
        "groups": args.groups,
        "timing": timing,
        "cost": cost,
        "scores": compact_scores(scores) if scores else None,
        "negative_check": neg,
    }
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ---- 控制台摘要 ----
    print(f"== {args.version} ({commit}{' [dirty]' if dirty else ''}) "
          f"{n_written} 页 / {wall:.1f}s / {timing['pages_per_min']} 页每分钟 "
          f"/ peak RSS {timing['peak_rss_mb']}MB")
    if scores:
        ov = scores["overall"]
        print(f"   title {ov['title_exact']:.3f} | authors {ov['authors_f1']:.3f} "
              f"| publish {ov['time']['publish_time']['score']:.3f} "
              f"| update {ov['time']['update_time']['score']:.3f} "
              f"| content {ov['content_f1']:.3f} "
              f"| 拒识 {ov.get('rejection_accuracy')}")
    if neg:
        print(f"   负例拒识 {neg['n_correct']}/{neg['n_total']}")
    print(f"   → {HISTORY.relative_to(ROOT)} 已追加；pred={pred_path} "
          f"scores={scores_path if scores else '(未评分)'}")


if __name__ == "__main__":
    main()
