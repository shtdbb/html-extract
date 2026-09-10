# 离线库 HTML 结构化提取 — 最终总报告

- 课题：解析爬虫抓取的原始 HTML，提取 title / content / authors / publish_time·update_time 等结构化字段（双形态：JSONL + Markdown）。
- 本文全部数字均从 `results/` 与 `external/` 的 JSON 产物真实读取（本报告写作时已逐一重算宏平均核对自洽），未凭记忆填写。
- 交付物总清单见 `MANIFEST.md`；迭代与裁决留痕见 `decision_log.md`（D-001~D-008）。

---

## 一、结论先行摘要

**关键数字（v2 冻结口径）**

| 评测面 | 规模 | baseline v4 主指标 |
|---|---|---|
| dev（自建开发集） | 85 页（fixed 30 + generic 55） | title 0.886 / authors 0.760 / publish 0.892 / update 1.000 / content 0.929 / 拒识 1.000 |
| test（预留终测，仅跑一次聚合） | 28 页（含 8 应拒识页） | title 0.650 / authors 0.486 / publish 0.333 / update 0.273 / content 0.720 / 拒识 0.000 |
| ISPRAS en 外部基准（B 组论文口径） | 160 页 / 80 站 | title 0.779 / text 0.745 / authors 0.397 / date 0.322（天粒度 0.421） |

**三个最重要的诚实结论**

1. **「规则库 + 通用兜底」双层架构在 dev 上成立、在 test 上明显衰减，衰减主因是拒识先验未覆盖 test 独有的 photo_set 类型。** dev 四轮迭代（v1→v4）把 authors 从 0.272 提到 0.760、publish 从 0 提到 0.892、拒识从 0 提到 1.000；但 test 终测 8 个应拒识页 0 命中（7 个为 photo_set 图集页，dev 中不存在此类页面，先验阈值无从训练），直接拉低 test 总盘。这是真实的泛化缺口，按纪律未根据 test 调优。
2. **外部基准证明方法在同一数量级、但不占优。** ISPRAS en 抽样（160 页/80 站）上，v4 的 Text 0.745 落在论文已发表方法区间（0.66–0.89）内偏低段，Title 0.779 低于三个开源库（0.94–1.00），Date 0.322–0.421 与开源库（0.42–0.50）同量级，Author 0.397 高于 Newspaper/News-Please（0.36）低于 Trafilatura（0.53）。后缀剥离与拒识启发式按中文站先验训练，英文站覆盖不足是主因（误拒识 16/160 构成所有字段的共同失分底噪）。
3. **评测基础设施是本课题最可靠的交付物。** v2 冻结口径（失败不从分母消失、按 gold 精度逐分量比较时间、双端皆空唯一豁免）经 13 场景 46 手算断言 + 49 项单测锁定；相对 v1 旧口径暴露出真实差距（dev time 曾 1.0 → v2 实锤 0.789 级别的虚高被消除；ISPRAS publish v1 0.853 vs v2 0.292 的落差可完全分解为口径差异 + 时区归一化差异，见 §7）。分数的可信度来自口径纪律，而非数字本身的高低。

---

## 二、数据资产

### 2.1 原始库构成（117 页，`data/html/` + `dataset_index.jsonl`）

| 组 | 页数 | 站点构成 | 角色 |
|---|---|---|---|
| fixed | 30 | news_cn / chinadaily / gov_cn 各 10 | 固定站·规则路由开发集 |
| generic | 55 | caixin 5 / chinanews 6 / cnblogs 7 / github_blog 4 / ifeng 5 / people 6 / python_docs 5 / segmentfault 5 / sina 6 / sohu 6 | 通用站·兜底路由开发集 |
| negative | 4 | chinanews / people / sina / sohu 频道列表页各 1 | 拒识负例（无 gold，仅索引标注 + 单独行为核对） |
| test | 28 | 新闻 15（netease 4 + gmw 4 + stdaily 3 + en_people 4）、博客 7（csdn 5 + devto 2）、文档 6（mdn 3 + mslearn 3） | 预留终测集（模板级隔离，不参与调优） |

每页保留原始 HTML + URL + final_url + 采集时间 + 字节数 + sha1 + 编码声明/检测 + `page_condition`（117 页全为 ok）+ `content_structure`（single 104 / photo_set 7 / list_page 6）。采集全部成功页零失败重试入库；20 次采集失败（ifeng 空壳拦截 ×4、oschina 空壳 ×13、403/404 ×2、51cto 种子页 0 文章链接 ×1）逐条登记于 `scripts/collection_log.md` 失败明细。

**与原计划的偏差（如实登记，decision_log D-005）**：fixed 组因栏目页全是 JS 壳改用「搜索引擎发现 + 直取」；test 组 cctv 整站剔除（4 页全为视频稿）改由 netease 补齐、oschina/51cto 整站失败改由 CSDN 补齐、mslearn 改直取；negative 组两处 403 替换。

### 2.2 gold 标准答案（113 条）与四轮质量关的本地实际执行情况

`gold/`：gold_fixed 30（全文章页）+ gold_generic 55（49 文章页 + 6 拒识：caixin×5 付费墙、python_docs__02 列表页）+ gold_test 28（20 文章页 + 8 拒识：gmw×4、netease×3 图集、mdn__01 列表页）= **113 条 = 文章页 99 + 拒识 14**。negative 4 页无 gold（会话 1 遗留缺口），仅在索引标注 list_page，行为核对走 `results/negative_check.json`。

标注指南（annotation_guide.md）规定的质量流程与实际执行对照：

| 质量关 | 规定 | 本地实际执行 |
|---|---|---|
| ① 自动化结构核查 100% | schema、时间格式与 XX 占位合法性、update≥publish、provenance 齐全、占位符与 images 一一对应 | **已执行**：`validate_gold.py` 对 113 条全量检查，结果 0 错误、1 警告（devto__01 源数据 update<publish 倒挂，白名单豁免，changelog C26） |
| ② 针对性全量复查 | 自动化发现一类问题即全样本复查该类 | **已执行**：C01–C03 工具层三处修复（注释泄漏、tail 乱序、figure 跳过）均为发现后全组重跑；C04–C10 等署名/容器问题按站点整组复查 |
| ③ 人工抽查 ≥10%、覆盖每个 content_structure 类别 | 每站至少抽 1 篇完整通读 | **降级执行为字段级证据核对 100%**：每页 byline、时间元素、容器边界均通过 evidence dump（probe_*.txt）与逐条 review 摘要核对；所有非空字段带 provenance。**正文未逐字通读**（见 §7 限制） |
| ④ 争议登记与铁律 | 争议挂起待裁决；gold 只含 HTML 真实信息，不联网、不采用提取器输出 | **已执行**：30 条 changelog（C01–C30）逐条登记；trafilatura 仅作起草对照；隔离集纪律写入 annotate_test.py 文件头（调优只读 dev gold） |

---

## 三、方法：baseline v4 管线架构

选型（`baseline_selection.md`）：比较五条路线（DOM+规则 / 成熟提取库 / 模型生成字段 / 模型选元素 / 混合流程）后选定**混合流程 E**；官方文档核查 + dev5 冒烟实测支撑（gov_cn__01 上 trafilatura 正文 62 字符、readability 19 字符，两库正文抽取均失败 → 站点规则层必要性的直接证据；trafilatura 传 bytes 在 GBK 页全部乱码 → 解码责任必须在调用方）。

`extract.py`（= v4 冻结快照，709 行）单页流程：

```
raw bytes
  → ① 解码（声明编码优先、chardet 兜底，declared/detected/used 三分留痕）
  → ② page_condition 判定（empty_shell / anti_bot_suspected / truncated 标记跳过）
  → ③ 拒识判定 check_refusal（list_page 长链接启发式、photo_set 三条件联合、付费墙）
  → ④ 三层路由（fixed 站走 site_rules.py 选择器规则库；generic 站走
       元数据层 JSON-LD/OG/meta → trafilatura bare_extraction(with_metadata=True)
       → DOM 文本密度容器兜底）
  → ⑤ 字段级后处理：标题后缀剥离（原串迭代切尾）、署名扫描（正文首行+尾部，
       媒体名过滤表）、时间补全（meta 优先于 JSON-LD、ISO 分数秒、
       dateModified==datePublished 抑制、弃用 htmldate 兜底）
  → ⑥ 正文装配 assemble_traf_body（段落合并、[[IMG_n]] 占位符、GFM 转换 flags）
  → ⑦ 逐字段 provenance 留痕 + 拒识页产出空记录
```

对照臂：`run_readability.py`（readability-lxml 0.9，title + summary→text；authors/time 无能力，如实记缺）。

迭代路径（每轮只改一类问题，改前改后各跑一次全量评测，回归即回滚留痕，见 decision_log D-002~D-004）：
**v1** trafilatura only → **v2** +元数据层 → **v3** +站点规则+拒识判定 → **v4** +标题后缀剥离重写/署名扫描修复/时间补全/图片占位符。

---

## 四、核心结果

### 4.1 dev 迭代表（v2 冻结口径，85 页，fixed/generic 分层；数字读自 `results/v{n}_scores_v2.json` 与 `results/v2_scores_all.json`）

| 臂 | title | authors | publish | update | content | 拒识 |
|---|---|---|---|---|---|---|
| v1（traf only） | 0.714 | 0.272 | 0.000 | 0.000 | 0.749 | 0.000 |
| v2（+元数据） | 0.714 | 0.376 | 0.321 | 0.889 | 0.749 | 0.000 |
| v3（+规则+拒识） | 0.886 | 0.599 | 0.536 | 1.000 | 0.928 | 1.000 |
| **v4（=extract.py）** | **0.886** | **0.760** | **0.892** | **1.000** | **0.929** | **1.000** |

v4 分层（v2_scores_all.json by_route）：
- **fixed**（30 页）：title 1.000 / authors 0.944 / publish 1.000 / update 1.000 / content 0.996
- **generic**（55 页）：title 0.816 / authors 0.634 / publish 0.844 / update 1.000 / content 0.889 / 拒识 1.000

### 4.2 readability 对照臂（dev，同口径）

| 臂 | title | authors | publish | update | content | 拒识 |
|---|---|---|---|---|---|---|
| readability-lxml | 0.024 | 0.200 | 0.000 | 0.000 | 0.778 | 0.000 |

content 0.778 尚可但 title 近乎全败（带后缀直接当标题）、authors/时间无能力、拒识无机制 —— 证明纯正文经典算法不能单独承担四字段任务。负例核对（`results/negative_check.json`）：v4 对 negative 4 页正确拒识 3/4（sina_list__01 漏拒，见 §6/§7）；readability 0/4。

### 4.3 test 终测聚合（28 页，只跑一次，`--no-pages`；`results/test_final_scores.json`）

| 臂 | title | authors | publish | update | content | 拒识 |
|---|---|---|---|---|---|---|
| v4 baseline | 0.650 | 0.486 | 0.333 | 0.273 | 0.720 | 0.000（0/8） |
| readability 对照 | 0.150 | 0.167 | 0.000 | 0.000 | 0.847 | 0.000 |

8 个应拒识页（gmw×4 + netease×3 photo_set、mdn__01 list_page）全部未拒识。test 不做逐页分析（纪律），拒识失败的类型构成来自 gold 侧标注事实。

### 4.4 ISPRAS 外部基准（en 抽样 160 页 / 80 站，每站 2 页；extract.py 零修改；崩溃 0 页；误拒识 16 页）

三口径总表（数字读自 `external/ispras_scores_{v1,v2,zyte}.json`，与本报告写作时逐页重算的宏平均完全一致）：

| 字段 | v1（旧口径） | v2（冻结口径） | B 组（论文口径） |
|---|---|---|---|
| title | 0.638 | 0.638（sim 0.793） | 0.779（词 4-gram F1） |
| authors | 0.249（n=94） | 0.268 | 0.397（n=59） |
| publish_time | 0.853（n=68，缺失跳过） | 0.292（n=154） | 0.313（n=144） |
| update_time | 1.000（n=1） | 0.017 | 0.125（n=8） |
| date 合一（publish∪update） | — | — | 分量级 0.322 / 天粒度 0.421（n=152） |
| content | 0.759 | 0.761 | 0.745 |
| 拒识 | —（ISPRAS 无负例） | — | — |

v2 诊断：num_f1 0.734、lcs_f1 0.843、dup_ratio 0.501、para_ratio 0.648；publish 时区三态 match 4 / missing 6 / mismatch 2 / gold_absent 132。

与论文 Table V（en 10 站 500 页 5-fold）数量级对照：Text 0.74 在论文方法区间（0.66–0.89）内偏低段；Title 0.78 低于三开源库（0.94–1.00）；Date 0.32–0.42 与开源库（0.42–0.50）同量级；Author 0.40 高于 Newspaper/News-Please（0.36）低于 Trafilatura（0.53）。**样本总体不同、日期粒度论文未定义、Updated 标签归属处理不同——只作数量级对照，不作精确比对**（`external/ispras_report.md` §五、§七）。

---

## 五、口径说明（v1 / v2 / B 组三处系统性差异）

1. **content**：v1 = 规范化后字符级 LCS-F1（对乱序敏感、对重复粘贴无惩罚）；v2 = 字符 3-gram 多重集 F1（LCS 降为诊断 lcs_f1，另出 dup_ratio / num_f1 / para_ratio）；B 组 = 词 4-gram 袋 F1。三者绝对值不可直接横比；同臂跨口径纵比才有意义。
2. **time**：v1 = 天粒度等值且**任一端缺失跳过**（系统性偏高，遮蔽时分秒差异与失败页）；v2 = 按 gold 精度逐分量比较、漏提/误填计 0 入分母、另出 time_confusion 与时区三态；B 组 = 解析后比较、缺失计 0 不跳过、gold 缺失不进分母（不罚 false_fill）。ISPRAS update_time 的 v2 0.017 vs B 组 0.125 差异即来自 false_fill 处理不同，两口径已并列保留。
3. **title / authors 归一化**：v1 title 用 lower，v2 用 casefold 并增 title_sim 诊断（区分"多带后缀"与"整体错位"）；v2 authors 在集合 F1 前剥角色括号与署名前缀，B 组仅 lower+strip。

---

## 六、badcase 归因摘要（dev v4 终态，`results/badcase_analysis.md`）

- **title（9 页失分/84 参评）**：people×6 为 `--` 双连字符+栏目段后缀未覆盖（sim 0.62–0.86，纯后缀型）；cnblogs×3 为博客首页型 gold 边界分歧（gold=博客名 vs pred=文章题，sim 0.00，非提取错误）。
- **authors（17 页失分）**：最大类是**媒体/栏目名误作作者**（sina×4、ifeng×4、chinadaily×1，meta/JSON-LD author 在门户转载页系统性污染）；其次是署名扫描 bug（sohu×4 正文首行从未生效）与多人多角色漏抓（chinanews、sina）；segmentfault__04 为过滤规则误伤机构号。
- **publish_time（7 页失分/65 有 gold 时间）**：全部为 cnblogs×7 false_fill——pred 取页面可见 `#post-date`，gold 全部 None，属边界解释分歧，按纪律不回改 gold。time_confusion=10 全部来自 gov_cn 同值双时间，系诊断指标误报，已剔除。
- **content（13 页 <0.85）**：chinanews×5 为 JS 薄正文页上 trafilatura 反而更脏（num_f1 0.10–0.16 极低）；people×5 容器 `div.rm_txt_con` 未被精确锁定（并段 + 漏数字段）。
- **update_time / 拒识**：dev update 满分（27 页）、时区 match 27/27；唯一应拒识页 python_docs__02 正确拒识；caixin×5 付费墙正确留空。negative 4 页中 sina_list__01 漏拒（261 字超薄列表页，两条信号都够不到阈值）。
- **迭代候选按证据强度排序**：媒体名过滤表扩充 > 署名扫描 bug 修复 > 薄正文页 DOM 容器装配 > `--` 后缀剥离 > news_cn 署名变体 > JSON-LD 双重转义 > 超薄列表页拒识信号；cnblogs 三类分歧挂起待 gold 侧裁决。
- **门控评估**：渲染兜底门（empty_shell+needs_render 占比 0% < 5%）不触发；模型路线门（v4 字段 miss 率 authors ≈9%、content 0，均 < 30%）不触发。

---

## 七、限制与已知缺口（全部如实声明）

1. **test 拒识 0/8 的原因**：8 个应拒识页中 7 个为 photo_set 图集页（gmw、netease），dev 集中不存在此类页面，v3 引入的 photo_set 三条件阈值只有 list_page/付费墙先验可参照，未命中 test 的真实图集形态；mdn__01 list_page 亦未命中。按「不调预留测试集」纪律，未根据 test 结果修改阈值——该缺口原样保留为后续迭代证据。
2. **cnblogs gold 边界分歧**：博客首页型页面 title 取博客名还是文章题（3 页）、`#post-date` 页面可见时间是否应采（7 页 false_fill）、用户名尾标点清洗（1 页），三处均为 gold 与提取器对规范的解释分歧，挂起待裁决；若 gold 后续确认应采，相关页立即转为正确。
3. **ISPRAS 抽样偏差**：站点为 en 320 站中文件内前 80 个（疑按域名字母序，开头站被系统性高估）、每站前 2 页、未重新抓取原站；authors 标注覆盖率仅 37%（"未标注 ≠ 无作者"），false_fill_rate 系统性偏高属数据集固有局限。ispras_report.md 内标注实验日期为 2025-09-11，与采集批次（2026-09-10）年份不一致，按原文转引、疑为笔误（decision_log D-008）。
4. **gold 验证深度**：自动结构核查与字段级证据核对 100% 覆盖，但 **99 篇正文未逐字通读**；正文中间段落的逐字正确性由容器规则与占位符一致性间接保证，不作逐字级承诺（gold/README.md 声明）。
5. **时分秒精度问题**：ISPRAS 上 publish v2 0.292 vs v1 0.853 的落差分解显示，75 页 miss 中 16 页来自误拒识，24 页"ok 但不等"中 13 页天粒度其实相等（pred 取 meta UTC、gold 标页面本地显示时间，存在整 8 小时级时区差）——即相当部分失分是时区归一化与精度表达差异，而非日期找错；`XX` 占位与 `utc_offset` 可知才记的设计能表达但不能消除该差异。
6. **negative 4 页无 gold**：会话 1 遗留的未标注缺口，不参与评分，仅以 `results/negative_check.json` 单独核对拒识行为（v4 3/4）。
7. **编码覆盖缺口**：dev/test 实测无真实 GBK 页，GBK 行为仅用合成转码样本验证（sina__01 → GB18030 字节）。
8. **诊断指标局限**：time_confusion 在 gov_cn 同值双时间场景系统性误报；dup_ratio 不可跨语言直接解读（英文长文本天然 0.3–0.5）。

---

## 八、复现命令（工作目录 `html-extract/`，Python 一律用项目 venv）

```bash
# 0. 环境（新建时；托管 Python 路径见 environment.md）
"<托管 Python>/bin/python3" -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install trafilatura readability-lxml beautifulsoup4 lxml chardet requests
venv/bin/python -c "import trafilatura, readability, bs4, lxml, chardet; print(trafilatura.__version__)"  # → 2.2.0

# 1. 数据采集（需联网；生成 data/html/ + dataset_index.jsonl + scripts/collection_log.md）
venv/bin/python scripts/collect.py

# 2. gold 标注 + 校验（在 gold/ 目录下运行，validate 依赖相对路径 ../dataset_index.jsonl）
cd gold
../venv/bin/python annotate_fixed.py   > review_fixed.txt
../venv/bin/python annotate_generic.py > review_generic.txt
../venv/bin/python annotate_test.py    > review_test.txt
../venv/bin/python validate_gold.py    # → 错误 0，警告 1（devto__01 白名单）
cd ..

# 3. 评分用 dev gold（fixed+generic + dataset/route 派生字段）
venv/bin/python - <<'EOF'
import json
gf=json.load(open('gold/gold_fixed.json')); gg=json.load(open('gold/gold_generic.json'))
out=[]
for r in gf+gg:
    r=dict(r); r['dataset']='dev'; r['route']=r['group']; out.append(r)
json.dump(out, open('results/dev_gold.json','w'), ensure_ascii=False, indent=1)
EOF

# 4. dev 全量提取 + 双口径跑分（v1 示例；v2/v3/v4 同构替换版本号）
venv/bin/python versions/extract_v1.py --groups fixed,generic,negative --out results/v1_pred_dev.jsonl
venv/bin/python eval/score.py    --pred results/v1_pred_dev.jsonl --gold results/dev_gold.json --out results/v1_scores_v1.json
venv/bin/python eval/score_v2.py --pred results/v1_pred_dev.jsonl --gold results/dev_gold.json --out results/v1_scores_v2.json

# 5. 对照臂 + test 终测（--no-pages）+ 负例核对 + 汇总（一键批量）
venv/bin/python scripts/run_all_eval.py

# 6. 单元测试（13 场景 46 断言 + 3 端到端 = 49 项）
venv/bin/python eval/test_score_v2.py

# 7. ISPRAS 外部基准（需联网；抽样→映射→提取→三口径跑分）
venv/bin/python external/sample_ispras.py     # 断点续跑，收满 80 站×2 页即中止
venv/bin/python external/map_ispras.py
venv/bin/python extract.py --index external/ispras_index.jsonl --groups ispras_en --out external/ispras_pred.jsonl
venv/bin/python eval/score.py    --pred external/ispras_pred.jsonl --gold external/ispras_gold_en.json --out external/ispras_scores_v1.json
venv/bin/python eval/score_v2.py --pred external/ispras_pred.jsonl --gold external/ispras_gold_en.json --out external/ispras_scores_v2.json
venv/bin/python external/score_zyte.py
```

---

## 九、后续建议

1. **渲染兜底门控评估**：当前门未触发（117 页 page_condition 全 ok、dev empty_shell+needs_render 占比 0% < 5%），但采集侧已观测到真实需求（oschina/51cto/ifeng 跟贴页全部空壳、cctv 视频稿）。建议在**采集扩容**时重估该门：空壳页一旦入库即推高占比。若触发，回补产物必须重过 `validate_gold.py` 同级校验后才准进 gold。
2. **模型路线预案**：门未触发（v4 authors miss ≈9%、content miss 0，均 < 30%）。若后续新站类把 miss 率推过阈值，优先走路线 D（模型选 DOM 节点、值仍从 DOM 取，无幻觉、可回溯 provenance），不走路线 C（直接生成字段，违反"HTML 即边界"铁律）；模型输出无法映射回原文节点的一律不采用。
3. **test 拒识缺口的迭代入口**：下一轮（v5）应优先补 photo_set/list_page 先验——test 的 7 个图集页形态（正文=图片+图说序列）与 sina_list__01 超薄列表页（<300 字、无文章容器）是两个明确的拒识信号来源；但**只能依据 dev 侧构造同类样本训练阈值**，test 终测分数保持一次性。
4. **WCXB（下游离线库入库）接入建议**：① 以 JSONL 为主交付形态，逐字段 `provenance` 原样带入库，支持"字段值 → HTML 节点"的回溯审计；② `page_condition` / `needs_render` / `rejected` 三标记映射为入库队列分流（直接入库 / 渲染回补队列 / 拒绝入库），拒识页的空记录也要落库留痕，保证"失败可观测"；③ 时间字段保留 `XX` 占位原串与 `utc_offset`（含 `inferred_site_locale` 推断标记），索引层按占位位置推导粒度，不要强转 UTC 后丢精度信息；④ `conversion_flags`（table_colspan_flattened 等）作为入库质量标签，供下游检索侧按需过滤有损记录；⑤ 编码三分（declared/detected/used）建议入库，"声明 GB2312 实为 GB18030"类故障在扩容后必然重现，留痕成本几乎为零。
5. **gold 侧待裁决项**：cnblogs 三类边界分歧（博客名 title、`#post-date` 时间、用户名尾标点）需要负责人裁决后回填争议表；裁决结果按"同类情形类推"执行，不逐页重开。
