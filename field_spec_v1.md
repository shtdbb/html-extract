# 字段语义规范 v1.2（冻结版）

- **文档性质**：离线库 HTML 结构化提取课题的字段定义唯一依据。标注、提取器实现、评分器实现三方都以此为准。
- **版本**：v1.2（冻结）。相对 v1.0 的演进过程见决策日志，本文件只描述最终状态。
- **边界原则**：一切字段值以**输入 HTML 中存在的信息**为边界（§3）。

---

## §1 总则

1. 输入：本地静态 HTML 文件（含其字节原始形态），不做 JS 渲染、不联网。
2. 输出：**双形态**——
   - **机器可读**：JSONL（每页一行，字段即本规范定义），供自动化管线与评分器消费；
   - **人类可读**：Markdown（每页一篇，字段渲染为标题、正文、图位、署名区），供人工抽检。
3. 抽不到信息的字段一律置 `null` 并计入过程日志，**禁止猜测填值**。
4. 连续多个 `\n` 在 `content_text` / `content_md` 中合并为 1~2 个（由解析策略在装配阶段统一执行）。

---

## §2 字段定义

### 2.1 `title`（字符串 | null）

文章/页面的真实标题。优先级证据链：JSON-LD `headline` → `og:title` / meta → `<h1>` → `<title>` 标签。**站点后缀、栏目名必须剥离**（如 `_财经频道_新浪网`、`| 运动周刊`）。h1 不可盲信（存在 h1 是博主名、频道名的真实案例）。

### 2.2 `content_text`（字符串 | null）

**无损纯文本底线**：正文主体的纯文本，保留段落换行（多个连续 `\n` 合并为 1~2 个），剥离导航、侧栏、页脚、相关推荐、版权声明等 boilerplate。图片以规约占位符标记（§2.5）。任何情况下本字段不得因下游格式转换而丢字——它是 content 类字段的裁判基准。

### 2.3 `content_md`（字符串 | null）+ `conversion_flags`（字符串列表）

**增强视图**：与 content_text 同源，但将正文内的特殊结构转换为 GFM（GitHub Flavored Markdown）：

| 结构 | 转换目标 |
|---|---|
| 表格 | GFM 管道表格 |
| 列表（有序/无序） | GFM 列表 |
| 公式块 | 代码围栏或 `$...$` 记号包裹的源码 |
| 代码块 | 带语言标注的代码围栏 |

**有损必留痕**：任何无法无损转换的情形（合并单元格的表格被拆平、MathML 转纯文本公式、脚注丢失锚点等）必须在同记录的 `conversion_flags` 中登记对应标记（如 `table_colspan_flattened`、`mathml_degraded`、`footnote_anchor_lost`），badcase 分析按 flag 归因。转换不出来的结构回退为 content_text 中的纯文本形态。

### 2.4 `authors`（列表 | null）

- **列表**，非拼接字符串；元素可为人名或机构名（如 `新华社`）。
- **摄影者入 authors**，并标注角色（如 `张三（摄影）`）。
- **责任编辑类推入 authors**：与摄影者同规则处理；但责编署名**允许同时保留在正文中**（不做强制剔除）。
- 无署名页面本字段为 `null`；不得用站点名、栏目名、编辑名顶替作者——但按本条规则，编辑/摄影属合法入列。

### 2.5 `images`（对象列表 | null）

每个元素：

| 子字段 | 含义 |
|---|---|
| `type` | 图片类型（正文插图 / 封面 / 图集项 等） |
| `alt` / `caption` | 说明文字（图说） |
| `url` | 图片地址（按 HTML 中实际出现的值记录） |
| `width` / `height` | 尺寸（HTML 中可知才记，否则 null） |

正文中图片原位置用**规约占位符**标记（如 `[[IMG_1]]`，与 images 列表下标一一对应），保证"图片在正文中的位置"这一信息不丢失。

### 2.6 时间字段组

发布、更新等多个时间**分别维护、务必不能混淆**（如 `publish_time`、`update_time` 各自独立成字段）。每个时间字段的结构：

| 子字段 | 规定 |
|---|---|
| `value` | 格式 `YYYY-MM-DD hh:mm:ss`；**未知分量用 `XX` 占位**（如 `XXXX-09-XX XX:XX:XX`、 `2024-03-21 XX:XX:XX`）。该设计对齐 **ISO 8601-2:2019 EDTF** 的 `X` 未指定数字位——占位字符串本身即完整表达"精确到哪个粒度"，废弃单独的 precision 枚举；粗粒度摘要由程序从占位位置推导 |
| `utc_offset` | **RFC 3339** 偏移（如 `+08:00`）。**可知才记、未知为 `null`、不强转 UTC** |
| `utc_offset_source` | 当 offset 是从站点区域**推断**而非页面显式给出时，必须填 `inferred_site_locale`，与页面显式值区分 |

### 2.7 记录级辅助字段

| 字段 | 规定 |
|---|---|
| `source.encoding` | **三分**：`declared`（页面声明，如 meta charset）/ `detected`（检测器结果）/ `used`（实际用于解码的）。对齐 **WHATWG Encoding** 的概念分层。动机：「声明 GB2312 实为 GB18030」类不一致是中文站真实故障源，且检测器可能把 UTF-8 中文页误报为其他编码——故解码策略定为**声明优先、检测兜底**，三者都要留痕 |
| `page_condition` | `ok` / `empty_shell` / `anti_bot_suspected` / `truncated`。空壳页、疑似反爬页属静态解析边界外，**标记跳过、留待渲染管线回补**，不得静默产出垃圾 |
| `needs_render` | 布尔。true = 该页需 DOM 渲染管线回补；归因时"输入质量"与"提取质量"分开统计 |
| `content_structure` | `single` / `multi_article` / `photo_set` / `live_blog` / `list_page`。多文章页**只识别标记 + 抽主文章**，拆多记录留待后续迭代 |
| `provenance` | **逐字段记录来源**：每个字段值取自哪个证据（如 `json-ld:headline`、`meta:og:title`、`dom:#article`、`manual_adjudication`）。gold 与提取输出都要带 |

### 2.8 字段命名映射表（对齐行业标准）

字段命名全面对齐 **schema.org/NewsArticle + Open Graph**，下游对接零转换成本：

| 本规范 | schema.org/NewsArticle | Open Graph / meta |
|---|---|---|
| `title` | `headline` | `og:title` |
| `content_text` / `content_md` | `articleBody` | — |
| `authors` | `author`（Person/Organization，可数组） | `article:author` |
| `publish_time` | `datePublished` | `article:published_time` |
| `update_time` | `dateModified` | `article:modified_time` |
| `images[].url` | `image` | `og:image` |
| `url`（记录级） | `url` / `mainEntityOfPage` | `og:url` |
| `source`（发布媒体） | `publisher` | `og:site_name` |

注意：`publisher`/站点名是机构，**永不进 authors**（机构署名如「新华社」除外——那是 author 角色的机构形态）。

---

## §3 gold 边界原则（标准答案的铁律）

1. **HTML 即边界**：标准答案只包含输入 HTML 中存在的信息。**不能直接采用提取器输出**（防循环论证），**不能联网补齐**。
2. **付费墙页**：因付费被阻挡、HTML 中只有部分内容且无法确保有效性的，按**"无可抽取"**处理——不因为"看到了三段"就把残段当 gold。
3. **script 内嵌 JSON**：`<script>` 内嵌的 JSON 数据（如懒加载图片清单）**暂不纳入**"HTML 中存在的信息"，从严处理。
4. **逐字段 provenance**：gold 每条记录的每个字段都要登记来源证据（§2.7），使任何字段值可回溯到 HTML 中的具体节点。
5. gold 的任何修订走 changelog 登记，不得在跑分后为使分数好看而回改 gold。
