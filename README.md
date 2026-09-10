# 离线库 HTML 结构化提取 — baseline 复现与迭代评测

## 产物地图

| 路径 | 内容 |
|---|---|
| `baseline_selection.md` | 任务一：五路线比较 + 官方文档核查 + dev5 实测 + baseline/对照/门控结论 |
| `results/dev5_validation.json` | dev5 冒烟原始输出（安装/API/四字段映射/耗时/GBK bytes 行为） |
| `extract.py` | **最终 baseline 提取器（= v4 冻结快照）** |
| `versions/extract_v1..v4.py` | 迭代留档：v1 trafilatura only → v2 +元数据层 → v3 +站点规则+拒识 → v4 +后缀剥离/署名扫描/时间补全/图片占位符 |
| `site_rules.py` / `extract_time.py` | fixed 三站规则库（选择器整理自 gold provenance）/ 共享时间解析 |
| `run_readability.py` | readability-lxml 对照臂 |
| `decision_log.md` | D-001~D-004：评分器除零修复、各轮回归/修复全记录 |
| `results/v{n}_pred_dev.jsonl` / `v{n}_scores_v1.json` / `v{n}_scores_v2.json` | 各版本 dev 预测与双口径分数 |
| `results/readability_*` | 对照臂预测与双口径分数 |
| `results/v2_scores_all.json` | dev 汇总：各臂 overall + fixed/generic 分层，主指标+全部诊断指标（v2 口径）+ v1 口径对照 |
| `results/test_final_scores.json` | **test 终测聚合分（只跑一次，--no-pages）** |
| `results/badcase_analysis.md` | dev v4 逐页错误归因 + 按证据强度排序的迭代候选 |
| `results/negative_check.json` | negative 4 页负例拒识行为单独核对 |
| `results/dev_gold.json` / `results/test_gold.json` | 评分用 gold（原 gold + dataset/route 派生字段；原 gold 未改） |
| `results/run_logs/` | 全部运行日志原样留存 |

## 可复现命令（工作目录 html-extract/，Python 一律 venv）

```bash
# 任务一：dev5 冒烟
venv/bin/python scripts/dev5_validate.py                      # → results/dev5_validation.json

# 评分用 dev gold（fixed+generic + dataset/route 派生字段）
venv/bin/python - <<'EOF'
import json
gf=json.load(open('gold/gold_fixed.json')); gg=json.load(open('gold/gold_generic.json'))
out=[]
for r in gf+gg:
    r=dict(r); r['dataset']='dev'; r['route']=r['group']; out.append(r)
json.dump(out, open('results/dev_gold.json','w'), ensure_ascii=False, indent=1)
EOF

# 各版本 dev 全量提取 + 双口径跑分（v1 示例，v2/v3/v4 同构替换版本号）
venv/bin/python versions/extract_v1.py --groups fixed,generic,negative --out results/v1_pred_dev.jsonl
venv/bin/python eval/score.py    --pred results/v1_pred_dev.jsonl --gold results/dev_gold.json --out results/v1_scores_v1.json
venv/bin/python eval/score_v2.py --pred results/v1_pred_dev.jsonl --gold results/dev_gold.json --out results/v1_scores_v2.json

# 对照臂 + test 终测 + 负例核对 + 汇总（一键批量）
venv/bin/python scripts/run_all_eval.py
```

注意：`eval/score_v2.py` 相对冻结版有一处崩溃修复（authors_f1 两集合不相交时除零），
按 §9 要求登记于 `decision_log.md` D-001，`eval/test_score_v2.py` 49/49 断言通过。

## 结果速览（dev，v2 冻结口径；fixed/generic 分层）

| 臂 | title | authors | publish | update | content | 拒识 |
|---|---|---|---|---|---|---|
| v1 (traf only) | 0.714 | 0.272 | 0.000 | 0.000 | 0.749 | 0.000 |
| v2 (+元数据) | 0.714 | 0.376 | 0.321 | 0.889 | 0.749 | 0.000 |
| v3 (+规则+拒识) | 0.886 | 0.599 | 0.536 | 1.000 | 0.928 | 1.000 |
| **v4 (=extract.py)** | **0.886** | **0.760** | **0.892** | **1.000** | **0.929** | **1.000** |
| readability 对照 | 0.024 | 0.200 | 0.000 | 0.000 | 0.778 | 0.000 |

v4 分层：fixed 层 1.000/0.944/1.000/1.000/0.996；generic 层 0.816/0.634/0.844/1.000/0.889。

test 终测（28 页，聚合）：v4 title 0.650 / authors 0.486 / publish 0.333 / update 0.273 / content 0.720 / 拒识 0.000；
readability 对照 title 0.150 / authors 0.167 / content 0.847 / 时间 0 / 拒识 0.000。
test 拒识 0 主因：8 个应拒识页中 7 个为 photo_set（dev 无此类页，先验阈值未命中），
按纪律未根据 test 调优——列入后续迭代证据。
