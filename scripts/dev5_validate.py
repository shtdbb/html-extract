#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dev5_validate.py — dev 集 5 样本冒烟验证（任务一）

覆盖站点：news_cn / chinadaily / sina / gov_cn / cnblogs（各取 01 号页）。
验证内容：
  1. trafilatura 2.2.0 / readability-lxml 0.9 的安装与 API 可用性；
  2. 返回值形态（trafilatura 1.11 起 metadata 必须 with_metadata=True）；
  3. 四字段（title / authors / publish_time / content_text）映射能力；
  4. 单页耗时（每页 3 次取中位数）；
  5. sina 页"传 bytes 让库自检编码"行为：
     - 实测：dev 集中 sina 6 页声明编码均为 utf-8（无真实 GBK 页），
       故额外构造"转码为 GBK + meta 改声明 gb2312"的合成字节串，
       验证两库在仅拿到 bytes、调用方不解码时的自检行为。

输出：results/dev5_validation.json（原始输出全量保留）。
运行：venv/bin/python scripts/dev5_validate.py
"""
import json
import re
import time
from pathlib import Path

import chardet
import trafilatura
from readability import Document
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "dev5_validation.json"

SAMPLES = [
    ("news_cn", "data/html/fixed/news_cn__01.html"),
    ("chinadaily", "data/html/fixed/chinadaily__01.html"),
    ("sina", "data/html/generic/sina__01.html"),
    ("gov_cn", "data/html/fixed/gov_cn__01.html"),
    ("cnblogs", "data/html/generic/cnblogs__01.html"),
]

REPS = 3  # 计时重复次数


def decode_declared_first(raw: bytes):
    """声明编码优先、chardet 兜底（课题既定解码策略，供对照基准用）。"""
    head = raw[:4096].decode("ascii", errors="ignore")
    m = re.search(r'charset=["\']?([\w-]+)', head, re.I)
    declared = m.group(1).lower() if m else None
    detected = chardet.detect(raw).get("encoding")
    for enc in [declared, detected, "utf-8", "gb18030"]:
        if not enc:
            continue
        try:
            return raw.decode(enc), declared, detected, enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), declared, detected, "utf-8(replace)"


def four_field_mapping_traf(doc: dict):
    """trafilatura bare_extraction(as_dict) → 四字段映射。"""
    if doc is None:
        return None
    return {
        "title": doc.get("title"),
        "authors_raw": doc.get("author"),          # 注意：单个拼接字符串，非列表
        "publish_time_raw": doc.get("date"),       # 形如 2025-12-29 或 ISO
        "content_text_len": len(doc.get("text") or ""),
        "content_text_head": (doc.get("text") or "")[:200],
        "other_keys": sorted(k for k in doc.keys()
                             if k not in ("title", "author", "date", "text")),
    }


def run_trafilatura(raw: bytes):
    """传 bytes，with_metadata=True（1.11 起 metadata 的强制开关）。"""
    t0 = time.perf_counter()
    doc = None
    err = None
    try:
        doc = trafilatura.bare_extraction(
            raw, with_metadata=True, as_dict=True,
            include_comments=False, include_tables=True)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return doc, err, elapsed_ms


def run_readability(raw: bytes):
    t0 = time.perf_counter()
    err, out = None, {}
    try:
        doc = Document(raw)
        out["title"] = doc.title()
        out["short_title"] = doc.short_title()
        out["author"] = doc.author() if hasattr(doc, "author") else "<no author() api>"
        summary = doc.summary()  # 返回 HTML 片段，不是纯文本
        soup = BeautifulSoup(summary, "lxml")
        text = soup.get_text("\n")
        out["summary_is_html"] = True
        out["content_text_len"] = len(text.strip())
        out["content_text_head"] = text.strip()[:200]
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return out, err, elapsed_ms


def main():
    report = {
        "meta": {
            "purpose": "dev5 冒烟验证：安装/API/返回值/四字段映射/单页耗时/bytes 自检编码",
            "samples": [{"site": s, "path": p} for s, p in SAMPLES],
            "note_sina_gbk": (
                "实测发现 dev 集 sina 6 页 encoding_declared 全部为 utf-8，"
                "不存在真实 GBK 页；GBK 行为用合成转码样本验证（sina__01 → gbk 字节 + meta charset=gb2312）。"
            ),
        },
        "library_check": {
            "trafilatura": trafilatura.__version__,
            "readability_lxml": "0.9",
            "trafilatura_bare_extraction_accepts_bytes": None,  # 下面填
        },
        "pages": [],
    }

    for site, rel in SAMPLES:
        raw = (ROOT / rel).read_bytes()
        html, declared, detected, used = decode_declared_first(raw)

        # --- trafilatura：计时 3 次取中位 ---
        traf_times, traf_doc, traf_err = [], None, None
        for _ in range(REPS):
            d, e, ms = run_trafilatura(raw)
            traf_times.append(round(ms, 1))
            traf_doc, traf_err = d, e
        # --- readability：同 ---
        read_times, read_out, read_err = [], None, None
        for _ in range(REPS):
            o, e, ms = run_readability(raw)
            read_times.append(round(ms, 1))
            read_out, read_err = o, e

        page = {
            "site": site, "path": rel, "bytes": len(raw),
            "encoding": {"declared": declared, "detected": detected, "used": used},
            "trafilatura": {
                "error": traf_err,
                "elapsed_ms_runs": traf_times,
                "elapsed_ms_median": sorted(traf_times)[1],
                "return_type": type(traf_doc).__name__ if traf_doc is not None else None,
                "four_field_mapping": four_field_mapping_traf(traf_doc),
            },
            "readability": {
                "error": read_err,
                "elapsed_ms_runs": read_times,
                "elapsed_ms_median": sorted(read_times)[1],
                "output": read_out,
            },
        }
        report["pages"].append(page)
        report["library_check"]["trafilatura_bare_extraction_accepts_bytes"] = traf_err is None

    # --- sina GBK 合成样本：传 bytes 让库自检编码 ---
    raw = (ROOT / "data/html/generic/sina__01.html").read_bytes()
    html = raw.decode("utf-8")
    html_gbk = re.sub(r'charset=["\']?utf-8', 'charset=gb2312', html, flags=re.I)
    gbk_bytes = html_gbk.encode("gb18030")
    syn = {
        "note": "合成样本：sina__01 文本转 gb18030 字节、meta 声明改 gb2312；调用方不解码，直接传 bytes。",
        "bytes": len(gbk_bytes),
        "chardet_on_bytes": chardet.detect(gbk_bytes),
        "trafilatura": {},
        "readability": {},
    }
    d, e, ms = run_trafilatura(gbk_bytes)
    syn["trafilatura"] = {
        "error": e, "elapsed_ms": round(ms, 1),
        "four_field_mapping": four_field_mapping_traf(d),
        "mojibake_in_title": (d is not None and "�" in (d.get("title") or "")),
    }
    o, e, ms = run_readability(gbk_bytes)
    syn["readability"] = {
        "error": e, "elapsed_ms": round(ms, 1),
        "output": o,
        "mojibake_in_title": bool(o and "�" in (o.get("title") or "")),
    }
    report["sina_gbk_bytes_test"] = syn

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written {OUT}")
    # 控制台摘要
    for p in report["pages"]:
        t, r = p["trafilatura"], p["readability"]
        tf = t["four_field_mapping"] or {}
        print(f"{p['site']:10s} traf {t['elapsed_ms_median']:7.1f}ms "
              f"title={str(tf.get('title'))[:30]!r} len={tf.get('content_text_len')} | "
              f"read {r['elapsed_ms_median']:7.1f}ms len={r['output'].get('content_text_len')}")


if __name__ == "__main__":
    main()
