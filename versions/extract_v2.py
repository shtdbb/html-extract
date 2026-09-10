#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_v2.py — baseline v2：v1 + 元数据层（JSON-LD NewsArticle + OG/meta）

路由：①元数据层（JSON-LD → OG/meta）逐字段优先 → trafilatura 兜底。
相对 v1 的新增：
  - JSON-LD 解析（@type ∈ NewsArticle/Article/BlogPosting/TechArticle/ReportageNewsArticle，
    兼容 @graph 与数组；author 兼容 str/dict/list）；
  - OG/meta：og:title、article:published_time/modified_time、meta[name=author/publishdate]；
  - ISO 8601 时间归一化（含显式时区偏移提取；日期粒度 → XX:XX:XX 占位）。
已知短板（留给 v3/v4）：无站点规则、无拒识、标题后缀未剥离、meta author 垃圾未过滤、
无图片占位符、DOM 时间扫描未做。

用法同 v1：
  venv/bin/python versions/extract_v2.py --groups fixed,generic,negative --out results/v2_pred_dev.jsonl
"""
import argparse
import html as html_mod
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import chardet
import trafilatura
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent

ARTICLE_TYPES = {"newsarticle", "article", "blogposting", "techarticle",
                 "reportagenewsarticle", "scholarlyarticle", "socialmediaposting"}


def decode_declared_first(raw: bytes):
    head = raw[:4096].decode("ascii", errors="ignore")
    m = re.search(r'charset=["\']?([\w-]+)', head, re.I)
    declared = m.group(1) if m else None
    detected = chardet.detect(raw).get("encoding")
    for enc in [declared, detected, "utf-8", "gb18030"]:
        if not enc:
            continue
        try:
            return raw.decode(enc), declared, detected, enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), declared, detected, "utf-8(replace)"


# ---------------------------------------------------------------------------
# 时间归一化：ISO 8601 / 常见格式 → {"value","utc_offset","utc_offset_source"}
# ---------------------------------------------------------------------------

def parse_time_str(s):
    """解析时间串。返回 dict 或 None。未知分量 XX 占位。"""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    # ISO 8601: 2026-08-11T17:30:01+08:00 / ...Z / 2024-02-22T18:32:28+00:00
    m = re.match(
        r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?"
        r"\s*(Z|[+-]\d{2}:?\d{2})?$", s)
    if m:
        y, mo, d, h, mi, sec, tz = m.groups()
        hh = f"{int(h):02d}" if h else "XX"
        mm = f"{int(mi):02d}" if mi else "XX"
        ss = f"{int(sec):02d}" if sec else ("00" if h and mi and sec is None and False else "XX")
        value = f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {hh}:{mm}:{ss}"
        off = None
        if tz:
            off = "+00:00" if tz == "Z" else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
        return {"value": value, "utc_offset": off,
                "utc_offset_source": None}
    # gov.cn 异形：2026-07-10-20:28:00
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})-(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$", s)
    if m:
        y, mo, d, h, mi, sec = (int(x) for x in m.groups() if x is not None)
        ss = f"{sec:02d}" if sec is not None else "XX"
        return {"value": f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{ss}",
                "utc_offset": None, "utc_offset_source": None}
    return None


# ---------------------------------------------------------------------------
# 元数据层：JSON-LD + OG/meta
# ---------------------------------------------------------------------------

def _iter_jsonld_nodes(obj):
    """拍平 JSON-LD：数组、@graph。"""
    if isinstance(obj, list):
        for x in obj:
            yield from _iter_jsonld_nodes(x)
    elif isinstance(obj, dict):
        yield obj
        graph = obj.get("@graph")
        if isinstance(graph, list):
            for x in graph:
                yield from _iter_jsonld_nodes(x)


def parse_metadata_layer(soup):
    """返回 {title, authors, publish_time, update_time, provenance} 候选。"""
    out = {"title": None, "authors": None, "publish_time": None,
           "update_time": None, "provenance": {}}

    # --- JSON-LD ---
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _iter_jsonld_nodes(data):
            t = node.get("@type")
            types = {str(x).lower() for x in (t if isinstance(t, list) else [t])}
            if not types & ARTICLE_TYPES:
                continue
            if not out["title"] and node.get("headline"):
                # script 为 CDATA，bs4 不做实体解码，需手工 unescape（D-002）
                out["title"] = html_mod.unescape(str(node["headline"])).strip()
                out["provenance"]["title"] = "json-ld:headline"
            au = node.get("author")
            if not out["authors"] and au:
                names = []
                items = au if isinstance(au, list) else [au]
                for a in items:
                    if isinstance(a, dict):
                        nm = a.get("name")
                        if nm:
                            names.append(html_mod.unescape(str(nm)).strip())
                    elif isinstance(a, str) and a.strip():
                        names.append(html_mod.unescape(a).strip())
                if names:
                    out["authors"] = names
                    out["provenance"]["authors"] = "json-ld:author"
            if not out["publish_time"] and node.get("datePublished"):
                pt = parse_time_str(str(node["datePublished"]))
                if pt:
                    out["publish_time"] = pt
                    out["provenance"]["publish_time"] = "json-ld:datePublished"
            if not out["update_time"] and node.get("dateModified"):
                ut = parse_time_str(str(node["dateModified"]))
                if ut:
                    out["update_time"] = ut
                    out["provenance"]["update_time"] = "json-ld:dateModified"

    # --- OG / meta ---
    def meta_val(*keys):
        for k in keys:
            tag = soup.find("meta", attrs={"property": k}) or \
                  soup.find("meta", attrs={"name": k})
            if tag and tag.get("content", "").strip():
                return tag["content"].strip(), k
        return None, None

    if not out["title"]:
        v, k = meta_val("og:title", "twitter:title")
        if v:
            out["title"] = v
            out["provenance"]["title"] = f"meta:{k}"
    if not out["publish_time"]:
        v, k = meta_val("article:published_time", "og:release_date",
                        "publishdate", "pubdate", "date", "firstpublishedtime")
        if v:
            pt = parse_time_str(v)
            if pt:
                out["publish_time"] = pt
                out["provenance"]["publish_time"] = f"meta:{k}"
    if not out["update_time"]:
        v, k = meta_val("article:modified_time", "lastmodifiedtime")
        if v:
            ut = parse_time_str(v)
            if ut:
                out["update_time"] = ut
                out["provenance"]["update_time"] = f"meta:{k}"
    if not out["authors"]:
        v, k = meta_val("article:author", "author")
        if v:
            names = [a.strip() for a in re.split(r"[,;，、；]", v) if a.strip()]
            if names:
                out["authors"] = names
                out["provenance"]["authors"] = f"meta:{k}"
    return out


def norm_traf_date(s):
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s.strip())
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    return {"value": f"{y:04d}-{mo:02d}-{d:02d} XX:XX:XX",
            "utc_offset": None, "utc_offset_source": None}


def extract_page(raw: bytes):
    html, declared, detected, used = decode_declared_first(raw)
    rec = {
        "title": None, "authors": None,
        "publish_time": None, "update_time": None,
        "content_text": None, "content_md": None,
        "images": None, "conversion_flags": [],
        "page_condition": "ok", "needs_render": False,
        "content_structure": "single",
        "source": {"encoding": {"declared": declared, "detected": detected,
                                "used": used}},
        "provenance": {}, "route": "metadata+trafilatura",
    }
    soup = BeautifulSoup(html, "lxml")
    meta = parse_metadata_layer(soup)

    try:
        doc = trafilatura.bare_extraction(
            html, with_metadata=True, include_comments=False,
            include_tables=True)
    except Exception:  # noqa: BLE001
        doc = None

    # 逐字段装配：元数据层优先 → trafilatura 兜底
    if meta["title"]:
        rec["title"] = meta["title"]
        rec["provenance"]["title"] = meta["provenance"]["title"]
    elif doc is not None and doc.title:
        rec["title"] = doc.title.strip()
        rec["provenance"]["title"] = "trafilatura:document.title"

    if meta["authors"]:
        rec["authors"] = meta["authors"]
        rec["provenance"]["authors"] = meta["provenance"]["authors"]
    elif doc is not None and doc.author:
        rec["authors"] = [a.strip() for a in re.split(r"[,;，；]", doc.author) if a.strip()]
        rec["provenance"]["authors"] = "trafilatura:document.author"

    for field, mkey in (("publish_time", "publish_time"),
                        ("update_time", "update_time")):
        if meta[mkey]:
            rec[field] = meta[mkey]
            rec["provenance"][field] = meta["provenance"][field]
        elif field == "publish_time" and doc is not None and doc.date:
            rec[field] = norm_traf_date(doc.date)
            rec["provenance"][field] = "trafilatura:document.date(htmldate)"

    if doc is not None and doc.text:
        text = re.sub(r"\n{3,}", "\n\n", doc.text.strip())
        rec["content_text"] = text
        rec["content_md"] = text
        rec["provenance"]["content_text"] = "trafilatura:document.text"
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="dataset_index.jsonl")
    ap.add_argument("--groups", default="fixed,generic,negative")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    groups = set(args.groups.split(","))
    rows = [json.loads(l) for l in open(ROOT / args.index, encoding="utf-8")]
    n = 0
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            if r["group"] not in groups:
                continue
            raw = (ROOT / r["path"]).read_bytes()
            rec = {"id": r["id"], **extract_page(raw)}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"v2: wrote {n} records -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
