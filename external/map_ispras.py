#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
map_ispras.py — ISPRAS 节点级标注 → 本项目字段级 gold 映射器

输入：external/ispras_sample_en.jsonl（sample_ispras.py 产出，
      每行 {"uuid","url","html","annotations":[{"xpath","text","label"}...],"_site"}）
输出：
  external/ispras_gold_en.json   — 与 gold/gold_generic.json 同构（顶层 list）
  external/ispras_index.jsonl    — extract.py 输入索引（id/group/site/path）
  external/html/<id>.html        — 原始页面 HTML（UTF-8 bytes 原样落盘）
  并打印/落盘 changelog：日期归一化决策、无法解析项、"Updated" 归类等。

映射规则（如实记录）：
  title     : label==title 节点按标注序 " " 连接（多节点记在 provenance 计数）
  authors   : label==author 节点文本有序去重 → 列表；无节点 → null
  date      : label==publication_date 节点；文本含 ^Updated / Updated: → update_time，
              其余第一个 → publish_time（多余非 Updated 节点记 changelog）。
              解析用 dateutil(fuzzy)；斜杠/点分隔数字日期按"某段>12"判 dayfirst，
              无法判定按 month-first（美国序）并记 changelog。缺年时间 → XXXX 占位；
              无时分秒 → XX 占位；GMT±n / (XXX) 时区尽力转 utc_offset。
  text      : label==text 节点按标注序 "\n" 连接 → content_text
  tag/category: 我们的 field_spec 无此字段 → 仅落入 provenance，不进评分字段
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from dateutil import parser as dtparser

ROOT = Path(__file__).resolve().parent.parent  # html-extract/

CHANGELOG = []


def log_change(kind, msg):
    CHANGELOG.append({"kind": kind, "msg": msg})


MONTHS = ("january february march april may june july august september "
          "october november december jan feb mar apr jun jul aug sep sept "
          "oct nov dec").split()

_TZ_NAMED = {
    "GMT": 0, "UTC": 0, "BST": 1, "EAT": 3, "BJT": 8, "CET": 1, "CEST": 2,
    "EST": -5, "EDT": -4, "PST": -8, "PDT": -7, "IST": 5.5, "MSK": 3,
    "DILI": 9, "AEST": 10, "KST": 9, "JST": 9, "SGT": 8, "WAT": 1,
    "CAT": 2, "EET": 2, "EEST": 3, "AST": 3, "GMT+3": 3,
}


def _off_str(hours):
    sign = "+" if hours >= 0 else "-"
    h = abs(hours)
    hi = int(h)
    mi = int(round((h - hi) * 60))
    return f"{sign}{hi:02d}:{mi:02d}"


def _numeric_order_hint(s):
    """数字日期 dd/mm/yyyy vs mm/dd/yyyy：返回 'dayfirst'/'monthfirst'/None。"""
    m = re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b", s)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a > 12 and b <= 12:
        return "dayfirst"
    if b > 12 and a <= 12:
        return "monthfirst"
    return None


def parse_ispras_date(text, page_id):
    """ISPRAS 日期文本 → {"value","utc_offset","utc_offset_source"} | None。"""
    if not text or not text.strip():
        return None
    raw = text.strip()
    s = raw
    # 常见包裹噪声：竖线、星期、"Published on:"、"Source:xxx"、尾缀 "- Article"
    s = re.sub(r"(?i)\bpublished\s*(on)?\s*:?\s*", "", s)
    s = re.sub(r"(?i)\bposted\s*:?\s*", "", s)
    s = re.sub(r"(?i)\bupdated\s*:?\s*", "", s)
    s = re.sub(r"(?i)^source\s*:\s*\S+\s*", "", s)
    s = re.sub(r"(?i)\s*-\s*article\s*$", "", s)
    s = re.sub(r"(?i)(monday|tuesday|wednesday|thursday|friday|saturday|sunday),?", "", s)
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)          # 1st July → 1 July
    s = re.sub(r"\s*\|\s*\d+\s*min read\s*$", "", s, flags=re.I)
    s = re.sub(r"AD\s*ـ.*$", "", s)                        # 阿语历对照尾缀
    s = s.strip(" |,\t")

    # 时区：GMT+n / (EAT) / 尾缀命名时区
    utc_offset = None
    m = re.search(r"GMT\s*([+-]\d{1,2})(?::(\d{2}))?", s, re.I)
    if m:
        h = int(m.group(1)) + (int(m.group(2) or 0) / 60) * (1 if int(m.group(1)) >= 0 else -1)
        utc_offset = _off_str(h)
        s = (s[:m.start()] + s[m.end():]).strip()
    else:
        m = re.search(r"\(([A-Z]{2,5})\)\s*$", s) or re.search(r"\b([A-Z]{2,5})\s*$", s)
        if m and m.group(1) in _TZ_NAMED:
            utc_offset = _off_str(_TZ_NAMED[m.group(1)])
            s = (s[:m.start()] + s[m.end():]).strip()
    s = s.strip(" -|,")

    # 含非英文月份名（俄/西等混入）→ 判不可解析
    if re.search(r"[а-яА-Я]", s) or re.search(r"\b(de|de\s+junio)\b", s) and \
            not re.search(r"(?i)" + "|".join(MONTHS), s):
        log_change("date_unparseable", f"{page_id}: 非英文月份 {raw!r}")
        return None

    has_hm = bool(re.search(r"\b\d{1,2}:\d{2}\b", s))
    has_sec = bool(re.search(r"\b\d{1,2}:\d{2}:\d{2}\b", s))
    has_year = bool(re.search(r"\b(19|20)\d{2}\b", s))
    hint = _numeric_order_hint(s)
    dayfirst = hint == "dayfirst"
    if hint is None and re.search(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b", s):
        log_change("date_ambiguous_numeric",
                   f"{page_id}: 数字日期顺序不可判，按 month-first 解析 {raw!r}")
    try:
        dt = dtparser.parse(s, fuzzy=True, dayfirst=dayfirst,
                            default=None)
    except (ValueError, OverflowError):
        dt = None
    if dt is None:
        # 兜底：长段落里搜一个 dd.mm.yyyy / dd/mm/yyyy 数字日期（标注噪声整段落入）
        m = re.search(r"\b(\d{1,2})[./](\d{1,2})[./]((?:19|20)\d{2})\b", s)
        if m:
            d_, mo_, y_ = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if mo_ > 12:
                d_, mo_ = mo_, d_
            log_change("date_regex_fallback",
                       f"{page_id}: 段落噪声中正则兜底取 {y_}-{mo_:02d}-{d_:02d} {raw[:40]!r}")
            return {"value": f"{y_:04d}-{mo_:02d}-{d_:02d} XX:XX:XX",
                    "utc_offset": utc_offset, "utc_offset_source": None}
        log_change("date_unparseable", f"{page_id}: dateutil 失败 {raw!r}")
        return None

    year = f"{dt.year:04d}" if has_year else "XXXX"
    if not has_year:
        log_change("date_no_year", f"{page_id}: 缺年份，XXXX 占位 {raw!r}")
    hh = f"{dt.hour:02d}" if has_hm else "XX"
    mm = f"{dt.minute:02d}" if has_hm else "XX"
    ss = f"{dt.second:02d}" if has_sec else "XX"
    value = f"{year}-{dt.month:02d}-{dt.day:02d} {hh}:{mm}:{ss}"
    return {"value": value, "utc_offset": utc_offset, "utc_offset_source": None}


def is_update_date(text):
    return bool(re.match(r"(?i)^\s*updated\b", text or "")) or \
        bool(re.search(r"(?i)\bupdated\s*:", text or ""))


def dedupe(seq):
    seen, out = set(), []
    for x in seq:
        k = x.strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def map_page(rec, html_dir):
    site = rec["_site"]
    uuid = rec["uuid"]
    page_id = f"ispras__{site.replace('.', '_')}__{uuid[:8]}"
    anns = rec.get("annotations", [])

    html_bytes = rec["html"].encode("utf-8")
    rel_path = f"external/html/{page_id}.html"
    (html_dir / f"{page_id}.html").write_bytes(html_bytes)

    by_label = {}
    for a in anns:
        by_label.setdefault(a.get("label"), []).append(a)

    prov = {}
    # title
    titles = [a["text"].strip() for a in by_label.get("title", []) if a["text"].strip()]
    title = " ".join(dedupe(titles)) or None
    if titles:
        prov["title"] = [a["xpath"] for a in by_label["title"]]
        if len(titles) > 1:
            log_change("title_multi", f"{page_id}: {len(titles)} 个 title 节点已 ' ' 连接")

    # authors
    authors = dedupe([a["text"].strip() for a in by_label.get("author", [])]) or None
    if authors:
        prov["authors"] = [a["xpath"] for a in by_label["author"]]

    # date
    publish_time, update_time = None, None
    date_nodes = by_label.get("publication_date", [])
    non_upd = []
    for a in date_nodes:
        t = a["text"]
        if is_update_date(t):
            if update_time is None:
                update_time = parse_ispras_date(t, page_id)
                prov["update_time"] = [a["xpath"]]
                log_change("date_as_update", f"{page_id}: 'Updated' 标注归入 update_time: {t!r}")
            else:
                log_change("date_extra_update", f"{page_id}: 多个 Updated 节点，取首个")
        else:
            non_upd.append(a)
    if non_upd:
        publish_time = parse_ispras_date(non_upd[0]["text"], page_id)
        prov["publish_time"] = [a["xpath"] for a in non_upd]
        if len(non_upd) > 1:
            log_change("date_multi", f"{page_id}: {len(non_upd)} 个 date 节点，publish 取首个")

    # content
    texts = [a["text"].strip("\n") for a in by_label.get("text", []) if a["text"].strip()]
    content = "\n".join(texts) or None
    if texts:
        prov["content_text"] = [a["xpath"] for a in by_label["text"]]

    # tags/categories 仅记 provenance
    for lab in ("tag", "category"):
        if by_label.get(lab):
            prov[f"ispras_{lab}"] = [a["text"] for a in by_label[lab]]

    gold = {
        "id": page_id,
        "dataset": "ispras_en",
        "group": "ispras",
        "site": site,
        "route": "generic",           # 全部站外页，走 generic 路由层
        "url": rec["url"],
        "path": rel_path,
        "sha1": hashlib.sha1(html_bytes).hexdigest(),
        "page_condition": "ok",
        "needs_render": False,
        "content_structure": "single",
        "expect_refusal": False,
        "title": title,
        "authors": authors,
        "publish_time": publish_time,
        "update_time": update_time,
        "content_text": content,
        "content_md": None,
        "conversion_flags": [],
        "images": None,
        "source": {"site_name": site,
                   "publisher": urlparse(rec["url"]).netloc,
                   "encoding": None},
        "provenance": prov,
        "notes": "",
    }
    index_row = {"id": page_id, "group": "ispras", "site": site, "path": rel_path}
    return gold, index_row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="external/ispras_sample_en.jsonl")
    ap.add_argument("--gold", default="external/ispras_gold_en.json")
    ap.add_argument("--index", default="external/ispras_index.jsonl")
    ap.add_argument("--changelog", default="external/logs/map_changelog.json")
    args = ap.parse_args()

    html_dir = ROOT / "external" / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    golds, indexes = [], []
    for line in open(ROOT / args.inp, encoding="utf-8"):
        rec = json.loads(line)
        g, ix = map_page(rec, html_dir)
        golds.append(g)
        indexes.append(ix)

    with open(ROOT / args.gold, "w", encoding="utf-8") as f:
        json.dump(golds, f, ensure_ascii=False, indent=1)
    with open(ROOT / args.index, "w", encoding="utf-8") as f:
        for ix in indexes:
            f.write(json.dumps(ix, ensure_ascii=False) + "\n")
    with open(ROOT / args.changelog, "w", encoding="utf-8") as f:
        json.dump(CHANGELOG, f, ensure_ascii=False, indent=1)

    n_title = sum(1 for g in golds if g["title"])
    n_auth = sum(1 for g in golds if g["authors"])
    n_pub = sum(1 for g in golds if g["publish_time"])
    n_upd = sum(1 for g in golds if g["update_time"])
    n_cont = sum(1 for g in golds if g["content_text"])
    print(f"gold pages={len(golds)} sites={len({g['site'] for g in golds})} "
          f"title={n_title} authors={n_auth} publish={n_pub} update={n_upd} "
          f"content={n_cont} changelog={len(CHANGELOG)}", file=sys.stderr)


if __name__ == "__main__":
    main()
