#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handcheck_draft.py — eval_spec_v2.md 手算例子验算脚本（草稿）

用途：在冻结 eval_spec_v2 之前，用代码验证规范中 13 个手算场景的全部断言
算术自洽（字符 3-gram 多重集 F1、dup_ratio、lcs_f1、作者集合 F1、时间按
gold 精度比较等）。本脚本通过 = 规范中的手算数字可信；后续 score_v2.py 的
单元测试应覆盖同一批场景。

运行：python handcheck_draft.py   （无第三方依赖，标准库即可）
退出码：全部断言通过为 0，任一失败为 1。
"""

import re
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

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


# ---------------------------------------------------------------------------
# 规范化与指标定义（与 eval_spec_v2.md §3/§4 一致）
# ---------------------------------------------------------------------------

def norm_text(s):
    """主规范化：NFKC + casefold + 删除全部空白字符。"""
    s = unicodedata.normalize("NFKC", s).casefold()
    return "".join(s.split())


def trigram_multiset(s):
    """字符 3-gram 多重集；长度 <3 的文本退化为全串单元素集合。"""
    if len(s) < 3:
        return Counter({s}) if s else Counter()
    return Counter(s[i:i + 3] for i in range(len(s) - 2))


def multiset_prf(pred_ms, gold_ms):
    """多重集 P/R/F1：交集大小按 min(count) 计。"""
    common = sum((pred_ms & gold_ms).values())
    tp, tg = sum(pred_ms.values()), sum(gold_ms.values())
    p = common / tp if tp else 0.0
    r = common / tg if tg else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def content_f1(pred, gold):
    """content 主指标：规范化后字符 3-gram 多重集 F1。"""
    return multiset_prf(trigram_multiset(norm_text(pred)),
                        trigram_multiset(norm_text(gold)))


def lcs_f1(pred, gold):
    """顺序敏感诊断：字符级 LCS 长度（SequenceMatcher matching_blocks）的 F1。"""
    a, b = norm_text(pred), norm_text(gold)
    m = SequenceMatcher(None, a, b, autojunk=False)
    common = sum(blk.size for blk in m.get_matching_blocks())
    if not a and not b:
        return None  # 双端皆空
    return 2 * common / (len(a) + len(b)) if (len(a) + len(b)) else 0.0


def dup_ratio(pred):
    """重复诊断：pred 3-gram 多重集中"重复出现"的比例 = (总数-去重数)/总数。"""
    ms = trigram_multiset(norm_text(pred))
    total = sum(ms.values())
    if total == 0:
        return 0.0
    return (total - len(ms)) / total


def num_f1(pred, gold):
    """关键数字保真诊断：数字串（\\d+(\\.\\d+)?）多重集 F1。"""
    np_ = Counter(re.findall(r"\d+(?:\.\d+)?", norm_text(pred)))
    ng = Counter(re.findall(r"\d+(?:\.\d+)?", norm_text(gold)))
    if not np_ and not ng:
        return None
    return multiset_prf(np_, ng)[2]


def para_ratio(pred, gold):
    """段落结构诊断：段落数之比 min/max（段落 = 1 个以上换行分隔）。"""
    def npara(s):
        return len([x for x in re.split(r"\n+", s.strip()) if x.strip()])
    a, b = npara(pred), npara(gold)
    if a == 0 and b == 0:
        return None
    if a == 0 or b == 0:
        return 0.0
    return min(a, b) / max(a, b)


# --- 作者 -----------------------------------------------------------------

AUTHOR_PREFIXES = ["记者", "通讯员", "作者", "执笔", "by"]


def norm_author(name):
    """作者名归一化：NFKC+casefold、剥角色括号、剥署名前缀、去全部空白。"""
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
    """作者集合 F1。返回 (f1, P, R)；双端皆空返回 (None, None, None)。"""
    ps = {norm_author(x) for x in (pred_list or []) if norm_author(x)}
    gs = {norm_author(x) for x in (gold_list or []) if norm_author(x)}
    if not ps and not gs:
        return None, None, None                  # correct_empty
    if not ps or not gs:
        return 0.0, 0.0, 0.0                     # 误填或漏提
    common = len(ps & gs)
    p, r = common / len(ps), common / len(gs)
    return 2 * p * r / (p + r), p, r


# --- 时间 -----------------------------------------------------------------

_TIME_COMPONENTS = [(0, 4), (5, 7), (8, 10), (11, 13), (14, 16), (17, 19)]
_TIME_NAMES = ["year", "month", "day", "hour", "minute", "second"]


def _pad19(s):
    return (s or "").ljust(19, "X")


def time_score(pred, gold):
    """
    按 gold 精度比较：gold 中凡含 X 的分量不参与；参与分量全部相等记 1 否则 0。
    gold 无任何已知分量时返回 None（双端皆空之外的退化情形，规范要求登记）。
    pred 为 None（漏提/崩溃）计 0。
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
    """pred 发布时间等于 gold 更新时间的任何已知前缀 → 类型混淆。"""
    if not pred_publish or not gold_update:
        return False
    p, g = _pad19(pred_publish), _pad19(gold_update)
    return p[:19] == g[:19] or p[:len(gold_update.rstrip("X"))] == \
        gold_update.rstrip("X")


def tz_status(pred_offset, gold_offset):
    """时区单独统计：match / missing / mismatch / gold_absent。"""
    if gold_offset is None:
        return "gold_absent"
    if pred_offset is None:
        return "missing"
    return "match" if pred_offset == gold_offset else "mismatch"


# --- 标题 -----------------------------------------------------------------

def title_exact(pred, gold):
    if pred is None:
        return 0
    return 1 if norm_text(pred) == norm_text(gold) else 0


def title_sim(pred, gold):
    if pred is None:
        return 0.0
    return content_f1(pred, gold)[2]


# ===========================================================================
# 13 个手算场景
# ===========================================================================

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
    # gold 6 个 3-gram，pred 2 个，交集 2 → P=1, R=1/3, F1=0.5
    check("S2.precision", p, 1.0)
    check("S2.recall", r, 1 / 3)
    check("S2.f1", f, 0.5)

    print("== S3 混入导航：pred 'abcdef导航栏' vs gold 'abcdef' ==")
    p, r, f = content_f1("abcdef导航栏", "abcdef")
    # gold 4 个 3-gram，pred 7 个，交集 4 → P=4/7, R=1, F1=8/11
    check("S3.precision", p, 4 / 7)
    check("S3.recall", r, 1.0)
    check("S3.f1", f, 8 / 11)
    check("S3.f1_value", f, 0.7273, tol=5e-5)

    print("== S4 重复一遍：pred 'abcdabcd' vs gold 'abcd' ==")
    p, r, f = content_f1("abcdabcd", "abcd")
    # pred 6 个 3-gram（abc×2 bcd×2 cda dab），交集 2 → P=1/3, R=1, F1=0.5
    check("S4.precision", p, 1 / 3)
    check("S4.recall", r, 1.0)
    check("S4.f1", f, 0.5)
    check("S4.dup_ratio", dup_ratio("abcdabcd"), 1 / 3)

    print("== S5 乱序：pred 'efghabcd' vs gold 'abcdefgh' ==")
    p, r, f = content_f1("efghabcd", "abcdefgh")
    # 交集 4（efg fgh abc bcd），各 6 个 → F1=2/3；LCS=4 → lcs_f1=0.5 < 2/3
    check("S5.f1", f, 2 / 3)
    check("S5.lcs_f1", lcs_f1("efghabcd", "abcdefgh"), 0.5)
    check("S5.lcs_below_main", lcs_f1("efghabcd", "abcdefgh") < f, True)

    print("== S6 作者误填 / 双端皆空 ==")
    f, _, _ = authors_f1(["张三"], [])
    check("S6.false_fill_f1", f, 0.0)
    check("S6.false_fill_flag", (authors_f1(["张三"], [])[0] == 0.0), True)
    f2, _, _ = authors_f1([], [])
    check("S6.correct_empty_is_None", f2, None)   # 不进分母，单独计 correct_empty

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
    # 宏平均演示：1 页崩溃 + 1 页全对 → title 宏平均 = (0+1)/2 = 0.5
    check("S12.macro_avg", (0 + 1) / 2, 0.5)

    print("== S13 标题多后缀：pred '美联储宣布加息_新浪财经' ==")
    check("S13.exact", title_exact("美联储宣布加息_新浪财经", "美联储宣布加息"), 0)
    # gold 5 个 3-gram，pred 10 个，交集 5 → sim = 10/15 = 2/3
    check("S13.sim", title_sim("美联储宣布加息_新浪财经", "美联储宣布加息"), 2 / 3)
    check("S13.sim_high_but_not_exact",
          title_sim("美联储宣布加息_新浪财经", "美联储宣布加息") > 0.5, True)

    print(f"\n断言合计：{PASS + FAIL}（通过 {PASS}，失败 {FAIL}）")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
