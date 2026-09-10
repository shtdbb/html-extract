# -*- coding: utf-8 -*-
# 隔离集：调优代码只读 dev gold（gold_fixed/gold_generic），本文件仅终测聚合使用。
"""test 组 gold 标注（28 篇）：与 generic 同流程，单独文件存放。"""
import json
import re
import sys

sys.path.insert(0, '.')
from goldlib import (evidence_dump, norm_ws, container_text_with_img,
                     container_to_md)
from annotate_generic import base_rec, refusal_rec, t, iso_to_value, clean_container

BASE = '../'
IDX = [json.loads(l) for l in open(BASE + 'dataset_index.jsonl')]

MONTHS = {'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
          'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12}

CONTAINERS = {
    'stdaily': '//div[contains(@class,"pages_content")]',
    'en_people': '//div[contains(@class,"d2txtCon")]',
    'csdn': '//div[@id="article_content"]',
    'devto': '//div[@id="article-body"]',
    'mdn': '//main//div[contains(@class,"layout__body")]',
    'mslearn': '//div[@class="content"]',  # 两个同名 div，取文本最长者（见 annotate 内特判）
    'netease': '//div[contains(@class,"post_content")]',
}
DROPS = {
    'stdaily': ['.//div[contains(@class,"related")]'],  # “相关稿件：”链接块
    'mdn': ['.//section[contains(@class,"article-footer")]'],  # “Help improve MDN / last modified”页脚
    'mslearn': [],
    'netease': ['.//p[contains(.,"用微信扫码")]', './/p[contains(.,"分享至好友")]',
                './/p[contains(.,"特别声明")]', './/p[contains(.,"Notice: The content")]',
                './/div[contains(@class,"post_statement")]'],
    'csdn': ['.//div[contains(@class,"article-copyright")]', './/div[contains(@class,"recommend")]'],
    'devto': ['.//div[contains(@class,"crayons-card__top")]'],
}

PHOTO_SET = {'gmw__01', 'gmw__02', 'gmw__03', 'gmw__04',
             'netease__01', 'netease__02', 'netease__03'}
LIST_PAGE = {'mdn__01'}


def annotate(row, ev, tree, text):
    site = row['site']
    rec = base_rec(row, ev)
    prov = {}
    og = ev['titles'].get('og:title')
    h1s = [norm_ws(h.text_content()) for h in tree.xpath('//h1')]
    h1s = [h for h in h1s if h and h != '全部导航']
    tt = ev['titles'].get('title_tag', '')
    # ---------- title ----------
    if site == 'csdn':
        rec['title'] = h1s[0] if h1s else og
        prov['title'] = 'dom://h1[1]（og:title/title_tag 带 SEO 后缀"_关键词-CSDN博客"，不取）'
    elif site == 'mslearn':
        rec['title'] = og or (h1s[0] if h1s else None)
        prov['title'] = 'meta:og:title'
    elif site == 'mdn':
        rec['title'] = h1s[0] if h1s else re.split(r'\s*[-|]', tt)[0]
        prov['title'] = 'dom://h1[1]'
    else:
        rec['title'] = og or (h1s[0] if h1s else None)
        prov['title'] = 'meta:og:title（与 h1 一致）' if og else 'dom://h1[1]'
    # ---------- content ----------
    cont = tree.xpath(CONTAINERS[site])
    if not cont:
        return None
    if site == 'mslearn':  # 页面含两个 div.content（标题壳/正文），取文本最长者
        cont = max(cont, key=lambda c: len(c.text_content()))
    else:
        cont = cont[0]
    ctext, md, flags, images = clean_container(cont, DROPS.get(site, []))
    rec['content_text'] = ctext or None
    rec['content_md'] = md or None
    rec['conversion_flags'] = flags
    rec['images'] = images or None
    prov['content_text'] = f'dom:{CONTAINERS[site]}' + (f'（剔除 {DROPS[site]}）' if site in DROPS else '')
    prov['content_md'] = '同源程序化 GFM 转换'
    prov['images'] = '同源容器内 <img> 收集（与 [[IMG_n]] 对应）'
    body_txt = norm_ws(tree.xpath('string(//body)'))

    # ---------- 站点特化 ----------
    if site == 'stdaily':
        tm = re.search(r'(20\d{2})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', body_txt)
        if tm:
            rec['publish_time'] = t('-'.join(tm.groups()[:3]) + ' ' + ':'.join(tm.groups()[3:]),
                                    '+08:00', 'inferred_site_locale')
            prov['publish_time'] = 'dom:byline"YYYY-MM-DD hh:mm:ss 来源：X"行'
        sm = re.search(r'来源[：:]\s*([^\s]{2,12})', body_txt)
        if sm:
            rec['source']['publisher'] = sm.group(1)
            prov['source.publisher'] = 'dom:byline"来源："行'
        # 尾部署名：文字记者/文案/海报设计/设计/责任编辑（科技日报转载新华社稿件的制作名单）
        c1 = re.sub(r'\s+', ' ', ctext)  # 折行合并后再匹配署名行
        authors, aprov = [], []
        def _names(seg):
            return [n for n in re.split(r'[、，,\s]+', seg.strip())
                    if re.fullmatch(r'[\u4e00-\u9fa5·]{2,4}', n)]
        wm = re.search(r'文字记者[：:]\s*(.+?)(?=海报设计|文案[：:]|设计[：:]|新华社|相关稿件|责任编辑|$)', c1)
        if wm:
            authors += _names(wm.group(1)); aprov.append('dom:尾部"文字记者：X、Y"')
        mm = re.search(r'文案[：:]\s*(.+?)(?=设计[：:]|新华社|相关稿件|责任编辑|$)', c1)
        if mm:
            authors += [f'{n}（文案）' for n in _names(mm.group(1))]; aprov.append('dom:尾部"文案：X Y"')
        hm = re.search(r'海报设计[：:]\s*(.+?)(?=新华社|相关稿件|责任编辑|$)', c1)
        if hm:
            authors += [f'{n}（海报设计）' for n in _names(hm.group(1))]; aprov.append('dom:尾部"海报设计：X"')
        dm = re.search(r'(?<!海报)设计[：:]\s*(.+?)(?=新华社|相关稿件|责任编辑|$)', c1)
        if dm:
            authors += [f'{n}（设计）' for n in _names(dm.group(1))]; aprov.append('dom:尾部"设计：X"')
        em = re.search(r'责任编辑[：:]\s*([\u4e00-\u9fa5·]{2,4})', body_txt)
        if em:
            authors.append(f'{em.group(1)}（责任编辑）'); aprov.append('dom:页尾"责任编辑：X"行')
        if authors:
            rec['authors'] = authors
            prov['authors'] = aprov
    elif site == 'en_people':
        tm = re.search(r'(\d{2}):(\d{2}), (\w+) (\d{2}), (\d{4})', body_txt)
        if tm and tm.group(3) in MONTHS:
            rec['publish_time'] = t(f'{tm.group(5)}-{MONTHS[tm.group(3)]:02d}-{tm.group(4)} {tm.group(1)}:{tm.group(2)}:XX',
                                    '+08:00', 'inferred_site_locale')
            prov['publish_time'] = 'dom:byline"hh:mm, Month DD, YYYY"（月名消歧，分钟级；en.people.cn 北京站点时区推断）'
        sm = re.search(r'source[：:]\s*([A-Za-z][^\s|]{0,40})', body_txt, re.I)
        msrc = (ev.get('meta', {}).get('source') or [''])[0]
        msrc = re.sub(r'^source[：:]', '', msrc).strip()
        if msrc:
            rec['source']['publisher'] = msrc
            prov['source.publisher'] = 'meta[name=source]（如"source：Xinhua"）'
        em = re.search(r'[（(][Ee]ditor[：:]\s*([A-Za-z ]+?)[)）]', ctext)
        if em:
            rec['authors'] = [f'{em.group(1).strip()}（编辑）']
            prov['authors'] = ['dom:正文尾部"(Editor: X)"（meta[name=author] 为 F_ 开头 ID，不采用）']
    elif site == 'csdn':
        j = None
        for jj in ev.get('jsonld', []):
            if isinstance(jj, dict) and jj.get('@type') == 'Article':
                j = jj
        if j and j.get('author'):
            au = j['author']
            nm = au[0].get('name') if isinstance(au, list) else au.get('name')
            if nm:
                rec['authors'] = [nm]
                prov['authors'] = ['json-ld:Article.author.name']
        if not rec['authors']:
            acc = [norm_ws(a.text_content()) for a in tree.xpath('//div[contains(@class,"user-info")]//a | //a[contains(@class,"nickname")]')]
            acc = [a for a in acc if a and '博客' in a or a == 'CSDN官方博客']
            if acc:
                rec['authors'] = [acc[0]]
                prov['authors'] = ['dom:博主账号名（官方机构号，json-ld 无 author）']
        v, off = iso_to_value((ev.get('meta', {}).get('article:published_time') or [''])[0])
        if v:
            rec['publish_time'] = t(v, off)
            prov['publish_time'] = 'meta:article:published_time（显式 +08:00）'
        v2, off2 = iso_to_value((ev.get('meta', {}).get('article:modified_time') or [''])[0])
        if v2:
            rec['update_time'] = t(v2, off2)
            prov['update_time'] = 'meta:article:modified_time'
    elif site == 'devto':
        j = ev.get('jsonld', [{}])[0]
        au = j.get('author') or {}
        nm = au.get('name') if isinstance(au, dict) else None
        if nm:
            rec['authors'] = [nm]
            prov['authors'] = ['json-ld:Article.author.name']
        v, off = iso_to_value(j.get('datePublished', '') or '')
        if v:
            rec['publish_time'] = t(v, off)
            prov['publish_time'] = 'json-ld:datePublished（UTC Z 显式；页面另有评论时间，不混淆）'
        v2, off2 = iso_to_value(j.get('dateModified', '') or '')
        if v2 and v2 != v:
            rec['update_time'] = t(v2, off2)
            prov['update_time'] = 'json-ld:dateModified'
    elif site == 'mdn':
        tes = ev.get('time_elements', [])
        if tes:
            v, off = iso_to_value(tes[0]['datetime'] or '')
            if v:
                rec['update_time'] = t(v, off)
                prov['update_time'] = 'dom://time/@datetime（MDN 页脚"Last modified"时间，UTC Z 显式；无发布时间）'
        prov['authors'] = ['页面无署名（MDN 文档页）']
    elif site == 'mslearn':
        ma = (ev.get('meta', {}).get('author') or [None])[0]
        if ma:
            rec['authors'] = [ma]
            prov['authors'] = ['meta[name=author]（MS Learn 文档负责人账号）']
        # 时间以页脚可见 "Last updated on YYYY-MM-DD" 为准（日期级，时分秒 XX 占位）；
        # meta ms.date 序列化为 T00:00:00Z 属占位，不作为偏移证据；mslearn__03 两者冲突取可见值
        fm = re.search(r'Last updated on\s*(\d{4})-(\d{2})-(\d{2})', body_txt)
        msd = (tree.xpath('//meta[@name="ms.date"]/@content') or [None])[0]
        if fm:
            dv = f'{fm.group(1)}-{fm.group(2)}-{fm.group(3)} XX:XX:XX'
            rec['update_time'] = t(dv, None)
            prov['update_time'] = 'dom:页脚"Last updated on YYYY-MM-DD"（日期级，时分秒未知用 XX 占位，无偏移信息）'
            if msd and not msd.startswith(f'{fm.group(1)}-{fm.group(2)}-{fm.group(3)}'):
                prov['update_time'] += f'；注意：meta[name=ms.date]={msd} 与页脚冲突，取可见页脚值（见 changelog）'
        elif msd:
            v, off = iso_to_value(msd)
            if v:
                vv = re.sub(r' 00:00:00$', ' XX:XX:XX', v)
                rec['update_time'] = t(vv, None)
                prov['update_time'] = 'meta[name=ms.date]（T00:00:00Z 为日期序列化占位，时分秒记 XX、偏移不取）'
    elif site == 'netease':
        v, off = iso_to_value((ev.get('meta', {}).get('article:published_time') or [''])[0])
        if v:
            rec['publish_time'] = t(v, off)
            prov['publish_time'] = 'meta:article:published_time（显式 +08:00；与 byline 一致）'
        m = re.search(r'本文转自[：:]\s*([^\s；。]{2,15})', ctext)
        if m:
            rec['source']['publisher'] = m.group(1)
            prov['source.publisher'] = 'dom:正文首行"本文转自：X"（byline 来源为网易号账号名）'
        else:
            sm = re.search(r'来源[：:]\s*([^\s]{2,12})', body_txt)
            if sm:
                rec['source']['publisher'] = sm.group(1)
                prov['source.publisher'] = 'dom:byline"来源："行'
        mm = re.search(r'本报记者\s*([\u4e00-\u9fa5· ]{2,15})', ctext)
        if mm:
            names = [n for n in re.split(r'[、 ]+', mm.group(1).strip())
                     if re.fullmatch(r'[\u4e00-\u9fa5·]{2,5}', n)]
            if names:
                rec['authors'] = names
                prov['authors'] = ['dom:正文"本报记者 X Y"署名行（meta[name=author]="网易"为站点名，不采用）']
    rec['provenance'] = prov
    return rec


out = []
for row in IDX:
    if row['group'] != 'test':
        continue
    ev, tree, text = evidence_dump(BASE + row['path'], row['encoding_declared'],
                                   row['encoding_detected'])
    if row['id'] in PHOTO_SET:
        out.append(refusal_rec(row, ev,
                               '图集页：正文为"图片+图说"序列（新华社图片稿/海报稿），按 photo_set 拒识',
                               f'dom:{CONTAINERS.get(row["site"], "//body")} 内图片与图说交替结构', structure='photo_set'))
        continue
    if row['id'] in LIST_PAGE:
        out.append(refusal_rec(row, ev,
                               '参考索引页（"This page lists all the HTML elements"），按页面功能判 list_page',
                               'dom://main 为全元素分类索引列表', structure='list_page'))
        continue
    rec = annotate(row, ev, tree, text)
    if rec:
        out.append(rec)

json.dump(out, open('gold_test.json', 'w'), ensure_ascii=False, indent=2)
print(f'wrote gold_test.json: {len(out)} records')
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
