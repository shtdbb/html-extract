#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
site_rules.py — fixed 三站（news_cn / chinadaily / gov_cn）站点规则库。

选择器整理自 gold/gold_fixed.json 各记录的 provenance 字段（人工标注证据），
例如：
  news_cn   content: dom://div[@id="detail"]；title: dom://h1[1]；
            authors: 图说"新华社发（X摄）"/"新华社记者 X 摄" + //span[contains(@class,"editor")]【责任编辑:X】
  chinadaily content: dom://div[@id="Content"]；byline: span.info_l / div.Artical_Info "By X | ... | Updated: ..."
  gov_cn    content: dom://div[@id="UCAP-CONTENT"]；publish: meta[name=firstpublishedtime]

规则输出语义：
  value      字段值（或 None）
  final=True 表示"本站规则已裁决该字段不存在"，禁止下层回退填值
             （如 chinadaily 页面只有 Updated 一个时间，publish_time 必须留空）。
"""
import re

from extract_time import parse_time_str

# ---------------------------------------------------------------------------
# 通用容器正文装配：段落 + [[IMG_n]] 图片占位 + GFM 表格
# ---------------------------------------------------------------------------

BLOCK_TAGS = {"p", "div", "section", "article", "li", "blockquote", "pre",
              "h1", "h2", "h3", "h4", "h5", "h6", "figure", "table",
              "ul", "ol", "tr", "td", "th", "thead", "tbody"}


def _img_url(img):
    for attr in ("src", "data-src", "data-original", "data-lazy-src"):
        v = img.get(attr)
        if v and v.strip():
            return v.strip()
    return None


def _gfm_table(table, flags):
    rows = []
    if table.find(attrs={"colspan": True}) or table.find(attrs={"rowspan": True}):
        flags.append("table_colspan_flattened")
    for tr in table.find_all("tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))
                 for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |",
           "| " + " | ".join(["---"] * width) + " |"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return out


def assemble_container(container, caption_mode=None):
    """
    把 bs4 容器装配为 (content_text, content_md, images, conversion_flags)。
    caption_mode:
      None        —— figcaption/图说保留在正文（通用默认）；
      'news_cn'   —— img 段落后紧跟的"…新华社…摄…"图说段移入 images[].caption；
      'figure'    —— figure/figcaption 移入 images[].caption（chinadaily）。
    """
    lines, md_lines, images, flags = [], [], [], []
    last_img_idx = None  # 最近一张图在 images 中的下标

    def emit_img(img, caption=None):
        nonlocal last_img_idx
        url = _img_url(img)
        images.append({"type": "正文插图",
                       "alt": (img.get("alt") or "").strip() or None,
                       "caption": caption, "url": url,
                       "width": img.get("width"), "height": img.get("height")})
        last_img_idx = len(images) - 1
        lines.append(f"[[IMG_{len(images)}]]")
        md_lines.append(f"[[IMG_{len(images)}]]")

    def walk(el):
        nonlocal last_img_idx
        from bs4 import NavigableString, Tag
        if isinstance(el, NavigableString):
            return
        if not isinstance(el, Tag) or el.name in ("script", "style", "noscript"):
            return
        if el.name == "table":
            trows = _gfm_table(el, flags)
            if trows:
                plain = [" ".join(r[1:-1].split("|")).strip() for r in trows[2:]]
                for pr in plain:
                    if pr:
                        lines.append(pr)
                md_lines.extend(trows)
            last_img_idx = None
            return
        if el.name == "figure":
            cap = None
            fc = el.find("figcaption")
            if fc:
                cap = re.sub(r"\s+", " ", fc.get_text(" ", strip=True)) or None
            imgs = el.find_all("img")
            if imgs:
                for im in imgs:
                    emit_img(im, caption=cap if caption_mode == "figure" else None)
                if caption_mode == "figure" and cap:
                    pass  # 图说已移入 images[].caption，不进正文
                elif cap:
                    lines.append(cap)
                    md_lines.append(cap)
            elif fc and fc.get_text(strip=True):
                lines.append(re.sub(r"\s+", " ", fc.get_text(" ", strip=True)))
            return
        if el.name == "img":
            emit_img(el)
            return
        block_children = [c for c in el.children
                          if isinstance(c, Tag) and c.name in BLOCK_TAGS]
        if block_children:
            for c in el.children:
                walk(c)
            return
        # 叶子块：按文档序交替收集文本与内联 img
        buf = []
        for node in el.descendants:
            if isinstance(node, NavigableString):
                if node.parent.name not in ("script", "style"):
                    buf.append(str(node))
            elif isinstance(node, Tag) and node.name == "img":
                text = re.sub(r"\s+", " ", "".join(buf)).strip()
                if text:
                    lines.append(text)
                    md_lines.append(text)
                buf = []
                emit_img(node)
        text = re.sub(r"\s+", " ", "".join(buf)).strip()
        if text:
            # news_cn 图说识别：紧邻上一张图、且是"…新华社…摄…"图说段
            if (caption_mode == "news_cn" and last_img_idx is not None
                    and "新华社" in text and "摄" in text):
                images[last_img_idx]["caption"] = text
            else:
                lines.append(text)
                md_lines.append(text)
                if el.name == "li":
                    md_lines[-1] = "- " + text
        if el.name in BLOCK_TAGS and text:
            last_img_idx = None if not images else last_img_idx

    walk(container)
    text = "\n".join(lines)
    md = "\n\n".join(md_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text or None, md or None, images or None, flags


# ---------------------------------------------------------------------------
# 站点规则
# ---------------------------------------------------------------------------

def _first_text(soup, selectors):
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            t = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
            if t:
                return t, f"dom:{sel}"
    return None, None


def rule_news_cn(soup, meta):
    out = {"provenance": {}, "conversion_flags": []}
    t, prov = _first_text(soup, ["h1"])
    if t:
        out["title"] = (t, "dom://h1[1]")
    info = soup.find("div", class_=lambda c: c and "info" in c.split())
    if info:
        itext = re.sub(r"\s+", " ", info.get_text(" ", strip=True))
        m = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})", itext)
        if m:
            out["publish_time"] = (
                {"value": f"{m.group(1)} {m.group(2)}", "utc_offset": "+08:00",
                 "utc_offset_source": "inferred_site_locale"},
                'dom://div[contains(@class,"info")] 文本行')
        m = re.search(r"来源：\s*(\S+)", itext)
        if m:
            out["publisher"] = (m.group(1), 'dom://div.info "来源："行')
    detail = soup.find("div", id="detail")
    if detail:
        text, md, images, flags = assemble_container(detail, caption_mode="news_cn")
        out["content"] = (text, md, images, flags,
                          'dom://div[@id="detail"]（图说 p 移入 images[].caption）')
        # 作者：图说摄影 + 尾部文字记者/海报设计 + 责任编辑 span
        authors, aprov = [], []
        for img in (images or []):
            cap = img.get("caption") or ""
            for pat in (r"新华社发（([^）]+?)\s*摄）", r"新华社记者\s+([^，。]+?)\s+摄"):
                m = re.search(pat, cap)
                if m:
                    for nm in re.split(r"[\s、，,]+", m.group(1)):
                        if nm and re.fullmatch(r"[一-龥]{2,4}", nm):
                            authors.append(f"{nm}（摄影）")
                    aprov.append("图说摄影署名")
                    break
        if text:
            for pat, role in ((r"^文字记者：(.+)$", None),
                              (r"^海报设计：(.+)$", "海报设计")):
                for m in re.finditer(pat, text, re.M):
                    for nm in re.split(r"[、，,\s]+", m.group(1).strip()):
                        if nm and re.fullmatch(r"[一-龥]{2,4}", nm):
                            authors.append(f"{nm}（{role}）" if role else nm)
                    aprov.append('正文尾部署名行')
        for sp in detail.find_all("span",
                                  class_=lambda c: c and "editor" in c.split()):
            m = re.search(r"责任编辑[:：]\s*([一-龥]{2,4})", sp.get_text())
            if m:
                authors.append(f"{m.group(1)}（责任编辑）")
                aprov.append('//span[contains(@class,"editor")]【责任编辑:X】')
        if authors:
            seen, dedup = set(), []
            for a in authors:
                if a not in seen:
                    seen.add(a)
                    dedup.append(a)
            out["authors"] = (dedup, "+".join(sorted(set(aprov))))
    return out


def rule_chinadaily(soup, meta):
    out = {"provenance": {}, "conversion_flags": []}
    t, prov = _first_text(soup, ["h1"])
    if t:
        out["title"] = (t, "dom://h1[1]")
    # byline：span.info_l 或 div.Artical_Info
    by = soup.find("span", class_=lambda c: c and "info_l" in c.split()) or \
         soup.find("div", class_="Artical_Info")
    authors = []
    if by:
        btext = re.sub(r"\s+", " ", by.get_text(" ", strip=True)).replace("\xa0", " ")
        m = re.search(r"^By\s+(.+?)\s*\|", btext)
        if m:
            seg = m.group(1)
            # "ZHOU LANXU in Beijing and SHI JING in Shanghai" → 两人
            for part in re.split(r"\s+and\s+", seg):
                part = re.sub(r"\s+in\s+[A-Z][A-Za-z]+$", "", part).strip()
                if part and part.lower() not in ("chinadaily.com.cn", "china daily"):
                    authors.append(part)
        elif not btext.lower().startswith(("chinadaily.com.cn", "china daily")):
            seg = re.split(r"\s*\|", btext)[0].strip()
            if seg and not re.search(r"updated", seg, re.I):
                authors.append(seg)  # 机构署名位，如 Xinhua
        m = re.search(r"Updated:\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", btext)
        if m:
            out["update_time"] = (
                {"value": f"{m.group(1)} {m.group(2)}:XX", "utc_offset": "+08:00",
                 "utc_offset_source": "inferred_site_locale"},
                'dom:byline "Updated:" 文本')
    # chinadaily 页面仅此一个时间：publish_time 裁决为空（final，禁止回退）
    out["publish_time"] = (None, "final", "dom:byline 页面仅此一个时间，无发布时间")
    content = soup.find("div", id="Content")
    if content:
        text, md, images, flags = assemble_container(content, caption_mode="figure")
        out["content"] = (text, md, images, flags,
                          'dom://div[@id="Content"]（figure/figcaption 移入 images[].caption）')
        # figcaption 纯摄影署名 "X/CHINA DAILY"
        for img in (images or []):
            cap = img.get("caption") or ""
            m = re.match(r"^([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\s*/\s*CHINA DAILY\s*$", cap)
            if m:
                authors.append(f"{m.group(1)}（摄影）")
    if authors:
        seen, dedup = set(), []
        for a in authors:
            if a not in seen:
                seen.add(a)
                dedup.append(a)
        out["authors"] = (dedup, 'dom:byline "By X | ..." + figure/figcaption 摄影署名')
    else:
        # v6：byline 区块无有效署名时 final 裁决为空——chinadaily 的
        # meta[name=author] 是后台录入编辑（chinadaily__07「贺霞婷」false_fill），
        # 全站 10 页核对：其余 9 页作者均来自 byline，无一依赖 meta 回退。
        out["authors"] = (None, "final",
                          "dom:byline 无有效署名；meta[name=author] 为后台录入编辑，不予采用")
    return out


def rule_gov_cn(soup, meta):
    out = {"provenance": {}, "conversion_flags": []}
    t, prov = _first_text(soup, ["h1", "div.share-title"])
    if t:
        prov = "dom://h1[1]" if soup.find("h1") and soup.find("h1").get_text(strip=True) \
               else 'dom://div[@class="share-title"]'
        out["title"] = (t, prov)
    au = soup.find("meta", attrs={"name": "author"})
    if au and au.get("content", "").strip():
        out["authors"] = ([f"{au['content'].strip()}（责任编辑）"],
                          "meta[name=author]（gov.cn 模板此字段为责任编辑）")
    pub = soup.find("meta", attrs={"name": "firstpublishedtime"})
    if pub and pub.get("content"):
        pt = parse_time_str(pub["content"].strip())
        if pt:
            pt["utc_offset"] = "+08:00"
            pt["utc_offset_source"] = "inferred_site_locale"
            out["publish_time"] = (pt, "meta[name=firstpublishedtime]")
    upd = soup.find("meta", attrs={"name": "lastmodifiedtime"})
    if upd and upd.get("content"):
        ut = parse_time_str(upd["content"].strip())
        if ut:
            ut["utc_offset"] = "+08:00"
            ut["utc_offset_source"] = "inferred_site_locale"
            out["update_time"] = (ut, "meta[name=lastmodifiedtime]")
    content = soup.find("div", id="UCAP-CONTENT")
    if content:
        text, md, images, flags = assemble_container(content)
        out["content"] = (text, md, images, flags, 'dom://div[@id="UCAP-CONTENT"]')
    pd_ = soup.find("div", class_=lambda c: c and "pages-date" in c.split())
    if pd_:
        m = re.search(r"来源：\s*(\S+)", re.sub(r"\s+", " ", pd_.get_text(" ", strip=True)))
        if m:
            out["publisher"] = (m.group(1), 'dom://div.pages-date "来源："行')
    return out


SITE_RULES = {
    "news_cn": rule_news_cn,
    "chinadaily": rule_chinadaily,
    "gov_cn": rule_gov_cn,
}
