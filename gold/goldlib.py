# -*- coding: utf-8 -*-
"""gold 标注公共工具：解码、解析、证据提取。
gold 边界铁律：一切字段值必须能在 HTML DOM 中找到证据；本模块只做"取证"，
不替标注者做最终裁决（除明确标注 site rule 命中的字段）。
"""
import json
import re
from lxml import html as lhtml
from lxml import etree

def decode_page(raw: bytes, declared: str | None, detected: str | None):
    """声明优先、检测兜底。返回 (text, used_encoding)。"""
    cands = []
    if declared:
        cands.append(declared)
    if detected and detected.lower() not in {c.lower() for c in cands}:
        cands.append(detected)
    cands += ['utf-8', 'gb18030']
    for enc in cands:
        if not enc:
            continue
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace'), 'utf-8-replace'


def parse(text: str):
    return lhtml.fromstring(text)


def norm_ws(s: str) -> str:
    return re.sub(r'[ \t 　]+', ' ', s).strip()


def clean_title(s: str) -> str:
    """剥离常见站点后缀/栏目名。只做机械剥离，供候选展示。"""
    s = norm_ws(s)
    s = re.split(r'[_|｜—–-]\s*(新华网|新华社|中国政府网|Chinadaily\.com\.cn|China Daily|新浪|搜狐|网易|凤凰网|澎湃|财新|人民网|光明网|中国新闻网|CSDN|博客园|SegmentFault|澎湃新闻|cnBeta)[^_|｜—–-]*$', s)[0]
    return s.strip(' _|｜—–-')


def get_jsonld(tree):
    out = []
    for sc in tree.xpath('//script[@type="application/ld+json"]'):
        try:
            data = json.loads(sc.text_content().strip())
            out.append(data)
        except Exception:
            pass
    return out


def meta_content(tree, name=None, prop=None):
    if name:
        els = tree.xpath(f'//meta[translate(@name,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="{name.lower()}"]/@content')
    else:
        els = tree.xpath(f'//meta[@property="{prop}"]/@content')
    return [e.strip() for e in els if e.strip()]


def evidence_dump(path, declared, detected):
    """提取一页的全部候选证据，返回 dict（供人工/规则裁决）。"""
    raw = open(path, 'rb').read()
    text, used = decode_page(raw, declared, detected)
    tree = parse(text)
    ev = {'used_encoding': used, 'declared': declared, 'detected': detected}

    titles = {}
    tl = tree.xpath('//title/text()')
    if tl:
        titles['title_tag'] = norm_ws(tl[0])
    og = meta_content(tree, prop='og:title')
    if og:
        titles['og:title'] = og[0]
    tw = meta_content(tree, name='twitter:title')
    if tw:
        titles['twitter:title'] = tw[0]
    h1s = [norm_ws(h.text_content()) for h in tree.xpath('//h1')]
    h1s = [h for h in h1s if h]
    if h1s:
        titles['h1'] = h1s[:3]
    mt = meta_content(tree, name='title')
    if mt:
        titles['meta_title'] = mt[0]
    ev['titles'] = titles

    # meta 作者/时间类
    for m in ['author', 'publishdate', 'publishdate2', 'firstpublishedtime',
              'lastmodifiedtime', 'pubdate', 'publishdate', 'source', 'date',
              'article:published_time', 'article:modified_time']:
        v = meta_content(tree, name=m) or meta_content(tree, prop=m)
        if v:
            ev.setdefault('meta', {})[m] = v

    jld = get_jsonld(tree)
    if jld:
        ev['jsonld'] = jld

    times = []
    for t in tree.xpath('//time'):
        times.append({'datetime': t.get('datetime'), 'text': norm_ws(t.text_content())[:80]})
    if times:
        ev['time_elements'] = times

    # 页面正文中可见的署名/时间行候选（正则扫描 body 文本片段）
    ev['byline_candidates'] = scan_byline(tree)
    ev['body_text_len'] = len(norm_ws(tree.xpath('string(//body)') or ''))
    return ev, tree, text


BYLINE_PAT = re.compile(
    r'(记者|作者|文/|摄|摄影|责任编辑|编辑|来源|By\s+[A-Z]|Byline|Reporter|Editor|Source)[：: ]{0,3}[^\n<>]{0,60}')


def scan_byline(tree):
    """在可能的信息区（正文容器附近、class 含 info/source/author/time 的元素）扫描署名候选。"""
    hits = []
    for el in tree.xpath('//*[contains(@class,"info") or contains(@class,"Info") or contains(@class,"source") or contains(@class,"Source") or contains(@class,"author") or contains(@class,"time") or contains(@class,"editor") or contains(@class,"byline")]'):
        t = norm_ws(el.text_content())
        if t and len(t) < 200 and BYLINE_PAT.search(t):
            hits.append(t[:160])
    # 去重保序
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out[:12]


BLOCK_TAGS = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote',
              'figcaption', 'pre', 'td', 'th'}


def _leaf_text_with_imgs(node, images):
    """按文档序遍历叶子块内联内容：文本 + img 占位符。跳过注释/PI 节点。"""
    buf = []

    def rec(el):
        if el.text:
            buf.append(el.text)
        for child in el:
            if not isinstance(child.tag, str):
                if child.tail:
                    buf.append(child.tail)
                continue  # 注释/PI
            tag = child.tag
            if tag in ('script', 'style'):
                if child.tail:
                    buf.append(child.tail)
                continue
            if tag == 'img':
                src = child.get('src') or child.get('data-src') or child.get('data-original')
                if src:
                    images.append({'type': '正文插图', 'alt': child.get('alt') or None,
                                   'caption': None, 'url': src,
                                   'width': child.get('width'), 'height': child.get('height')})
                    buf.append(f' [[IMG_{len(images)}]] ')
            else:
                rec(child)
            if child.tail:
                buf.append(child.tail)

    rec(node)
    return norm_ws(''.join(buf))


def container_text_with_img(el):
    """提取容器内纯文本：叶子块元素逐块成行，img 以 [[IMG_n]] 占位。"""
    images = []
    lines = []

    def walk(node):
        tag = node.tag if isinstance(node.tag, str) else ''
        if tag in ('script', 'style'):
            return
        if tag == 'figure':
            im = node.xpath('.//img')
            if im:
                img = im[0]
                src = img.get('src') or img.get('data-src') or img.get('data-original')
                if src:
                    images.append({'type': '正文插图', 'alt': img.get('alt') or None,
                                   'caption': None, 'url': src,
                                   'width': img.get('width'), 'height': img.get('height')})
                    cap = node.xpath('.//figcaption')
                    if cap:
                        ct = norm_ws(cap[0].text_content())
                        if ct:
                            images[-1]['caption'] = ct
                    lines.append(f'[[IMG_{len(images)}]]')
                return
            # 无图 figure（如表格 figure）：回退递归
            for child in node:
                if isinstance(child.tag, str):
                    walk(child)
            return
        if tag in BLOCK_TAGS:
            has_block_child = any(
                isinstance(c.tag, str) and c.tag in BLOCK_TAGS for c in node.iter()
                if c is not node)
            if not has_block_child:
                line = _leaf_text_with_imgs(node, images)
                if line:
                    lines.append(line)
                return
        # 游离 img（不在块元素内）
        if tag == 'img':
            src = node.get('src') or node.get('data-src') or node.get('data-original')
            if src:
                images.append({'type': '正文插图', 'alt': node.get('alt') or None,
                               'caption': None, 'url': src,
                               'width': node.get('width'), 'height': node.get('height')})
                lines.append(f'[[IMG_{len(images)}]]')
            return
        for child in node:
            if isinstance(child.tag, str):
                walk(child)
            if child.tail and norm_ws(child.tail) and tag in ('div', 'section', 'article'):
                pass  # 容器级游离文本由调用方另行检查，正文容器一般无此形态

    walk(el)
    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text, images


# ================= Markdown 转换（content_md） =================

def container_to_md(el):
    """容器 → GFM。返回 (md, flags, images)。有损必留痕。"""
    flags = set()
    images = []
    out = []

    def img_ph(node):
        src = node.get('src') or node.get('data-src') or node.get('data-original')
        if not src:
            return ''
        images.append({'type': '正文插图', 'alt': node.get('alt') or None,
                       'caption': None, 'url': src,
                       'width': node.get('width'), 'height': node.get('height')})
        return f'[[IMG_{len(images)}]]'

    def inline_md(node):
        buf = []

        def rec(el):
            if el.text:
                buf.append(el.text)
            for child in el:
                if not isinstance(child.tag, str):
                    if child.tail:
                        buf.append(child.tail)
                    continue  # 注释/PI
                tag = child.tag
                if tag in ('script', 'style'):
                    if child.tail:
                        buf.append(child.tail)
                    continue
                if tag == 'img':
                    buf.append(' ' + img_ph(child) + ' ')
                else:
                    if tag == 'math':
                        flags.add('mathml_degraded')
                    if tag == 'code' and (child.getparent() is None or child.getparent().tag != 'pre'):
                        start = len(buf)
                        rec(child)
                        seg = ''.join(buf[start:]).strip()
                        del buf[start:]
                        buf.append('`' + seg + '`')
                    else:
                        rec(child)
                if child.tail:
                    buf.append(child.tail)

        rec(node)
        return norm_ws(''.join(buf))

    def table_md(tbl):
        rows = []
        has_span = bool(tbl.xpath('.//*[@colspan or @rowspan]'))
        if has_span:
            flags.add('table_colspan_flattened')
        for tr in tbl.xpath('.//tr'):
            cells = []
            for c in tr.xpath('./th|./td'):
                cs = int(c.get('colspan', 1))
                txt = norm_ws(c.text_content()).replace('|', '\\|')
                cells.append(txt)
                cells += [''] * (cs - 1)
            if cells:
                rows.append(cells)
        if not rows:
            return []
        w = max(len(r) for r in rows)
        rows = [r + [''] * (w - len(r)) for r in rows]
        lines = ['| ' + ' | '.join(rows[0]) + ' |',
                 '|' + ' --- |' * w]
        for r in rows[1:]:
            lines.append('| ' + ' | '.join(r) + ' |')
        return lines

    def walk(node, depth=0):
        tag = node.tag if isinstance(node.tag, str) else ''
        if tag in ('script', 'style'):
            return
        if tag == 'img':
            ph = img_ph(node)
            if ph:
                out.append(ph)
            return
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            t = inline_md(node)
            if t:
                out.append('#' * (int(tag[1]) + 1) + ' ' + t)
            return
        if tag == 'p' or tag == 'blockquote' or tag == 'figcaption':
            has_blk = any(isinstance(c.tag, str) and c.tag in
                          ('p', 'ul', 'ol', 'table', 'pre', 'figure', 'h1', 'h2', 'h3', 'h4')
                          for c in node)
            if not has_blk:
                t = inline_md(node)
                if t:
                    out.append(('> ' if tag == 'blockquote' else '') + t)
                return
        if tag == 'pre':
            code_el = node.xpath('.//code')
            lang = ''
            if code_el:
                cls = code_el[0].get('class', '') or ''
                m = re.search(r'(?:language|lang|highlight)-?([\w+#]*)', cls)
                lang = m.group(1) if m else ''
            txt = node.text_content().rstrip('\n')
            out.append(f'```{lang}\n{txt}\n```')
            return
        if tag == 'table':
            out.extend(table_md(node))
            return
        if tag in ('ul', 'ol'):
            i = 0
            for li in node.xpath('./li'):
                i += 1
                bullet = '-' if tag == 'ul' else f'{i}.'
                t = inline_md(li)
                if t:
                    out.append(f'{bullet} {t}')
            return
        if tag == 'figure':
            im = node.xpath('.//img')
            if im:
                ph = img_ph(im[0])
                cap = node.xpath('.//figcaption')
                if ph:
                    out.append(ph)
                if cap:
                    cap_t = norm_ws(cap[0].text_content())
                    if cap_t and images:
                        images[-1]['caption'] = cap_t
                return
            # 无图 figure（如 wp-block-table）：回退按普通容器递归
            for c in node:
                if isinstance(c.tag, str):
                    walk(c, depth + 1)
            return
        if tag == 'math':
            flags.add('mathml_degraded')
            out.append('$' + norm_ws(node.text_content()) + '$')
            return
        for c in node:
            if isinstance(c.tag, str):
                walk(c, depth + 1)

    walk(el)
    md = '\n\n'.join(out)
    md = re.sub(r'\n{3,}', '\n\n', md)
    return md, sorted(flags), images
