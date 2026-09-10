#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ollama_client.py — 本地 Ollama 生成接口的薄封装（v10 模型兜底臂）。

- 只走 localhost:11434 /api/generate，无第三方依赖（urllib）；
- format=json + temperature=0，保证输出可解析、可复现；
- 进程内累计统计（调用数、页数、token、耗时），由 extract.get_model_stats()
  暴露给 loop/run_iteration.py 记入成本。

reset_stats() 在每轮迭代开始时由 run_iteration 隐式清零（新进程）；
同一进程内多次批跑时可手动调用。
"""
import json
import time
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5-7b"          # Qwen2.5-7B-Instruct Q4_K_M 的本地别名
TIMEOUT = 120

_stats = {
    "model": MODEL,
    "backend": "ollama/Q4_K_M",
    "calls": 0,
    "n_pages": 0,             # 触发模型兜底的页面数
    "prompt_tokens": 0,
    "eval_tokens": 0,
    "total_seconds": 0.0,     # 模型调用累计墙钟（含首载）
    "errors": 0,
}


def stats():
    return dict(_stats)


def note_page():
    """某页触发了模型兜底（可能多次调用）。"""
    _stats["n_pages"] += 1


def generate(prompt: str, num_predict: int = 300):
    """调用本地模型，返回解析后的 JSON 对象；失败返回 None。"""
    body = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": num_predict},
    }
    t0 = time.time()
    try:
        req = urllib.request.Request(
            OLLAMA_URL, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read())
    except Exception:  # noqa: BLE001
        _stats["errors"] += 1
        return None
    _stats["calls"] += 1
    _stats["prompt_tokens"] += r.get("prompt_eval_count", 0)
    _stats["eval_tokens"] += r.get("eval_count", 0)
    _stats["total_seconds"] += time.time() - t0
    try:
        return json.loads(r["response"])
    except Exception:  # noqa: BLE001
        _stats["errors"] += 1
        return None
