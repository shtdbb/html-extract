#!/usr/bin/env python3
"""离线库 HTML 样本采集脚本（本地复现）。

用法:
    venv/bin/python scripts/collect.py --group fixed
    venv/bin/python scripts/collect.py --group generic --sites sina,sohu

行为:
    - 对每个站点: 抓种子页(栏目/索引页) -> 按正则提取文章链接 -> 抓文章页。
    - negative 组为直取模式: 直接抓给定 URL(列表页), 不做链接提取。
    - 原始字节原样保存(不转码), 索引写入 <项目根>/dataset_index.jsonl。
    - 每站请求间 0.5~1.0s 礼貌间隔; 失败(非200/超时/空壳页/过小)记录并跳过。
    - 运行状态累积在 scripts/collection_state.json, 每次运行后重新生成
      scripts/collection_log.md(各组合并视图)。
"""
import argparse
import hashlib
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import chardet
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "html"
INDEX = ROOT / "dataset_index.jsonl"
STATE = ROOT / "scripts" / "collection_state.json"
LOG_MD = ROOT / "scripts" / "collection_log.md"

DEVIATIONS = """## 实际构成与原计划的偏差（如实说明）

1. **fixed 组发现方式改变**：news.cn、chinadaily.com.cn、gov.cn 的栏目/索引页实测均为
   JS 动态加载的静态壳（news.cn politics 页只能提取到 2022 年陈旧静态兜底链接；
   chinadaily 频道页提取到 0 个文章链接；gov.cn yaowen/liebiao 页只有 2023 年及更早的
   /home/ 兜底链接）。因此 fixed 组改用「搜索引擎发现同站同模板近期文章 URL + 直取」，
   未按计划「抓栏目页提链接」。同站模板一致性由人工核对 URL 形态保证。
2. **test 组 cctv 整站替换**：news.cctv.com 可提取的文章链接极少，且实际抓到的 4 页
   全部为视频稿（静态 HTML 中正文为视频播放器、无文本正文，已逐页实测确认），按
   「需要 JS 渲染/无语义内容则跳过并记录」规则整组剔除（已保存的 cctv__01~04.html
   已删除），中文新闻缺口改由网易新闻（netease，4 页，dy/article 模板）补齐。
   cctv 由此记为"视频稿无静态正文"的失败站点。
3. **test 组 oschina 整站失败**：文章页全部返回 ~3.6KB SPA 空壳（可见文本 27 字符，
   需 JS 渲染），13 次尝试全部失败，已逐条记录。博客类缺口由 CSDN（5 页）补齐。
4. **test 组 51cto 整站失败**：首页与 blog 首页可访问但提取到 0 个文章链接（JS 壳）；
   另经手工诊断确认其文章页（如 /article/819776.html）对脚本请求只返回 ~1KB 反爬壳。
   未采集到任何 51cto 页面。
5. **test 组 mslearn 改直取**：training/browse 索引页为 JS 壳，改用搜索发现的 3 篇
   静态 quickstart 文档直取。
6. **negative 组两处替换**：politics.people.com.cn 与 www.chinanews.com.cn/gn/ 对脚本
   UA 返回 403，分别替换为 finance.people.com.cn 频道页与 chinanews 滚动新闻列表页。
7. **generic 组 chinanews 种子页替换**：/gn/、/cj/ 频道页 403，改用首页 + 滚动新闻页
   提取文章链接。
8. **数量结构**：总数 117 = fixed 30 + generic 55 + negative 4 + test 28，与计划一致。
   test 组内：新闻 15（中文 netease 4 + gmw 4 + stdaily 3 = 11，英文 en_people 4）、
   博客 7（csdn 5 + devto 2，其中 csdn 为 oschina/51cto 失败后的替代站）、
   文档 6（mdn 3 + mslearn 3）。
9. **已知样本质量注记**：python_docs__02 为 library 索引页（文档目录性质）；
   ifeng 的 4 个 gentie.ifeng.com 跟贴页被空壳检测正确拦截（记为失败而非样本）；
   sohu 部分页面为快讯短稿（正文容器实测 102~1485 字符，静态 HTML 中确有正文，
   非空壳，予以保留）；news_cn__05、ifeng__04 同为真实短讯稿。"""


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 12
MIN_BYTES = 2000          # 过小视为反爬/错误页
MIN_TEXT_CHARS = 150      # 可见文本过少视为 JS 空壳页
MAX_BYTES = 8 * 1024 * 1024

# ------------------------- 站点配置 -------------------------
# mode=index: seeds 为栏目页, pattern 匹配文章链接, target 为目标篇数
# mode=direct: urls 直取(用于负例)
SITES = {
    # fixed 组说明: news.cn / chinadaily / gov.cn 的栏目索引页均为 JS 动态加载的
    # 静态壳(实测 2026-09: 索引页只能提取到陈旧静态兜底链接), 因此改用
    # "搜索引擎发现同模板近期文章 URL + 直取" 的方式, 模板一致性由人工核对 URL
    # 形态保证。此为与原计划"抓栏目页提链接"的偏差, 已记入 collection_log。
    "fixed": [
        {"site": "news_cn", "mode": "direct", "target": 10,
         "urls": [
             "https://www.news.cn/politics/20251229/d88b731b55844876badbe2a1c7b00476/c.html",
             "https://www.news.cn/politics/leaders/20260720/ee2fbe58bd30444093bc08d9962ddc62/c.html",
             "https://www.news.cn/politics/20260126/95843e6cf3094828825ef3b0e86eaf0e/c.html",
             "https://www.news.cn/politics/leaders/20260803/5486539215f84753b83d7b96e96a0142/c.html",
             "http://www.news.cn/20260305/30e6e4c643ef4f2584746d37f196eb25/c.html",
             "https://www.news.cn/20260210/4b60c541f37245e3bbb299dd3db357ae/c.html",
             "https://www.news.cn/fortune/20260317/df7f200a0ec4408db44b31c4b2d62f83/c.html",
             "https://www.news.cn/politics/leaders/20260323/e7ee7e89f78f4808bbd04892e66c84a7/c.html",
             "https://www.news.cn/20251208/1fccb8c5124346d7847d78f9880dbd23/c.html",
             "https://www.news.cn/politics/20260313/085af5de5a4b4268aa7d87d90817df2f/c.html",
             "https://www.news.cn/fortune/20260121/cf0e1899edbc44039a790516dab079c6/c.html",
             "https://www.news.cn/politics/20251023/3fd2eabcfb704fbdb2c63b58299adebc/c.html",
         ]},
        {"site": "chinadaily", "mode": "direct", "target": 10,
         "urls": [
             "https://www.chinadaily.com.cn/a/202608/03/WS6a6fea22a310986e2b4689b8.html",
             "https://www.chinadaily.com.cn/a/202605/22/WS6a0f9c71a310d6866eb4a08d.html",
             "https://www.chinadaily.com.cn/a/202608/06/WS6a73f58da310986e2b4694c7.html",
             "https://www.chinadaily.com.cn/a/202511/19/WS691d1526a310d6866eb2a30e.html",
             "https://www.chinadaily.com.cn/a/202604/13/WS69dcac70a310d6866eb431cb.html",
             "https://www.chinadaily.com.cn/a/202603/09/WS69ae0139a310d6866eb3c947.html",
             "https://www.chinadaily.com.cn/a/202605/21/WS6a0efe7da310d6866eb49fd2.html",
             "https://www.chinadaily.com.cn/a/202602/04/WS69830a63a310d6866eb37786.html",
             "https://www.chinadaily.com.cn/a/202604/27/WS69ef03c8a310d6866eb45bfd.html",
             "https://www.chinadaily.com.cn/a/202407/23/WS669ee4b3a31095c51c50f4fd.html",
         ]},
        {"site": "gov_cn", "mode": "direct", "target": 10,
         "urls": [
             "https://www.gov.cn/yaowen/liebiao/202607/content_7074983.htm",
             "https://www.gov.cn/yaowen/liebiao/202603/content_7062604.htm",
             "https://www.gov.cn/yaowen/liebiao/202602/content_7058021.htm",
             "https://www.gov.cn/yaowen/liebiao/202607/content_7076148.htm",
             "https://www.gov.cn/yaowen/liebiao/202605/content_7069789.htm",
             "https://www.gov.cn/yaowen/liebiao/202407/content_6962524.htm",
             "https://www.gov.cn/zhengce/202606/content_7070926.htm",
             "https://www.gov.cn/zhengce/content/202407/content_6961215.htm",
             "https://www.gov.cn/gongbao/2026/issue_12706/202604/content_7067356.html",
             "https://www.gov.cn/gongbao/2026/issue_12626/202603/content_7063199.html",
             "https://www.gov.cn/gongbao/2026/issue_12746/202605/content_7069432.html",
         ]},
    ],
    "generic": [
        {"site": "sina", "mode": "index", "target": 6,
         "seeds": ["https://news.sina.com.cn/china/", "https://finance.sina.com.cn/"],
         "pattern": r"sina\.com\.cn/.*/20\d\d-\d\d-\d\d/doc-[a-z0-9]+\.shtml"},
        {"site": "sohu", "mode": "index", "target": 6,
         "seeds": ["https://news.sohu.com/", "https://www.sohu.com/"],
         "pattern": r"www\.sohu\.com/a/\d+_\d+"},
        {"site": "ifeng", "mode": "index", "target": 5,
         "seeds": ["https://news.ifeng.com/", "https://finance.ifeng.com/"],
         "pattern": r"ifeng\.com/c/[0-9A-Za-z]{8,}"},
        {"site": "caixin", "mode": "index", "target": 5,
         "seeds": ["https://www.caixin.com/", "https://finance.caixin.com/"],
         "pattern": r"caixin\.com/20\d\d-\d\d-\d\d/\d+\.html"},
        {"site": "chinanews", "mode": "index", "target": 6,
         # /gn/ /cj/ 频道页对脚本 UA 返回 403(实测), 首页与滚动新闻页可访问
         "seeds": ["https://www.chinanews.com.cn/", "https://www.chinanews.com.cn/scroll-news/news1.html"],
         "pattern": r"chinanews\.com\.cn/[a-z]+/20\d\d/\d\d-\d\d/\d+\.shtml"},
        {"site": "people", "mode": "index", "target": 6,
         "seeds": ["http://politics.people.com.cn/", "http://finance.people.com.cn/"],
         "pattern": r"people\.com\.cn/n1/20\d\d/\d{4}/c\d+-\d+\.html"},
        {"site": "cnblogs", "mode": "index", "target": 7,
         "seeds": ["https://www.cnblogs.com/", "https://www.cnblogs.com/pick"],
         "pattern": r"cnblogs\.com/[\w-]+/p/\d+"},
        {"site": "segmentfault", "mode": "index", "target": 5,
         "seeds": ["https://segmentfault.com/blogs", "https://segmentfault.com/"],
         "pattern": r"segmentfault\.com/a/119\d{7,}"},
        {"site": "python_docs", "mode": "index", "target": 5,
         "seeds": ["https://docs.python.org/3/tutorial/", "https://docs.python.org/3/howto/"],
         "pattern": r"docs\.python\.org/3/(tutorial|howto|library)/[\w./-]+\.html"},
        {"site": "github_blog", "mode": "index", "target": 4,
         "seeds": ["https://github.blog/", "https://github.blog/changelog/"],
         "pattern": r"github\.blog/(changelog/20\d\d-\d\d-\d\d-[\w-]+/|(news-insights|engineering|security|ai-and-ml|developer-skills|open-source|policy|company|education|community)/[\w-]+/[\w-]+/)$"},
    ],
    "negative": [
        {"site": "people_list", "mode": "direct",
         # politics.people.com.cn 对脚本 UA 403(实测), 改用财经频道列表页
         "urls": ["http://finance.people.com.cn/"]},
        {"site": "sohu_list", "mode": "direct",
         "urls": ["https://news.sohu.com/"]},
        {"site": "sina_list", "mode": "direct",
         "urls": ["https://news.sina.com.cn/china/"]},
        {"site": "chinanews_list", "mode": "direct",
         # /gn/ 频道页 403(实测), 改用滚动新闻列表页
         "urls": ["https://www.chinanews.com.cn/scroll-news/news1.html"]},
    ],
    "test": [
        # cctv 整站替换: news.cctv.com 首页/频道页可提取到的文章链接极少(1~3个),
        # 且实际抓到的 4 页全部是视频稿(静态 HTML 中无文本正文, 正文为视频播放器,
        # 已实测确认), 按"JS 渲染/无语义内容跳过"规则剔除, 改用网易新闻(静态良好)。
        {"site": "netease", "mode": "index", "target": 4,
         "seeds": ["https://news.163.com/", "https://www.163.com/"],
         "pattern": r"163\.com/dy/article/[A-Z0-9]+\.html"},
        {"site": "gmw", "mode": "index", "target": 4,
         "seeds": ["https://news.gmw.cn/", "https://www.gmw.cn/"],
         "pattern": r"gmw\.cn/20\d\d-\d\d/\d\d/content_\d+\.htm"},
        {"site": "stdaily", "mode": "index", "target": 3,
         "seeds": ["https://www.stdaily.com/", "https://www.stdaily.com/index/kejixinwen/"],
         "pattern": r"stdaily\.com/.*20\d\d-\d\d/\d\d/.*\.s?html"},
        {"site": "en_people", "mode": "index", "target": 4,
         "seeds": ["http://en.people.cn/"],
         "pattern": r"en\.people\.cn/n3/20\d\d/\d{4}/c\d+-\d+\.html"},
        # oschina 文章页为 SPA 空壳(实测返回 ~3.6KB JS 壳), 51cto 首页/文章页均返回
        # ~1KB 反爬壳(实测)。两站保留在配置中用于如实记录失败; 博客类样本缺口由
        # 下方 CSDN(5页) 补齐。
        {"site": "oschina", "mode": "index", "target": 3,
         "seeds": ["https://www.oschina.net/news"],
         "pattern": r"oschina\.net/news/\d+"},
        {"site": "51cto", "mode": "index", "target": 2,
         "seeds": ["https://www.51cto.com/", "https://blog.51cto.com/"],
         "pattern": r"51cto\.com/article/\d+\.html"},
        {"site": "csdn", "mode": "index", "target": 5,
         "seeds": ["https://blog.csdn.net/nav/career", "https://blog.csdn.net/nav/programming"],
         "pattern": r"blog\.csdn\.net/[\w]+/article/details/\d+"},
        {"site": "devto", "mode": "index", "target": 2,
         "seeds": ["https://dev.to/", "https://dev.to/top/week"],
         "pattern": r"dev\.to/[a-z0-9_]+/[a-z0-9-]+-[a-z0-9]{4,}$"},
        {"site": "mdn", "mode": "index", "target": 3,
         "seeds": ["https://developer.mozilla.org/en-US/docs/Web/HTML",
                   "https://developer.mozilla.org/en-US/docs/Web/CSS"],
         "pattern": r"developer\.mozilla\.org/en-US/docs/Web/(HTML|CSS|JavaScript)/[\w/]+$"},
        {"site": "mslearn", "mode": "direct", "target": 3,
         # training/browse 等索引页为 JS 壳(实测), 改用搜索发现的静态 quickstart 文档直取
         "urls": [
             "https://learn.microsoft.com/en-us/azure/app-service/quickstart-python",
             "https://learn.microsoft.com/en-us/azure/storage/blobs/storage-quickstart-blobs-python",
             "https://learn.microsoft.com/en-us/azure/azure-functions/functions-get-started",
         ]},
    ],
}

# ------------------------- 工具函数 -------------------------
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def polite_sleep():
    time.sleep(random.uniform(0.5, 1.0))


def fetch(url):
    """返回 (raw_bytes, final_url)；失败抛异常，由调用方记录。"""
    resp = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True)
    resp.raise_for_status()
    chunks, total = [], 0
    for chunk in resp.iter_content(65536):
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_BYTES:
            raise ValueError(f"oversize>{MAX_BYTES}")
    return b"".join(chunks), resp.url


def declared_encoding(raw: bytes) -> str | None:
    head = raw[:8192]
    m = re.search(rb'charset\s*=\s*["\']?\s*([A-Za-z0-9_\-]+)', head, re.I)
    return m.group(1).decode("ascii", "replace") if m else None


def visible_text_len(raw: bytes) -> int:
    enc = chardet.detect(raw[:200000]).get("encoding") or "utf-8"
    try:
        text = raw.decode(enc, "replace")
    except (LookupError, TypeError):
        text = raw.decode("utf-8", "replace")
    soup = BeautifulSoup(text, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return len(soup.get_text(" ", strip=True))


def make_record(group, site, url, final_url, raw, path, note):
    return {
        "id": path.stem,
        "path": str(path.relative_to(ROOT)),
        "url": url,
        "final_url": final_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bytes": len(raw),
        "sha1": hashlib.sha1(raw).hexdigest(),
        "encoding_declared": declared_encoding(raw),
        "encoding_detected": chardet.detect(raw[:200000]).get("encoding"),
        "group": group,
        "site": site,
        "note": note,
    }


def extract_links(seed_url, raw, pattern):
    enc = chardet.detect(raw[:200000]).get("encoding") or "utf-8"
    try:
        text = raw.decode(enc, "replace")
    except (LookupError, TypeError):
        text = raw.decode("utf-8", "replace")
    soup = BeautifulSoup(text, "lxml")
    rx = re.compile(pattern)
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        u = urljoin(seed_url, a["href"].split("#")[0])
        p = urlparse(u)
        if p.scheme not in ("http", "https"):
            continue
        if rx.search(u) and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"runs": [], "failures": []}


def save_state(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2))


def update_index(new_records, group, sites):
    old = []
    if INDEX.exists():
        with INDEX.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec["group"] == group and rec["site"] in sites:
                    continue  # 本次重跑的站点，旧记录替换
                old.append(rec)
    with INDEX.open("w") as f:
        for rec in old + new_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ------------------------- 主流程 -------------------------
def run_group(group, only_sites=None):
    cfgs = SITES[group]
    if only_sites:
        cfgs = [c for c in cfgs if c["site"] in only_sites]
    records, failures, summary = [], [], []

    for cfg in cfgs:
        site = cfg["site"]
        site_dir = DATA / group
        site_dir.mkdir(parents=True, exist_ok=True)
        # 清掉该站点旧文件(重跑幂等)
        for old in site_dir.glob(f"{site}__*.html"):
            old.unlink()

        got, fails, seq = 0, [], 1
        if cfg["mode"] == "direct":
            candidates = list(cfg["urls"])
        else:
            candidates = []
            for seed in cfg["seeds"]:
                polite_sleep()
                try:
                    raw, final = fetch(seed)
                    links = extract_links(final, raw, cfg["pattern"])
                    print(f"  [{site}] seed {seed} -> {len(links)} links", flush=True)
                    candidates.extend(links)
                except Exception as e:
                    fails.append({"url": seed, "reason": f"seed_fetch:{type(e).__name__}:{e}"})
                    print(f"  [{site}] seed {seed} FAILED: {e}", flush=True)
            # 去重保序
            seen, uniq = set(), []
            for u in candidates:
                if u not in seen:
                    seen.add(u)
                    uniq.append(u)
            candidates = uniq
            if not candidates:
                fails.append({"url": "|".join(cfg["seeds"]),
                              "reason": "no_article_links_extracted:种子页可访问但提取到0个文章链接(JS壳或模式不匹配)"})

        target = cfg.get("target", len(cfg.get("urls", [])))
        max_attempts = target + 10  # 反爬站点兜底: 不无限重试
        attempts = 0
        for url in candidates:
            if got >= target or attempts >= max_attempts:
                break
            attempts += 1
            polite_sleep()
            try:
                raw, final = fetch(url)
                if len(raw) < MIN_BYTES:
                    raise ValueError(f"too_small:{len(raw)}B")
                tlen = visible_text_len(raw)
                if tlen < MIN_TEXT_CHARS:
                    raise ValueError(f"empty_shell_suspected:visible_text={tlen}")
                fname = f"{site}__{seq:02d}.html"
                fpath = site_dir / fname
                fpath.write_bytes(raw)
                note = ""
                if group == "negative":
                    note = "negative:list_page"
                records.append(make_record(group, site, url, final, raw, fpath, note))
                seq += 1
                got += 1
                print(f"  [{site}] OK {fname} ({len(raw)}B) {url}", flush=True)
            except Exception as e:
                reason = f"{type(e).__name__}:{e}"
                fails.append({"url": url, "reason": reason})
                print(f"  [{site}] FAIL {url} -> {reason}", flush=True)

        summary.append({"site": site, "target": target, "saved": got, "failed": len(fails)})
        failures.extend({"site": site, **f} for f in fails)

    update_index(records, group, {c["site"] for c in cfgs})

    st = load_state()
    done_sites = {c["site"] for c in cfgs}
    st["runs"] = [r for r in st["runs"]
                  if not (r.get("group") == group and r.get("site") in done_sites)]
    st["failures"] = [f for f in st["failures"]
                      if not (f.get("group") == group and f.get("site") in done_sites)]
    for s in summary:
        st["runs"].append({
            "group": group,
            "site": s["site"],
            "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "target": s["target"], "saved": s["saved"], "failed": s["failed"],
        })
    st["failures"].extend({"group": group, **f} for f in failures)
    save_state(st)
    regenerate_log(st)
    print(f"[{group}] saved={sum(s['saved'] for s in summary)} failed={len(failures)}", flush=True)


def regenerate_log(st):
    lines = ["# 采集日志（自动生成，勿手改）", ""]
    lines.append("> 本文件由 scripts/collect.py 依据 collection_state.json 重新生成。")
    lines.append("")
    by_group = {}
    for run in st["runs"]:
        by_group.setdefault(run["group"], []).append(run)
    total_saved = 0
    for group, runs in by_group.items():
        gsaved = sum(r["saved"] for r in runs)
        total_saved += gsaved
        last = max(r["ran_at"] for r in runs)
        lines.append(f"## 组: {group}（最近运行 {last} UTC，保存 {gsaved} 页）")
        lines.append("")
        lines.append("| 站点 | 目标 | 成功 | 失败 | 运行时间(UTC) |")
        lines.append("|---|---|---|---|---|")
        for r in sorted(runs, key=lambda x: x["site"]):
            lines.append(f"| {r['site']} | {r['target']} | {r['saved']} | {r['failed']} | {r['ran_at']} |")
        lines.append("")
    lines.append(f"**累计保存：{total_saved} 页**")
    lines.append("")
    lines.append("## 失败明细")
    lines.append("")
    if st["failures"]:
        lines.append("| 组 | 站点 | URL | 原因 |")
        lines.append("|---|---|---|---|")
        for f in st["failures"]:
            lines.append(f"| {f['group']} | {f['site']} | {f['url']} | {f['reason']} |")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append(DEVIATIONS)
    lines.append("")
    LOG_MD.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, choices=list(SITES.keys()))
    ap.add_argument("--sites", default=None, help="逗号分隔，只跑指定站点")
    args = ap.parse_args()
    only = set(args.sites.split(",")) if args.sites else None
    run_group(args.group, only)


if __name__ == "__main__":
    main()
