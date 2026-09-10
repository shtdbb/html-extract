#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract.py — 最终 baseline 提取器（= v4 冻结快照）

版本沿革（每版真实存在、真实全量跑分，见 versions/ 与 results/）：
  v1 trafilatura only → v2 +元数据层(JSON-LD/OG) → v3 +站点规则+拒识 →
  v4 +后缀剥离/署名扫描/时间补全/图片占位符装配。
迭代决策与回归记录见 decision_log.md（D-001~D-004）。

原 v4 文档头：
extract_v4.py — baseline v4：v3 + 标题后缀剥离 + 署名扫描 + 时间补全 + 正文图片占位符装配

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
  venv/bin/python extract.py --groups fixed,generic,negative --out results/v4_pred_dev.jsonl
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from site_rules import SITE_RULES, assemble_container  # noqa: E402
from extract_time import parse_time_str  # noqa: E402

ROOT = Path(__file__).resolve().parent

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
    jld = {"title": None, "authors": None, "publish_time": None,
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
            if not jld["title"] and node.get("headline"):
                jld["title"] = html_mod.unescape(str(node["headline"])).strip()
                jld["provenance"]["title"] = "json-ld:headline"
            au = node.get("author")
            if not jld["authors"] and au:
                names = []
                for a in (au if isinstance(au, list) else [au]):
                    if isinstance(a, dict) and a.get("name"):
                        names.append(html_mod.unescape(str(a["name"])).strip())
                    elif isinstance(a, str) and a.strip():
                        names.append(html_mod.unescape(a).strip())
                if names:
                    jld["authors"] = names
                    jld["provenance"]["authors"] = "json-ld:author"
            if not jld["publish_time"] and node.get("datePublished"):
                pt = parse_time_str(str(node["datePublished"]))
                if pt:
                    jld["publish_time"] = pt
                    jld["provenance"]["publish_time"] = "json-ld:datePublished"
            if not jld["update_time"] and node.get("dateModified"):
                ut = parse_time_str(str(node["dateModified"]))
                if ut:
                    jld["update_time"] = ut
                    jld["provenance"]["update_time"] = "json-ld:dateModified"

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
    # JSON-LD 兜底（D-004：全部字段 meta 优先、JSON-LD 补缺——time 字段同一瞬时
    # 的不同时区表示以 meta 为准，与 gold provenance「取 meta」一致；title/authors
    # 亦同序，og:title/twitter:title 通常已是剥离后缀的干净标题）
    if not out["publish_time"] and jld["publish_time"]:
        out["publish_time"] = jld["publish_time"]
        out["provenance"]["publish_time"] = jld["provenance"]["publish_time"]
    if not out["update_time"] and jld["update_time"]:
        out["update_time"] = jld["update_time"]
        out["provenance"]["update_time"] = jld["provenance"]["update_time"]
    if not out["title"] and jld["title"]:
        out["title"] = jld["title"]
        out["provenance"]["title"] = jld["provenance"]["title"]
    if not out["authors"] and jld["authors"]:
        out["authors"] = jld["authors"]
        out["provenance"]["authors"] = jld["provenance"]["authors"]
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
# v4：标题站点品牌后缀剥离
# ---------------------------------------------------------------------------

BRAND_EXACT = {
    "新华网", "新华社", "中国政府网", "新浪网", "新浪财经", "微博", "网易",
    "网易新闻", "腾讯", "腾讯网", "搜狐", "搜狐网", "手机搜狐网", "凤凰网",
    "凤凰财经", "澎湃新闻", "财新网", "中新网", "中国新闻网", "人民网",
    "光明网", "观察者网", "极目新闻", "博客园", "CSDN", "SegmentFault",
    "思否", "掘金", "开源中国", "IT之家", "知乎", "今日头条", "界面新闻",
    "人民日报", "环球网", "央视新闻", "东方财富", "同花顺", "证券时报",
    "每日经济新闻", "GitHub", "The GitHub Blog",
}
BRAND_PAT = re.compile(
    r"(?i)^(?:[a-z0-9][a-z0-9.-]*\.(?:com|cn|net|org|io|dev)(?:\.[a-z]{2})?"
    r"|.*\bdocumentation\b.*"
    r"|.*(?:chinadaily|china daily).*)$")


def _is_brand_segment(seg):
    s = seg.strip()
    if not s:
        return True
    if s in BRAND_EXACT:
        return True
    if BRAND_PAT.match(s):
        return True
    # 短栏目/频道名：含「频道/网」且 ≤6 字（如「财经频道」）
    if len(s) <= 6 and re.search(r"频道$|^.*网$", s) and not re.search(r"[，。！？：、]", s):
        return True
    return False


def strip_title_suffix(title):
    """剥离标题尾部的站点品牌/栏目后缀。

    D-004 重写：不再 split/rejoin（曾把标题内的「｜」「——」吞掉，
    chinanews__02「习言道｜一图读懂“金砖”」、segmentfault__03 标题内
    「——」被误改）。改为在**原串**上迭代：仅当末尾段经分隔符
    （_ | 前后带空格的 - — –）隔开且判定为品牌段时，切掉该段及分隔符，
    其余原样保留。全角「｜」不作分隔符（多为标题内栏目分隔，属标题本体）。
    """
    if not title:
        return title
    t = re.sub(r"\s+", " ", title).strip()
    sep_pat = re.compile(r"^(.*?)(?:[_|]|——|\s[-—–]\s)([^_|—–]+?)\s*$")
    while True:
        m = sep_pat.match(t)
        if not m:
            return t
        head, tail = m.group(1), m.group(2)
        if not head.strip():
            return t
        if _is_brand_segment(tail):
            t = head.rstrip(" _|—–-")
            continue
        return t


# ---------------------------------------------------------------------------
# v4：署名扫描（通用路由）+ meta 作者垃圾过滤
# ---------------------------------------------------------------------------

NAME_CN = r"[一-龥·]{2,4}"
GARBAGE_AUTHORS = {
    "admin", "administrator", "佚名", "编辑部", "官网", "官方", "原创",
    "新浪", "新浪财经", " chinanews", "chinanews", "中国新闻网", "本站",
    "来源", "未知", "网络", "互联网",
}


def _clean_author_name(name):
    n = re.sub(r"\s+", " ", name).strip(" ，,、。:：|｜")
    if not n or len(n) > 20:
        return None
    if n.lower() in GARBAGE_AUTHORS or n.isdigit():
        return None
    if re.fullmatch(NAME_CN, n):
        return n
    if re.fullmatch(r"[A-Z][A-Za-z.'-]+(?:\s+[A-Za-z.'-]+){0,3}", n):
        return n
    # 机构形态署名（新华社 / 博客园团队 / 极目新闻 等）保留
    if re.fullmatch(r"[一-龥A-Za-z0-9·]{2,10}", n) and not re.search(r"网$|频道$", n):
        return n
    return None


def filter_meta_authors(names):
    out = []
    for n in names or []:
        c = _clean_author_name(n)
        if c:
            out.append(c)
    return out or None


def scan_signature_authors(soup, content_text):
    """byline 区域 + 正文首行署名扫描。返回 (authors, provenance_list)。"""
    found, provs = [], []

    def add(names, role, prov):
        for nm in names:
            c = _clean_author_name(nm)
            if c:
                found.append(f"{c}（{role}）" if role else c)
                provs.append(prov)

    byline_texts = []
    seen_el = set()
    for el in soup.find_all(True):
        cid = " ".join(el.get("class", [])) + "#" + (el.get("id") or "")
        if not re.search(r"byline|author|editor|info|source|time|meta|edit", cid, re.I):
            continue
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if 0 < len(t) <= 150 and t not in seen_el:
            seen_el.add(t)
            byline_texts.append(t)
    head = (content_text or "")[:150]

    for t in byline_texts + [head]:
        m = re.search(r"责任编辑[:：]\s*([一-龥·]{2,4}(?:[\s、,，]+[一-龥·]{2,4}){0,3})", t)
        if m:
            add(re.split(r"[\s、,，]+", m.group(1)), "责任编辑", "署名扫描:责任编辑")
        m = re.search(r"(?<!责任)(?<!责)编辑[:：]\s*([一-龥·]{2,4}(?:[\s、,，]+[一-龥·]{2,4}){0,3})", t)
        if m:
            add(re.split(r"[\s、,，]+", m.group(1)), "编辑", "署名扫描:编辑")
        m = re.search(r"责编[:：]\s*([一-龥·]{2,4}(?:[\s、,，]+[一-龥·]{2,4}){0,3})", t)
        if m:
            add(re.split(r"[\s、,，]+", m.group(1)), "责任编辑", "署名扫描:责编")
        m = re.search(r"作者[:：]\s*([一-龥·A-Za-z]{2,15})", t)
        if m:
            add([m.group(1)], None, "署名扫描:作者")
        m = re.search(r"记者\s+([一-龥·]{2,4})(?=[\s，,。]|$)", t)
        if m:
            add([m.group(1)], None, "署名扫描:记者")
        m = re.search(r"^文\s*[|｜]\s*([一-龥·]{2,4})", t)
        if m:
            add([m.group(1)], None, "署名扫描:文|")
        m = re.search(r"(?<![A-Za-z])[Bb]y\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,2})", t)
        if m:
            add([m.group(1)], None, "署名扫描:By")
        m = re.search(r"摄影[:：]\s*([一-龥·]{2,4}(?:[\s、,，]+[一-龥·]{2,4}){0,3})", t)
        if m:
            add(re.split(r"[\s、,，]+", m.group(1)), "摄影", "署名扫描:摄影")
    # 去重（按去角色括号后名字）
    seen, out = set(), []
    for a in found:
        key = re.sub(r"（[^）]*）", "", a)
        if key not in seen:
            seen.add(key)
            out.append(a)
    return (out or None), provs


# ---------------------------------------------------------------------------
# v4：时间补全（byline 区域 DOM 扫描）
# ---------------------------------------------------------------------------

def scan_time_byline(soup):
    """在 class/id 含 time|date|info|source|byline 的短文本元素中找发布时间。"""
    for el in soup.find_all(True):
        cid = " ".join(el.get("class", [])) + "#" + (el.get("id") or "")
        if not re.search(r"time|date|info|source|byline", cid, re.I):
            continue
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if not (4 <= len(t) <= 120):
            continue
        pt = parse_time_str(t)
        if pt and pt["value"][:4] != "XXXX":
            if pt["utc_offset"] is None:
                pt["utc_offset"] = "+08:00"
                pt["utc_offset_source"] = "inferred_site_locale"
            return pt, f"dom:byline扫描[{cid.split('#')[0].strip() or cid}]"
    return None, None


# ---------------------------------------------------------------------------
# v4：trafilatura body 树正文装配（图片占位符 + GFM 表格）
# ---------------------------------------------------------------------------

def assemble_traf_body(body, title=None):
    """把 trafilatura bare_extraction 的 lxml body 树装配为
    (content_text, content_md, images, conversion_flags)。
    树形态：<body><head rend=hN/><p>…<graphic src=…/></p><list><item/>…"""
    lines, md_lines, images, flags = [], [], [], []
    norm_title = re.sub(r"\s+", "", title or "")

    def emit_graphic(g):
        images.append({"type": "正文插图",
                       "alt": g.get("alt") or g.get("title") or None,
                       "caption": None, "url": g.get("src"),
                       "width": None, "height": None})
        return f"[[IMG_{len(images)}]]"

    def text_with_imgs(el):
        parts = []
        if el.text:
            parts.append(el.text)
        for node in el:
            if node.tag == "graphic":
                parts.append(emit_graphic(node))
            else:
                parts.append(text_with_imgs(node))
            if node.tail:
                parts.append(node.tail)
        return "".join(parts)

    def handle(el):
        if el.tag in ("p", "head", "item", "quote", "code", "cell", "figure"):
            raw = text_with_imgs(el)
            # 图片占位符独立成行
            segs = re.split(r"(\[\[IMG_\d+\]\])", raw)
            for s in segs:
                s2 = re.sub(r"\s+", " ", s).strip()
                if not s2:
                    continue
                if re.fullmatch(r"\[\[IMG_\d+\]\]", s2):
                    lines.append(s2)
                    md_lines.append(s2)
                else:
                    if el.tag == "head" and norm_title and \
                            re.sub(r"\s+", "", s2) == norm_title:
                        continue  # trafilatura 会把标题作为第一个 head，去重
                    lines.append(s2)
                    md_lines.append(("- " if el.tag == "item" else "") + s2)
        elif el.tag in ("list", "table", "row"):
            for ch in el:
                handle(ch)
        else:
            for ch in el:
                handle(ch)

    for child in body:
        handle(child)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    md = "\n\n".join(md_lines).strip()
    return text or None, md or None, images or None, flags

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
            include_tables=True, include_images=True)  # v4: 图片占位符需要
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

    # title：规则/元数据 → traf → h1 → <title> 标签（v4 回退链补全）
    title = pick("title")
    title_from_rules = rec["provenance"].get("title", "").startswith("dom:")
    if title is None and doc is not None and doc.title:
        title = doc.title.strip()
        rec["provenance"]["title"] = "trafilatura:document.title"
    if title is None:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            title = re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
            rec["provenance"]["title"] = "dom://h1[1]"
    if title is None and soup.title and soup.title.string:
        title = re.sub(r"\s+", " ", soup.title.string.strip())
        rec["provenance"]["title"] = "dom://title"
    if title and not title_from_rules:
        stripped = strip_title_suffix(title)
        if stripped != title:
            rec["provenance"]["title"] = \
                rec["provenance"].get("title", "") + "+品牌后缀剥离"
        title = stripped
    rec["title"] = title

    # authors：规则/元数据（v4 垃圾过滤）→ traf → 署名扫描合并
    authors = pick("authors")
    if authors and rec["provenance"].get("authors", "").startswith(("meta:", "json-ld")):
        authors = filter_meta_authors(authors)
    if authors is None and doc is not None and doc.author:
        authors = filter_meta_authors(
            [a.strip() for a in re.split(r"[,;，；]", doc.author) if a.strip()])
        if authors:
            rec["provenance"]["authors"] = "trafilatura:document.author"
    scanned, scan_provs = scan_signature_authors(soup, None)
    if scanned:
        if authors:
            have = {re.sub(r"（[^）]*）", "", a) for a in authors}
            merged = authors + [a for a in scanned
                                if re.sub(r"（[^）]*）", "", a) not in have]
            if len(merged) > len(authors):
                rec["provenance"]["authors"] = \
                    rec["provenance"].get("authors", "") + "+" + "+".join(sorted(set(scan_provs)))
            authors = merged
        else:
            authors = scanned
            rec["provenance"]["authors"] = "+".join(sorted(set(scan_provs)))
    rec["authors"] = authors or None

    # time：规则/元数据 → v4 byline DOM 扫描补全与精化。
    # D-004：弃用 trafilatura htmldate 兜底——它从 URL/正文猜日期（日粒度），
    # 在 gold 不认可其来源的页面上制造 false_fill（python_docs×4、cnblogs×7），
    # 收益页为零（dev 上无仅靠 htmldate 得分的页面）。
    for field in ("publish_time", "update_time"):
        val = pick(field)
        rec[field] = val
    # D-004：通用路由下 dateModified==datePublished 视为 CMS 字段复制，
    # 不构成独立更新事件，update 留空（segmentfault×5 false_fill 修复；
    # fixed 规则站不受影响——gov.cn gold 确有 publish==update 的显式双时间）。
    if not rule_first and rec["publish_time"] and rec["update_time"] \
            and rec["publish_time"]["value"] == rec["update_time"]["value"]:
        rec["update_time"] = None
        rec["provenance"]["update_time"] = "suppressed:dateModified==datePublished(CMS字段复制)"
    if rec["publish_time"] is None and "publish_time" not in rec["provenance"]:
        st, sprov = scan_time_byline(soup)
        if st:
            rec["publish_time"] = st
            rec["provenance"]["publish_time"] = sprov
    elif rec["publish_time"] is not None:
        # 精化：已有值但时分秒为 XX（meta 只有日期）→ byline 扫描找同日更细粒度
        timepart = rec["publish_time"]["value"].split(" ", 1)[1] \
            if " " in rec["publish_time"]["value"] else "XX:XX:XX"
        if timepart.startswith("XX"):
            st, sprov = scan_time_byline(soup)
            if st and st["value"][:10] == rec["publish_time"]["value"][:10] \
                    and not st["value"].split(" ", 1)[1].startswith("XX"):
                rec["publish_time"] = st
                rec["provenance"]["publish_time"] = sprov + "（精化时分）"

    # content：规则层容器 → trafilatura body 树装配（v4 图片占位符）→ DOM 密度
    rc = rules.get("content")
    if rc and rc[0]:
        rec["content_text"], rec["content_md"], rec["images"], cflags, prov = rc
        rec["conversion_flags"] = cflags
        rec["provenance"]["content_text"] = prov
    elif doc is not None and doc.text:
        if doc.body is not None:
            text, md, images, cflags = assemble_traf_body(doc.body, title=rec["title"])
            if text:
                rec["content_text"], rec["content_md"] = text, md
                rec["images"] = images
                rec["conversion_flags"] = cflags
                rec["provenance"]["content_text"] = \
                    "trafilatura:bare_extraction.body树装配([[IMG_n]]占位)"
        if rec["content_text"] is None:
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
    print(f"extract.py(v4): wrote {n} records -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
