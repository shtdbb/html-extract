#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_v3.py — baseline v3：v2 + 站点规则层（fixed 三站）+ 拒识判定 + DOM 密度兜底

管线：解码（声明优先，chardet 兜底）→ page_condition 判定 → 拒识判定
（付费墙 / list_page / 空壳 / 图集）→ 三层路由：
  ①元数据层 JSON-LD + OG/meta（继承 v2，含 D-002 实体解码修复）
  ②站点规则库 site_rules.py（fixed 三站，规则可 final 裁决字段为空）
  ③trafilatura 兜底 → 失败则 DOM 文本密度容器兜底
fixed 站：规则层优先，缺口字段回退元数据层→trafilatura；
generic 站：元数据层优先 → trafilatura → DOM 密度。

拒识信号（v3 新增）：
  - 付费墙：#chargeWall（caixin）→ rejected + 全字段空（gold 边界：付费墙无可抽取）；
  - list_page：长链接(文本≥12字)数≥30 且其文本占全文比≥0.55 → rejected；
  - empty_shell：body 文本<200 且 trafilatura 无产出 → page_condition=empty_shell，
    needs_render=true，rejected；
  - photo_set：正文候选容器 img≥8 且 文本/img<120 → rejected（dev 无此类页，按先验阈值）。

用法：
  venv/bin/python versions/extract_v3.py --groups fixed,generic,negative --out results/v3_pred_dev.jsonl
"""
import argparse
import html as html_mod
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import chardet
import trafilatura
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from site_rules import SITE_RULES, assemble_container  # noqa: E402
from extract_time import parse_time_str  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

ARTICLE_TYPES = {"newsarticle", "article", "blogposting", "techarticle",
                 "reportagenewsarticle", "scholarlyarticle", "socialmediaposting"}


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


# ---------------------------------------------------------------------------
# 元数据层（同 v2）
# ---------------------------------------------------------------------------

def _iter_jsonld_nodes(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _iter_jsonld_nodes(x)
    elif isinstance(obj, dict):
        yield obj
        graph = obj.get("@graph")
        if isinstance(graph, list):
            for x in graph:
                yield from _iter_jsonld_nodes(x)


def parse_metadata_layer(soup):
    out = {"title": None, "authors": None, "publish_time": None,
           "update_time": None, "provenance": {}}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _iter_jsonld_nodes(data):
            t = node.get("@type")
            types = {str(x).lower() for x in (t if isinstance(t, list) else [t])}
            if not types & ARTICLE_TYPES:
                continue
            if not out["title"] and node.get("headline"):
                out["title"] = html_mod.unescape(str(node["headline"])).strip()
                out["provenance"]["title"] = "json-ld:headline"
            au = node.get("author")
            if not out["authors"] and au:
                names = []
                for a in (au if isinstance(au, list) else [au]):
                    if isinstance(a, dict) and a.get("name"):
                        names.append(html_mod.unescape(str(a["name"])).strip())
                    elif isinstance(a, str) and a.strip():
                        names.append(html_mod.unescape(a).strip())
                if names:
                    out["authors"] = names
                    out["provenance"]["authors"] = "json-ld:author"
            if not out["publish_time"] and node.get("datePublished"):
                pt = parse_time_str(str(node["datePublished"]))
                if pt:
                    out["publish_time"] = pt
                    out["provenance"]["publish_time"] = "json-ld:datePublished"
            if not out["update_time"] and node.get("dateModified"):
                ut = parse_time_str(str(node["dateModified"]))
                if ut:
                    out["update_time"] = ut
                    out["provenance"]["update_time"] = "json-ld:dateModified"

    def meta_val(*keys):
        for k in keys:
            tag = soup.find("meta", attrs={"property": k}) or \
                  soup.find("meta", attrs={"name": k})
            if tag and tag.get("content", "").strip():
                return tag["content"].strip(), k
        return None, None

    if not out["title"]:
        v, k = meta_val("og:title", "twitter:title")
        if v:
            out["title"] = v
            out["provenance"]["title"] = f"meta:{k}"
    if not out["publish_time"]:
        v, k = meta_val("article:published_time", "og:release_date",
                        "publishdate", "pubdate", "date", "firstpublishedtime")
        if v:
            pt = parse_time_str(v)
            if pt:
                out["publish_time"] = pt
                out["provenance"]["publish_time"] = f"meta:{k}"
    if not out["update_time"]:
        v, k = meta_val("article:modified_time", "lastmodifiedtime")
        if v:
            ut = parse_time_str(v)
            if ut:
                out["update_time"] = ut
                out["provenance"]["update_time"] = f"meta:{k}"
    if not out["authors"]:
        v, k = meta_val("article:author", "author")
        if v:
            names = [a.strip() for a in re.split(r"[,;，、；]", v) if a.strip()]
            if names:
                out["authors"] = names
                out["provenance"]["authors"] = f"meta:{k}"
    return out


def norm_traf_date(s):
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s.strip())
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    return {"value": f"{y:04d}-{mo:02d}-{d:02d} XX:XX:XX",
            "utc_offset": None, "utc_offset_source": None}


# ---------------------------------------------------------------------------
# 拒识判定
# ---------------------------------------------------------------------------

def check_refusal(soup, site, traf_text_len):
    """返回 (rejected: bool, reason: str|None, content_structure)。

    D-003 修正：gov.cn 模板畸形 HTML 导致正文容器落在 <body> 之外，
    页面文本量必须按全文档（除 script/style）统计，不能只看 body；
    photo_set 初版"任意 div 图多即拒"误伤大量文章页（chinadaily/cnblogs/
    chinanews 的图集挂件 div），改为"提取器几无产出 + 图片主导容器"双条件。
    """
    # 不 decompose（JSON-LD 也在 script 里，后续元数据层要用）：
    # 跳过 script/style/noscript 祖先统计可见文本
    def visible_text(root):
        parts = []
        for s in root.stripped_strings:
            node = getattr(s, "parent", None)
            if node is None:
                parts.append(str(s))
                continue
            if not any(p.name in ("script", "style", "noscript")
                       for p in node.parents):
                parts.append(str(s))
        return "".join(parts)
    page_text = visible_text(soup)
    # 1. 付费墙（caixin #chargeWall；gold 边界：付费墙页无可抽取）
    if soup.select_one("#chargeWall"):
        return True, "paywall:#chargeWall", "single"
    # 2. list_page：长链接文本占比
    links = soup.find_all("a")
    long_links = [a for a in links if len(a.get_text(strip=True)) >= 12]
    share = sum(len(a.get_text(strip=True)) for a in long_links) / max(len(page_text), 1)
    if len(long_links) >= 30 and share >= 0.55:
        return True, f"list_page:long_link_share={share:.2f},n={len(long_links)}", "list_page"
    # 3. empty_shell：全文档文本极少
    if len(page_text) < 200:
        return True, f"empty_shell:page_text={len(page_text)}", "single"
    # 4. photo_set：提取器几乎无产出 且 页面无实质文本容器 且 存在图片主导容器
    #    （D-003 第三轮：gov.cn 页脚图集挂件也曾误触发；真图集页的特征是
    #    图片容器即主内容、页面上不存在其他实质文本容器）
    if traf_text_len < 200:
        has_text_container = any(
            len(el.get_text(strip=True)) >= 400
            for el in soup.find_all(["article", "div", "section"]))
        if not has_text_container:
            for el in soup.find_all(["article", "div", "section"]):
                imgs = el.find_all("img")
                if len(imgs) >= 8:
                    tl = len(el.get_text(strip=True))
                    if tl / len(imgs) < 80:
                        return True, (f"photo_set:imgs={len(imgs)},"
                                      f"text_per_img={tl/len(imgs):.0f},"
                                      f"traf_text={traf_text_len}"), "photo_set"
    return False, None, "single"


# ---------------------------------------------------------------------------
# DOM 文本密度兜底
# ---------------------------------------------------------------------------

def dom_density_content(soup):
    # 不用 soup.body：gov.cn 畸形模板正文容器落在 <body> 之外（D-003）
    best, best_score = None, 0
    for el in soup.find_all(["article", "div", "section", "td", "main"]):
        text = el.get_text(strip=True)
        tl = len(text)
        if tl < 200:
            continue
        links = el.find_all("a")
        lt = sum(len(a.get_text(strip=True)) for a in links)
        if lt / max(tl, 1) > 0.5:
            continue
        np_ = len(el.find_all("p"))
        score = tl * min(np_, 10)
        if score > best_score:
            best, best_score = el, score
    if best is None:
        return None
    text, md, images, flags = assemble_container(best)
    return text, md, images, flags


# ---------------------------------------------------------------------------
# 主提取
# ---------------------------------------------------------------------------

def empty_record(declared, detected, used):
    return {
        "title": None, "authors": None, "publish_time": None, "update_time": None,
        "content_text": None, "content_md": None, "images": None,
        "conversion_flags": [], "page_condition": "ok", "needs_render": False,
        "content_structure": "single", "rejected": False,
        "source": {"encoding": {"declared": declared, "detected": detected,
                                "used": used}},
        "provenance": {}, "route": None,
    }


def extract_page(raw: bytes, site: str):
    html, declared, detected, used = decode_declared_first(raw)
    rec = empty_record(declared, detected, used)
    soup = BeautifulSoup(html, "lxml")

    # --- trafilatura 先行（拒识的 photo_set 信号需要其产出量） ---
    try:
        doc = trafilatura.bare_extraction(
            html, with_metadata=True, include_comments=False,
            include_tables=True)
    except Exception:  # noqa: BLE001
        doc = None
    traf_text_len = len((doc.text or "").strip()) if doc is not None else 0

    # --- 拒识判定 ---
    rejected, reason, cstruct = check_refusal(soup, site, traf_text_len)
    if rejected:
        rec["rejected"] = True
        rec["content_structure"] = cstruct
        rec["route"] = f"refused:{reason}"
        if reason.startswith("empty_shell"):
            rec["page_condition"] = "empty_shell"
            rec["needs_render"] = True
        rec["provenance"]["refusal"] = reason
        return rec

    # --- 各层候选 ---
    meta = parse_metadata_layer(soup)
    rules = SITE_RULES[site](soup, meta) if site in SITE_RULES else {}

    rule_first = site in SITE_RULES
    rec["route"] = "site_rules" if rule_first else "metadata+trafilatura"

    def pick(field, rule_key=None):
        """按路由优先级取字段；规则层 final 裁决优先一切。"""
        rk = rule_key or field
        rv = rules.get(rk)
        if rv is not None:
            val, prov = rv[0], rv[1]
            if prov == "final":        # 规则裁决为空，禁止回退
                rec["provenance"][field] = rv[2]
                return None
            if val is not None:
                rec["provenance"][field] = prov
                return val
        if meta.get(field):
            rec["provenance"][field] = meta["provenance"][field]
            return meta[field]
        return None

    # title
    title = pick("title")
    if title is None and doc is not None and doc.title:
        title = doc.title.strip()
        rec["provenance"]["title"] = "trafilatura:document.title"
    rec["title"] = title

    # authors
    authors = pick("authors")
    if authors is None and doc is not None and doc.author:
        authors = [a.strip() for a in re.split(r"[,;，；]", doc.author) if a.strip()]
        rec["provenance"]["authors"] = "trafilatura:document.author"
    rec["authors"] = authors or None

    # time
    for field in ("publish_time", "update_time"):
        val = pick(field)
        if val is None and field == "publish_time" and doc is not None and doc.date \
                and field not in rec["provenance"]:
            val = norm_traf_date(doc.date)
            rec["provenance"][field] = "trafilatura:document.date(htmldate)"
        rec[field] = val

    # content：规则层容器 → trafilatura → DOM 密度
    rc = rules.get("content")
    if rc and rc[0]:
        rec["content_text"], rec["content_md"], rec["images"], cflags, prov = rc
        rec["conversion_flags"] = cflags
        rec["provenance"]["content_text"] = prov
    elif doc is not None and doc.text:
        text = re.sub(r"\n{3,}", "\n\n", doc.text.strip())
        rec["content_text"] = text
        rec["content_md"] = text
        rec["provenance"]["content_text"] = "trafilatura:document.text"
    else:
        dc = dom_density_content(soup)
        if dc and dc[0]:
            rec["content_text"], rec["content_md"], rec["images"], cflags = dc
            rec["conversion_flags"] = cflags
            rec["provenance"]["content_text"] = "dom:density_container"
            rec["route"] = (rec["route"] or "") + "+dom_density"
    if rules.get("publisher"):
        rec["provenance"]["source.publisher"] = rules["publisher"][1]
        rec["source"]["publisher"] = rules["publisher"][0]
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
            rec = {"id": r["id"], **extract_page(raw, r["site"])}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"v3: wrote {n} records -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
