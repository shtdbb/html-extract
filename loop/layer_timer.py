#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
layer_timer.py — 轻量分层计时注册表。

提取器各阶段用 `with timed("trafilatura"): ...` 包裹；
loop/run_iteration.py 在同进程内 reset() → 跑全量 → report() 汇总。
只测 wall time；不引入第三方依赖。
"""
import time
from collections import defaultdict
from contextlib import contextmanager

_TIMES = defaultdict(float)
_COUNTS = defaultdict(int)


@contextmanager
def timed(stage: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        _TIMES[stage] += time.perf_counter() - t0
        _COUNTS[stage] += 1


def reset():
    _TIMES.clear()
    _COUNTS.clear()


def report():
    return {s: {"seconds": round(_TIMES[s], 6), "calls": _COUNTS[s]}
            for s in _TIMES}
