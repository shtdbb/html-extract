#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract.py — 当前提取器（自进化迭代工作版）

版本沿革（每版真实存在、真实全量跑分，见 versions/ 与 results/）：
  v1 trafilatura only → v2 +元数据层(JSON-LD/OG) → v3 +站点规则+拒识 →
  v4 +后缀剥离/署名扫描/时间补全/图片占位符装配（= 上一课题阶段冻结终态）→
  v5 +loop 分层耗时埋点（策略与 v4 完全一致，用于闭环成本观测基线）。
迭代决策与回归记录见 decision_log.md（D-001~D-004 为上一阶段；自进化阶段
见 loop/iteration_log.md 与 git 历史）。

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
import os
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
from loop.layer_timer import timed  # noqa: E402  # v5: 分层耗时埋点

# v10：模型兜底臂开关。默认关闭（纯规则路径零模型依赖、行为与 v9 一致）；
# EXTRACT_MODEL=1 时低置信字段才走本地 Qwen2.5-7B 补全（loop/model_arm.py）。
_MODEL_ENABLED = os.environ.get("EXTRACT_MODEL") == "1"


def get_model_stats():
    """run_iteration.py 的成本钩子：返回模型臂累计统计（未启用则为 None）。"""
    if not _MODEL_ENABLED:
        return None
    from loop import ollama_client
    return ollama_client.stats()

ROOT = Path(__file__).resolve().parent

ARTICLE_TYPES = {"newsarticle", "article", "blogposting", "techarticle",
                 "reportagenewsarticle", "scholarlyarticle", "socialmediaposting"}

# v8：通用 CMS 模板正文容器先验表（选择器, 标签）。均为全网流通的 CMS 模板
# 签名，非 dev 页面私有结构；逐项在 dev 上验证过容器区域=gold 区域。
CONTAINER_PRIORS = [
    ("div.left_zw", "left_zw(chinanews系CMS)"),
    ("div.rm_txt_con", "rm_txt_con(人民网CMS)"),
    ("div#artibody", "artibody(新浪系CMS)"),
    ('div[class^="index_text_"]', "index_text_*(凤凰CSS-modules)"),
]


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


def _unescape_stable(s: str) -> str:
    """v6：迭代实体解码直至稳定（JSON-LD 双重转义 &amp;quot; → &quot; → "，
    cnblogs__03 标题残留 &quot; 的修复）。上限 3 趟防构造性死循环。"""
    for _ in range(3):
        t = html_mod.unescape(s)
        if t == s:
            return t
        s = t
    return s


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
                jld["title"] = _unescape_stable(str(node["headline"])).strip()
                jld["provenance"]["title"] = "json-ld:headline"
            au = node.get("author")
            if not jld["authors"] and au:
                names = []
                for a in (au if isinstance(au, list) else [au]):
                    if isinstance(a, dict) and a.get("name"):
                        names.append(_unescape_stable(str(a["name"])).strip())
                    elif isinstance(a, str) and a.strip():
                        names.append(_unescape_stable(a).strip())
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


def _is_channel_segment(seg):
    """v7：短栏目段（-- 链中间段），如「经济·科技」「财经·滚动」。
    保守口径：≤10 字、无句读标点、含间隔号 · 或频道/栏目/滚动/专题/原创字样。"""
    s = seg.strip()
    if not s or len(s) > 10:
        return False
    if re.search(r"[，。！？：；、（）()《》“”『』「」…—]", s):
        return False
    return "·" in s or bool(re.search(r"频道|栏目|滚动|专题$|原创$", s))


# v11：英文品牌段词表（站名后缀通用词，非具体站点私有签名）。
# 驱动证据：ISPRAS 25+ 页「标题 - Brand | News」「 | Ghana News Agency」
# 「 — Official website of …」型后缀未剥（title 0 分最大簇）。
_EN_BRAND_WORDS = {"news", "online", "network", "agency", "official",
                   "website", "events", "home", "english"}


def _is_brand_segment_en(seg, site):
    """英文品牌/面包屑尾段判定。保守口径，满足其一——
    ①归一化后含站点词干（首标 ≥4 字符，或整域归一化 ≥4 字符——
      24.kg→24kg、fm.gov.om→fmgovom，首标过短站点的兜底）；
    ②含面包屑层级符 > / »；③含 official website/site 字样；
    ④≤40 字符且命中品牌词表（News/Online/Network/Agency/Events…）。"""
    s = seg.strip()
    if not s:
        return True
    low = s.lower()
    if "official website" in low or "official site" in low:
        return True
    if " > " in s or " » " in s:
        return True
    if len(s) > 60:
        return False
    norm = re.sub(r"[^a-z0-9]", "", low)
    labels = (site or "").lower().split(".")
    stems = {re.sub(r"[^a-z0-9]", "", x) for x in (labels[0], "".join(labels))}
    if any(len(st) >= 4 and st in norm for st in stems):
        return True
    if len(s) <= 40 and set(re.findall(r"[a-z]+", low)) & _EN_BRAND_WORDS:
        return True
    return False


_H1_POSITIVE = re.compile(
    r"article|post|content|entry|detail|main|headline|story|body", re.I)
_H1_NEGATIVE = re.compile(
    r"header|banner|masthead|blog[-_]?title|site[-_]?(title|name|header)"
    r"|topbar|navbar|gnb|logo|slogan", re.I)

# v14.1 二次守卫：h1 文本本身是通用栏目/导航标签时不是标题。
# 证据：ISPRAS v14 首跑的 8 个误翻转全部为此类——「Welcome」「Events」
# 「Vol 65 No 6」（刊期标签），均通过 DOM 位置守卫但文本无标题信息。
_H1_LABEL_WORDS = {
    "welcome", "events", "event", "news", "home", "homepage", "articles",
    "article", "latest", "more", "features", "feature", "topics", "topic",
    "sections", "section", "category", "categories", "archive", "archives",
    "index", "overview", "vol", "volume", "no", "issue", "iss", "pp",
    "page", "pages", "edition", "back", "next", "previous", "menu",
}


def _h1_is_generic_label(text: str) -> bool:
    """h1 文本全由通用栏目词/数字/标点组成 → 刊期标签或导航词，非标题。"""
    tokens = re.findall(r"[a-z]+|\d+", text.lower())
    return bool(tokens) and all(
        t in _H1_LABEL_WORDS or t.isdigit() for t in tokens)


def _h1_is_headline(h1) -> bool:
    """h1 是否为文章标题位（而非页头横幅位的站名/博客标语）。
    逐级上溯（≤6 层）：每级先查正文语义（article/headline/content…），
    命中即真；再查横幅语义（header/banner/blogTitle/logo…），命中即假。
    同级正文优先——<header> 嵌在 article 内时是标题区而非页头
    （abc h1 链：h1 < div.Headline_meta < header < div.Article_layoutMain）。
    皆无信号默认真（h1 在大多数模板中即标题）。"""
    el = h1
    for _ in range(6):
        el = el.parent
        if not el or not el.name or el.name == "body":
            break
        sig = f"{el.get('id') or ''} {' '.join(el.get('class') or [])}"
        if _H1_POSITIVE.search(sig):
            return True
        if _H1_NEGATIVE.search(sig):
            return False
    return True


def strip_title_suffix(title, site=None):
    """剥离标题尾部的站点品牌/栏目后缀。

    D-004 重写：不再 split/rejoin（曾把标题内的「｜」「——」吞掉，
    chinanews__02「习言道｜一图读懂“金砖”」、segmentfault__03 标题内
    「——」被误改）。改为在**原串**上迭代：仅当末尾段经分隔符
    （_ | 前后带空格的 - — –）隔开且判定为品牌段时，切掉该段及分隔符，
    其余原样保留。全角「｜」不作分隔符（多为标题内栏目分隔，属标题本体）。

    v7：双连字符 -- 后缀链先行剥离（people 全站：标题--经济·科技--人民网）。
    rpartition 取最后一段，品牌段或短栏目段（_is_channel_segment）才剥，
    否则原样保留（cnblogs__05「---（1）--- 总体」类标题内连字符不受损，
    已核 dev gold 全量仅此一例含 -- 标题且尾段不通过检查）。
    """
    if not title:
        return title
    t = re.sub(r"\s+", " ", title).strip()
    while "--" in t:
        head, _, tail = t.rpartition("--")
        if not head.strip():
            break
        if _is_brand_segment(tail) or _is_channel_segment(tail):
            t = head.rstrip(" _|—–-")
            continue
        break
    sep_pat = re.compile(r"^(.*?)(?:[_|]|——|\s[-—–]\s)([^_|—–]+?)\s*$")
    while True:
        m = sep_pat.match(t)
        if not m:
            return t
        head, tail = m.group(1), m.group(2)
        if not head.strip():
            return t
        if _is_brand_segment(tail) or _is_brand_segment_en(tail, site):
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
# v6：媒体/栏目名 ≠ 作者。门户转载页的 meta/JSON-LD author 系统性填媒体名
# （澎湃新闻/市场资讯/观察者网/凤凰网综合/央视新闻/中国新闻周刊……）。
# len≥4 约束：避免误伤「张新闻」类真实人名（人名一般 2-3 字）。
# 已对 dev gold 121 个作者名全量核对零碰撞（loop/probe_authors.py 口径）。
MEDIA_NAME_PAT = re.compile(
    r"(新闻|资讯|周刊|日报|晚报|时报|快报|传媒|媒体|电视台|广播|频道|综合|"
    r"客户端|杂志|早报|周刊社|作者库)$|网$")


def _is_media_name(n: str) -> bool:
    return len(n) >= 4 and bool(MEDIA_NAME_PAT.search(n))


def _clean_author_name(name):
    n = re.sub(r"\s+", " ", name).strip(" ，,、。:：|｜")
    if not n or len(n) > 20:
        return None
    if n.lower() in GARBAGE_AUTHORS or n.isdigit():
        return None
    if _is_media_name(n):
        return None
    if re.fullmatch(NAME_CN, n):
        return n
    if re.fullmatch(r"[A-Z][A-Za-z.'-]+(?:\s+[A-Za-z.'-]+){0,3}", n):
        return n
    # 机构形态署名（新华社 / 博客园团队 / OceanBase技术站 等）保留。
    # v6：长度上限 10→16（OceanBase技术站 12 字符曾被误杀）；网$/频道$
    # 拒收已由 _is_media_name 统一承担。
    if re.fullmatch(r"[一-龥A-Za-z0-9·]{2,16}", n):
        return n
    return None


def filter_meta_authors(names, soup=None):
    """meta/json-ld/traf 来源作者过滤。v12：机构/角色类垃圾名仅当在页面
    可见文本中作为独立署名行出现时豁免（可见署名=真值；meta 声称需佐证）。
    soup 仅在有垃圾名候选时才取用（惰性，避免每页付出文本装配成本）。"""
    out = []
    page_text = None
    for n in names or []:
        c = _clean_author_name(n)
        if not c:
            continue
        cat = _author_en_category(c)
        if cat in ("social", "month"):
            continue
        if cat == "org_role":
            if soup is not None:
                if page_text is None:
                    page_text = _visible_page_text(soup)
                if _is_standalone_byline(c, page_text):
                    out.append(c)
            continue
        out.append(c)
    return out or None


# v12：英文机构/角色/垃圾署名过滤（通用路由全来源共用：meta 过滤、
# 署名扫描、模型臂）。驱动证据：ISPRAS authors false_fill 最大簇——
# meta:author 填机构名（ABS-CBN News/The Federal Council/Service Canada）、
# 通用角色（Staff Reporter/Global Stringer）、社交品牌（Facebook）、
# 月份词（May——By 扫描把日期词当署名）。均为通用垃圾形态，非站点私有。
# 分三类：社媒词=永拒（分享按钮非署名）；月份/星期词=永拒（日期误抓）；
# 机构/角色词=仅当作为可见独立署名行出现时豁免（ISPRAS gold 实测口径：
# 可见署名「News Team」「Citizen Reporter」照标，meta-only「Staff Reporter」不标）。
_EN_SOCIAL_WORDS = {"facebook", "twitter", "instagram", "youtube",
                    "telegram", "whatsapp", "linkedin", "tiktok", "x"}
_EN_ORG_ROLE_WORDS = {
    "news", "reporter", "stringer", "correspondent", "bureau", "desk",
    "council", "service", "services", "ministry", "department", "government",
    "admin", "administrator", "editor", "editors", "editorial",
    "writer", "team", "agency", "agencies", "media", "press", "radio",
    "television",
    "tv", "online", "digital", "web", "website", "network", "wire",
}
_EN_MONTH_WORDS = {"january", "february", "march", "april", "may", "june",
                   "july", "august", "september", "october", "november",
                   "december", "jan", "feb", "mar", "apr", "jun", "jul",
                   "aug", "sep", "sept", "oct", "nov", "dec",
                   "monday", "tuesday", "wednesday", "thursday", "friday",
                   "saturday", "sunday", "mon", "tue", "wed", "thu", "fri",
                   "sat", "sun"}


def _author_en_category(name):
    """纯拉丁署名分类：'social'（永拒）/ 'month'（永拒）/ 'org_role'
    （需可见署名佐证）/ None（正常名）。中文署名不受影响
    （dev gold 121 名零碰撞已核，含 GitHub Staff——staff 已移出词表）。"""
    if not re.fullmatch(r"[A-Za-z0-9 .,'&-]+", name or ""):
        return None
    words = set(re.findall(r"[a-z]+", name.lower()))
    if words & _EN_SOCIAL_WORDS:
        return "social"
    if words and words <= _EN_MONTH_WORDS:
        return "month"
    if words & _EN_ORG_ROLE_WORDS:
        return "org_role"
    return None


_BYLINE_PREFIX = re.compile(
    r"^(?:by|作者|记者|撰文|撰稿|编辑|责编|摄影|文)\s*[:：/]?\s*", re.I)


def _is_standalone_byline(name: str, page_text: str) -> bool:
    """署名位置核验：名字作为独立行（或剥掉署名前缀后的独立行）出现。

    v12 起承担双重职责：①模型臂作者采纳的前提；②meta 机构/角色名的
    豁免依据——ISPRAS gold 口径实测：可见署名行里的角色名照标
    （anguillafocus「News Team」、citizen_digital「Citizen Reporter」），
    仅存在于 meta 的角色名不标（newsday「Staff Reporter」）——
    可见署名 = 真值，meta 声称需可见佐证，与本项目「值须页内可核验」
    纪律同源。
    """
    target = re.sub(r"\s+", "", (name or "")).lower()
    for line in page_text.split("\n"):
        line = line.strip()
        if not line or len(line) > 80:
            continue
        if re.sub(r"\s+", "", line).lower() == target:
            return True
        stripped = _BYLINE_PREFIX.sub("", line)
        if stripped != line and re.sub(r"\s+", "", stripped).lower() == target:
            return True
    return False


def _visible_page_text(soup, limit=6000) -> str:
    """全页可见文本（script/style/noscript 剔除；副本操作不污染原树）。"""
    import copy
    sp = copy.copy(soup)
    for tag in sp(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", sp.get_text("\n", strip=True))[:limit]


def scan_signature_authors(soup, content_text):
    """byline 区域 + 正文首/尾署名扫描。返回 (authors, provenance_list)。

    v6：①content_text 真实传入（v4 传 None，正文首行扫描从未生效——sohu×4
    漏抽的直接原因）；②扫描窗扩为 首部300+尾部300 字符（署名常居正文末段，
    如 news_cn「（记者A、B、C）」、sohu「责任编辑：X」）；③byline 元素属性
    匹配补 data-role/rel（sohu 的 p[data-role=editor-name]）；④新增模式：
    多人并列（空格/顿号分隔）、执笔：、记者顿号列表、行尾「X 摄」。
    """
    found, provs = [], []

    def add(names, role, prov):
        for nm in names:
            c = _clean_author_name(nm)
            if not c:
                continue
            cat = _author_en_category(c)
            if cat in ("social", "month"):
                continue
            if cat == "org_role":
                # 扫描来源本身可见，但分享按钮等杂讯需独立署名行佐证
                # （org_role 命中稀少，直接装配可见文本，不做跨调用缓存）
                if _is_standalone_byline(c, _visible_page_text(soup)):
                    found.append(f"{c}（{role}）" if role else c)
                    provs.append(prov)
                continue
            found.append(f"{c}（{role}）" if role else c)
            provs.append(prov)

    # v6 修订①：并列名的续接分隔符只认 [空格/制表/顿号]——不认换行与逗号
    # （「王灿\n近日，…」「韩迅\n谁也没想到…」跨行误抓下句首词）；
    # 末尾负向断言：名字串后不得再接「分隔符+汉字」（防半截名字串）。
    NAME1 = r"[一-龥·]{2,4}"
    NAMES = rf"({NAME1}(?:[ \t、]+{NAME1}){{0,3}})(?![ \t、]*{NAME1})"
    # v6 修订②：电头括注记者署名（「…电（记者X、Y）」「…电 （记者 X）」，
    # 全/半角括号均存在）不计——gold 边界实测：电头内记者未标注
    # （people__02、chinanews__05），正文末段独立「（记者…）」credit 才标注
    # （news_cn__09、sina__04）。
    def _in_dateline(t, start):
        return bool(re.search(r"电\s*[（(]\s*$", t[max(0, start - 16):start]))

    def scan_text(t, where):
        m = re.search(r"责任编辑[:：]\s*" + NAMES, t)
        if m:
            add(re.split(r"[ \t、]+", m.group(1)), "责任编辑",
                f"署名扫描:责任编辑[{where}]")
        m = re.search(r"(?<!责任)(?<!责)编辑[:：]\s*" + NAMES, t)
        if m:
            add(re.split(r"[ \t、]+", m.group(1)), "编辑",
                f"署名扫描:编辑[{where}]")
        m = re.search(r"责编[:：]\s*" + NAMES, t)
        if m:
            add(re.split(r"[ \t、]+", m.group(1)), "责任编辑",
                f"署名扫描:责编[{where}]")
        m = re.search(r"作者[:：]\s*" + NAMES, t)
        if m:
            add(re.split(r"[ \t、]+", m.group(1)), None,
                f"署名扫描:作者[{where}]")
        m = re.search(r"执笔[:：]\s*" + NAMES, t)
        if m:
            add(re.split(r"[ \t、]+", m.group(1)), None,
                f"署名扫描:执笔[{where}]")
        # 空格分隔形式：「澎湃新闻记者 计思敏」「总台记者 张玥 石玥」。
        # [ \t] 而非 \s：防止跨行把下行首词当名字（「新华社记者\n近日，…」误抓「近日」）。
        m = re.search(r"记者[ \t]+" + NAMES + r"(?=[\s，,。）)】]|$)", t)
        if m and not _in_dateline(t, m.start()):
            add(re.split(r"[ \t、]+", m.group(1)), None,
                f"署名扫描:记者[{where}]")
        # 无空格顿号列表形式：「（记者魏玉坤、谢希瑶、申铖、王雨萧）」
        m = re.search(r"记者((?:[一-龥·]{2,4}、)+[一-龥·]{2,4})(?=[）)])", t)
        if m and not _in_dateline(t, m.start()):
            add(re.split(r"[、]", m.group(1)), None,
                f"署名扫描:记者列表[{where}]")
        m = re.search(r"^文\s*[|｜]\s*([一-龥·]{2,4})", t)
        if m:
            add([m.group(1)], None, f"署名扫描:文|[{where}]")
        m = re.search(r"(?<![A-Za-z])[Bb]y[ \t]+([A-Z][A-Za-z.'-]+(?:[ \t]+[A-Z][A-Za-z.'-]+){0,2})", t)
        # v6 修订⑤：散文中的「…supported by Python.\nFor example…」非署名——
        # 捕获名以句点结尾（句子边界）时拒收；[ \t] 不换行同 修订①。
        # v9 修订：首词为英文虚词/栏目词的拒收（ISPRAS「Just For The …」误抓）。
        BY_STOP = {"just", "for", "the", "a", "an", "this", "that", "these",
                   "those", "read", "more", "click", "see", "watch", "listen",
                   "sponsored", "special", "from", "with", "breaking", "live",
                   "update", "updated", "video", "photos", "gallery", "opinion"}
        if m and not m.group(1).rstrip().endswith(".") \
                and t[m.end():m.end() + 1] != "." \
                and m.group(1).split()[0].lower() not in BY_STOP:
            add([m.group(1)], None, f"署名扫描:By[{where}]")
        m = re.search(r"摄影[:：]\s*" + NAMES, t)
        if m:
            add(re.split(r"[ \t、]+", m.group(1)), "摄影",
                f"署名扫描:摄影[{where}]")

    CAPTION_STOP = {"本报记者", "新华社", "央视记者", "总台记者", "本报", "记者"}

    def scan_lines(t, where):
        """逐行模式：行尾「X 摄」（图说摄影署名，如 chinanews__05 薛伟 摄）。"""
        for line in (t or "").split("\n"):
            line = line.strip()
            if not (2 <= len(line) <= 40):
                continue
            m = re.search(r"(?:^|[\s。])([一-龥·]{2,4})\s*摄$", line)
            if m and m.group(1) not in CAPTION_STOP \
                    and not m.group(1).endswith("记者"):
                add([m.group(1)], "摄影", f"署名扫描:行尾摄[{where}]")

    def scan_caption_els():
        """全文档图说元素（figcaption / class 含 pictext|caption|photo）的
        「X 摄」署名——图说常不在 pred 正文内（trafilatura 会丢 pictext 块，
        chinanews__05 薛伟），需直接扫 DOM。"""
        for el in soup.find_all(True):
            cid = " ".join(el.get("class", [])) + "#" + (el.get("id") or "")
            if el.name != "figcaption" and \
                    not re.search(r"pictext|caption|photo", cid, re.I):
                continue
            scan_lines(el.get_text("\n", strip=True), "图说元素")

    byline_texts = []
    seen_el = set()
    for el in soup.find_all(True):
        cid = (" ".join(el.get("class", [])) + "#" + (el.get("id") or "")
               + "#" + (el.get("data-role") or "")
               + "#" + " ".join(el.get("rel") or []))
        if not re.search(r"byline|author|editor|info|source|time|meta|edit", cid, re.I):
            continue
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if 0 < len(t) <= 150 and t not in seen_el:
            seen_el.add(t)
            byline_texts.append(t)
    head = (content_text or "")[:300]
    tail = (content_text or "")[-500:] if len(content_text or "") > 500 else ""  # v6 修订③: 尾部 300→500（chinanews 署名校样块在末 371 字符）

    for t in byline_texts:
        scan_text(t, "byline")
    scan_text(head, "首部")
    scan_text(tail, "尾部")
    scan_lines(head, "首部")
    scan_lines(tail, "尾部")
    scan_caption_els()
    # 去重（按去角色括号后名字；同名人保留先出现的角色标注）
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
    # 3.5 v9：超薄列表页（200–400 字带）：文本极少 + 链接主导 + 几乎无段落文本
    #    + 链接数足够——sina_list__01（274字/链接密度0.56/p文本98/49链接）漏拒修复；
    #    薄文章页安全：gov_cn  stub 页 p文本 1337、chinanews 薄页 p文本 886，
    #    均不满足 p_text<150（dev 全量核对见 loop/calibrate_refusal.py）。
    links_all = soup.find_all("a")
    link_density = sum(len(a.get_text(strip=True)) for a in links_all) / max(len(page_text), 1)
    p_text_len = sum(len(p.get_text(strip=True)) for p in soup.find_all("p"))
    if len(page_text) < 400 and link_density >= 0.4 \
            and p_text_len < 150 and len(links_all) >= 20:
        return True, (f"list_page_ultra_thin:page_text={len(page_text)},"
                      f"link_density={link_density:.2f},p_text={p_text_len},"
                      f"n_links={len(links_all)}"), "list_page"
    # 4. photo_set：图片主导的图集容器即主内容。
    #    v9 重写：去掉 traf_text_len<200 前置条件（traf 会抽图说文字，
    #    图集页因此漏拒；改为直接识别结构）——只数内容图（不在 <a> 内、
    #    非 icon/logo/二维码类装饰图；people 的 ~77 张侧栏缩略图几乎全在
    #    链接内，被此过滤）、最内层内容图≥8 容器、占全页内容图 ≥60%、
    #    无长段落（>200字的 p）、文本/图<120（图说短）。
    #    dev 安全：chinadaily 正文 figure 组 text/img≥120、cnblogs 多图
    #    技术文有长段落（calibrate A 组零误拒，见 loop/calibrate_refusal.py）。
    def _content_imgs(root):
        """内容图（排除装饰图）：不包在 <a> 里、src/类名无 icon|logo|qrcode|
        arrow|sound|counter 等 UI 件字样。people 的 ~77 张侧栏缩略图几乎全
        在链接内，箭头/喇叭/计数器图样由名字过滤。"""
        out = []
        for img in root.find_all("img"):
            if img.find_parent("a"):
                continue
            sig = " ".join(img.get("class", [])) + (img.get("id") or "") + (img.get("src") or "")
            if re.search(r"icon|logo|qrcode|avatar|blank|pixel|loading|"
                         r"arrow|sound|counter|sprite|btn", sig, re.I):
                continue
            out.append(img)
        return out

    def _caption_of(img):
        """图片的图说元素：父 figure 的 figcaption，或兄弟/父级 caption 类元素。"""
        fig = img.find_parent("figure")
        if fig:
            cap = fig.find("figcaption")
            if cap:
                return cap.get_text(strip=True)
        par = img.parent
        if par:
            cid = " ".join(par.get("class", [])) + (par.get("id") or "")
            if re.search(r"caption|pictext|desc", cid, re.I):
                return par.get_text(strip=True)
            for sib in par.find_next_siblings(limit=1) or []:
                cid = " ".join(sib.get("class", [])) + (sib.get("id") or "")
                if re.search(r"caption|pictext|desc", cid, re.I):
                    return sib.get_text(strip=True)
        return None

    n_content_page = len(_content_imgs(soup))
    for el in soup.find_all(["article", "div", "section", "ul"]):
        imgs = _content_imgs(el)
        if len(imgs) < 6:
            continue
        el_text = el.get_text(strip=True)
        if any(len(p.get_text(strip=True)) > 200 for p in el.find_all("p")):
            continue
        # v9 修订：容器外存在实质段落文本（≥400字，p>100字）→ 图集只是
        # 文章页的相关模块，不拒（ISPRAS 误拒修复：dawn/bbc/chathamhouse
        # 等英文文章页正文在图集容器之外）。
        outside_p = sum(len(p.get_text(strip=True))
                        for p in soup.find_all("p")
                        if el not in p.parents and len(p.get_text(strip=True)) > 100)
        if outside_p >= 400:
            continue
        caps = [c for c in (_caption_of(img) for img in imgs) if c]
        cap_text = sum(len(c) for c in caps)
        # v9 修订②：图集文本必须是「图说性质」——纯图墙（text/img<15）
        # 或 ≥6 张图有图说且图说占容器文本 ≥40%。
        # bna 短讯文章（582字正文+8张内联图，text/img=73 连续散文、无图说）
        # 不再误拒；chinadaily 文章 figure 组图说占比<40% 不触发。
        caption_like = len(el_text) / len(imgs) < 15 or \
            (len(caps) >= 6 and cap_text / max(len(el_text), 1) >= 0.4)
        # 路径 A：结构主导——最内层内容图≥8 容器且占全页内容图 ≥50%
        if len(imgs) >= 8 and len(imgs) >= n_content_page * 0.5 and \
                not any(len(_content_imgs(d)) >= 8
                        for d in el.find_all(["article", "div", "section", "ul"])):
            if caption_like and len(el_text) / len(imgs) < 120:
                return True, (f"photo_set:content_imgs={len(imgs)}/{n_content_page},"
                              f"text_per_img={len(el_text)/len(imgs):.0f}"), "photo_set"
        # 路径 B：图说驱动——≥6 张图带图说且图说占容器文本 ≥40%
        if len(caps) >= 6:
            if cap_text / max(len(el_text), 1) >= 0.4 \
                    and len(el_text) / len(imgs) < 150:
                return True, (f"photo_set:captioned={len(caps)}/{len(imgs)},"
                              f"cap_share={cap_text/max(len(el_text),1):.2f}"), "photo_set"
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
    with timed("decode"):
        html, declared, detected, used = decode_declared_first(raw)
    rec = empty_record(declared, detected, used)
    soup = BeautifulSoup(html, "lxml")

    # --- trafilatura 先行（拒识的 photo_set 信号需要其产出量） ---
    try:
        with timed("trafilatura"):
            doc = trafilatura.bare_extraction(
                html, with_metadata=True, include_comments=False,
                include_tables=True, include_images=True)  # v4: 图片占位符需要
    except Exception:  # noqa: BLE001
        doc = None
    traf_text_len = len((doc.text or "").strip()) if doc is not None else 0

    # --- 拒识判定 ---
    with timed("refusal"):
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
    with timed("metadata"):
        meta = parse_metadata_layer(soup)
    with timed("rules"):
        rules = SITE_RULES[site](soup, meta) if site in SITE_RULES else {}

    rule_first = site in SITE_RULES
    rec["route"] = "site_rules" if rule_first else "metadata+trafilatura"
    final_fields = set()  # 规则层 final 裁决为空的字段（v10：模型臂同样不得回退）

    def pick(field, rule_key=None):
        """按路由优先级取字段；规则层 final 裁决优先一切。"""
        rk = rule_key or field
        rv = rules.get(rk)
        if rv is not None:
            val, prov = rv[0], rv[1]
            if prov == "final":        # 规则裁决为空，禁止回退
                rec["provenance"][field] = rv[2]
                final_fields.add(field)
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
        stripped = strip_title_suffix(title, site)
        if stripped != title:
            rec["provenance"]["title"] = \
                rec["provenance"].get("title", "") + "+品牌后缀剥离"
        title = stripped
    # v14：meta 标题与可见 h1 整标题分歧（互不含对方）时 h1 优先。
    # 证据：ISPRAS og≠h1 约 21 页 gold 全取 h1 可见标题（abc_net_au/
    # alliancefr/euronews）；v14 模型二选一裁决实测与 gold 口径不一致
    # （模型偏好 og 侧短标题），确定性规则零成本且口径对齐。
    # 互含情况=后缀差异，已由上方剥离处理，不触发本规则。
    # 守卫 _h1_is_headline：h1 须位于正文语义区（article/headline/content…），
    # 排除页头横幅位的博客名/站名口号（cnblogs h1=「自由、创新、研究、探索」
    # 是 div#blogTitle 里的博客标语——gold 边界分歧页挂起口径不因本规则翻转）。
    if title and rec["provenance"].get("title", "").startswith(("meta:", "json-ld")):
        h1 = soup.find("h1")
        h1t = re.sub(r"\s+", " ", h1.get_text(" ", strip=True)) if h1 else ""
        if 4 <= len(h1t) <= 200 and h1 is not None \
                and not _h1_is_generic_label(h1t) and _h1_is_headline(h1):
            cur, oth = re.sub(r"\s+", "", title).lower(), \
                re.sub(r"\s+", "", h1t).lower()
            if oth and cur != oth and cur not in oth and oth not in cur:
                title = strip_title_suffix(h1t, site)
                rec["provenance"]["title"] = \
                    "dom://h1[1](整标题分歧h1优先于meta)"
    rec["title"] = title

    # authors：规则/元数据（v6 媒体名过滤）→ traf；署名扫描合并移至正文装配后
    with timed("postprocess"):
        authors = pick("authors")
        # v9：站名/域名词干不是作者（ISPRAS fijivillage json-ld author=站点名）。
        stem = site.split(".")[0].lower()
        if authors:
            authors = [a for a in authors
                       if a.lower().replace(" ", "") not in (stem, site.lower())] or None
        if authors and rec["provenance"].get("authors", "").startswith(("meta:", "json-ld")):
            authors = filter_meta_authors(authors, soup)
        if authors is None and doc is not None and doc.author:
            authors = filter_meta_authors(
                [a.strip() for a in re.split(r"[,;，；]", doc.author) if a.strip()],
                soup)
            if authors:
                rec["provenance"]["authors"] = "trafilatura:document.author"

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
            else:
                # v15：英文/欧式同日精化（akipress「July 16」只摘到日，页面
                # 另有「16.07.2024 11:58」；ewn 同型）。只升精度不新填。
                _refine_publish_precision_en(rec, soup)

    # content：规则层容器 → v8 CMS 容器先验（门控）→ trafilatura body 树装配 → DOM 密度
    rc = rules.get("content")
    if rc and rc[0]:
        rec["content_text"], rec["content_md"], rec["images"], cflags, prov = rc
        rec["conversion_flags"] = cflags
        rec["provenance"]["content_text"] = prov
    else:
        # v8：通用 CMS 模板正文容器先验。这些类名是全网流通的 CMS 模板签名
        # （chinanews 系 left_zw / 人民网 rm_txt_con / 新浪系 artibody /
        # 凤凰 CSS-modules index_text_ 前缀），非 dev 页面私有结构。
        # 门控：容器文本 ≥60 字且比 traf 产出更紧凑（traf 在这些模板上系统性
        # 拖入相关推荐/页头尾样板——chinanews num_f1 0.10-0.16、people 头尾
        # 样板行），或 traf 无产出时，改走 DOM 容器装配。
        prior = None
        for sel, label in CONTAINER_PRIORS:
            el = soup.select_one(sel)
            if not el:
                continue
            ctext = re.sub(r"\s+", "", el.get_text())
            if len(ctext) >= 60 and (traf_text_len == 0
                                     or len(ctext) < traf_text_len):
                prior = (el, label)
                break
        if prior is not None:
            el, label = prior
            text, md, images, cflags = assemble_container(el)
            if text:
                rec["content_text"], rec["content_md"] = text, md
                rec["images"] = images
                rec["conversion_flags"] = cflags
                rec["provenance"]["content_text"] = f"dom:container_prior[{label}]"
                rec["route"] = (rec["route"] or "") + "+container_prior"
        if rec["content_text"] is None and doc is not None and doc.text:
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
        if rec["content_text"] is None:
            dc = dom_density_content(soup)
            if dc and dc[0]:
                rec["content_text"], rec["content_md"], rec["images"], cflags = dc
                rec["conversion_flags"] = cflags
                rec["provenance"]["content_text"] = "dom:density_container"
                rec["route"] = (rec["route"] or "") + "+dom_density"
    if rules.get("publisher"):
        rec["provenance"]["source.publisher"] = rules["publisher"][1]
        rec["source"]["publisher"] = rules["publisher"][0]

    # v6：署名扫描合并（需在正文装配之后——扫描窗取自身 content_text 首/尾）
    with timed("postprocess"):
        scanned, scan_provs = scan_signature_authors(soup, rec["content_text"])
    # v6 修订④：通用路由下 json-ld/meta 给出的作者是平台自声明的强来源
    # （segmentfault 组织账号：gold 取账号名 MindMux/OceanBase技术站，
    # 不取正文 bio 里的「作者：祁宁」），不再合并扫描名；
    # trafilatura/空列表为弱来源，fixed 规则站（规则可能只覆盖责任编辑，
    # news_cn__09 需合并记者列表）照常合并。
    aprov = rec["provenance"].get("authors", "")
    strong_source = aprov.startswith(("json-ld", "meta:")) and not rule_first
    if scanned and (not authors or not strong_source):
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

    # v10：模型兜底臂（EXTRACT_MODEL=1 才启用）。门控触发：title 缺失/弱来源、
    # authors 空、publish_time 缺失任一命中；单次调用合并抽取；所有模型值
    # 必须在页面可见文本中可核验（in-page verified），时间须可解析。
    if _MODEL_ENABLED and not rec["rejected"]:
        from loop.model_arm import model_fallback
        with timed("model"):
            filled = model_fallback(rec, soup, site, final_fields)
        if filled:
            rec["route"] = (rec["route"] or "") + "+model[" + ",".join(filled) + "]"
        # v15.1：模型填的日粒度 publish 同样过 EN 同日精化（模型常只摘
        # 「July 16」而页面另有「16.07.2024 11:58」——精化块在管线前段，
        # 模型兜底在其后，需在兜底后再跑一次）。
        _refine_publish_precision_en(rec, soup)
    return rec


def _refine_publish_precision_en(rec, soup):
    """EN/欧式同日精化：publish 已有日粒度值（XX:XX:XX）且页面存在同一日期
    的带时分写法时升级粒度。只升精度、不新填日期，无 false_fill 通道。"""
    pub = rec.get("publish_time")
    if not pub or " " not in pub["value"]:
        return
    if not pub["value"].split(" ", 1)[1].startswith("XX"):
        return
    from loop.model_arm import _DATE_CAND, _parse_model_time
    day = pub["value"][:10]
    for dm in _DATE_CAND.finditer(_visible_page_text(soup)):
        pt = _parse_model_time(dm.group(0))
        if pt and pt["value"][:10] == day:
            tp2 = pt["value"].split(" ", 1)[1]
            if not tp2.startswith("XX"):
                rec["publish_time"] = {
                    "value": pt["value"],
                    "utc_offset": pub.get("utc_offset"),
                    "utc_offset_source": pub.get("utc_offset_source")}
                rec["provenance"]["publish_time"] = \
                    rec["provenance"].get("publish_time", "") + "（EN同日精化时分）"
                return


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
