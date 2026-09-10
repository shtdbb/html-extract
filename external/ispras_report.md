# ISPRAS 外部基准对照实验报告（en 子集抽样）

- 实验日期：2025-09-11（本机，所有分数真实运行产生）
- 提取器：`extract.py`（baseline v4 冻结快照，未改代码）
- 样本：ISPRAS news-page-dataset 多语言版 en.json 抽样 **160 页 / 80 站**（每站 2 页）
- 产物：`external/` 目录（清单见文末）

## 一、获取方式与偏差声明（如实记录）

- 数据源：`github.com/ispras/news-page-dataset` README 指向的 Nextcloud 公开分享
  `https://nextcloud.ispras.ru/index.php/s/gkttoE637s9kxfJ`（multilingual-ae，按语言 JSON，每页含 uuid/url/**内联 html**/annotations）。
- **未全量下载**（en.json 2.8 GB、全语言 8.4 GB、HTML 整包 1.5 GB）。采用 WebDAV 流式抽样
  （`sample_ispras.py`）：从 offset 0 起按 JSON 状态机逐站扫描，每站完整解析前 2 个页面对象、
  其余字节状态机跳过（不解析），收满 80 站即中止响应；分 4 批断点续跑，实际流经约 671 MB。
- 偏差：
  1. **站点取文件内前 80 个**（en 共 320 站；键序疑按域名排序，实测开头为 24.kg、aap.com.au、
     abc.net.au…），**非均匀随机**，域名字母序靠前的站被系统性高估；
  2. 每站取文件内前 2 页，页内顺序未知；
  3. 未重新抓取原站，**零网络抓取失败率**（HTML 为数据集快照，采集于 2023–2024，见日期分布）。
- 口径差异（重要）：论文（arXiv:2502.02167）评测用 en 子集是 **10 站 / 500 页、5-fold 按站划分**；
  本样本是扩展版全集（320 站）中的前 80 站 × 2 页。**页面总体不同，只能数量级对照，不宜精确比对。**

## 二、gold 映射（map_ispras.py）

ISPRAS 标注为节点级 `xpath+text+label` 三元组（label ∈ title/publication_date/text/author/tag/category），
聚合为本项目字段级 gold：

| ISPRAS | 本项目字段 | 规则 |
|---|---|---|
| title 节点（按标注序） | title | 多节点 " " 连接（4 页，记 changelog） |
| author 节点 | authors 列表 | 有序去重；59/160 页（37%）有标注，其余 null |
| publication_date | publish_time / update_time | 文本以 `Updated` 开头或含 `Updated:` → update_time（8 页）；其余首个节点 → publish_time；dateutil fuzzy 解析，未知分量 XX 占位、缺年份 XXXX（5 页）；`GMT+n`/命名时区（EAT/BJT/DILI 等）尽力转 utc_offset；整段噪声正则兜底（2 页）；不可解析 6 页 → null（记 changelog） |
| text 节点（按标注序） | content_text | "\n" 连接 |
| tag / category | —（我方 field_spec 无此字段） | 仅落 provenance，不评分 |
| xpath | provenance | 每字段保留原 xpath 列表 |

gold 统计：160 页全部有 title 与 content；publish 142 页、update 8 页、authors 59 页。
changelog 39 条：`external/logs/map_changelog.json`（date_unparseable 6、date_ambiguous_numeric 8、
date_as_update 8、date_multi 6、date_no_year 5、title_multi 4、date_regex_fallback 2）。

## 三、三口径指标定义对齐

| 字段 | v1（我方旧口径 score.py） | v2（我方冻结口径 score_v2.py） | B 组（论文口径 score_zyte.py，§VII-A Zyte 方法论） |
|---|---|---|---|
| title | NFKC+去空白+小写精确匹配 0/1 | 同左（另出 3-gram sim 诊断） | 词 4-gram 袋 F1 |
| authors | 集合 F1（剥角色括号） | 集合 F1（另剥"记者/By"前缀） | 集合 F1，仅 lower+strip |
| date | 天粒度等值；**任一端缺失该页跳过** | 按 gold 精度逐分量比较；gold 有值 pred 缺失计 0；gold 无 pred 有计 false_fill=0 | 解析后比较，缺失计 0 不跳过；gold 缺失不进分母（不罚 false_fill）；本实现另出天粒度敏感性变体 |
| content | 字符 LCS（matching_blocks）F1 | 字符 3-gram 多重集 F1 | 词 4-gram 袋 F1 |
| 失败页 | — | 崩溃/缺页四字段计 0 入分母 | 缺失即 0 |

论文原文：title/text "bags of 4-grams"，authors/tags 集合 lower+strip，date 用 dateparser 解析归一化后比较
（**未指明比较粒度**——故 B 组同时给出分量级与天粒度两个 date 数）。

## 四、结果总表（160 页 / 80 站；崩溃 0 页；误拒识 16 页）

| 字段 | v1 | v2 | B 组（论文口径） |
|---|---|---|---|
| title | 0.638 | 0.638（sim 0.793） | **0.779** |
| authors | 0.249 | 0.268 | **0.397**（n=59） |
| publish_time | 0.853（n=68，缺失跳过） | 0.292（n=154） | 0.313（n=144） |
| update_time | 1.000（n=1） | 0.017 | 0.125（n=8） |
| date 合一（publish∪update，论文单 Date 属性对照） | — | — | 分量级 0.322 / 天粒度 0.421（n=152） |
| content | 0.759 | 0.761 | **0.745** |
| 拒识 | —（ISPRAS 无负例） | — | — |

v2 诊断：num_f1 0.734、lcs_f1 0.843、dup_ratio 0.501、para_ratio 0.648；
publish_time 时区三态 match 4 / missing 6 / mismatch 2 / gold_absent 132。

## 五、与论文已发表数字的数量级对照（B 组口径）

论文 Table V（en 子集 10 站 500 页，5-fold）：

| 方法 | Title | Date | Text | Author |
|---|---|---|---|---|
| Trafilatura 1.11.0 | 1.00 | 0.49 | 0.86 | 0.53 |
| Newspaper 0.2.8 | 0.94 | 0.42 | 0.89 | 0.36 |
| News-Please 1.6.10 | 0.95 | 0.50 | 0.89 | 0.36 |
| DOM-LM（多语微调） | 0.85 | 0.64 | 0.83 | 0.00 |
| **baseline_v4（本实验）** | **0.78** | **0.32 / 0.42（天粒度）** | **0.74** | **0.40** |

结论（数量级判断）：

- **Text 0.74**：落在论文方法区间（0.66–0.89）内偏低段，与 XLM-RoBERTa（0.74）同档，距头部库（0.86–0.89）约 0.1——同一量级。
- **Title 0.78**：低于三个开源库（0.94–1.00），接近 DOM-LM（0.85）——同一量级偏弱；主因是后缀剥离规则按中文站先验训练，英文站后缀形态覆盖不足（见 badcase）。
- **Date 0.32–0.42**：与开源库（0.42–0.50）同量级，低于 DOM-LM（0.64）。
- **Author 0.40**：高于 Newspaper/News-Please（0.36），低于 Trafilatura（0.53）——同量级。
- **总体：四字段均落在论文已发表方法的同一数量级内，无越界异常**；但样本来源不同（80 站 × 2 页 vs 10 站 × 500 页）、日期比较粒度论文未定义、"Updated" 标签归属处理不同，**不宜做精确比对**。

## 六、badcase 归因

1. **误拒识 16/160（10%）**：extract.py 的 list_page 启发式（长链接数≥30 且文本占比≥0.55）在英文站上
   误伤（alquds.com、aps.dz、newzimbabwe.com 等均为 gold 文章页），这 16 页四字段全 0，
   是 v2/B 组所有字段的共同失分底噪（title 16 例 miss 全部来源于此）。
2. **title 失分（42 页精确匹配失败）**：22 例为**包含关系**（pred 多带站点后缀或 gold 含副标题拼接），
   20 例完全错位；title_sim 0.793 ≫ exact 0.638 佐证"差后缀而非找错节点"。后缀剥离规则的站点模式
   库是中文站先验，英文站分隔符形态（" | SiteName"、" - SiteName" 带 kicker 前置等）覆盖不足。
3. **authors false_fill 35 页（v2 false_fill_rate 0.35）**：gold 未标作者而 pred 从 meta/署名扫描填了
   （如 'RG Cruz'、'The Federal Council'、'ABS-CBN News'）。**ISPRAS 作者标注覆盖率仅 37%，
   "未标注 ≠ 无作者"**——这 35 例中相当比例是 gold 覆盖不全而非提取错误，属数据集固有局限，
   authors 各口径分数均因此系统性偏低。
4. **publish_time v2 0.292 vs v1 0.853 的落差分解**：miss 75 页中 16 页来自误拒识；ok-但不等 24 页中
   **13 页天粒度其实相等**（只差时分秒，如 abs-cbn/bworldonline/citizen_digital 的 pred 取 meta UTC、
   gold 标页面本地显示时间，存在整 8 小时/时区差）——即时区归一化差异而非日期找错；
   另有真错误（bbc 一例 gold 为 "13 February" 缺年 XXXX 占位，pred 取到 2011 旧日期，属 gold 标注不完整）。
5. **update_time v2 0.017 是口径产物**：gold 仅 8 页标 update，而 extract.py 大量从 meta
   `article:modified_time` 填 update → v2 按 false_fill 计 0。B 组口径不罚 false_fill（gold 缺失不进分母），
   故不显现。两种处理都已如实分列。
6. **content 最差页**（chathamhouse.org 0.04/0.06、oup.com 0.09、crisisgroup.org 0.10 等 13 页 <0.3）：
   多为正文容器识别失败退化为导航/推荐文本；num_f1 0.734 < content 0.761，关键数字丢失仍是正文失分成分之一；
   dup_ratio 0.501 为英文长文本 3-gram 天然重复，仅作跨版本相对比较。

## 七、声明

- 论文数字为完整 en 集（10 站 500 页）5-fold 交叉验证；本实验为扩展版数据集前 80 站小样本，
  站点总体不同、抽样有字母序偏差，**数量级可比、不宜精确比对**。
- 本样本 authors/tag 标注覆盖率低、部分 date 标注为 "Updated:" 或含段落噪声（已按 changelog 如实处理），
  数据集固有局限会压低 authors 与 date 的绝对分数。
- 全部分数由 `eval/score.py`、`eval/score_v2.py`、`external/score_zyte.py` 真实运行产生；
  extract.py 未做任何修改；崩溃页 0（若出现将按 v2 默认计 0 不跳过）。

## 八、产物清单

| 路径 | 内容 |
|---|---|
| `external/sample_ispras.py` | 流式抽样器（WebDAV，断点续跑） |
| `external/ispras_sample_en.jsonl` | 原始样本 160 页（含内联 html 与节点级标注） |
| `external/html/` | 160 个页面 HTML 落盘 |
| `external/map_ispras.py` | gold 映射器 |
| `external/ispras_gold_en.json` | 字段级 gold（本项目格式） |
| `external/ispras_index.jsonl` | extract.py 输入索引 |
| `external/ispras_pred.jsonl` | baseline v4 预测（160 条） |
| `external/ispras_scores_v1.json` / `external/ispras_scores_v2.json` | 我方双口径分数 |
| `external/score_zyte.py` / `external/ispras_scores_zyte.json` | B 组论文口径 scorer 与分数 |
| `external/logs/` | sample_run1–3.log、sample_test.log、map_changelog.json、extract_ispras.log、score_v1/v2/zyte.log、badcase_analysis.log |
