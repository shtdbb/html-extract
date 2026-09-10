#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sample_ispras.py — 从 Nextcloud 公开分享流式抽样 ISPRAS multilingual en.json

为什么不整包下载：en.json 2.8GB（320 站 / 10479 页，含内联 html）。
本脚本从 offset 0 开始流式读，用 JSON 状态机：
  - 每站只完整解析前 PAGES_PER_SITE 个页面对象（uuid/url/html/annotations）
  - 该站其余页面字节扫描跳过（不解析，只维护字符串/转义/深度状态）
  - 收满 N_SITES 个站即中止 HTTP 响应
偏差声明：站点按文件内出现顺序取前 N_SITES 个（键序未知，疑按域名排序），
非均匀随机抽样；每站取文件内前 2 页。所有数字如实记录。

用法：
  venv/bin/python external/sample_ispras.py --sites 80 --pages-per-site 2 \
      --out external/ispras_sample_en.jsonl --log external/logs/sample.log
"""
import argparse
import json
import sys
import time
import urllib.request

URL = "https://nextcloud.ispras.ru/public.php/webdav/en.json"
AUTH = ("gkttoE637s9kxfJ", "")  # Nextcloud 公开分享的 WebDAV 口令


class StreamScanner:
    """对 en.json 字节流的增量 JSON 状态机。顶层结构假定 {"site": [page, ...], ...}。"""

    def __init__(self, fp, log):
        self.fp = fp
        self.log = log
        self.buf = bytearray()
        self.off = 0            # 已消费到流中的绝对偏移
        self.decoder = json.JSONDecoder()

    def fill(self, need):
        while len(self.buf) < need:
            chunk = self.fp.read(1 << 20)
            if not chunk:
                return False
            self.buf += chunk
        return True

    def read_some(self, timeout_note=""):
        chunk = self.fp.read(1 << 20)
        if chunk:
            self.buf += chunk
        return bool(chunk)

    def skip_ws(self):
        while True:
            while self.buf and self.buf[0] in b" \t\r\n":
                del self.buf[0]
                self.off += 1
            if self.buf:
                return True
            if not self.read_some():
                return False

    def expect(self, ch):
        if not self.skip_ws():
            raise EOFError(f"expect {ch!r}: EOF")
        got = chr(self.buf[0])
        if got != ch:
            raise ValueError(f"expect {ch!r}, got {got!r} at off={self.off}")
        del self.buf[0]
        self.off += 1

    def parse_string(self):
        """解析一个 JSON 字符串（buffer 需以引号开头）。"""
        while True:
            try:
                s, end = self.decoder.raw_decode(self.buf.decode("utf-8", "strict"))
                del self.buf[:end]
                self.off += end
                return s
            except (json.JSONDecodeError, UnicodeDecodeError):
                if not self.read_some():
                    raise EOFError("parse_string: EOF")

    def parse_value(self):
        """解析任意 JSON 值（用于完整页面对象）。返回 Python 对象。"""
        while True:
            try:
                obj, end = self.decoder.raw_decode(
                    self.buf.decode("utf-8", "strict"))
                del self.buf[:end]
                self.off += end
                return obj
            except (json.JSONDecodeError, UnicodeDecodeError):
                if not self.read_some():
                    raise EOFError("parse_value: EOF")

    def skip_value(self):
        """状态机跳过一个 JSON 值（不构建对象）。"""
        depth = 0
        in_str = False
        esc = False
        started = False
        while True:
            if not self.buf:
                if not self.read_some():
                    raise EOFError("skip_value: EOF")
                continue
            b = self.buf[0]
            del self.buf[0]
            self.off += 1
            if in_str:
                if esc:
                    esc = False
                elif b == 0x5C:      # backslash
                    esc = True
                elif b == 0x22:      # quote
                    in_str = False
                continue
            if b == 0x22:
                in_str = True
                started = True
            elif b in b"{[":
                depth += 1
                started = True
            elif b in b"}]":
                depth -= 1
                if depth == 0:
                    return
            elif started and depth == 0 and b in b",]} \t\r\n":
                # 标量字面量结束（true/false/null/number）
                return
            elif b not in b" \t\r\n":
                started = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=int, default=80)
    ap.add_argument("--skip-sites", type=int, default=0,
                    help="从头快进跳过的站数（断点续跑用）")
    ap.add_argument("--pages-per-site", type=int, default=2)
    ap.add_argument("--out", required=True)
    ap.add_argument("--log", required=True)
    args = ap.parse_args()

    logf = open(args.log, "w", encoding="utf-8")
    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, file=sys.stderr)
        logf.write(line + "\n")
        logf.flush()

    log(f"start: target {args.sites} sites x {args.pages_per_site} pages, url={URL}")
    req = urllib.request.Request(URL)
    # Nextcloud 公开分享 WebDAV 需要 Basic auth（share token 为用户名）
    import base64
    token = base64.b64encode(f"{AUTH[0]}:{AUTH[1]}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=120)
    log(f"connected, status={resp.status}, total_len={resp.headers.get('Content-Length')}")

    sc = StreamScanner(resp, log)
    n_sites = 0        # 全局限序站计数（含跳过的）
    n_kept = 0         # 实际落盘的站数
    n_pages = 0
    out = open(args.out, "a", encoding="utf-8")

    sc.expect("{")
    first = True
    while n_kept < args.sites:
        if not first:
            try:
                sc.expect(",")
            except EOFError:
                break
        if not sc.skip_ws():
            break
        if sc.buf and sc.buf[0] == 0x7D:  # '}' 顶层结束
            break
        first = False
        site = sc.parse_string()
        sc.expect(":")
        sc.expect("[")
        n_sites += 1
        keep = n_sites > args.skip_sites
        pps = args.pages_per_site if keep else 0
        taken = 0
        # 数组元素消费循环：首元素前无逗号，之后每个元素前有逗号
        elem_idx = 0
        while True:
            if not sc.skip_ws():
                break
            if sc.buf and sc.buf[0] == 0x5D:  # ']' 数组闭合
                del sc.buf[0]
                sc.off += 1
                break
            if elem_idx > 0:
                sc.expect(",")
                if not sc.skip_ws():
                    break
                if sc.buf and sc.buf[0] == 0x5D:
                    del sc.buf[0]
                    sc.off += 1
                    break
            if elem_idx < pps:
                page = sc.parse_value()
                page["_site"] = site
                out.write(json.dumps(page, ensure_ascii=False) + "\n")
                taken += 1
                n_pages += 1
            else:
                sc.skip_value()
            elem_idx += 1
        if keep:
            n_kept += 1
        out.flush()
        mb = sc.off / 1e6
        rate = mb / (time.time() - t0)
        if n_sites % 5 == 0 or n_sites <= 3:
            log(f"site#{n_sites} {site!r} keep={keep} took={taken} "
                f"pages_total={n_pages} streamed={mb:.0f}MB rate={rate:.1f}MB/s")
    resp.close()
    out.close()
    log(f"done: sites_seen={n_sites} sites_kept={n_kept} pages={n_pages} "
        f"streamed={sc.off/1e6:.0f}MB elapsed={time.time()-t0:.0f}s -> {args.out}")
    logf.close()


if __name__ == "__main__":
    main()
