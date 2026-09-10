# Badcase 分析（dev / extract v4 终态）

- 数据基础：`results/v4_scores_v2.json` 逐页明细 + `results/v4_pred_dev.jsonl` provenance，探查脚本输出 `results/run_logs/badcase_probe.txt`。
- 范围纪律：仅基于 dev（fixed 30 + generic 55）逐页分析；test 只跑过一次聚合分，不做逐页分析。
- v4 dev 总盘：title 0.886 / authors 0.760 / content 0.929 / publish 0.892 / update 1.0 / rejection 1.0。

---

## 1. title（9 页失分 / 84 参评）

| 错误类型 | 页面 | 证据 | 归因 |
|---|---|---|---|
| 后缀型（sim 0.62–0.86） | people__01–06（6 页） | pred 尾部多 `--经济·科技--人民网`，sim 均 >0.5 | **双连字符 `--` 分隔 + 栏目段「经济·科技」未被后缀剥离覆盖**（trafilatura 取 `<title>`，剥离器不认识 `--` 与栏目段） |
| 语义分歧型（sim 0.00） | cnblogs__03/04/07（3 页） | gold title = 博客名（「自由、创新、研究、探索」「茴香饺子、」），pred = JSON-LD headline（文章题） | 博客首页型页面：gold 按"页面 h1=博客名"标注，提取器按文章题抽取。**gold 边界解释分歧，非提取错误**；另见 cnblogs__03 pred 残留 `&quot;`（JSON-LD 双重转义，unescape 只过一遍） |

## 2. authors（17 页失分）

| 错误类型 | 页面 | 归因 |
|---|---|---|
| 媒体/栏目名误作作者（false_fill 或拉低 P） | sina__02/03/04/06（`澎湃新闻`/`市场资讯`，meta article:author）、ifeng__01/03/04/05（`观察者网`/`凤凰网综合`/`央视新闻`，json-ld author）、chinadaily__07（`贺霞婷`，meta author 为后台录入编辑） | **媒体名/栏目名/录入名不是作者**：meta/JSON-LD author 字段在门户转载页系统性污染；现有垃圾过滤表太小 |
| 正文首行署名漏扫（miss） | sohu__01/03/04/06（4 页，gold「极目新闻记者 王灿」「文｜张彦宗」「责任编辑：钟庆辉」） | **实现 bug**：`scan_signature_authors(soup, None)` 第二参数传了 None，正文首行扫描从未生效；署名在 article 正文内、不在 byline 类元素里 |
| 尾部署名变体漏抽 | news_cn__09（gold 含 魏玉坤/谢希瑶/申铖/王雨萧 4 记者，pred 只有责任编辑） | 站点规则尾部模式只有 `^文字记者：`，未覆盖该页变体 |
| 多人漏一 | chinanews__04（漏 阚枫/高萌）、chinanews__05（漏 薛伟（摄影））、sina__05（漏 周松清/韩迅） | 署名行多人/多角色（作者+摄影混合）扫描覆盖不足 |
| 机构号作者漏抽 | segmentfault__04（gold `OceanBase技术站`，json-ld author 存在但被垃圾过滤误杀——含大写混排被 `网$` 规则拒） | 过滤规则误伤机构号 |
| gold 边界分歧 | cnblogs__07（gold `茴香饺子、` 带顿号尾，pred `茴香饺子`） | 用户名含尾标点，清洗规则不一致 |

## 3. publish_time（7 页失分 / 65 有 gold 时间）

- **cnblogs__01–07 false_fill ×7（全部）**：pred 取 `dom:#post-date`（页面可见发布时间，如 `2026-09-07 10:41`），gold 全部 None 且 provenance 未记录理由。**提取器按"HTML 中存在的信息"填入，gold 未采纳——边界解释分歧**。按 §1.3 不得为分数回改 gold，此处如实登记分歧；若 gold 后续补录理由确认该字段应采，此 7 页立即转为正确。
- 时区三态：match 52 / missing 6 / mismatch 0（missing 为 cnblogs 7 页中 6 页 false_fill 不计 + 少量无 offset 页）。
- time_confusion=10：全部来自 gov_cn（gold publish 与 update 同值，pred 正确填 publish 时必然命中"等于 gold update"的混淆检测）——**诊断指标误报，非真实混淆**，已在归因时剔除。

## 4. content（13 页 <0.85）

| 站点 | 页面 | 指标特征 | 归因 |
|---|---|---|---|
| chinanews | 01/02/03/05/06（5 页，f1 0.35–0.77） | **num_f1 0.10–0.16 极低、dup 0.34–0.45 高、para_ratio 0.05–0.30** | 正文 JS 薄页：gold 只取 `div.left_zw` 可见残段（82–497 字），trafilatura 抓入相关推荐/导读块（401–816 字）——**通用路由正文边界问题**：薄正文页上 traf 产出反而更脏 |
| people | 02–06（5 页，f1 0.68–0.85） | num_f1 0.35–0.59 偏低、para_ratio 0.10–0.20 | traf 把多段并段（para 低）且漏数字段（num 低），正文容器 `div.rm_txt_con` 未被 traf 精确锁定 |
| sina__02 / ifeng__01/04 | f1 0.70–0.84 | num 0.46–0.88 | 同上路边界 + 图说/附注混入 |

## 5. update_time / 拒识

- update_time dev 满分（1.0，27 页有 gold 值）；时区 match 27/27。
- 拒识：dev 唯一应拒识页 python_docs__02 正确拒识（rejection 1.0）；caixin×5 付费墙页正确留空（correct_empty）。
- negative 4 页（不在 gold 内，单独核对）：3/4 正确拒识；**sina_list__01 未拒识**（页面仅 261 字、长链接占比 0.05，两条信号都够不到阈值）——见 `results/negative_check.json`。

---

## 迭代候选清单（按证据强度排序）

1. **媒体/栏目名 ≠ 作者过滤表扩充**（authors 10+ 页，证据最强）：已知媒体名/站点名/「XX新闻」「XX资讯」「综合」模式拒用作 author；同步修 segmentfault 机构号误杀。
2. **署名扫描 content 首行 bug 修复**（sohu×4 miss + sina/chinanews 多人漏）：`scan_signature_authors` 传入真实 content_text（需在正文装配后调用），并扩展多人多角色模式。
3. **chinanews/people 类薄正文页的通用边界策略**（content 6+5 页、num_f1 系统偏低）：traf 产出 dup_ratio 高且页面存在明显 `left_zw`/`rm_txt_con` 类主容器时，改走 DOM 容器装配——这是"通用路由正文边界"问题，也是 num_f1 低分主因。
4. **标题后缀剥离补 `--` 双连字符与栏目段**（people×6，sim 0.62–0.86 全为后缀型，修复便宜收益确定）。
5. **news_cn 尾部记者署名变体**（news_cn__09 等，规则库内补模式）。
6. **JSON-LD 双重转义**（`&amp;quot;` → 需二次 unescape，cnblogs__03 等）。
7. **sina_list__01 类超薄列表页信号**（负例 1/4 漏拒）：正文量 <300 且无可识别文章容器时拒识。
8. **暂不修（gold 边界分歧，需 gold 侧决策）**：cnblogs 博客首页型 title（3 页）、cnblogs `#post-date` 时间（7 页）、cnblogs__07 用户名尾标点。

## 门控评估（baseline_selection.md §4 的门）

- 渲染兜底门：`empty_shell + needs_render` dev 占比 0%（< 5%）→ **不触发**。
- 模型路线门：v4 后四字段 miss 率（authors miss 6/66≈9%、content miss 0）均 < 30% → **不触发**。
