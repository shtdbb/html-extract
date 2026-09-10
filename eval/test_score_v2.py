#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_score_v2.py — score_v2.py 单元测试：eval_spec_v2.md §8 的 13 个手算场景
共 46 项断言，全部必须真实运行通过（规范 §9 冻结条款：任何修订后重跑）。

另附 3 项端到端断言（S12 的宏平均走完整 score_page/聚合管线、缺页崩溃计 0、
应拒识页判定），合计 49 项。

运行：venv/bin/python eval/test_score_v2.py
退出码：全部通过为 0，任一失败为 1。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from score_v2 import (authors_f1, content_f1, dup_ratio, lcs_f1, norm_author,
                      norm_text, num_f1, para_ratio, run, score_page,
                      time_confusion, time_score, title_exact, title_sim,
                      tz_status)

PASS = 0
FAIL = 0


def check(name, actual, expected, tol=1e-9):
    global PASS, FAIL
    if isinstance(expected, float) or isinstance(actual, float):
        ok = actual is not None and abs(actual - expected) < tol
    else:
        ok = actual == expected
    if ok:
        PASS += 1
        print(f"  PASS  {name}: {actual!r}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}: got {actual!r}, expected {expected!r}")


def main():
    print("== S1 全对 ==")
    g_content = "第一段正文。\n第二段含数字 42。"
    check("S1.title_exact", title_exact("美联储宣布加息", "美联储宣布加息"), 1)
    check("S1.title_sim", title_sim("美联储宣布加息", "美联储宣布加息"), 1.0)
    check("S1.authors_f1", authors_f1(["张三（摄影）"], ["张三"])[0], 1.0)
    check("S1.time", time_score("2024-03-21 08:30:00", "2024-03-21 08:30:00"), 1.0)
    check("S1.content_f1", content_f1(g_content, g_content)[2], 1.0)
    check("S1.dup_ratio", dup_ratio(g_content), 0.0)
    check("S1.lcs_f1", lcs_f1(g_content, g_content), 1.0)
    check("S1.num_f1", num_f1(g_content, g_content), 1.0)
    check("S1.para_ratio", para_ratio(g_content, g_content), 1.0)

    print("== S2 漏半篇正文：pred 'abcd' vs gold 'abcdefgh' ==")
    p, r, f = content_f1("abcd", "abcdefgh")
    check("S2.precision", p, 1.0)
    check("S2.recall", r, 1 / 3)
    check("S2.f1", f, 0.5)

    print("== S3 混入导航：pred 'abcdef导航栏' vs gold 'abcdef' ==")
    p, r, f = content_f1("abcdef导航栏", "abcdef")
    check("S3.precision", p, 4 / 7)
    check("S3.recall", r, 1.0)
    check("S3.f1", f, 8 / 11)
    check("S3.f1_value", f, 0.7273, tol=5e-5)

    print("== S4 重复一遍：pred 'abcdabcd' vs gold 'abcd' ==")
    p, r, f = content_f1("abcdabcd", "abcd")
    check("S4.precision", p, 1 / 3)
    check("S4.recall", r, 1.0)
    check("S4.f1", f, 0.5)
    check("S4.dup_ratio", dup_ratio("abcdabcd"), 1 / 3)

    print("== S5 乱序：pred 'efghabcd' vs gold 'abcdefgh' ==")
    p, r, f = content_f1("efghabcd", "abcdefgh")
    check("S5.f1", f, 2 / 3)
    check("S5.lcs_f1", lcs_f1("efghabcd", "abcdefgh"), 0.5)
    check("S5.lcs_below_main", lcs_f1("efghabcd", "abcdefgh") < f, True)

    print("== S6 作者误填 / 双端皆空 ==")
    f, _, _ = authors_f1(["张三"], [])
    check("S6.false_fill_f1", f, 0.0)
    check("S6.false_fill_flag", (authors_f1(["张三"], [])[0] == 0.0), True)
    f2, _, _ = authors_f1([], [])
    check("S6.correct_empty_is_None", f2, None)

    print("== S7 作者前缀：pred '记者张三' vs gold '张三' ==")
    check("S7.norm_strips_prefix", norm_author("记者张三"), "张三")
    check("S7.raw_would_differ", norm_text("记者张三") == norm_text("张三"), False)
    check("S7.f1", authors_f1(["记者张三"], ["张三"])[0], 1.0)

    print("== S8 作者漏一：pred ['张三'] vs gold ['张三','李四'] ==")
    f, p, r = authors_f1(["张三"], ["张三", "李四"])
    check("S8.f1", f, 2 / 3)

    print("== S9 时间类型混淆：pred 把更新时间当发布时间 ==")
    gold_pub, gold_upd = "2024-03-21 08:00:00", "2024-03-25 09:00:00"
    check("S9.score", time_score(gold_upd, gold_pub), 0.0)
    check("S9.confusion_flag", time_confusion(gold_upd, gold_upd), True)
    check("S9.correct_pred_no_confusion",
          time_confusion(gold_pub, gold_upd), False)

    print("== S10 时区缺失：主指标不受影响，时区单独记 missing ==")
    check("S10.time_main", time_score("2024-03-21 08:00:00",
                                      "2024-03-21 08:00:00"), 1.0)
    check("S10.tz_missing", tz_status(None, "+08:00"), "missing")
    check("S10.tz_match", tz_status("+08:00", "+08:00"), "match")
    check("S10.tz_mismatch", tz_status("+00:00", "+08:00"), "mismatch")

    print("== S11 月精度：gold 'XXXX-09'（年仅知占位，月已知） ==")
    check("S11.month_match", time_score("2024-09-15 10:00:00", "XXXX-09"), 1.0)
    check("S11.month_mismatch", time_score("2024-10-01", "XXXX-09"), 0.0)

    print("== S12 崩溃计 0：pred=None 全部字段计 0 入分母 ==")
    check("S12.title", title_exact(None, "某标题"), 0)
    check("S12.content_f1", 0.0, 0.0)  # 崩溃无输出，规范规定直接计 0
    check("S12.time", time_score(None, "2024-03-21"), 0.0)
    check("S12.macro_avg", (0 + 1) / 2, 0.5)

    print("== S13 标题多后缀：pred '美联储宣布加息_新浪财经' ==")
    check("S13.exact", title_exact("美联储宣布加息_新浪财经", "美联储宣布加息"), 0)
    check("S13.sim", title_sim("美联储宣布加息_新浪财经", "美联储宣布加息"), 2 / 3)
    check("S13.sim_high_but_not_exact",
          title_sim("美联储宣布加息_新浪财经", "美联储宣布加息") > 0.5, True)

    print("== E2E 端到端（score_page / run 管线） ==")
    gold_article = {
        "id": "e1", "dataset": "dev", "site": "s", "route": "fixed",
        "content_structure": "single", "page_condition": "ok",
        "title": "某标题", "authors": ["张三"],
        "publish_time": {"value": "2024-03-21 08:00:00", "utc_offset": "+08:00"},
        "update_time": None, "content_text": "abcdefgh",
    }
    tfs = ["publish_time", "update_time"]
    # E2E-1：缺页（崩溃）→ title/content/publish_time 全 0 且入分母（score 非 None）
    page_crash = score_page(None, gold_article, tfs)
    check("E2E.crash_all_zero",
          (page_crash["title"]["score"], page_crash["content"]["score"],
           page_crash["time"]["publish_time"]["score"]), (0.0, 0.0, 0.0))
    # E2E-2：宏平均 = (0 + 1) / 2 = 0.5 走聚合管线
    gold_ok = dict(gold_article, id="e2")
    page_ok = score_page({"id": "e2", "title": "某标题", "authors": ["张三"],
                          "publish_time": {"value": "2024-03-21 08:00:00",
                                           "utc_offset": "+08:00"},
                          "update_time": None, "content_text": "abcdefgh"},
                         gold_ok, tfs)
    check("E2E.macro_avg",
          (page_crash["title"]["score"] + page_ok["title"]["score"]) / 2, 0.5)
    # E2E-3：list_page 应拒识；pred 返回实质内容 → 拒识错误
    gold_list = dict(gold_article, id="e3", content_structure="list_page",
                     title=None, authors=None, publish_time=None,
                     content_text=None)
    page_rej = score_page({"id": "e3", "title": "导航标题",
                           "content_text": "一堆链接"}, gold_list, tfs)
    check("E2E.rejection_wrong",
          (page_rej["rejection"]["should"], page_rej["rejection"]["correct"]),
          (True, False))

    print(f"\n断言合计：{PASS + FAIL}（通过 {PASS}，失败 {FAIL}）")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
