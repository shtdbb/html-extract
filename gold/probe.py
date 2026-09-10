# -*- coding: utf-8 -*-
"""generic/test/negative 组逐页证据探针：为 content_structure/page_condition
判定与文章页标注提供 DOM 证据 + trafilatura 草稿对照。"""
import json
import re
import sys

sys.path.insert(0, '.')
from goldlib import evidence_dump, norm_ws
import trafilatura

BASE = '../'
IDX = [json.loads(l) for l in open(BASE + 'dataset_index.jsonl')]


def probe(row):
    ev, tree, text = evidence_dump(BASE + row['path'], row['encoding_declared'],
                                   row['encoding_detected'])
    lines = []
    lines.append(f"### {row['id']} | {row['url']}")
    lines.append(f"enc used={ev['used_encoding']} declared={row['encoding_declared']} detected={row['encoding_detected']} | body_text_len={ev['body_text_len']}")
    tt = ev['titles'].get('title_tag', '')
    lines.append(f"title_tag: {tt[:120]}")
    for k in ('og:title', 'twitter:title', 'meta_title'):
        if k in ev['titles']:
            lines.append(f"{k}: {ev['titles'][k][:120]}")
    if 'h1' in ev['titles']:
        for h in ev['titles']['h1']:
            lines.append(f"h1: {h[:120]}")
    if ev.get('meta'):
        lines.append('meta: ' + json.dumps(ev['meta'], ensure_ascii=False)[:300])
    if ev.get('jsonld'):
        for j in ev['jsonld'][:3]:
            s = json.dumps(j, ensure_ascii=False)
            lines.append('jsonld: ' + s[:350])
    if ev.get('time_elements'):
        lines.append('time_el: ' + json.dumps(ev['time_elements'][:4], ensure_ascii=False)[:250])
    if ev['byline_candidates']:
        lines.append('byline: ' + ' || '.join(ev['byline_candidates'][:5])[:350])
    # 链接密度 / 列表页信号
    body = tree.xpath('//body')
    if body:
        a_txt = sum(len(norm_ws(a.text_content())) for a in body[0].xpath('.//a'))
        tot = max(ev['body_text_len'], 1)
        lines.append(f'link_density={a_txt / tot:.2f} | n_links={len(body[0].xpath(".//a"))} | n_img={len(body[0].xpath(".//img"))} | n_video={len(body[0].xpath(".//video"))}')
    # trafilatura 草稿（仅对照，不作 gold）
    draft = trafilatura.extract(text, with_metadata=True, output_format='json',
                                include_images=True, include_tables=True)
    if draft:
        d = json.loads(draft)
        lines.append(f"TRAF title: {(d.get('title') or '')[:120]}")
        lines.append(f"TRAF author: {d.get('author')} | date: {d.get('date')}")
        t0 = d.get('text') or ''
        lines.append(f"TRAF text len={len(t0)} head: {t0[:100].replace(chr(10),'⏎')}")
    else:
        lines.append('TRAF: None')
    return '\n'.join(lines)


group = sys.argv[1]
out = []
for row in IDX:
    if row['group'] == group:
        try:
            out.append(probe(row))
        except Exception as e:
            out.append(f"### {row['id']} PROBE_ERROR: {e}")
open(f'probe_{group}.txt', 'w').write('\n\n'.join(out))
print(f'probe_{group}.txt written, {len(out)} pages')
