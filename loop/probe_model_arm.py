#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_model_arm.py — v10 前置探查：在 v9 失分的 ISPRAS 页上测试 Qwen2.5-7B 抽取质量与延迟。"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import extract as E  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

gold = {r["id"]: r for r in json.load(open(ROOT / "external/ispras_gold_en.json"))}
v9 = {p["id"]: p for p in json.load(open(ROOT / "external/ispras_scores_v9.json"))["pages"]}
cands = [pid for pid in v9 if v9[pid].get("authors", {}).get("score") == 0.0
         and gold[pid].get("authors")]
print("authors 失分且有 gold 的候选页:", cands[:5])
pid = cands[0]
print("gold authors:", gold[pid].get("authors"))
print("gold title:", str(gold[pid].get("title"))[:60])

raw = (ROOT / f"external/html/{pid}.html").read_bytes()
html, *_ = E.decode_declared_first(raw)
soup = BeautifulSoup(html, "lxml")
for tag in soup(["script", "style", "noscript"]):
    tag.decompose()
text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))[:3500]

prompt = (
    "从以下网页可见文本中抽取新闻字段。只输出 JSON，不要解释。\n"
    "字段：title（文章真实标题，不含站点名后缀）、authors（作者人名数组，"
    "没有则空数组；媒体名/栏目名/站点名不是作者）、publish_time（发布时间，"
    "原样摘录页面中的写法，没有则 null）。\n\n"
    "网页文本：\n<<<\n" + text + "\n>>>\n"
)

t0 = time.time()
req = urllib.request.Request(
    "http://localhost:11434/api/generate",
    data=json.dumps({
        "model": "qwen2.5-7b", "prompt": prompt, "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": 300},
    }).encode(),
    headers={"Content-Type": "application/json"})
r = json.loads(urllib.request.urlopen(req).read())
dt = time.time() - t0
print("\n模型输出:", r["response"][:400])
ev = r.get("eval_count", 0)
ed = r.get("eval_duration", 1) / 1e9
print(f"耗时 {dt:.1f}s | prompt {r.get('prompt_eval_count')} tok | "
      f"eval {ev} tok | eval_rate {ev / ed:.0f} tok/s")
