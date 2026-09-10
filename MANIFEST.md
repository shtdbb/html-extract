# MANIFEST.md — 全量交付物清单

- 课题：离线库 HTML 结构化提取。根目录：`html-extract/`。
- 统计口径：排除 `venv/`（依赖环境，可用 environment.md 重建）、`__pycache__/`、`.DS_Store`。
- **合计：398 个文件，108,359,517 字节（≈103.3 MiB）**（本清单自身不计入）。
- 每类下格式：`路径 | 一句话说明 | 大小`。大小为字节数；目录条目给出「文件数 / 合计大小」。

## 规范（8 项）

| 路径 | 说明 | 大小 |
|---|---|---|
| `plan.md` | 执行蓝图：任务边界、五条默认假设、八阶段计划 | 4,882 |
| `field_spec_v1.md` | 字段语义规范 v1.2（冻结）：四字段+images+时间组+辅助字段+gold 边界铁律 | 7,332 |
| `annotation_guide.md` | 标注操作手册：逐字段方法、误判清单、防循环论证、质量复核 | 7,997 |
| `eval_spec_v2.md` | 评测规范 v2（冻结，与 score_v2.py 绑定）：主指标+诊断指标+13 场景 46 断言 | 12,309 |
| `baseline_selection.md` | 五路线比较 + 官方文档核查 + dev5 冒烟实测 + 门控结论 | 7,741 |
| `environment.md` | venv 创建命令、依赖版本（pip freeze 实测）、验收命令 | 2,081 |
| `README.md` | 产物地图 + 可复现命令 + 结果速览 | 4,076 |
| `decision_log.md` | 决策日志 D-001~D-008（评分器修复、各轮迭代回归/修复、采集/gold/ISPRAS 阶段补登） | 10,637 |

另：`final_report.md`（21,863 字节）为最终总报告，与本清单一同位于项目根。

## 数据（5 项 + 117 个 HTML）

| 路径 | 说明 | 大小 |
|---|---|---|
| `dataset_index.jsonl` | 117 行索引：id/path/url/采集时间/sha1/编码/page_condition/content_structure | 58,699 |
| `dataset_index.jsonl.bak` | 补登 page_condition/content_structure 前的原文件备份 | 52,225 |
| `data/html/fixed/` | fixed 组 30 页原始 HTML（news_cn/chinadaily/gov_cn 各 10） | 30 文件 / 1,359,612 |
| `data/html/generic/` | generic 组 55 页原始 HTML（10 站） | 55 文件 / 4,452,156 |
| `data/html/negative/` | negative 组 4 页频道列表页 | 4 文件 / 447,259 |
| `data/html/test/` | test 组 28 页原始 HTML（预留终测集） | 28 文件 / 4,088,832 |
| `scripts/collect.py` | 采集器（种子页提链接/直取、空壳检测、失败逐条登记） | 23,252 |
| `scripts/collection_log.md` | 采集日志（自动生成）：分组统计 + 20 条失败明细 + 与计划的 9 项偏差声明 | 8,096 |
| `scripts/collection_state.json` | 采集断点状态 | 8,932 |

## gold（14 项）

| 路径 | 说明 | 大小 |
|---|---|---|
| `gold/gold_fixed.json` | fixed 组 gold 30 条（全文章页） | 972,494 |
| `gold/gold_generic.json` | generic 组 gold 55 条（49 文章页 + 6 拒识） | 870,622 |
| `gold/gold_test.json` | test 组 gold 28 条（20 文章页 + 8 拒识） | 493,831 |
| `gold/goldlib.py` | 解码 + 证据提取 + 容器文本/Markdown 转换共用库 | 14,016 |
| `gold/annotate_fixed.py` / `annotate_generic.py` / `annotate_test.py` | 三组标注脚本（可重复运行） | 14,556 / 21,771 / 13,856 |
| `gold/validate_gold.py` | 结构校验器（当前 0 错误 1 警告，警告为 devto__01 白名单） | 6,841 |
| `gold/probe.py` | trafilatura 起草对照生成器 | 2,926 |
| `gold/probe_generic.txt` / `probe_test.txt` / `probe_negative.txt` | trafilatura 起草对照（非 gold 来源；fixed 组对照在 review 流程中合并核对） | 63,819 / 26,798 / 2,578 |
| `gold/review_fixed.txt` / `review_generic.txt` / `review_test.txt` | 标注脚本逐条摘要输出（字段级证据核对载体） | 23,601 / 32,214 / 44,633 |
| `gold/changelog.md` | 全部判定/修复记录 C01–C30 | 6,940 |
| `gold/README.md` | gold 构成、隔离集纪律、验证深度声明、复现命令 | 2,979 |

注：gold/ 目录下共 17 个文件（含上表全部条目）。

## 代码（评测 + baseline，15 项）

| 路径 | 说明 | 大小 |
|---|---|---|
| `extract.py` | **最终 baseline 提取器（= v4 冻结快照）**，709 行 | 30,817 |
| `site_rules.py` | fixed 三站选择器规则库（整理自 gold provenance） | 14,140 |
| `extract_time.py` | 共享时间解析（ISO 分数秒、XX 占位） | 2,152 |
| `run_readability.py` | readability-lxml 对照臂 | 4,100 |
| `versions/extract_v1.py` ~ `extract_v4.py` | 迭代留档：v1 traf only → v2 +元数据 → v3 +规则+拒识 → v4 终态 | 4,426 / 11,057 / 15,839 / 30,431 |
| `eval/score.py` | v1 历史口径评分器（仅对照，不再修订） | 8,445 |
| `eval/score_v2.py` | **v2 冻结主评分器**（唯一实现依据 eval_spec_v2.md） | 24,060 |
| `eval/test_score_v2.py` | 单测：13 场景 46 断言 + 3 端到端 = 49 项 | 7,659 |
| `eval/handcheck_draft.py` | 冻结前手算验算草稿 | 12,117 |
| `eval/README.md` | 评测器使用说明 + v1/v2 口径差异 + 实现注记 | 5,614 |
| `eval/fixtures/` | 迷你 pred/gold 样例及两版跑分输出 | 4 文件 / 20,916 |
| `scripts/dev5_validate.py` | dev5 冒烟验证脚本 | 8,065 |
| `scripts/run_all_eval.py` | 对照臂 + test 终测 + 负例核对 + 汇总一键批量 | 7,510 |

## 结果（results/，50 个文件）

| 路径 | 说明 | 大小 |
|---|---|---|
| `results/v{n}_pred_dev.jsonl`（n=1..4） | 各版本 dev 预测（含 provenance） | 1.4–1.8 MB ×4 |
| `results/v{n}_scores_v1.json` / `v{n}_scores_v2.json` | 各版本 dev 双口径分数（v2 为主） | 19–103 KB ×8 |
| `results/v2_scores_all.json` | dev 汇总：各臂 overall + fixed/generic 分层 + 双口径对照 | 19,092 |
| `results/v4_pred_test.jsonl` / `test_v4_scores.json` | test 终测预测与分数（--no-pages 聚合） | 488,785 / 24,202 |
| `results/test_final_scores.json` | **test 终测聚合（v4 + readability 双臂，只跑一次）** | 52,612 |
| `results/readability_pred_{dev,test}.jsonl` / `readability_scores_{v1,v2}.json` / `test_readability_scores.json` | 对照臂预测与分数 | 合计 ≈1.97 MB |
| `results/dev_gold.json` / `test_gold.json` | 评分用 gold（原 gold + dataset/route 派生字段；原 gold 未改） | 1,830,130 / 486,836 |
| `results/dev5_validation.json` | dev5 冒烟原始输出（安装/API/四字段映射/耗时/GBK 行为） | 14,516 |
| `results/badcase_analysis.md` | dev v4 逐页错误归因 + 按证据强度排序的迭代候选 + 门控评估 | 6,649 |
| `results/negative_check.json` | negative 4 页负例拒识行为单独核对（v4 3/4，readability 0/4） | 1,634 |
| `results/run_logs/` | 全部运行日志 24 个原样留存（含本次验收抽查 spotcheck_index/spotcheck_pred） | 24 文件 / ≈58 KB |

## 外部基准（external/，21 个文件 + 160 个 HTML）

| 路径 | 说明 | 大小 |
|---|---|---|
| `external/sample_ispras.py` | WebDAV 流式抽样器（断点续跑，80 站×2 页） | 7,951 |
| `external/ispras_sample_en.jsonl` | 原始样本 160 页（内联 html + 节点级标注） | 41,200,386 |
| `external/html/` | 160 个页面 HTML 落盘 | 160 文件 / 38,681,914 |
| `external/map_ispras.py` | gold 映射器（xpath+text+label → 字段级 gold） | 11,720 |
| `external/ispras_gold_en.json` | 字段级 gold（本项目格式，160 页） | 1,065,188 |
| `external/ispras_index.jsonl` | extract.py 输入索引 | 23,416 |
| `external/ispras_pred.jsonl` | baseline v4 预测（160 条，零修改运行） | 1,408,198 |
| `external/ispras_scores_v1.json` / `ispras_scores_v2.json` | 我方双口径分数 | 78,806 / 286,183 |
| `external/score_zyte.py` / `ispras_scores_zyte.json` | B 组论文口径 scorer 与分数 | 6,193 / 43,615 |
| `external/ispras_report.md` | 外部基准实验报告（获取方式、偏差声明、三口径对齐、badcase 归因） | 10,136 |
| `external/logs/` | sample_run1–3、sample_test、map_changelog（39 条）、extract、三口径 score、badcase 日志 | 10 文件 / 12,993 |
