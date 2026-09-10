#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_time.py — 共享时间串解析：ISO 8601 / gov.cn 异形 → 规范时间结构。"""

import re


def parse_time_str(s):
    """解析时间串 → {"value","utc_offset","utc_offset_source"} 或 None。

    未知分量 XX 占位（对齐 ISO 8601-2:2019 EDTF 的 X 未指定数字位）。
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    # ISO 8601: 2026-08-11T17:30:01+08:00 / ...Z / 2026-09-10 19:32 / 2026-06-28T03:07:37.000Z
    m = re.match(
        r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{1,2})(?::(\d{1,2})(?:\.\d+)?)?)?"
        r"\s*(Z|[+-]\d{2}:?\d{2})?$", s)
    if m:
        y, mo, d, h, mi, sec, tz = m.groups()
        hh = f"{int(h):02d}" if h else "XX"
        mm = f"{int(mi):02d}" if mi else "XX"
        ss = f"{int(sec):02d}" if sec else "XX"
        value = f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {hh}:{mm}:{ss}"
        off = None
        if tz:
            off = "+00:00" if tz == "Z" else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
        return {"value": value, "utc_offset": off, "utc_offset_source": None}
    # gov.cn 异形：2026-07-10-20:28:00
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})-(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$", s)
    if m:
        g = m.groups()
        y, mo, d, h, mi = (int(x) for x in g[:5])
        ss = f"{int(g[5]):02d}" if g[5] else "XX"
        return {"value": f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{ss}",
                "utc_offset": None, "utc_offset_source": None}
    # 中文格式：2026年08月11日 17:30(:01)
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*"
                  r"(?:(\d{1,2})\s*[:：]\s*(\d{1,2})(?:\s*[:：]\s*(\d{1,2}))?)?", s)
    if m:
        g = m.groups()
        y, mo, d = int(g[0]), int(g[1]), int(g[2])
        hh = f"{int(g[3]):02d}" if g[3] else "XX"
        mm = f"{int(g[4]):02d}" if g[4] else "XX"
        ss = f"{int(g[5]):02d}" if g[5] else "XX"
        return {"value": f"{y:04d}-{mo:02d}-{d:02d} {hh}:{mm}:{ss}",
                "utc_offset": None, "utc_offset_source": None}
    return None
