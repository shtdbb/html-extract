#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_readability.py — 对照臂：readability-lxml 0.9 全量提取

能力边界（官方 API 清单，见 baseline_selection.md §2）：
  title → .title()（不做后缀剥离——对照臂保持库原生行为）
  content_text → .summary()（HTML 片段）经 bs4 转纯文本
  authors → .author()（多数页 [no-author]，空则 null）
  publish/update_time → 库无此能力，恒 null（如实记缺，不补 meta）
解码与 baseline 相同（声明优先，chardet 兜底），保证对照只差"提取引擎"。

用法：
  venv/bin/python run_readability.py --groups fixed,generic,negative --out results/readability_pred_dev.jsonl
  venv/bin/python run_readability.py --groups test --out results/readability_pred_test.jsonl
"""
import argparse
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import chardet
from readability import Document
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent


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


def extract_page(raw: bytes):
    html, declared, detected, used = decode_declared_first(raw)
    rec = {
        "title": None, "authors": None, "publish_time": None, "update_time": None,
        "content_text": None, "content_md": None, "images": None,
        "conversion_flags": [], "page_condition": "ok", "needs_render": False,
        "content_structure": "single",
        "source": {"encoding": {"declared": declared, "detected": detected,
                                "used": used}},
        "provenance": {}, "route": "readability-lxml",
    }
    try:
        doc = Document(html)
        title = doc.title()
        if title and title.strip():
            rec["title"] = re.sub(r"\s+", " ", title).strip()
            rec["provenance"]["title"] = "readability:document.title()"
        author = doc.author() if hasattr(doc, "author") else None
        if author and author != "[no-author]":
            rec["authors"] = [author.strip()]
            rec["provenance"]["authors"] = "readability:document.author()"
        summary = doc.summary()
        if summary:
            soup = BeautifulSoup(summary, "lxml")
            text = soup.get_text("\n")
            text = re.sub(r"\n{3,}", "\n\n",
                          "\n".join(l.strip() for l in text.split("\n") if l.strip()))
            if text:
                rec["content_text"] = text
                rec["content_md"] = text
                rec["provenance"]["content_text"] = "readability:document.summary()→text"
    except Exception as e:  # noqa: BLE001
        rec["route"] = "crash"
        rec["provenance"]["error"] = f"{type(e).__name__}: {e}"
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
    print(f"readability: wrote {n} records -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
