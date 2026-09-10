#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_authors.py — v6 过程定位：authors 失分页的署名证据探查（只读 dev）。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from extract import (decode_declared_first, parse_metadata_layer,  # noqa: E402
                     _clean_author_name)
from bs4 import BeautifulSoup  # noqa: E402

PAGES = ["sina__02", "sina__03", "sina__04", "sina__06", "sina__05",
         "ifeng__01", "ifeng__03", "ifeng__04", "ifeng__05",
         "chinadaily__07", "sohu__01", "sohu__03", "sohu__04", "sohu__06",
         "news_cn__09", "chinanews__04", "chinanews__05",
         "segmentfault__04", "cnblogs__07"]

gold = {r["id"]: r for r in
        json.load(open(ROOT / "results" / "dev_gold.json"))}
preds = {json.loads(l)["id"]: json.loads(l)
         for l in open(ROOT / "results" / "v5_pred_dev.jsonl")}
index = {json.loads(l)["id"]: json.loads(l)
         for l in open(ROOT / "dataset_index.jsonl")}

for pid in PAGES:
    g, p, ix = gold[pid], preds[pid], index[pid]
    raw = (ROOT / ix["path"]).read_bytes()
    html, *_ = decode_declared_first(raw)
    soup = BeautifulSoup(html, "lxml")
    meta = parse_metadata_layer(soup)
    print(f"\n===== {pid} =====")
    print(f"  gold authors : {g.get('authors')}")
    print(f"  pred authors : {p.get('authors')}  prov={p.get('provenance',{}).get('authors')}")
    print(f"  meta authors : {meta['authors']}  prov={meta['provenance'].get('authors')}")
    # 正文首行
    ct = (p.get("content_text") or "")[:120].replace("\n", "⏎")
    print(f"  content head : {ct}")
    # gold 作者名在 HTML 中的出现位置（前 3 处上下文）
    for a in (g.get("authors") or [])[:4]:
        name = re.sub(r"（[^）]*）", "", a)
        hits = [m.start() for m in re.finditer(re.escape(name), html)][:3]
        for h in hits[:2]:
            ctx = re.sub(r"\s+", " ", html[max(0, h-60):h+40])
            print(f"    [{name}] …{ctx}…")
    for n in (meta["authors"] or []):
        print(f"    clean({n!r}) -> {_clean_author_name(n)!r}")
