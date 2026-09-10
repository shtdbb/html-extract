# Baseline 选型报告（baseline_selection.md）

- 课题：离线库 HTML 结构化提取（四字段：title / authors / publish_time·update_time / content_text+content_md）
- 依据：官方文档核查（标注【官方声明】）+ dev 集 5 样本冒烟实测（标注【实测】，原始数据 `results/dev5_validation.json`，复现命令 `venv/bin/python scripts/dev5_validate.py`）
- 冒烟样本：news_cn__01 / chinadaily__01 / sina__01 / gov_cn__01 / cnblogs__01（覆盖 fixed 三站 + generic 两站）

---

## 1. 五条候选路线比较

| 路线 | 做法 | 优点 | 风险/成本 | 适用性判断 |
|---|---|---|---|---|
| A. DOM+规则 | bs4/lxml 解析 + 站点级选择器规则 | 精度最高、可解释、逐字段 provenance 天然可得 | 站点覆盖面=规则数；generic 长尾站无规则可用 | fixed 三站主路线；不可单独覆盖全量 |
| B. 成熟提取库 | trafilatura / readability-lxml | 零规则成本覆盖长尾；正文抽取久经验证 | 字段粒度受限（authors/time 弱）；编码/后缀等边角需自行补 | generic 兜底主路线 |
| C. 模型生成字段 | LLM 直接读 HTML 生成四字段 | 理论上长尾适应强 | 幻觉风险违反"HTML 即边界"铁律；离线复现性、成本、可审计性差 | 不选为 baseline；仅作证据门控后的备选 |
| D. 模型选原文元素 | LLM 只负责"指出正/标题是哪个 DOM 节点"，值仍从 DOM 取 | 无幻觉（值可回溯），可补规则泛化 | 仍依赖模型可用性与稳定性；工程链路最长 | 同 C，门控备选 |
| E. 混合流程 | 元数据层(JSON-LD/OG)→站点规则→提取库兜底，逐字段回退链 | 每层各有最擅长场景；provenance 分层清晰；风险逐层隔离 | 层间冲突仲裁需规则 | **选为 baseline 架构** |

## 2. 官方文档核查（【官方声明】）

### trafilatura 2.2.0
- `extract()` 默认输出纯文本、**不含元数据**；要拿 title/author/date 必须 `with_metadata=True`（1.11 起的行为），或直接用 `bare_extraction()` 返回 `Document` 对象（`.title/.author/.date/.text` 等属性，`.as_dict()` 转字典）。【官方声明】 [trafilatura 文档 usage-python](https://trafilatura.readthedocs.io/en/latest/usage-python.html "citation")
- 抽取是级联：自有规则提取器先行，结果过短时 readability 与 jusText 作 fallback；`fast=True` 跳过 fallback 约提速一倍。【官方声明】 同上
- `favor_precision` / `favor_recall` 预设调节噪声与召回；`include_comments`/`include_tables` 默认开启；`include_images=True` 可保留 img 的 alt/src/title。【官方声明】 同上
- 输入可以是 str / bytes / lxml 树 / 响应对象。【官方声明】 同上 ——**但实测见 §3：bytes 输入在 GBK 页上产生乱码，编码自检不可靠，必须调用方先解码**。
- 无"作者列表"概念：`.author` 是单个拼接字符串，多作者/角色署名需自解析。【官方声明+实测】

### readability-lxml 0.9
- 定位：`Document(html)` → `.title()`、`.short_title()`、`.summary()`；**summary 返回清洗后的 HTML 片段，不是纯文本**，需再转文本。【官方声明】 [python-readability README](https://github.com/buriy/python-readability "citation")
- 0.9 起修复 bytes 输入与编码探测；0.8.2 起有 `.author()`；0.8.4 起改进 CJK 支持；0.9 修复 CJK 标题长度处理。【官方声明】 同上（Change Log）
- 官方自报基准：181 页可复现对照中 F1 0.975（正文抽取口径，非本课题四字段口径）。【官方声明】 同上
- 无发布时间抽取能力（API 无 date 字段）。【官方声明（API 清单）+实测】

### BeautifulSoup 4.15 + lxml 6.1
- bs4 提供解析树导航/搜索（`find/find_all/select` CSS 选择器），官方推荐 lxml 解析器（"Very fast"）。【官方声明】 [bs4 文档](https://www.crummy.com/software/BeautifulSoup/bs4/doc/ "citation")
- bs4 传 bytes 时按 UTF-8 假定处理（字节串过滤场景），文档要求尽量传 Unicode 串——与"调用方负责解码"的策略一致。【官方声明】 同上
- bs4/lxml 本身**不做**正文/boilerplate 判别——纯规则路线需自建密度/容器启发式。【官方声明（能力边界）】

## 3. dev5 冒烟实测（【实测】）

复现：`venv/bin/python scripts/dev5_validate.py`；原始输出 `results/dev5_validation.json`。耗时为单页 3 次中位（本机）。

| 页 | trafilatura 耗时 | traf title 命中 | traf 正文长度 | readability 耗时 | read 正文长度 | 备注 |
|---|---|---|---|---|---|---|
| news_cn__01 | 4.5 ms | ✔ 精确命中 gold | 3917 | 5.4 ms | 3987 | 两库均可用 |
| chinadaily__01 | 6.6 ms | ✔（带站点后缀需剥离） | 5845 | 14.7 ms | 5976 | 英文页正常 |
| sina__01 | 14.1 ms | 带 `_新浪财经_新浪网` 后缀 | 885 | 12.1 ms | 690 | 正文偏短（页面含大量 script 内嵌内容，gold 边界内正文本就短） |
| gov_cn__01 | 4.9 ms | ✔（带后缀） | **62** | 3.4 ms | **19** | **两库正文抽取均失败** → 站点规则层必要性的直接证据 |
| cnblogs__01 | 3.7 ms | ✔ | 983 | 6.3 ms | 1006 | 正常 |

四字段映射能力【实测】：

| 字段 | trafilatura | readability-lxml |
|---|---|---|
| title | ✔ `.title`（常带站点后缀，需自剥离） | ✔ `.title()`/`.short_title()`（同样带后缀） |
| authors | △ `.author` 单字符串，多人/角色需自解析；常含垃圾署名 | ✖ `.author()` 多数页返回 `[no-author]` |
| publish_time | △ `.date` 只到日粒度（htmldate），时分秒/多时间字段不区分 | ✖ 无此能力 |
| content_text | ✔ 段落纯文本；图片占位/表格 GFM 需自做 | △ summary() 是 HTML，需二次转文本 |

编码行为【实测】：
- dev 集 sina 6 页声明编码全为 utf-8，**无真实 GBK 页**（如实记录）；故构造合成样本（sina__01 转 GB18030 字节 + meta 改 `charset=gb2312`）验证"传 bytes 让库自检编码"：
  - **trafilatura 传 bytes → 标题/正文全部乱码**（mojibake），未正确自检 GBK；
  - **readability-lxml 传 bytes → 正常**（与 0.9 changelog"修复 bytes 输入与编码探测"一致）；
  - chardet 对该字节串报 GB2312（confidence 0.99）。
- 结论：**管线必须自己解码（声明编码优先、chardet 兜底）后以 str 喂库**；不能把编码责任下放给 trafilatura。

## 4. 结论

**Baseline（混合流程 E）**：解码（声明优先，chardet 兜底，declared/detected/used 三分留痕）→ page_condition 判定 → 拒识判定 → 三层路由：

1. **元数据层**：JSON-LD(NewsArticle) + OG/meta → 四字段候选；
2. **站点规则层**：fixed 三站（news_cn / chinadaily / gov_cn）选择器规则库（从 gold provenance 整理，`site_rules.py`）；
3. **通用兜底层**：trafilatura（`bare_extraction(with_metadata=True)`）→ 失败则 DOM 文本密度容器兜底。

**对照臂**：readability-lxml（title + summary→text；authors/time 无能力，如实记缺）。

**证据门控（模型/渲染不进 baseline，由证据触发）**：
- 渲染兜底：dev 全量中 `empty_shell + needs_render` 占比 > 5% 才触发渲染管线回补；当前 117 页 `page_condition` 全为 ok【实测：dataset_index 统计】，门未触发；
- 模型路线：迭代至 v4 后若字段 miss 率仍 > 30% 且失败页无 JSON-LD 可走，才启动路线 C/D 评估。

**迭代计划（真实留痕）**：v1=trafilatura only → v2=+元数据层 → v3=+站点规则+拒识 → v4=+后缀剥离/署名扫描/时间补全。每版 dev 全量双口径（score.py v1 / score_v2.py）跑分，回归即回滚并记录。
