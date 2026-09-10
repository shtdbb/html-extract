# 自进化迭代日志（loop/iteration_log.md）

自进化闭环：**评估 → 过程定位 → 问题发现 → 新策略制定与实现 → git 版本化 → 评估**。
每轮记录：目标问题、策略增量、git 提交、dev 全量指标（v2 冻结口径）、耗时/成本。
机器可读指标流见 `loop/metrics_history.jsonl`（run_iteration.py 自动追加）。

评测纪律（继承上一课题阶段）：
- 调优只看 dev（fixed 30 + generic 55 + negative 4）；test 28 页预留终测，仅在最终交付时跑一次聚合分；
- 评分器 score_v2.py 冻结（49 项单测）；gold 不为分数回改（边界分歧挂起登记）；
- 每轮策略改动须全量重跑 dev；回归即回滚或修复后重跑，留痕。

## 版本总览（随时更新）

| 版本 | git | 策略增量 | title | authors | publish | update | content | 拒识 | 负例 | 页/分 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v4 | fcf7965 | （上一阶段终态）规则库+元数据+traf+DOM 密度 | 0.886 | 0.760 | 0.892 | 1.000 | 0.929 | 1.000 | 3/4 | — | 基线 |
| v5 | b74d34f | +loop 埋点（策略不变） | 0.886 | 0.760 | 0.892 | 1.000 | 0.929 | 1.000 | 3/4 | 732 | 分数复现验证 |
| v6 | 34a7dca | authors 轮：媒体名过滤+署名扫描修复+多人模式+电头排除+强来源门控 | 0.886 | **0.971** | 0.892 | 1.000 | 0.929 | 1.000 | 3/4 | 732 | 零回归 |
| v7 | c90df58 | title 轮：-- 后缀链剥离+短栏目段 | **0.962** | 0.971 | 0.892 | 1.000 | 0.931 | 1.000 | 3/4 | 732 | 零回归 |
| v8 | f17f341 | content 轮：CMS 容器先验门控装配 | 0.962 | 0.971 | 0.892 | 1.000 | **0.982** | 1.000 | 3/4 | 724 | 零回归 |
| v9 | ca97da4 | 拒识轮：photo_set 结构识别+超薄列表页 | 0.962 | 0.971 | 0.892 | 1.000 | 0.982 | 1.000 | **4/4** | 698 | ISPRAS 全面≥v4 |
| v10 | 8a0bd30 | 模型兜底臂：门控触发+页内核验(Qwen2.5-7B) | 0.962 | 0.971 | 0.892 | 1.000 | 0.982 | 1.000 | 4/4 | 267* | dev 零回归；ISPRAS publish 0.292→**0.506**、authors 0.280→**0.319** |
| v11 | 804d641 | title 轮②：英文品牌后缀剥离 | 0.962 | 0.971 | 0.892 | 1.000 | 0.982 | 1.000 | 4/4 | 267* | ISPRAS title 0.637→**0.762**，零回归 |
| v12 | a7083bd | 英文垃圾署名三分过滤+欧式日期+日期两级佐证 | 0.962 | 0.971 | 0.892 | 1.000 | 0.982 | 1.000 | 4/4 | 266* | ISPRAS authors→**0.334**、publish→**0.519**，零回归 |
| v13 | cb1b29b | 正文 route-D 实验【回滚】 | =v12 | =v12 | =v12 | =v12 | =v12 | =v12 | =v12 | 265* | 负结果留档：薄≠失败（gov_ai 真短讯被误扩写） |
| v14 | 6b1bb29 | meta与h1整标题分歧h1优先(双重守卫) | 0.962 | 0.971 | 0.892 | 1.000 | 0.982 | 1.000 | 4/4 | 266* | ISPRAS title 0.762→**0.806**；模型裁决负结果后的规则替代 |
| v15 | 3d1cb5e | EN 同日时分精化(只升精度不新填) | 0.962 | 0.971 | 0.892 | 1.000 | 0.982 | 1.000 | 4/4 | 266* | ISPRAS publish 0.519→**0.544**，零回归 |
| 终测 | 3d1cb5e | test 28 页一次性聚合（--no-pages） | 0.550 | 0.529 | 0.467 | 0.273 | 0.696 | **0.125** | — | 38 | 模板迁移差距+拒识泛化缺口，见残留 badcase |

*v10 起页/分为 dev 全程（规则 ~580 页/分 + 模型兜底 10/89 页触发、模型 51 页/分）。
ISPRAS 模型臂成本：160 页约 130-310s（触发率约 40%，约 2s/触发页），模型常驻 12GB 统一内存。

## 各轮详情

### v6（authors 轮，34a7dca）
- 目标问题：authors 0.760，17 页失分——媒体名误作作者（sina/ifeng meta/json-ld 污染）、署名扫描 bug（sohu 首行扫描从未生效）、多人漏抓、机构号误杀。
- 过程定位：loop/probe_authors.py 逐页证据 dump。
- 策略增量：MEDIA_NAME_PAT 过滤表（len≥4 防误伤）；机构名 10→16；署名扫描传真实 content_text（首300/尾500窗）+多人/执笔/记者列表/行尾摄模式+图说元素扫描；电头括注排除（「电（记者X）」gold 不标）；强来源门控（json-ld/meta 不合并扫描名）；chinadaily byline 缺失 final 空；JSON-LD 双重转义；By 散文排除。
- 同轮三连修：「近日/谁也没想」跨行误抓（续接符限 [空格/制表/顿号]）、「曾玥/任军吴雨」电头误抓（半角括号兼容+门控）、「Python. For」By 散文误抓（句点拒收）。
- 结果：authors 0.760→0.971；其余指标不变；逐页零回归。

### v7（title 轮，c90df58）
- 目标问题：people×6「标题--经济·科技--人民网」后缀未剥（sim 0.62-0.86 全为后缀型）。
- 策略增量：-- 链先行剥离（rpartition 逐尾段，品牌段/短栏目段才剥）+_is_channel_segment（·间隔或频道/栏目/滚动/专题字样）。
- 安全核查：dev gold 唯一含 -- 标题 cnblogs__05 尾段不通过检查，不受影响。
- 结果：title 0.886→0.962（剩 3 页为 cnblogs gold 边界分歧挂起）；零回归。

### v8（content 轮，f17f341）
- 目标问题：chinanews×6（num_f1 0.10-0.16）、people×6、sina/ifeng 薄页——traf 在 CMS 模板上系统性拖入相关推荐/页头尾样板。
- 策略增量：CONTAINER_PRIORS（left_zw/rm_txt_con/artibody/index_text_* 全网流通 CMS 签名），门控=容器≥60字且比 traf 紧凑。
- 结果：content 0.931→0.982；chinanews 0.35-0.77→0.92-1.00；零回归。

### v9（拒识轮）
- 目标问题：test 曾暴露 photo_set 0/7 拒识缺口（dev 无此类页）、sina_list__01 超薄列表页漏拒。
- 纪律：不读 test；dev 侧构造标定集（loop/calibrate_refusal.py：A dev 85 页零误拒/B dev 壳合成图集 9 变体/C negative 4 页）。
- 策略增量：photo_set 双路径（结构主导：内容图≥8+最内层+≥50%份额+图说性；图说驱动：≥6图带图说+图说占比≥40%）+容器外实质段落守卫+超薄列表页信号（文本<400+链接密度≥0.4+p文本<150+链接≥20）。
- 同轮两修：people 装饰图误拒（内容图过滤：链接内/icon 名排除）；ISPRAS 英文页误拒 6 页（容器外守卫+bna 连续散文非图说）。
- 附带：站名词干过滤（fijivillage）、By 虚词过滤（Just For The）。
- 结果：dev 主指标不变、负例 3/4→4/4；ISPRAS 全面≥v4（authors 0.268→0.280）。
- 留档声明：president_go_kr 为真图集页，按我方规范拒识，ISPRAS 口径计为失分——任务定义差异，非错误。

### v10（模型兜底臂，8a0bd30）
- 目标问题：dev 头room≈0（残余为 gold 边界分歧挂起），模型臂价值须在 ISPRAS 验证——title 0.637/authors 0.280/publish 0.292 有真实空间。
- 策略增量：规则先行+模型兜底。门控（title 缺失或仅裸 <title> 弱来源/authors 空/publish 空，且遵守规则层 final 裁决）→ 本地 Qwen2.5-7B(Q4_K_M, ollama) 单页单次调用合并抽取 → 三重核验：①值须在页面可见文本中（规范化子串）②authors 过媒体名/站名/敬称过滤+独立署名行位置核验 ③时间须可解析（补英文月名解析器 June 2, 2024/5th March/Sept. 3 PM）。
- 同轮三连修（首跑 dev 回归定位）：final 裁决门控贯通（chinadaily×10 publish 误填——pick() 存的是理由串非 "final" 字面值，改为 final_fields 集合显式传递）；媒体名过滤（ifeng__01「观察者网」）；敬称过滤（sohu__02「朱先生」——句中断行形成伪独立署名行，位置核验失效，敬称=报道提及人物非署名，已核 dev gold 121 名零碰撞）。
- 结果：dev 全指标与 v9 逐页一致（10/89 页触发模型、零误填，模型成本 11.8s）；ISPRAS authors 0.280→0.319、publish 0.292→0.506（采纳 44 页）、48 页字段提升、逐页零回归。模型 12GB 统一内存常驻、约 2s/触发页 vs 规则 85ms/页——门控使模型只落在规则失陷页。
- 遗留：publish 采纳未得分 9 页（4 页精度不足——页面同时有日+时分而模型只摘日；4 页 www_gov_cn/qstheory false_fill——gold 口径不认可页面日期；1 页摘错日期实例）。

### v11（title 轮②，804d641）
- 目标问题：ISPRAS title 0 分 58 页中 25+ 页为「标题 - Brand | News」型英文后缀未剥（v7 只覆盖中文 -- 链与中文品牌段）。
- 策略增量：_is_brand_segment_en——站点词干（首标/整域归一化 ≥4 字符，24.kg→24kg、fm.gov.om→fmgovom）、面包屑段（>/»）、official website 字样、≤40 字符品牌词表（news/online/network/agency/events/home/english）。
- 安全核查：dev 全量逐页零差异；对抗用例「He lifted 24kg weights - record broken」（词干巧合嵌入标题本体）不误剥。
- 结果：ISPRAS title 0.637→0.762（26 页字段提升、零回归）；其余字段持平。
- 遗留：og:title ≠ gold h1 的整标题分歧（abc_net_au/alliancefr/euronews 等约 30 页）——需模型在候选标题间裁决或 h1 优先策略，属 v12 候选。

### v12（英文垃圾署名+欧式日期，a7083bd）
- 目标问题：ISPRAS authors false_fill 40 页为最大簇（meta 机构名/通用角色/社媒品牌/日期词）；publish 漏抽 20 页模型摘回但解析失败（DD.MM.YYYY 欧式）。
- 策略增量：_author_en_category 三分（社媒词永拒=分享按钮；月份词永拒=日期误抓；机构/角色词需可见独立署名行佐证——ISPRAS gold 实测口径：可见「News Team」「Citizen Reporter」照标，meta-only「Staff Reporter」不标）；_parse_model_time 补 DD.MM.YYYY；publish 页内核验；prompt 补时分要求。
- 同轮两修：staff 移出词表（dev gold「GitHub Staff」碰撞核查发现）；日期核验放宽为两级（整串解析/月日+月年跨串 grounding——bna 电头「May 26 (BNA):」无年份、归档导航「May 2024」佐证，首跑严格核验误杀正确值）。
- 重要教训：首跑聚合分净零掩盖内部对冲（9 个 false_fill 清除被 3 类误杀抵消），逐页 diff 才暴露——再次验证逐页回归检查的必要性。
- 结果：dev 逐页零差异；ISPRAS authors 0.319→0.334、publish 0.506→0.519，7 升 0 回归。

### v13（正文 route-D 实验，cb1b29b，已回滚）
- 假设：正文薄（<300字）/臃肿（>6000字）=抽取失败，模型选容器编号、DOM 取值可修。
- 负结果：gov_ai×2 为 242/330 字真短讯（v12 得分 1.00/0.85），route-D 扩写反降至 0.18/0.22——「薄=失败」前提不成立；臃肿门控（oup 15K 字壳）因正文碎成逐段 <p> 无可选单一容器，全程 0 正收益 2 负收益。
- 处置：_ROUTE_D_ENABLED=False 旁路，代码与教训留档（model_arm.py）。段落级取舍划归分类头 IE 模型方向（训练方案设计，不直接训练）。
- 附带收益：字段级门控细分（三字段均有值时跳过字段生成调用），ISPRAS 耗时 309s→132s。

### v14（title 轮③，6b1bb29）
- 目标问题：ISPRAS og:title ≠ gold h1 整标题分歧约 21 页。
- 先试模型二选一裁决——负结果：abc_net_au 实测模型偏好 og 侧短标题，与 gold h1 口径不一致（模型「品味」≠标注口径），改确定性规则。
- 策略增量：meta/json-ld 标题与 h1 互不含对方时 h1 优先（互含=后缀差异归 v7/v11）；双重守卫：①_h1_is_headline 正文语义区限定（cnblogs h1=div#blogTitle 博客标语——gold 边界分歧挂起页不被翻转，dev 零差异得以保持）②_h1_is_generic_label 栏目词/数字标签拒收（Welcome/Events/Vol 65 No 6——首跑 8 个误翻转全部此类）。
- 结果：dev 逐页零差异；ISPRAS title 0.762→0.806（8 升 1 微降 -0.009：abc content 标题过滤联动扰动，同页 title 0→1，净正）。

### v15（publish 轮②，3d1cb5e）
- 目标问题：publish 精度差异簇 17 页中可修复部分——模型/meta 只摘到日，页面另有同日带时分写法（akipress「July 16」 vs 页面「16.07.2024 11:58」、ewn 同型）。
- 策略增量：_refine_publish_precision_en——日粒度 publish 在页面找到同一日期带时分写法时升级粒度；只升精度不新填日期（gold 日粒度页只比日期、gold 时分页原来也是 0，评分口径下单调非负，无 false_fill 通道）。
- 同轮两修：精化块原在管线前段（模型兜底在其后填值吃不到）→移至兜底后共用 helper；日期-时分分隔符放行 [/|–-]（akipress「July 16, 2024 / 11:58 AM」）。
- 结果：dev 逐页零差异；ISPRAS publish 0.519→0.544，4 升 0 回归。

## 停滞判定与终测（v15 即止）

停滞判据（近三轮边际收益 + 残余构成分析）：
- v12 +0.013~0.015、v13 零（回滚）、v14 +0.044（规则发现自失败模型实验）、v15 +0.025；
- 残余簇全部落入四类不可继续区：①任务定义差异（17 页拒识：英文门户首页按我方规范为列表页，ISPRAS 计为抽取目标；president_go_kr 真图集）②gold 口径差异（update 50 页 meta dateModified 不标——抑制反降分；authors 真实人名 false_fill；时区/12 小时制）③false_fill 风险区（14 页 gold 空但页面有可见日期，填则制造 false_fill——gov_cn/qstheory 已有先例）④段落级正文取舍（oup 逐段 <p> 壳）=分类头模型适用场景（按任务要求只设计训练方案、不训练）。

终测（test 28 页，交付时一次性、聚合口径 --no-pages，v15=3d1cb5e）：
- title 0.550 / authors 0.529 / publish 0.467 / update 0.273 / content 0.696 / **拒识 0.125**
- false_fill 全面为 0（title/authors/publish）——精度优先策略在未见模板上的体现；
- 拒识 0.125（8 个应拒识页仅拒 1）：v9 photo_set 检测以 chinadaily/sina/people 壳合成标定，未覆盖 test 的 gmw 模板族——合成标定模板覆盖不足，如实登记为残留 badcase 与评测不足（纪律：不读 test 页细节、不回调）；
- dev→test 落差（title 0.962→0.550）反映 dev 站点覆盖与 test 新模板族的迁移差距——数据集不足项，见最终报告。

