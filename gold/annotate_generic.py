# -*- coding: utf-8 -*-
"""generic 组 gold 标注（55 篇）。
逐页判定 content_structure / page_condition；文章页逐字段 DOM 证据标注；
拒识页（付费墙/列表页）全空 + expect_refusal。
所有字段 provenance 可回溯；trafilatura 仅作草稿对照（probe_*.txt），不作 gold。
"""
import json
import re
import sys

sys.path.insert(0, '.')
from goldlib import (evidence_dump, norm_ws, container_text_with_img,
                     container_to_md, get_jsonld)

BASE = '../'
IDX = [json.loads(l) for l in open(BASE + 'dataset_index.jsonl')]


def t(value, offset=None, src=None):
    if value is None:
        return None
    return {'value': value, 'utc_offset': offset, 'utc_offset_source': src}


def base_rec(row, ev):
    return {
        'id': row['id'], 'group': row['group'], 'site': row['site'],
        'url': row['url'], 'path': row['path'], 'sha1': row['sha1'],
        'page_condition': 'ok', 'needs_render': False,
        'content_structure': 'single', 'expect_refusal': False,
        'title': None, 'authors': None,
        'publish_time': None, 'update_time': None,
        'content_text': None, 'content_md': None, 'conversion_flags': [],
        'images': None,
        'source': {'site_name': row['site'], 'publisher': None,
                   'encoding': {'declared': row['encoding_declared'],
                                'detected': row['encoding_detected'],
                                'used': ev['used_encoding']}},
        'provenance': {}, 'notes': '',
    }


def refusal_rec(row, ev, reason, evidence, structure='single', condition='ok'):
    rec = base_rec(row, ev)
    rec['expect_refusal'] = True
    rec['content_structure'] = structure
    rec['page_condition'] = condition
    rec['needs_render'] = condition != 'ok'
    rec['notes'] = reason
    rec['provenance'] = {'refusal_evidence': evidence}
    return rec


def clean_container(cont, drops):
    """先移除 boilerplate 子树，再提取。返回 (text, md, flags, images)。"""
    for xp in drops:
        for el in cont.xpath(xp):
            el.getparent().remove(el)
    ctext, images = container_text_with_img(cont)
    md, flags, _ = container_to_md(cont)
    return ctext, md, flags, images


def iso_to_value(s):
    """'2026-08-11T17:30:01+08:00' → ('2026-08-11 17:30:01', '+08:00')"""
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$', s.strip())
    if not m:
        return None, None
    sec = m.group(6) or 'XX'
    val = f'{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}:{sec}'
    off = m.group(7)
    if off == 'Z':
        off = '+00:00'
    elif off and len(off) == 5 and ':' not in off:
        off = off[:3] + ':' + off[3:]
    return val, off


CONTAINERS = {
    'sina': '//div[@id="artibody"]',
    'sohu': '//article[@id="mp-editor"]',
    'ifeng': '//main[contains(@class,"index_content")]//div[contains(@class,"leftContent")]',
    'chinanews': '//div[@class="left_zw"] | //div[contains(@class,"content_maincontent_content")]',
    'people': '//div[contains(@class,"rm_txt_con")]',
    'cnblogs': '//div[@id="cnblogs_post_body"]',
    'segmentfault': '//article[contains(@class,"fmt")]',
    'python_docs': '//div[@class="body"]',
    'github_blog': '//section[contains(@class,"post__content")]',
}

DROPS = {
    'sina': ['.//blockquote[contains(.,"金麒麟")]', './/p[contains(.,"登录新浪财经APP")]'],
    'sohu': ['.//a[@id="backsohucom"]'],
    'github_blog': ['.//div[contains(@class,"post-content-cta")]',
                    './/div[contains(@class,"content-table-wrap")]',
                    './/section[contains(@class,"my-6")]',
                    './/h2[contains(.,"reading list")]/following-sibling::ul[1]',
                    './/h2[contains(.,"reading list")]',
                    './/div[contains(@class,"mt-8") and contains(.,"Written by")]'],
    'python_docs': ['.//div[contains(@class,"sphinxsidebar")]', './/h1'],
    'ifeng': ['.//h1', './/section[contains(@class,"copyRight")]'],
    'people': ['.//em[contains(@class,"section-common-share-wrap")]'],
    'chinanews': ['.//div[contains(@class,"channel")]', './/p[contains(@class,"videojsDesc")]',
                  './/table[contains(@class,"adInContent")]', './/div[.//script]'],
}


def annotate_article(row, ev, tree):
    site = row['site']
    rec = base_rec(row, ev)
    prov = {}
    # ---------- title ----------
    og = ev['titles'].get('og:title')
    h1s = [norm_ws(h.text_content()) for h in tree.xpath('//h1')]
    h1s = [h for h in h1s if h]
    tt = ev['titles'].get('title_tag', '')
    if site == 'sohu':
        # h1[1] 是账号名，真标题在 h1(screen-reader-only) 或 og:title
        rec['title'] = og or h1s[0]
        prov['title'] = 'meta:og:title（h1 之一为搜狐号账号名，不取）'
    elif site == 'python_docs':
        h1 = h1s[0].rstrip('¶').strip() if h1s else og
        rec['title'] = h1
        prov['title'] = 'dom://h1 去除 ¶ 永久链接符（与 og:title 一致）'
    elif site in ('segmentfault',):
        tw = ev['titles'].get('twitter:title')
        rec['title'] = tw or (h1s[0] if h1s else og)
        prov['title'] = 'meta:twitter:title（title_tag 含栏目前缀"- SegmentFault 思否"）'
    elif site in ('people', 'chinanews'):
        rec['title'] = h1s[0] if h1s else re.split(r'[-_]', tt)[0]
        prov['title'] = 'dom://h1[1]'
    else:
        rec['title'] = og or (h1s[0] if h1s else None)
        prov['title'] = 'meta:og:title（与 h1 一致）' if og else 'dom://h1[1]'
    # ---------- content ----------
    if site == 'chinanews':
        cont = tree.xpath('//div[@class="left_zw"]') or \
               tree.xpath('//div[contains(@class,"content_maincontent_content")]')
    else:
        cont = tree.xpath(CONTAINERS[site])
    if not cont:
        return None, f'NO_CONTAINER {site}'
    cont = cont[0]
    # chinanews：pictext 图说 div 先摘出（就近挂前图），避免混入正文
    pictexts = []
    if site == 'chinanews':
        for cap_el in cont.xpath('.//div[contains(@class,"pictext")]'):
            cap = norm_ws(cap_el.text_content())
            prev = cap_el.xpath('preceding::img')
            prev_src = None
            for im in reversed(prev):
                prev_src = im.get('src') or im.get('data-src')
                if prev_src:
                    break
            if cap:
                pictexts.append((cap, prev_src))
            cap_el.getparent().remove(cap_el)
    ctext, md, flags, images = clean_container(cont, DROPS.get(site, []))
    for cap, src in pictexts:
        # 若图说以 <p> 形态进入了正文行，剔除
        ctext = '\n'.join(l for l in ctext.split('\n') if norm_ws(l) != cap)
        md = '\n'.join(l for l in md.split('\n') if norm_ws(l) != cap)
        for im in images:
            if src and im['url'] == src:
                im['caption'] = cap
    rec['content_text'] = ctext or None
    rec['content_md'] = md or None
    rec['conversion_flags'] = flags
    rec['images'] = images or None
    prov['content_text'] = (f'dom://div[@class="left_zw"]' if site == 'chinanews' else f'dom:{CONTAINERS[site]}') + (f'（剔除 {DROPS[site]}）' if site in DROPS else '')
    prov['content_md'] = '同源程序化 GFM 转换'
    prov['images'] = '同源容器内 <img> 收集（与 [[IMG_n]] 对应）'

    body_txt = norm_ws(tree.xpath('string(//body)'))
    # ---------- 站点特化：authors / times / publisher ----------
    if site == 'sina':
        eds = [norm_ws(el.text_content()) for el in tree.xpath('//*[contains(text(),"责任编辑")]')]
        authors = []
        for e in eds:
            m = re.match(r'责任编辑[：:]\s*([\u4e00-\u9fa5·]+?)(?:\s+[A-Z]{2}\d+)?\s*$', e)
            if m:
                authors.append(f'{m.group(1)}（责任编辑）')
                prov.setdefault('authors', []).append('dom:页尾"责任编辑：X"行（剔除工号如 SF183）')
        # 文内尾部"X新闻记者 计思敏"署名
        tail_lines = [l for l in ctext.split('\n') if l and not l.startswith('[[')][-3:]
        for l in tail_lines:
            mm = re.search(r'[\u4e00-\u9fa5]{2,10}记者\s*([\u4e00-\u9fa5·]{2,4}(?:\s*[、 ]\s*[\u4e00-\u9fa5·]{2,4})*)\s*$', l)
            if mm:
                for nm in re.split(r'[、 ]+', mm.group(1)):
                    if nm:
                        authors.append(nm)
                prov.setdefault('authors', []).append('dom://div[@id="artibody"] 正文尾部"X新闻记者 …"署名行')
        m = re.search(r'本文来源[：:]\s*([^\s　]+)\s*作者[：:]\s*([\u4e00-\u9fa5·、 ]+)', ctext)
        if m:
            rec['source']['publisher'] = m.group(1)
            prov['source.publisher'] = 'dom://div[@id="artibody"] 文内"本文来源：X 作者：…"行'
            for nm in re.split(r'[、 ]+', m.group(2).strip()):
                if re.fullmatch(r'[\u4e00-\u9fa5·]{2,5}', nm):
                    authors.append(nm)
            prov.setdefault('authors', []).append('dom://div[@id="artibody"] 文内"本文来源：时代周报 作者：…"行')
        else:
            # 文内首行"来源：X"/"文章来源：X" 优先于 byline 渠道名
            src_override = None
            for l in [x for x in ctext.split('\n') if x and not x.startswith('[[')][:3]:
                mo = re.match(r'(?:文章来源|来源)[：:]\s*([^\s]{2,15})\s*$', l)
                if mo:
                    src_override = mo.group(1)
            if src_override:
                rec['source']['publisher'] = src_override
                prov['source.publisher'] = 'dom://div[@id="artibody"] 文内首行"来源：X"'
            else:
                sm = re.search(r'20\d{2}年\d{2}月\d{2}日\s*\d{2}:\d{2}\s*([^\s]{2,10})', body_txt)
                if sm:
                    rec['source']['publisher'] = sm.group(1)
                    prov['source.publisher'] = 'dom:byline 区"时间 + 来源"行'
        rec['authors'] = authors or None
        v, off = iso_to_value((ev.get('meta', {}).get('article:published_time') or [''])[0])
        if v:
            rec['publish_time'] = t(v, off)
            prov['publish_time'] = 'meta:article:published_time（含显式 +08:00；与 byline 显示时分一致）'
    elif site == 'sohu':
        authors = []
        h1acc = h1s[1] if len(h1s) > 1 and h1s[1] != rec['title'] else None
        info_txt = norm_ws(' '.join(norm_ws(el.text_content()) for el in
                                    tree.xpath('//div[contains(@class,"article-info")]')))
        msrc = re.search(r'来源[：:]\s*([^\s]+)', info_txt)
        if msrc:
            rec['source']['publisher'] = msrc.group(1)
            prov['source.publisher'] = 'dom://div[contains(@class,"article-info")] "来源："行'
        elif h1acc:
            rec['source']['publisher'] = h1acc
            prov['source.publisher'] = 'dom://h1[2]（搜狐号账号名）'
        m = re.match(r'(?:[\u4e00-\u9fa5]+新闻)?记者\s*([\u4e00-\u9fa5·]{2,4})\s*$', ctext.split('\n')[0])
        if not m:
            m = re.match(r'文\s*[|｜]\s*([\u4e00-\u9fa5·]{2,4})\s*$', ctext.split('\n')[0])
        if m:
            authors.append(m.group(1))
            prov.setdefault('authors', []).append('dom://article 正文首行署名（"X新闻记者 王灿"/"文| 张彦宗"）')
        for el in tree.xpath('//p[@data-role="editor-name"]'):
            mm = re.search(r'责任编辑[：:]\s*([\u4e00-\u9fa5·]+?)(?:\s+[A-Z]{2}\d+)?\s*$', norm_ws(el.text_content()))
            if mm:
                authors.append(f'{mm.group(1)}（责任编辑）')
                prov.setdefault('authors', []).append('dom://p[@data-role="editor-name"]')
        rec['authors'] = authors or None
        tm = re.search(r'(20\d{2})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})', info_txt)
        if tm:
            rec['publish_time'] = t(f'{tm.group(1)}-{tm.group(2)}-{tm.group(3)} {tm.group(4)}:{tm.group(5)}:XX',
                                    '+08:00', 'inferred_site_locale')
            prov['publish_time'] = 'dom://div[contains(@class,"article-info")]//span[@class="time"]（分钟级，秒 XX）'
    elif site == 'ifeng':
        tes = ev.get('time_elements', [])
        if tes:
            v, off = iso_to_value(tes[0]['datetime'] or '')
            if v:
                rec['publish_time'] = t(v, off)
                prov['publish_time'] = 'dom://time[1]/@datetime（显式 +08:00）'
            for te in tes[1:]:
                if 'Updated' in (te.get('text') or ''):
                    v2, off2 = iso_to_value(te['datetime'] or '')
                    if v2:
                        rec['update_time'] = t(v2, off2)
                        prov['update_time'] = 'dom://time[contains(text(),"Updated")]/@datetime'
        sels = [norm_ws(el.text_content()) for el in tree.xpath('//*[contains(@class,"source") or contains(@class,"ssrc")]')]
        sels = [s for s in sels if s and '下载客户端' not in s]
        if sels:
            rec['source']['publisher'] = sels[-1]
            prov['source.publisher'] = 'dom:来源区（如"央视新闻"/"观察者网"）'
        tm2 = re.search(r'（(?:总台)?记者\s*([\u4e00-\u9fa5· ]{2,15})）\s*$', ctext)
        authors = []
        if tm2:
            authors += [n for n in re.split(r'[、 ]+', tm2.group(1).strip())
                        if re.fullmatch(r'[\u4e00-\u9fa5·]{2,5}', n)]
            if authors:
                prov.setdefault('authors', []).append('dom:正文尾部"（总台记者 X Y）"署名')
        # 尾部"红星新闻记者 江龙 …" / "作者：郑宇" 行
        tail_lines = [l for l in ctext.split('\n') if l and not l.startswith('[[')][-3:]
        for l in tail_lines:
            mm = re.match(r'[\u4e00-\u9fa5]{2,10}记者\s*([\u4e00-\u9fa5·]{2,4})', l)
            if mm:
                authors.append(mm.group(1))
                prov.setdefault('authors', []).append('dom:正文尾部"X新闻记者 …"署名行')
            mm2 = re.match(r'作者[：:]\s*([\u4e00-\u9fa5·]{2,4})\s*$', l)
            if mm2:
                authors.append(mm2.group(1))
                prov.setdefault('authors', []).append('dom:正文尾部"作者：X"署名行')
        rec['authors'] = authors or None
    elif site == 'chinanews':
        zone = norm_ws(' '.join(norm_ws(el.text_content()) for el in
                                tree.xpath('//div[contains(@class,"content_maincontent_more")]')[:1]))
        tm = re.search(r'(20\d{2})年(\d{2})月(\d{2})日\s*(\d{2}):(\d{2})', zone)
        if tm:
            rec['publish_time'] = t(f'{tm.group(1)}-{tm.group(2)}-{tm.group(3)} {tm.group(4)}:{tm.group(5)}:XX',
                                    '+08:00', 'inferred_site_locale')
            prov['publish_time'] = 'dom:byline 可见"YYYY年MM月DD日 hh:mm"（隐藏 BaiduSpider 块不采用）'
        sm = re.search(r'来源[：:]\s*([^\s]+)', zone)
        if sm:
            rec['source']['publisher'] = sm.group(1)
            prov['source.publisher'] = 'dom:byline"来源："行'
        em = re.search(r'【编辑[：:]\s*([\u4e00-\u9fa5·]+?)】', body_txt)
        authors = []
        zb = re.search(r'执笔[：:]\s*([\u4e00-\u9fa5· ]{2,15})', ctext)
        if zb:
            for nm in re.split(r'[、 ]+', zb.group(1).strip()):
                if re.fullmatch(r'[\u4e00-\u9fa5·]{2,5}', nm):
                    authors.append(nm)
            prov.setdefault('authors', []).append('dom:正文尾部出品 credits"｜执笔：X Y"行')
        if em:
            authors.append(f'{em.group(1)}（编辑）')
            prov.setdefault('authors', []).append('dom:正文尾部可见"【编辑：X】"（display:none 的 BaiduSpider"作者：X"块与来源矛盾，弃用）')
        # pictext 图说中的摄影署名（"… 薛伟 摄"）
        for im in rec['images'] or []:
            cap = im.get('caption') or ''
            mp = re.search(r'([\u4e00-\u9fa5·]{2,4})\s*摄\s*$', cap)
            if mp:
                authors.append(f'{mp.group(1)}（摄影）')
                prov.setdefault('authors', []).append('dom://div[contains(@class,"pictext")] 图说"X 摄"')
        rec['authors'] = authors or None
    elif site == 'people':
        em = re.search(r'[（(]责编[：:]\s*([\u4e00-\u9fa5·、 ]+?)[)）]', body_txt)
        if em:
            names = [n for n in re.split(r'[、 ]+', em.group(1)) if re.fullmatch(r'[\u4e00-\u9fa5·]{2,5}', n)]
            rec['authors'] = [f'{n}（责任编辑）' for n in names] or None
            prov['authors'] = ['dom://div[contains(@class,"edit")]"（责编：X、Y）"（meta[name=author] 为数字 ID，不采用）']
        # byline 区：b#newstime + 其父 div 内"来源："行
        nb = tree.xpath('//b[@id="newstime"]')
        if nb:
            t0 = norm_ws(nb[0].getparent().text_content())
            tm = re.search(r'(20\d{2})年(\d{2})月(\d{2})日\s*(\d{2}):(\d{2})', t0)
            if tm:
                rec['publish_time'] = t(f'{tm.group(1)}-{tm.group(2)}-{tm.group(3)} {tm.group(4)}:{tm.group(5)}:XX',
                                        '+08:00', 'inferred_site_locale')
                prov['publish_time'] = 'dom://b[@id="newstime"]（分钟级；来源行为父 div.col-1-1）'
            sm = re.search(r'来源[：:]\s*([\u4e00-\u9fa5]{2,10})', t0)
            if sm:
                rec['source']['publisher'] = sm.group(1)
                prov['source.publisher'] = 'dom://b[@id="newstime"]/.. "来源："行（meta[name=source] 佐证）'
    elif site == 'cnblogs':
        j = ev.get('jsonld', [{}])[0]
        au = j.get('author') or {}
        if au.get('name'):
            rec['authors'] = [au['name']]
            prov['authors'] = ['json-ld:BlogPosting.author.name（与页面"posted @ … 用户名"一致）']
        v, off = iso_to_value(j.get('datePublished', ''))
        if v:
            rec['publish_time'] = t(v, off)
            prov['publish_time'] = 'json-ld:datePublished（显式 +08:00；页面 posted @ 佐证）'
        v2, off2 = iso_to_value(j.get('dateModified', '') or '')
        if v2 and v2 != v:
            rec['update_time'] = t(v2, off2)
            prov['update_time'] = 'json-ld:dateModified'
    elif site == 'segmentfault':
        j = ev.get('jsonld', [{}])[0]
        au = j.get('author') or {}
        if isinstance(au, dict) and au.get('name'):
            rec['authors'] = [au['name']]
            prov['authors'] = ['json-ld:Article.author.name']
        v, off = iso_to_value(j.get('datePublished', ''))
        if v:
            rec['publish_time'] = t(v, off)
            prov['publish_time'] = 'json-ld:datePublished（UTC Z 显式；与 time/@datetime 一致）'
        v2, off2 = iso_to_value(j.get('dateModified', '') or '')
        if v2 and v2 != v:
            rec['update_time'] = t(v2, off2)
            prov['update_time'] = 'json-ld:dateModified'
    elif site == 'python_docs':
        prov['authors'] = ['页面无署名（Python 文档页）']
        prov['publish_time'] = ['页面无显式时间']
    elif site == 'github_blog':
        ma = (ev.get('meta', {}).get('author') or [None])[0]
        if ma:
            rec['authors'] = [ma]
            prov['authors'] = ['meta[name=author]（与 byline 区用户名一致）']
        v, off = iso_to_value((ev.get('meta', {}).get('article:published_time') or [''])[0])
        if v:
            rec['publish_time'] = t(v, off)
            prov['publish_time'] = 'meta:article:published_time（显式 +00:00；json-ld 同瞬时的 -08:00/-07:00 表示等价，取 meta）'
        v2, off2 = iso_to_value((ev.get('meta', {}).get('article:modified_time') or [''])[0])
        if v2:
            rec['update_time'] = t(v2, off2)
            prov['update_time'] = 'meta:article:modified_time'
    rec['provenance'] = prov
    return rec, None


out = []
errors = []
for row in IDX:
    if row['group'] != 'generic':
        continue
    ev, tree, text = evidence_dump(BASE + row['path'], row['encoding_declared'],
                                   row['encoding_detected'])
    site = row['site']
    if site == 'caixin':
        if 'chargeWall' in text or 'payreadwarp' in text:
            out.append(refusal_rec(row, ev,
                                   '付费墙：HTML 仅含开头 1-2 段，正文被收费框截断，按"无可抽取"处理',
                                   'dom://div[@id="chargeWall" and contains(@class,"payreadwarp")]（"全站公用文章页收费框碎片"注释）'))
            continue
    if row['id'] == 'python_docs__02':
        out.append(refusal_rec(row, ev,
                               '文档索引页（The Python Standard Library 目录），按页面功能判 list_page',
                               'dom:链接密度 0.76、正文为库目录 toctree', structure='list_page'))
        continue
    rec, err = annotate_article(row, ev, tree)
    if err:
        errors.append((row['id'], err))
    else:
        out.append(rec)

json.dump(out, open('gold_generic.json', 'w'), ensure_ascii=False, indent=2)
print(f'wrote gold_generic.json: {len(out)} records; errors: {errors}')
for r in out:
    ct = r['content_text'] or ''
    print('=' * 14, r['id'], '| REFUSAL' if r['expect_refusal'] else '')
    if r['expect_refusal']:
        print('  notes:', r['notes'])
        continue
    print(' title:', (r['title'] or '')[:60])
    print(' authors:', r['authors'], '| publisher:', r['source']['publisher'])
    print(' pub:', r['publish_time'], '| upd:', r['update_time'])
    print(' len:', len(ct), '| imgs:', len(r['images'] or []), '| flags:', r['conversion_flags'])
    print(' head:', ct[:70].replace('\n', '⏎'))
    print(' tail:', ct[-70:].replace('\n', '⏎'))
