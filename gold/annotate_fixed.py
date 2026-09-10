# -*- coding: utf-8 -*-
"""fixed 组 gold 标注：news_cn / chinadaily / gov_cn 三站站点规则。
规则起草 → 逐字段 DOM 证据核对（provenance 逐字段登记）。
产出 gold_fixed.json + review 摘要（供人工核对）。
"""
import json
import re
import sys

sys.path.insert(0, '.')
from goldlib import (evidence_dump, norm_ws, container_text_with_img,
                     container_to_md)

BASE = '../'
IDX = [json.loads(l) for l in open(BASE + 'dataset_index.jsonl')]

CN_OFFSET = {'value_offset': '+08:00', 'src': 'inferred_site_locale'}


def t(value, offset=None, offset_src=None):
    if value is None:
        return None
    return {'value': value, 'utc_offset': offset, 'utc_offset_source': offset_src}


CREDIT_END = re.compile(r'摄）?$')
PAT_XH_JIZHE = re.compile(r'新华社记者[　 ]*([\u4e00-\u9fa5·　 ]+?)[　 ]*摄')
PAT_XH_FA = re.compile(r'新华社发（([\u4e00-\u9fa5·　 ]+?)[　 ]*摄）')
PAT_EDITOR = re.compile(r'【责任编辑[::]\s*([\u4e00-\u9fa5·]+?)\s*】')
PAT_TAIL_REPORTER = re.compile(r'（记者([\u4e00-\u9fa5·、 ]+?)）\s*$')
PAT_WENZI = re.compile(r'文字记者[：:]\s*([\u4e00-\u9fa5·、 ]+?)\s*$')
PAT_HAIBAO = re.compile(r'海报设计[：:]\s*([\u4e00-\u9fa5·]+?)\s*$')


def split_names(s):
    """'丁增尼达 毕晓洋' / '魏玉坤、谢希瑶' → ['丁增尼达','毕晓洋'] ..."""
    parts = re.split(r'[、,，　 ]+', s.strip())
    return [p for p in parts if p and re.fullmatch(r'[\u4e00-\u9fa5·]{2,5}', p)]


def news_cn(row):
    ev, tree, text = evidence_dump(BASE + row['path'], row['encoding_declared'],
                                   row['encoding_detected'])
    rec = base_rec(row, ev)
    prov = {}
    # title
    h1 = [norm_ws(h.text_content()) for h in tree.xpath('//h1')]
    h1 = [h for h in h1 if h]
    title = h1[0] if h1 else re.sub(r'-新华网$', '', ev['titles'].get('title_tag', ''))
    rec['title'] = title
    prov['title'] = 'dom://h1[1]' if h1 else 'dom://title 剥离站点后缀"-新华网"'
    # 信息区
    info_txt = norm_ws(tree.xpath('string(//div[contains(@class,"info")])'))
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', info_txt)
    if m:
        rec['publish_time'] = t(f'{m.group(1)}-{m.group(2)}-{m.group(3)} '
                                f'{m.group(4)}:{m.group(5)}:{m.group(6)}',
                                '+08:00', 'inferred_site_locale')
        prov['publish_time'] = 'dom://div[contains(@class,"info")] 文本行（meta[name=publishdate] 佐证日期）'
    m2 = re.search(r'来源[：:]\s*([\u4e00-\u9fa5]+)', info_txt)
    if m2:
        rec['source']['publisher'] = m2.group(1)
        prov['source.publisher'] = 'dom://div[contains(@class,"info")] "来源："行'
    # content + 图说/摄影/责编
    detail = tree.xpath('//div[@id="detail"]')[0]
    lines, images = [], []
    authors, aprov = [], []
    ps = detail.xpath('.//p')
    i = 0
    while i < len(ps):
        p = ps[i]
        ptxt = norm_ws(p.text_content())
        has_img = bool(p.xpath('.//img'))
        if has_img and not ptxt:
            # 图片组：连续 img-only p 合并为一组，逐个入 images
            group_imgs = []
            j = i
            while j < len(ps):
                pj = ps[j]
                if pj.xpath('.//img') and not norm_ws(pj.text_content()):
                    for im in pj.xpath('.//img'):
                        src = im.get('src') or im.get('data-src')
                        if src:
                            group_imgs.append(src)
                    j += 1
                else:
                    break
            cap_txt = None
            if j < len(ps):
                ntxt = norm_ws(ps[j].text_content())
                if ntxt and CREDIT_END.search(ntxt) and not ps[j].xpath('.//img'):
                    cap_txt = ntxt
                    i = j  # caption p 不再作为正文行
            for k, src in enumerate(group_imgs):
                images.append({'type': '正文插图', 'alt': None,
                               'caption': cap_txt if k == len(group_imgs) - 1 else None,
                               'url': src, 'width': None, 'height': None})
                lines.append(f'[[IMG_{len(images)}]]')
            if cap_txt:
                for mm in PAT_XH_JIZHE.finditer(cap_txt):
                    for nm in split_names(mm.group(1)):
                        authors.append(f'{nm}（摄影）')
                        aprov.append('dom://div[@id="detail"] 图说"新华社记者 X 摄"')
                for mm in PAT_XH_FA.finditer(cap_txt):
                    for nm in split_names(mm.group(1)):
                        authors.append(f'{nm}（摄影）')
                        aprov.append('dom://div[@id="detail"] 图说"新华社发（X摄）"')
            i += 1
            continue
        if ptxt:
            lines.append(ptxt)
            ed = PAT_EDITOR.search(ptxt)
            if ed:
                authors.append(f'{ed.group(1)}（责任编辑）')
                aprov.append('dom://div[@id="detail"]//span[@class="editor"]【责任编辑:X】')
            tr = PAT_TAIL_REPORTER.search(ptxt)
            if tr:
                for nm in split_names(tr.group(1)):
                    authors.append(nm)
                    aprov.append('dom://div[@id="detail"] 正文尾部"（记者…）"署名')
            wz = PAT_WENZI.search(ptxt)
            if wz:
                for nm in split_names(wz.group(1)):
                    authors.append(nm)
                    aprov.append('dom://div[@id="detail"] 正文尾部"文字记者：…"署名行')
            hb = PAT_HAIBAO.search(ptxt)
            if hb:
                for nm in split_names(hb.group(1)):
                    authors.append(f'{nm}（海报设计）')
                    aprov.append('dom://div[@id="detail"] 正文尾部"海报设计：…"署名行')
        i += 1
    # 责任编辑：在 detail 内但不一定包在 <p> 中（span.editor），单独扫描
    detail_txt = norm_ws(detail.text_content())
    for ed in PAT_EDITOR.finditer(detail_txt):
        nm = f'{ed.group(1)}（责任编辑）'
        if nm not in authors:
            authors.append(nm)
            aprov.append('dom://div[@id="detail"]//span[contains(@class,"editor")]【责任编辑:X】')
    rec['content_text'] = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines))
    rec['images'] = images or None
    prov['content_text'] = 'dom://div[@id="detail"]（图说 p 移入 images[].caption；摄影署名移出正文）'
    md, flags, md_images = container_to_md(detail)
    rec['content_md'] = md
    rec['conversion_flags'] = flags
    prov['content_md'] = 'dom://div[@id="detail"] 程序化 GFM 转换'
    prov['images'] = '同源容器内 <img> 收集（caption 来自图说 p，与 [[IMG_n]] 对应）'
    rec['authors'] = authors or None
    if authors:
        prov['authors'] = sorted(set(aprov))
    rec['provenance'] = prov
    return rec


def chinadaily(row):
    ev, tree, text = evidence_dump(BASE + row['path'], row['encoding_declared'],
                                   row['encoding_detected'])
    rec = base_rec(row, ev)
    prov = {}
    og = ev['titles'].get('og:title')
    h1 = [norm_ws(h.text_content()) for h in tree.xpath('//h1')]
    h1 = [h for h in h1 if h]
    rec['title'] = og or (h1[0] if h1 else None)
    prov['title'] = 'meta:og:title（与 dom://h1 一致）' if og else 'dom://h1[1]'
    # byline
    by_el = tree.xpath('//span[contains(@class,"info_l")] | //div[contains(@class,"Artical_Info")]//h4')
    by_txt = norm_ws(by_el[0].text_content()) if by_el else ''
    authors = []
    m = re.match(r'By\s+(.+?)\s*\|', by_txt)
    if m:
        seg = m.group(1)
        # 多人："ZHOU LANXU in Beijing and SHI JING in Shanghai"
        for part in re.split(r'\s+and\s+', seg):
            part = re.sub(r'\s+in\s+[A-Z][A-Za-z ]+$', '', part).strip()
            if part:
                authors.append(part)
        prov['authors'] = ['dom://span[contains(@class,"info_l")] 或 div.Artical_Info/h4 "By X | ..."署名行（采访地 in X 剥离）']
    elif by_txt.startswith('Xinhua'):
        authors.append('Xinhua')
        prov['authors'] = ['dom:byline 机构署名位"Xinhua"（作者角色的机构形态）']
    rec['authors'] = authors or None
    mu = re.search(r'Updated[：:]\s*(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})', by_txt)
    if mu:
        rec['update_time'] = t(f'{mu.group(1)}-{mu.group(2)}-{mu.group(3)} '
                               f'{mu.group(4)}:{mu.group(5)}:XX',
                               '+08:00', 'inferred_site_locale')
        prov['update_time'] = 'dom:byline "Updated:" 文本（页面仅此一个时间，无发布时间）'
    # publisher
    if 'CHINA DAILY' in by_txt or 'China Daily' in by_txt:
        rec['source']['publisher'] = 'China Daily'
    elif 'chinadaily.com.cn' in by_txt:
        rec['source']['publisher'] = 'chinadaily.com.cn'
    elif by_txt.startswith('Xinhua'):
        rec['source']['publisher'] = 'Xinhua'
    prov['source.publisher'] = 'dom:byline 署名行'
    # content
    d = tree.xpath('//div[@id="Content"]')[0]
    ctext, images = container_text_with_img(d)
    # 摄影署名（caption 纯 credit 形态 "JIN DING/CHINA DAILY"）
    for im in images:
        cap = im.get('caption') or ''
        mc = re.fullmatch(r'([A-Z ]+)/CHINA DAILY', cap)
        if mc:
            nm = mc.group(1).strip()
            if rec['authors'] is None:
                rec['authors'] = []
            rec['authors'].append(f'{nm}（摄影）')
            prov.setdefault('authors', []).append('dom://figure/figcaption 纯摄影署名"X/CHINA DAILY"')
    rec['content_text'] = ctext
    rec['images'] = images or None
    prov['content_text'] = 'dom://div[@id="Content"]（figure/figcaption 移入 images[].caption）'
    md, flags, _ = container_to_md(d)
    rec['content_md'] = md
    rec['conversion_flags'] = flags
    prov['content_md'] = 'dom://div[@id="Content"] 程序化 GFM 转换'
    prov['images'] = '同源容器内 figure/img 收集（caption 来自 figcaption，与 [[IMG_n]] 对应）'
    rec['provenance'] = prov
    return rec


def gov_cn(row):
    ev, tree, text = evidence_dump(BASE + row['path'], row['encoding_declared'],
                                   row['encoding_detected'])
    rec = base_rec(row, ev)
    prov = {}
    h1 = [norm_ws(h.text_content()) for h in tree.xpath('//h1')]
    h1 = [h for h in h1 if h]
    if h1:
        rec['title'] = h1[0]
        prov['title'] = 'dom://h1[1]'
    else:
        st = [norm_ws(e.text_content()) for e in tree.xpath('//div[@class="share-title"]')]
        st = [s for s in st if s]
        rec['title'] = st[0] if st else None
        prov['title'] = 'dom://div[@class="share-title"]（与 //title 剥离栏目后缀后一致）'
    # authors：meta[name=author]=责任编辑
    ma = ev.get('meta', {}).get('author')
    if ma:
        rec['authors'] = [f'{ma[0]}（责任编辑）']
        prov['authors'] = ['meta[name=author]（gov.cn 模板此字段为责任编辑，与页面"责任编辑：X"一致）']
    # times
    fp = ev.get('meta', {}).get('firstpublishedtime')
    lm = ev.get('meta', {}).get('lastmodifiedtime')
    fmt = lambda s: re.sub(r'(\d{4}-\d{2}-\d{2})-(\d{2}:\d{2}:\d{2})', r'\1 \2', s)
    if fp:
        rec['publish_time'] = t(fmt(fp[0]), '+08:00', 'inferred_site_locale')
        prov['publish_time'] = 'meta[name=firstpublishedtime]（与页面信息区日期一致）'
    if lm:
        rec['update_time'] = t(fmt(lm[0]), '+08:00', 'inferred_site_locale')
        prov['update_time'] = 'meta[name=lastmodifiedtime]'
    # publisher：信息区"来源："行（pages-date 区块，含"字号：默认"工具行）
    src_txt = ''
    for el in tree.xpath('//div[contains(@class,"pages-date")] | //div[contains(@class,"pages_date")]'):
        src_txt = norm_ws(el.text_content())
        if src_txt:
            break
    if not src_txt:
        for el in tree.xpath('//*[contains(text(),"来源")]'):
            t0 = norm_ws(el.text_content())
            if len(t0) < 300 and '来源' in t0:
                src_txt = t0
                break
    m = re.search(r'来源[：:]\s*([\u4e00-\u9fa5]+(?:网站)?)', src_txt)
    if m:
        rec['source']['publisher'] = m.group(1)
        prov['source.publisher'] = 'dom://div[contains(@class,"pages-date")] 信息区"来源："行'
    d = tree.xpath('//div[@id="UCAP-CONTENT"]')[0]
    ctext, images = container_text_with_img(d)
    rec['content_text'] = ctext
    rec['images'] = images or None
    prov['content_text'] = 'dom://div[@id="UCAP-CONTENT"]'
    md, flags, _ = container_to_md(d)
    rec['content_md'] = md
    rec['conversion_flags'] = flags
    prov['content_md'] = 'dom://div[@id="UCAP-CONTENT"] 程序化 GFM 转换'
    prov['images'] = '同源容器内 <img> 收集（与 [[IMG_n]] 对应）'
    rec['provenance'] = prov
    return rec


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


SITES = {'news_cn': news_cn, 'chinadaily': chinadaily, 'gov_cn': gov_cn}

out = []
for row in IDX:
    if row['group'] != 'fixed':
        continue
    rec = SITES[row['site']](row)
    out.append(rec)

json.dump(out, open('gold_fixed.json', 'w'), ensure_ascii=False, indent=2)
print(f'wrote gold_fixed.json: {len(out)} records')
# review 摘要
for r in out:
    ct = r['content_text'] or ''
    print('=' * 16, r['id'])
    print(' title:', r['title'])
    print(' authors:', r['authors'])
    print(' pub:', r['publish_time'], '| upd:', r['update_time'], '| pub-lisher:', r['source']['publisher'])
    print(' imgs:', len(r['images'] or []), '| flags:', r['conversion_flags'], '| len:', len(ct))
    print(' head:', ct[:80].replace('\n', '⏎'))
    print(' tail:', ct[-80:].replace('\n', '⏎'))
