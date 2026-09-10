#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_v1.py — baseline v1：trafilatura only（无元数据层/无站点规则/无拒识）

管线：解码（声明编码优先，chardet 兜底）→ trafilatura bare_extraction
（with_metadata=True）→ 四字段直接映射。

已知短板（留给后续版本）：标题带站点后缀、author 为单串、date 只到日、
无图片占位符、无拒识（list 页/付费墙页会误抽）、无时间时分秒。

用法：
  venv/bin/python versions/extract_v1.py --index dataset_index.jsonl \
      --groups fixed,generic,negative --out results/v1_pred_dev.jsonl
"""
import argparse
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import chardet
import trafilatura

ROOT = Path(__file__).resolve().parent.parent


def decode_declared_first(raw: bytes):
    """声明编码优先、chardet 兜底；返回 (html, declared, detected, used)。"""
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


def norm_date_only(s):
    """trafilatura .date → 'YYYY-MM-DD XX:XX:XX'（日粒度，时分秒 XX 占位）。"""
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s.strip())
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d} XX:XX:XX"


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
        "provenance": {}, "route": "trafilatura",
    }
    try:
        doc = trafilatura.bare_extraction(
            html, with_metadata=True, include_comments=False,
            include_tables=True)
    except Exception as e:  # noqa: BLE001
        rec["route"] = "crash"
        rec["provenance"]["error"] = f"{type(e).__name__}: {e}"
        return rec
    if doc is None:
        rec["route"] = "trafilatura_empty"
        return rec
    if doc.title:
        rec["title"] = doc.title.strip()
        rec["provenance"]["title"] = "trafilatura:document.title"
    if doc.author:
        rec["authors"] = [a.strip() for a in re.split(r"[,;，；]", doc.author) if a.strip()]
        rec["provenance"]["authors"] = "trafilatura:document.author"
    v = norm_date_only(doc.date)
    if v:
        rec["publish_time"] = {"value": v, "utc_offset": None,
                               "utc_offset_source": None}
        rec["provenance"]["publish_time"] = "trafilatura:document.date(htmldate)"
    if doc.text:
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
            rec = extract_page(raw)
            rec = {"id": r["id"], **rec}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"v1: wrote {n} records -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
