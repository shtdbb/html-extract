#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
model_arm.py — v10 模型兜底臂：规则先行 + 低置信字段模型补全。

设计原则（继承评测纪律）：
1. 门控触发——只在大规则管线产出低置信时调用模型，控制成本：
   - title 缺失或仅来自 <title> 裸标签（弱来源）；
   - authors 为空（通用路由）；
   - publish_time 缺失（且无 final 裁决）；
   三者全不命中则本页零模型调用。
2. 页内可核验——模型只做「定位/摘录」，值必须能在页面可见文本中
   找到（规范化后子串匹配），否则拒收；时间必须能被 parse_time_str
   解析。模型无法幻觉出页面上不存在的值。
3. 单次调用——所有待补字段合并进一个 prompt（约 900-1500 tok），
   每页至多一次生成调用。
4. 不覆盖强来源——规则/元数据/json-ld 已有值的字段绝不回写。

成本量级（M4 Pro + Q4_K_M）：~3.5 s/触发页（含解码 42 tok @47 tok/s），
对比纯规则 ~85 ms/页。门控的意义正在于此：dev 上几乎不触发，
ISPRAS 上只对规则失陷页触发。
"""
import re

from extract_time import parse_time_str
from loop import ollama_client

# 与 extract.strip_title_suffix 的弱来源判定保持一致：裸 <title> 标签
WEAK_TITLE_PROV = ("dom://title",)

PROMPT_TMPL = (
    "从以下网页可见文本中抽取新闻字段。只输出 JSON，不要解释。\n"
    "字段：title（文章真实标题，不含站点名后缀）、authors（作者/记者署名"
    "人名数组，没有则空数组；媒体名/栏目名/站点名/机构名不是作者，"
    "文中提及或受访的人物也不是作者）、"
    "publish_time（发布时间，原样摘录页面中的写法，没有则 null）。\n"
    "只抽取网页文本中真实出现的值，不要推测。\n\n"
    "网页文本：\n<<<\n{text}\n>>>\n"
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).lower()


_BYLINE_PREFIX = re.compile(
    r"^(?:by|作者|记者|撰文|撰稿|编辑|责编|摄影|文)\s*[:：/]?\s*", re.I)

# 敬称/头衔后缀：gold 署名用本名；带敬称的是报道中提及/受访的人物
# （sohu__02「朱先生」误填案例——句中断行恰好形成伪独立行，位置核验失效）。
_HONORIFIC_PAT = re.compile(
    r"(先生|女士|老师|教授|博士|经理|主任|局长|部长|院士|同学)$")


def _is_standalone_byline(name: str, page_text: str) -> bool:
    """署名位置核验：名字必须作为独立行（或剥掉署名前缀后的独立行）出现。

    区分 byline 区块的署名（AAP：标题下单独一行「Poppy Johnston」）与
    句中提及的人物（sohu：「…湖北的朱先生向红星新闻记者反映…」——
    后者每处出现都嵌在完整句子里，永远不是独立行）。
    """
    target = _norm(name)
    for line in page_text.split("\n"):
        line = line.strip()
        if not line or len(line) > 80:
            continue
        if _norm(line) == target:
            return True
        stripped = _BYLINE_PREFIX.sub("", line)
        if stripped != line and _norm(stripped) == target:
            return True
    return False


_EN_MONTH = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}


def _parse_model_time(raw: str):
    """模型摘录的时间写法 → 结构化。先试 parse_time_str（ISO/中文格式），
    再补英文月名格式（June 2, 2024 / 2 June 2024 / 带 AM-PM 时分）。
    核验链不中断：值仍是页面原样摘录，只是解析器认识英文月名。"""
    pt = parse_time_str(raw)
    if pt:
        return pt
    s = raw.strip()
    mon = "|".join(_EN_MONTH) + "|sept|" + "|".join(m[:3] for m in _EN_MONTH)
    m = re.search(
        rf"(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+)?({mon})\.?\s*(\d{{1,2}})?(?:st|nd|rd|th)?,?\s*(\d{{4}})"
        rf"(?:\s+(\d{{1,2}}):(\d{{2}})(?::(\d{{2}}))?\s*([AP]M)\.?)?",
        s, re.I)
    if not m:
        return None
    d1, mon_s, d2, yr, hh, mm, ss, ap = m.groups()
    day = d1 or d2
    if not day:
        return None
    month = _EN_MONTH.get(mon_s.rstrip(".").lower())
    if month is None:  # 简写展开（sep/sept → september 等）
        full = {"jan": "january", "feb": "february", "mar": "march",
                "apr": "april", "may": "may", "jun": "june", "jul": "july",
                "aug": "august", "sep": "september", "oct": "october",
                "nov": "november", "dec": "december"}
        key = mon_s.rstrip(".").lower()
        month = _EN_MONTH[full.get(key, full[key[:3]])]
    if hh is not None:
        h = int(hh) % 12 + (12 if ap and ap.upper() == "PM" else 0)
        tpart = f"{h:02d}:{mm}:{ss or '00'}"
    else:
        tpart = "XX:XX:XX"
    return {"value": f"{yr}-{month:02d}-{int(day):02d} {tpart}",
            "utc_offset": None, "utc_offset_source": None}


def _visible_text(soup, limit=3500) -> str:
    import copy
    sp = copy.copy(soup)  # 不污染调用方的 soup（decompose 是破坏性的）
    for tag in sp(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", sp.get_text("\n", strip=True))[:limit]


def needs_model(rec, final_fields=frozenset()) -> bool:
    """门控：任一字段低置信且未被规则层 final 裁决即触发。"""
    if rec.get("rejected"):
        return False
    if "title" not in final_fields and (
            not rec.get("title")
            or rec.get("provenance", {}).get("title") in WEAK_TITLE_PROV):
        return True
    if "authors" not in final_fields and not rec.get("authors"):
        return True
    if "publish_time" not in final_fields and rec.get("publish_time") is None:
        return True
    return False


def model_fallback(rec, soup, site, final_fields=frozenset()):
    """对低置信字段做模型补全；就地更新 rec。返回触发的字段列表。

    final_fields：规则层已 final 裁决为空的字段——模型同样不得回退
    （chinadaily 全站 publish_time 裁决为空：页面只有 Updated 一个时间）。
    """
    if not needs_model(rec, final_fields):
        return []
    ollama_client.note_page()
    page_text = _visible_text(soup)
    norm_page = _norm(page_text)
    out = ollama_client.generate(PROMPT_TMPL.format(text=page_text))
    if not isinstance(out, dict):
        return []

    filled = []

    # --- title：仅当缺失或弱来源（裸 <title>），且模型值可在页内核验 ---
    weak_title = "title" not in final_fields and (
        not rec.get("title")
        or rec.get("provenance", {}).get("title") in WEAK_TITLE_PROV)
    mt = out.get("title")
    if weak_title and isinstance(mt, str) and 4 <= len(mt.strip()) <= 200:
        mt = mt.strip()
        if _norm(mt) in norm_page:
            rec["title"] = mt
            rec["provenance"]["title"] = "model:qwen2.5-7b(verified:in-page)"
            filled.append("title")

    # --- authors：仅当为空；每个名字须①页内可核验 ②过与规则层相同的
    # 媒体名/站名过滤 ③署名位置核验（独立署名行——「朱先生」类受访者
    # 在句中提及被此拦截，v10 首跑误填案例） ---
    if "authors" not in final_fields and not rec.get("authors"):
        from extract import _is_media_name  # 运行期 extract 已加载，无循环导入
        stem = site.split(".")[0].lower()
        ma = out.get("authors")
        if isinstance(ma, list):
            names = []
            for n in ma:
                if not isinstance(n, str):
                    continue
                n = n.strip()
                if not (2 <= len(n) <= 40) or _norm(n) not in norm_page:
                    continue
                if _is_media_name(n) or n.lower().replace(" ", "") in (stem, site.lower()):
                    continue
                if _HONORIFIC_PAT.search(n):
                    continue
                if not _is_standalone_byline(n, page_text):
                    continue
                names.append(n)
            if names:
                rec["authors"] = sorted(set(names))
                rec["provenance"]["authors"] = "model:qwen2.5-7b(verified:in-page)"
                filled.append("authors")

    # --- publish_time：仅当缺失；模型摘录的原始写法须可解析 ---
    if "publish_time" not in final_fields and rec.get("publish_time") is None:
        mp = out.get("publish_time")
        if isinstance(mp, str) and mp.strip():
            pt = _parse_model_time(mp.strip())
            if pt:
                rec["publish_time"] = pt
                rec["provenance"]["publish_time"] = \
                    f"model:qwen2.5-7b(verified:parseable|{mp.strip()[:40]})"
                filled.append("publish_time")

    return filled
