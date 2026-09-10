# 决策日志（decision_log.md）

按 eval_spec_v2.md §9 要求登记。所有条目均为本轮真实发生。
D-005 起为总报告阶段（复现批次 2026-09-10）对前序各阶段关键决策的补登，依据为 scripts/collection_log.md、gold/changelog.md、gold/README.md、external/ispras_report.md 中的真实记录；无明确日期者不伪造，标注来源批次。

## D-001 score_v2.py authors_f1 除零崩溃修复（2026-09-14 会话）

- **现象**：v1 全量跑分时 `score_v2.py` 崩溃 `ZeroDivisionError: float division by zero`（`authors_f1`，pred 与 gold 作者集合均非空但交集为空时 P=R=0，`2PR/(P+R)` 除零）。冻结版 13 场景 46 断言未覆盖"两集合不相交"场景，属实现 bug 而非口径问题。
- **修复**：`common == 0` 时直接返回 `(0.0, 0.0, 0.0)`。口径不变（不相交作者集 F1 本应为 0，与 §4 定义一致）。
- **验证**：`venv/bin/python eval/test_score_v2.py` 49/49 断言通过（含修复后新增覆盖）。
- **影响面**：v1 起全部跑分均用修复后评分器；此前无任何已产出的 v2 口径分数被覆盖（崩溃发生在首次全量跑分）。

## D-002 extract_v2 JSON-LD 实体未解码修复（同轮迭代内修复）

- **现象**：v2 首轮 title_exact 0.714→0.702 回归。逐页 diff 定位 chinadaily__01：JSON-LD `headline` 中 `&#39;` 未解码（`<script>` 内容为 CDATA，BeautifulSoup 不做实体解码），pred `"China&#39;s"` ≠ gold `"China's"`。
- **修复**：JSON-LD 的 headline/author 值统一 `html.unescape`。v2 重跑全量。
- **结果**：title_exact 恢复至 0.714（与 v1 持平；中间态曾跌至 0.702），authors_f1 0.272→0.376，publish_time 0→0.32，update_time 0→0.89。
- **教训**：元数据层的字符串值必须过实体解码；该修复同步进 v3/v4。

## D-003 extract_v3 拒识误判三连修（同轮迭代内修复）

- **现象**：v3 首轮大 regress——title 0.714→0.494、content 0.749→0.470。逐页归因：
  1. `empty_shell` 用 `body.get_text` 统计：gov.cn 模板 HTML 畸形，正文容器 #UCAP-CONTENT 落在 `<body>` 之外，body 文本仅 46 字符 → 10 个 gov 页全被误拒；
  2. `photo_set` 初版"任意 div 图多即拒"：chinadaily 正文 figure 组、cnblogs 正文配图、chinanews 导航图集挂件 div 全部误触发 → 20+ 文章页被误拒；
  3. bs4 4.15 `stripped_strings` 返回 `str` 无 `.parents` → 提取器中途崩溃（首跑 v3_scores 为截断 pred 的 0 分，作废重跑）。
- **修复**：①页面文本量改按全文档可见文本（跳过 script/style 祖先，不 decompose——JSON-LD 也在 script 里）；②photo_set 改为三条件联合：trafilatura 产出<200 字符 且 页面无≥400字符文本容器 且 存在 img≥8 且 text/img<80 的容器；③`stripped_strings` 兼容 str/NavigableString。
- **结果**：v3 第三轮 title 0.886 / authors 0.599 / content 0.928 / rejection 1.0 / publish 0.536 / update 1.0，全面超过 v2。

## D-004 extract_v4 五项修复（同轮迭代内修复，均已重跑全量验证）

1. **标题后缀剥离重写**：初版 split/rejoin 吞掉标题内「｜」「——」（chinanews__02「习言道｜一图读懂“金砖”」、segmentfault__03 各丢 1 分）。改为原串上迭代切尾：仅当末尾段经 _ | - — – 分隔且判为品牌段才切除；全角「｜」不作分隔符。修复后 title 0.848→0.886。
2. **时间字段 meta 优先于 JSON-LD**：github_blog JSON-LD datePublished 为 -08:00/-07:00 表示，meta article:published_time 为等价 +00:00 表示；gold provenance 明确「取 meta」。调整优先级后 github×4 publish 全对。
3. **ISO 分数秒**：segmentfault `datePublished=2026-06-28T03:07:37.000Z` 因 `.000` 无法解析漏提 → 正则支持 `(\.\d+)?`，segmentfault×5 publish 全对。
4. **弃用 trafilatura htmldate 兜底**：其日期猜测在 gold 不认可来源的页面制造 false_fill（python_docs×4 出分母、cnblogs×7 仍在分母——后者属 gold 边界分歧，见 badcase_analysis.md），dev 上无仅靠它得分的页面。
5. **dateModified==datePublished 抑制**：通用路由下两值相等视为 CMS 字段复制（segmentfault×5 update false_fill 修复）；fixed 规则站豁免（gov.cn gold 确有相等双时间）。
- **结果**：v4 终态 title 0.886 / authors 0.760 / content 0.929 / publish 0.892 / update 1.0 / rejection 1.0，全面 ≥ v3。

## D-005 数据采集阶段的站点处置决策（采集批次 2026-09-10，见 scripts/collection_log.md）

- **fixed 组发现方式变更**：news.cn / chinadaily.com.cn / gov.cn 栏目索引页实测均为 JS 动态加载的静态壳（chinadaily 频道页提取到 0 个文章链接；news.cn/gov.cn 只剩 2022–2023 年陈旧兜底链接）。改用「搜索引擎发现同站同模板近期文章 URL + 直取」，模板一致性由人工核对 URL 形态保证。未按计划「抓栏目页提链接」，属计划偏差，如实登记。
- **test 组 cctv 整站剔除**：抓到的 4 页全部为视频稿（静态 HTML 中无文本正文，逐页实测确认），按「需 JS 渲染/无语义内容则跳过并记录」规则整组剔除（已存的 cctv__01~04.html 删除）；中文新闻缺口由 netease（4 页）补齐。cctv 记为「视频稿无静态正文」失败站点。
- **test 组 oschina / 51cto 整站失败**：oschina 文章页全部返回 ~3.6KB SPA 空壳（可见文本 27 字符，13 次尝试全败，逐条记录）；51cto 种子页 0 文章链接且文章页对脚本请求返回 ~1KB 反爬壳。博客类缺口由 CSDN（5 页）补齐。
- **test 组 mslearn 改直取**：training/browse 索引页为 JS 壳，改用搜索发现的 3 篇静态 quickstart 文档直取。
- **negative 组两处替换**：politics.people.com.cn 与 chinanews /gn/ 对脚本 UA 返回 403，分别替换为 finance.people.com.cn 频道页与 chinanews 滚动新闻列表页；generic 组 chinanews 种子页同因改用首页 + 滚动新闻页。
- **空壳拦截记为失败而非样本**：ifeng 4 个 gentie.ifeng.com 跟贴页被空壳检测（visible_text=39）正确拦截，计入失败明细、不入数据集。
- **结果**：累计保存 117 页 = fixed 30 + generic 55 + negative 4 + test 28，与计划总量一致。

## D-006 字段规范与评测口径冻结（规范冻结阶段，日期以 v1.2/v2 文首版本号为准）

- `field_spec_v1.md` 冻结为 **v1.2**：时间未知分量用 `XX` 占位（对齐 ISO 8601-2 EDTF）、`utc_offset` 可知才记不强转 UTC、`inferred_site_locale` 区分推断时区、编码三分（declared/detected/used）、字段命名对齐 schema.org/NewsArticle + Open Graph、gold 边界铁律（HTML 即边界，禁提取器输出直接入 gold、禁联网补齐）。
- `eval_spec_v2.md` 冻结为 **v2** 并与 `score_v2.py` 绑定：逐页评分宏平均、失败不从分母消失（唯一例外 correct_empty）、title 精确匹配 + title_sim 诊断、content 字符 3-gram 多重集 F1、time 按 gold 精度逐分量比较、拒识与文章页分母互斥。§8 手算 13 场景 46 断言由 `eval/handcheck_draft.py` 实际运行通过；`eval/test_score_v2.py` 49/49 断言通过（含 D-001 修复后新增覆盖）。
- v1 口径（score.py）保留为历史对照，不再修订；三处系统性差异（content LCS→3-gram、time 天粒度+缺失跳过→按精度+失败计 0、title 小写→casefold+诊断）登记于 eval/README.md。

## D-007 gold 构建关键裁决（gold 构建会话，见 gold/changelog.md C01–C30、gold/README.md）

- **工具层三处修复（C01–C03，影响全组）**：lxml 注释节点文本泄漏进正文 → 跳过非 str tag 节点；`iter()` 前序遍历致叶子块 tail 顺序错乱 → 改递归按文档序拼接；figure 无 img 整块被跳过 → 回退递归处理子树。
- **付费墙整组拒识（C19）**：caixin__01–05 HTML 仅含开头 1–2 段、正文被收费框截断，5 篇全部判付费墙拒识（四字段全空 + expect_refusal），page_condition 仍记 ok（抓取成功）。
- **隐藏块弃用（C14）**：chinanews 全 6 篇 `display:none` 的 BaiduSpider 块内署名与可见信息矛盾，按「gold 只含页面真实可见信息」弃用隐藏块，authors 取可见尾部【编辑：X】，隐藏块事实登记 changelog。
- **源数据冲突不篡改（C25/C26）**：mslearn__03 meta ms.date 与可见页脚 Last updated 冲突 → 取可见值并登记；devto__01 JSON-LD update<publish 倒挂 → 源数据原样保留，validate_gold 白名单降级为警告（当前唯一警告）。
- **验证深度声明（gold/README.md）**：自动结构核查 100%（0 错误 1 警告）、字段级证据核对 100%（全部非空字段带 provenance），但**正文未逐字通读**——实际执行为 head/tail 摘要核对 + 字段级证据核对 + 容器剔除清单核对，不作逐字级承诺。

## D-008 ISPRAS 外部基准的抽样与映射决策（见 external/ispras_report.md；报告内标注实验日期 2025-09-11，与采集批次年份不一致，按原文如实转引，疑为笔误）

- **抽样策略**：未全量下载（en.json 2.8 GB），采用 WebDAV 流式抽样（sample_ispras.py），从 offset 0 起逐站扫描、每站取文件内前 2 页、收满 80 站即中止，分 4 批断点续跑，实际流经约 671 MB。**已知偏差**：站点取 en 320 站中文件内前 80 个（键序疑按域名排序，字母序靠前站被系统性高估），非均匀随机；HTML 为数据集快照（2023–2024 采集），零网络抓取失败率。与论文口径（10 站 500 页 5-fold）页面总体不同，**只做数量级对照、不做精确比对**。
- **gold 映射（map_ispras.py）**：节点级 xpath+text+label 三元组聚合为字段级 gold；`Updated` 开头/含 `Updated:` 的 publication_date → update_time（8 页），其余首个节点 → publish_time；dateutil fuzzy 解析 + 未知分量 XX 占位 + 缺年份 XXXX；命名时区尽力转 utc_offset；不可解析 6 页记 null。映射 changelog 39 条落盘 external/logs/map_changelog.json。
- **三口径并列**：我方 v1、我方 v2（冻结）、B 组论文口径（score_zyte.py，词 4-gram 袋 F1 / 集合 F1 / 缺失计 0 不跳过）三份分数并列保留，不以任何一口径覆盖另一口径。
- **extract.py 零修改**：外部基准全程使用 v4 冻结快照，未为英文站做任何适配调优；误拒识 16/160（list_page 启发式按中文站先验设定）如实计入失分底噪。
