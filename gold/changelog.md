# Gold 构建变更日志（changelog）

编号、页面、问题、处理、依据。所有处理遵循同一铁律：**gold 只记录 HTML 中真实存在的信息**；trafilatura 输出仅作起草对照，不作 gold 来源；全程不联网。

## 工具层修复（影响全组）

| # | 问题 | 处理 | 依据 |
|---|------|------|------|
| C01 | lxml 注释节点文本泄漏进正文（chinanews 页正文混入"画中画广告 end"等注释文字） | `goldlib.container_text_with_img` 跳过非 str tag 的节点（Comment/ProcessingInstruction） | field_spec v1.2：gold 只含页面可见信息 |
| C02 | lxml `iter()` 前序遍历导致叶子块 tail 顺序错乱，python_docs 内联 code 文本错位 | 改为递归 `rec()` 按文档序拼接 text/tail | 同上 |
| C03 | figure 无 img 时整块被跳过（github_blog__03 的 wp-block-table 表格丢失） | figure 无 img 回退为递归处理其子树 | 同上 |

## fixed 组

| # | 页面 | 问题 | 处理 | 依据 |
|---|------|------|------|------|
| C04 | news_cn 多篇 | 多人摄影署名"丁增尼达 毕晓洋"（空格分隔）初版正则只抓第一人 | 正则放宽为 `[、\s]` 分隔多人 | field_spec：摄影入 authors 带角色后缀 |
| C05 | news_cn 多篇 | 责任编辑在 `span.editor` 而非 p 内，初版漏入 authors | 补 span.editor 扫描 | field_spec：责任编辑入 authors |
| C06 | news_cn 多篇 | 尾部"文字记者：X／海报设计：X"初版漏 | 补署名行扫描并入 authors（带角色后缀） | 同上 |
| C07 | chinadaily 全 10 篇 | byline "By X in 地点" 采访地混入作者名 | 剥离 " in 地点" 后缀；多人大小写混合名归一 | field_spec：authors 只记人名/机构名 |
| C08 | chinadaily 全 10 篇 | 机构署名 Xinhua 未入 authors | 机构署名入 authors | field_spec：authors 含机构 |
| C09 | chinadaily__06 | 无 byline，仅 "Xinhua \| Updated: ..." | authors 取 Xinhua；仅 Updated 时间→update_time，publish_time=null | field_spec：只见更新时间不补发布 |
| C10 | chinadaily 多篇 | figcaption 为纯 credit（"JIN DING/CHINA DAILY"式） | credit 剥出→摄影入 authors，caption 只留说明文字 | field_spec 摄影规则 |
| C11 | gov_cn__08/09/10 | 公文页无 h1，标题在 div.share-title；且公文自体标题行保留在内容容器内 | title 取 div.share-title；容器内标题行视为公文自体标题保留 | annotation_guide：公文自体结构 |
| C12 | gov_cn 全组 | meta firstpublishedtime/lastpublishedtime 格式 `2026-07-10-20:28:00` | 日期-时间间 `-` 换空格后按规范格式化 | field_spec 时间格式 |

## generic 组

| # | 页面 | 问题 | 处理 | 依据 |
|---|------|------|------|------|
| C13 | sina 全 6 篇 | #artibody 混入"金麒麟"推广 blockquote 与登录 APP 引导 p | 列入剔除清单 | annotation_guide：推广/导航不入正文 |
| C14 | chinanews 全 6 篇 | `display:none` 的 BaiduSpider 块内有"作者：胡寒笑"，与可见"【编辑：X】"及页面来源矛盾 | 弃用隐藏块，authors 取可见尾部【编辑：X】；隐藏块事实登记于此 | 铁律：gold 只含页面真实可见信息 |
| C15 | people 全 6 篇 | meta author 为数字 ID | 不采用；责编取可见"（责编：X、Y）"；byline 用 `//b[@id="newstime"]` 父 div 文本（`contains(text(),"来源")` xpath 在该页返回 0，弃用） | field_spec：authors 记可归属名 |
| C16 | github_blog 全 4 篇 | 容器混入相关推荐、CTA、Tags、"Written by"、reading list | 剔除清单：post-content-cta / content-table-wrap / my-6 Tags / Written by / reading list h2+ul（先删 ul 再删 h2，否则 following-sibling 失效） | annotation_guide：boilerplate 不入正文 |
| C17 | github_blog__01 | JSON-LD 与 meta 时间偏移表示等价（-08:00 vs +00:00 Z） | 取 meta（+00:00 规范化表示） | field_spec：等价表示取规范化源 |
| C18 | python_docs__02 | The Python Standard Library 目录页 | 判 list_page 拒识（页面功能为库索引） | annotation_guide list_page 定义 |
| C19 | caixin__01–05 | HTML 仅含开头 1–2 段，正文被收费框截断 | 5 篇全部判付费墙拒识，四字段全空 + expect_refusal；page_condition 仍记 ok（抓取成功） | annotation_guide 付费墙条款 |

## test 组

| # | 页面 | 问题 | 处理 | 依据 |
|---|------|------|------|------|
| C20 | stdaily 全 3 篇 | 原容器 div.article 混入 breadcrumb/articleHead/相关稿件 | 容器改 `div.pages_content`，剔除 div.related（"相关稿件："） | 容器边界复核 |
| C21 | stdaily__02/03 | 尾部"文字记者：张代蕾、朱瑞卿""海报设计：马发展""文案：郭洁宇 张海磊""设计：潘红宇"初版漏抓 | 补四类署名 pattern（lookahead 边界防止"朱瑞卿海报设计"粘连误吞），入 authors 带角色后缀 | field_spec authors 规则 |
| C22 | mdn 全 3 篇 | 容器 main 混入 layout__header/right-sidebar/article-footer（"Help improve MDN"及 last modified 行） | 容器改 `main//div.layout__body`，剔除 section.article-footer；last modified 时间仍作 update_time 证据（time/@datetime，Z 显式） | 容器边界复核 |
| C23 | mslearn 全 3 篇 | 页内两个 `div.content`（标题壳/正文）；page-metadata、反馈、"Ask Learn" 等杂件 | 容器取文本最长的 div.content；杂件本就在容器外 | 容器边界复核 |
| C24 | mslearn 全 3 篇 | meta ms.date 序列化为 `T00:00:00Z`（日期占位，非真实零时） | update_time 取页脚可见 "Last updated on YYYY-MM-DD"，值记 `YYYY-MM-DD XX:XX:XX`，utc_offset=null | field_spec：未知分量 XX 占位，偏移可知才记 |
| C25 | mslearn__03 | meta ms.date=2026-03-23 与可见页脚 Last updated 2026-06-03 冲突 | 取可见页脚值 2026-06-03，冲突登记于此并在 provenance 注明 | 铁律：以页面可见信息为准 |
| C26 | devto__01 | JSON-LD datePublished=2026-09-09T14:32:00Z 晚于 dateModified=2026-09-08T22:24:29Z（update<publish 倒挂） | 源数据原样保留，validate_gold 白名单降级为警告，登记于此 | 铁律：不篡改源数据 |
| C27 | csdn__01/02 | JSON-LD Article.author 缺失 | 用显示账号名"CSDN官方博客"（机构号）；03–05 用 JSON-LD author.name；title 用 h1（og:title 带 SEO 后缀） | field_spec authors/title 规则 |
| C28 | en_people 全 4 篇 | meta author 为 F_ 开头内部 ID | 不采用；publisher 取 meta[name=source] 剥 "source：" 前缀；时间 "16:42, September 09, 2026" 月名消歧→分钟级 XX 秒、+08:00 inferred_site_locale | field_spec 时间/作者规则 |
| C29 | gmw__01–04、netease__01–03 | 正文为"图片+图说"序列（新华社图片稿/海报稿） | 判 photo_set 拒识 | annotation_guide photo_set 定义 |
| C30 | mdn__01 | "This page lists all the HTML elements" 全元素分类索引 | 判 list_page 拒识 | annotation_guide list_page 定义 |
