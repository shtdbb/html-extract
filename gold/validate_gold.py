# -*- coding: utf-8 -*-
"""三份 gold 的结构校验（不逐字通读正文，只做机器可核查项）：
1) 必填字段齐全、类型正确；2) 时间格式 YYYY-MM-DD hh:mm:ss（XX 占位合法）；
3) utc_offset 与 utc_offset_source 配套；4) update>=publish（白名单例外仅警告）；
5) provenance 覆盖所有非空字段；6) authors 为 list|null；
7) 拒识页四字段全空且 expect_refusal=true；
8) [[IMG_n]] 占位符与 images 列表一一对应；9) id 与 dataset_index 对齐。
"""
import json
import re
import sys

BASE = '../'
IDX = {r['id']: r for r in map(json.loads, open(BASE + 'dataset_index.jsonl'))}

TIME_RE = re.compile(r'^\d{4}-(?:\d{2}|XX)-(?:\d{2}|XX) (?:\d{2}|XX):(?:\d{2}|XX):(?:\d{2}|XX)$')
OFF_RE = re.compile(r'^[+-]\d{2}:\d{2}$')
REQUIRED = ['id', 'group', 'site', 'url', 'path', 'sha1', 'page_condition',
            'needs_render', 'content_structure', 'expect_refusal', 'title',
            'authors', 'publish_time', 'update_time', 'content_text',
            'content_md', 'conversion_flags', 'images', 'source', 'provenance', 'notes']
# update<publish 的源数据原样保留白名单（见 changelog）
INVERTED_OK = {'devto__01'}
STRUCTURES = {'single', 'multi', 'list_page', 'photo_set'}
CONDITIONS = {'ok', 'dns_fail', 'http_403', 'http_404', 'redirect_loop', 'shell_only'}


def check_time(rec, field, errs, warns):
    tv = rec[field]
    if tv is None:
        return
    if not isinstance(tv, dict) or set(tv) != {'value', 'utc_offset', 'utc_offset_source'}:
        errs.append(f'{rec["id"]}.{field}: 结构错误 {tv}')
        return
    v, off, src = tv['value'], tv['utc_offset'], tv['utc_offset_source']
    if not TIME_RE.match(v or ''):
        errs.append(f'{rec["id"]}.{field}: value 格式非法 {v!r}')
    if off is not None and not OFF_RE.match(off):
        errs.append(f'{rec["id"]}.{field}: utc_offset 非法 {off!r}')
    if src is not None and src != 'inferred_site_locale':
        errs.append(f'{rec["id"]}.{field}: utc_offset_source 非法 {src!r}')
    if src and not off:
        errs.append(f'{rec["id"]}.{field}: 标了 inferred_site_locale 但 utc_offset 为空')


def parse_cmp(tv):
    """可比较化：XX 分段不可比时返回 None"""
    if not tv or 'XX' in tv['value']:
        return None
    return tv['value'] + (tv['utc_offset'] or '')


def check_rec(rec, errs, warns):
    rid = rec.get('id', '?')
    for k in REQUIRED:
        if k not in rec:
            errs.append(f'{rid}: 缺字段 {k}')
    idx = IDX.get(rid)
    if not idx:
        errs.append(f'{rid}: 不在 dataset_index')
    else:
        for k in ('group', 'site', 'url', 'path', 'sha1'):
            if rec.get(k) != idx.get(k):
                errs.append(f'{rid}: {k} 与 dataset_index 不一致')
    if rec.get('content_structure') not in STRUCTURES:
        errs.append(f'{rid}: content_structure 非法 {rec.get("content_structure")!r}')
    if rec.get('page_condition') not in CONDITIONS:
        errs.append(f'{rid}: page_condition 非法 {rec.get("page_condition")!r}')

    prov = rec.get('provenance') or {}
    if rec.get('expect_refusal'):
        for f in ('title', 'authors', 'publish_time', 'update_time',
                  'content_text', 'content_md', 'images'):
            if rec.get(f) not in (None, [], ''):
                errs.append(f'{rid}: 拒识页 {f} 应为空，实际={str(rec.get(f))[:40]!r}')
        if 'refusal_evidence' not in prov:
            errs.append(f'{rid}: 拒识页缺 provenance.refusal_evidence')
        if not rec.get('notes'):
            errs.append(f'{rid}: 拒识页缺 notes')
        return

    # 文章页
    if not rec.get('title'):
        errs.append(f'{rid}: 文章页 title 为空')
    if not rec.get('content_text'):
        errs.append(f'{rid}: 文章页 content_text 为空')
    if not rec.get('content_md'):
        errs.append(f'{rid}: 文章页 content_md 为空')
    if rec.get('authors') is not None and not isinstance(rec['authors'], list):
        errs.append(f'{rid}: authors 非 list')
    if not isinstance(rec.get('conversion_flags'), list):
        errs.append(f'{rid}: conversion_flags 非 list')

    check_time(rec, 'publish_time', errs, warns)
    check_time(rec, 'update_time', errs, warns)
    p, u = parse_cmp(rec.get('publish_time')), parse_cmp(rec.get('update_time'))
    if p and u and u < p:
        (warns if rid in INVERTED_OK else errs).append(
            f'{rid}: update_time < publish_time（{u} < {p}）')

    # provenance 覆盖：非空字段必须有出处
    need = []
    for f in ('title', 'authors', 'publish_time', 'update_time',
              'content_text', 'content_md', 'images'):
        if rec.get(f) not in (None, [], ''):
            need.append(f)
    if (rec.get('source') or {}).get('publisher'):
        need.append('source.publisher')
    missing = [f for f in need if f not in prov]
    if missing:
        errs.append(f'{rid}: provenance 缺 {missing}')

    # 图片占位符一一对应
    images = rec.get('images') or []
    ct = rec.get('content_text') or ''
    md = rec.get('content_md') or ''
    for i in range(1, len(images) + 1):
        if f'[[IMG_{i}]]' not in ct:
            errs.append(f'{rid}: content_text 缺 [[IMG_{i}]]（images 有 {len(images)} 条）')
    stray = set(re.findall(r'\[\[IMG_(\d+)\]\]', ct)) - {str(i) for i in range(1, len(images) + 1)}
    if stray:
        errs.append(f'{rid}: content_text 出现越界占位符 {sorted(stray)}')
    if images and '[[IMG_1]]' not in md:
        warns.append(f'{rid}: content_md 未含 [[IMG_1]] 占位（images 非空）')


def main():
    total_err, total_warn = 0, 0
    for fn, grp in (('gold_fixed.json', 'fixed'), ('gold_generic.json', 'generic'),
                    ('gold_test.json', 'test')):
        recs = json.load(open(fn))
        errs, warns = [], []
        ids = set()
        for r in recs:
            if r['id'] in ids:
                errs.append(f'{r["id"]}: id 重复')
            ids.add(r['id'])
            if r['group'] != grp:
                errs.append(f'{r["id"]}: group={r["group"]} 与文件 {fn} 不符')
            check_rec(r, errs, warns)
        expect = {i for i, x in IDX.items() if x['group'] == grp}
        if ids != expect:
            errs.append(f'{fn}: 覆盖不齐，缺 {sorted(expect - ids)} 多 {sorted(ids - expect)}')
        print(f'== {fn}: {len(recs)} 条（拒识 {sum(1 for r in recs if r["expect_refusal"])}），'
              f'错误 {len(errs)}，警告 {len(warns)}')
        for e in errs:
            print('  ERR ', e)
        for w in warns:
            print('  WARN', w)
        total_err += len(errs)
        total_warn += len(warns)
    print(f'\n总计：错误 {total_err}，警告 {total_warn}')
    sys.exit(1 if total_err else 0)


if __name__ == '__main__':
    main()
