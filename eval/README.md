# eval/ — 离线库 HTML 结构化提取评测器

| 文件 | 说明 |
|---|---|
| `score_v2.py` | **冻结主版本**，唯一实现依据是 `../eval_spec_v2.md`（绑定冻结，§9） |
| `score.py` | v1 历史口径，仅用于新旧对照，不再修订 |
| `test_score_v2.py` | 规范 §8 的 13 场景 46 断言 + 3 项端到端断言，共 49 项 |
| `handcheck_draft.py` | 冻结前的手算验算草稿（与 `test_score_v2.py` 算术同源） |
| `fixtures/` | 3 页迷你 pred/gold 样例及两版跑分输出 |

## 运行

```bash
cd html-extract

# v2（冻结主版本）：逐页评分 → 宏平均 → 分组输出（含全部诊断指标）
venv/bin/python eval/score_v2.py \
    --pred predictions.jsonl --gold gold.json --out scores_v2.json
# 预留测试集纪律：只出聚合分，不出逐页明细
venv/bin/python eval/score_v2.py --pred ... --gold ... --out ... --no-pages

# v1（历史对照口径）
venv/bin/python eval/score.py \
    --pred predictions.jsonl --gold gold.json --out scores_v1.json

# 单元测试（13 场景 46 断言 + 3 端到端 = 49 项）
venv/bin/python eval/test_score_v2.py
```

迷你样例自验：

```bash
venv/bin/python eval/score_v2.py --pred eval/fixtures/mini_pred.jsonl \
    --gold eval/fixtures/mini_gold.json --out eval/fixtures/mini_scores_v2.json
venv/bin/python eval/score.py --pred eval/fixtures/mini_pred.jsonl \
    --gold eval/fixtures/mini_gold.json --out eval/fixtures/mini_scores_v1.json
```

## 输入格式

**gold.json**：`{"pages": [...]}`（顶层为列表亦可）。每页：

| 键 | 说明 |
|---|---|
| `id` | 页面 id，与 pred 对齐的键 |
| `dataset` / `site` / `route` | 分组维度：数据集 / 站点 / 路由层（fixed / generic；route 缺省取 site） |
| `content_structure` | `single` / `multi_article` / `photo_set` / `live_blog` / `list_page`；非 `single` 只评拒识 |
| `page_condition` | `ok` / `empty_shell` / `anti_bot_suspected` / `truncated`；非 `ok` 只评拒识 |
| `title` / `content_text` | 字符串 \| null |
| `authors` | 列表 \| null |
| `*_time` | `{"value": "YYYY-MM-DD hh:mm:ss（XX 占位）", "utc_offset": "+08:00"\|null}`，或纯字符串（视为 value）；null = 不存在。时间字段按 gold 中出现的所有 `*_time` 键各自独立评分 |

**predictions.jsonl**：每行 `{"id": ..., 同名字段...}`。缺页按崩溃处理（文章页各字段计 0 入分母）；行解析异常计入输出的 `pred_parse_errors`，不吞。显式拒识：`{"id": ..., "rejected": true}` 或四字段全空。

## v1 vs v2 口径差异（三处系统性差异）

| 字段 | v1（score.py，历史） | v2（score_v2.py，冻结） | 影响 |
|---|---|---|---|
| **title** | 规范化（NFKC+去全部空白+**小写**）精确匹配 0/1 | 同为精确匹配（NFKC+**casefold**+去空白），另增诊断 `title_sim`（字符 3-gram 多重集 F1），区分"多带站点后缀"（sim>0.5）与"整体错位" | 主指标口径基本一致；v2 多了失败归因诊断 |
| **content** | 规范化后**字符级 LCS-F1**（SequenceMatcher matching_blocks 公共长度算 P/R/F1） | 规范化后**字符 3-gram 多重集 F1**；LCS 降为诊断 `lcs_f1`，另增 `dup_ratio` / `num_f1` / `para_ratio` | v1 对乱序敏感但对"重复粘贴"无惩罚（dup 场景虚高为 1）；v2 多重集使其正确降为 0.5（规范 §8-S4），且中英同规则 |
| **time** | **天粒度**等值；任一端缺失**跳过不计** | 按 **gold 精度**逐分量比较（XX 分量不参与）；漏提/误填**计 0 入分母**；新增 `time_confusion`（抽到更新时间）与时区三态统计 | v1 的"天粒度+缺失跳过"系统性偏高，遮蔽时分秒差异与失败页（dev time 曾 1.0 → v2 实锤 0.789） |

其他 v2 新增纪律（v1 无对应物）：失败不从分母消失（崩溃/漏提/误填全计 0）；唯一例外是双端皆空 = `correct_empty` 不进分母；authors 必报 `false_fill_rate` / `miss_rate`；非文章页与文章页分母互斥，拒识准确率单列。

## 输出结构（scores.json）

`overall` + `by_dataset` / `by_site` / `by_route` / `by_content_structure` 五个视图，每组同构：

- 主指标平铺：`title_exact`、`authors_f1`、`content_f1`、`<字段>_score`（每个时间字段）、`rejection_accuracy`；
- 诊断指标平铺：`title_sim`、`lcs_f1`、`dup_ratio`、`num_f1`、`para_ratio`、`authors_false_fill_rate`、`authors_miss_rate`；
- 明细嵌套：`*_detail`（分母 n、correct_empty / false_fill / miss 计数）、`time.<字段>`（confusion、tz 三态、gold_all_xx）、`rejection_detail.badcases`（误抽页清单）；
- 顶层 `pages` 为逐页明细（`--no-pages` 可关）；`pred_parse_errors` 上报解析异常行。

## 实现注记（与规范的关系）

- 与 eval_spec_v2.md **零已知偏离**：§2~§7 全部条款逐一对应实现，§8 的 46 断言由 `test_score_v2.py` 真实运行通过。
- 两处规范未明文、本实现按语义取值并已在此声明：
  1. gold 时间值无任何已知分量（全 XX）时该页不进分母，单独计 `gold_all_xx`（规范 §5.1 只要求"登记"）；
  2. 应拒识页在 pred 中**缺行**视为"未返回实质内容"，计正确拒识（§7 只定义了"返回实质内容 = 错误"）。
- `dup_ratio` 不可跨语言直接解读：英文长文本天然有约 0.3~0.5 的重复 3-gram，只能同数据集内跨版本相对比（规范 §6.2）。
- 外部数据集（如 ISPRAS）作者标注覆盖率不全时，`false_fill_rate` 系统性偏高，报告必须声明该局限（规范 §4）。
