# Gold 标准答案库（离线库 HTML 结构化提取课题）

依据：`field_spec_v1.md`（v1.2 冻结）与 `annotation_guide.md`。铁律：**gold 只含 HTML 中真实存在的信息**；trafilatura 仅作起草对照（`probe_*.txt`），不作 gold 来源；全程不联网。

## 文件构成

| 文件 | 说明 |
|------|------|
| `gold_fixed.json` | fixed 组 30 篇（news_cn / chinadaily / gov_cn 各 10），全部文章页 |
| `gold_generic.json` | generic 组 55 篇：49 文章页 + 6 拒识（caixin×5 付费墙、python_docs__02 列表页） |
| `gold_test.json` | test 组 28 篇：20 文章页 + 8 拒识（gmw×4、netease×3 图集页，mdn__01 列表页） |
| `goldlib.py` | 解码（声明优先）+ 证据提取 + 容器文本/Markdown 转换共用库 |
| `annotate_fixed.py` / `annotate_generic.py` / `annotate_test.py` | 三组标注脚本，可重复运行 |
| `validate_gold.py` | 结构校验器（见下） |
| `probe_*.txt` | trafilatura 起草对照（非 gold） |
| `review_*.txt` | 标注脚本运行的逐条摘要输出 |
| `changelog.md` | 全部判定/修复记录（C01–C30） |

合计 gold 记录 113 条 = 文章页 99 + 拒识 14。negative 组 4 页（频道/滚动列表页）无 gold 记录，其 `content_structure=list_page` 标注在 `../dataset_index.jsonl`（117 行均已补 `page_condition` 与 `content_structure` 两字段；原文件备份为 `dataset_index.jsonl.bak`）。

## 隔离集纪律

**test 组为隔离集：调优抽取代码只允许读 dev gold（`gold_fixed.json` / `gold_generic.json`）；`gold_test.json` 仅供终测聚合使用。** 该约定同时写在 `annotate_test.py` 文件头；JSON 本身无法携带注释，特此声明。

## 验证深度（诚实声明）

- **自动结构核查 100%**：`validate_gold.py` 对 113 条全量检查必填字段、时间格式（含 XX 占位合法性）、utc_offset 配套、update≥publish、provenance 覆盖、authors 类型、拒识页四字段全空、[[IMG_n]] 占位符与 images 一一对应。当前结果：**0 错误，1 警告**（devto__01 源数据 update<publish 倒挂，白名单豁免，见 changelog C26）。
- **字段级证据核对 100%**：每页的 byline、时间元素、容器边界均通过 evidence dump（`probe_*.txt`）与逐条 review 摘要（`review_*.txt`）核对过；所有非空字段带 provenance 出处。
- **正文通读仅限抽查**：实际执行的是"每页 head/tail 摘要核对 + 字段级证据核对 + 容器剔除清单核对"，**未对 99 篇正文逐字通读**。正文中间段落的逐字正确性由容器规则与占位符一致性间接保证，不作逐字级别承诺。

## 复现

```bash
cd gold
../venv/bin/python annotate_fixed.py   > review_fixed.txt
../venv/bin/python annotate_generic.py > review_generic.txt
../venv/bin/python annotate_test.py    > review_test.txt   # 会先重跑 generic（import 副作用，输出一致）
../venv/bin/python validate_gold.py
```
