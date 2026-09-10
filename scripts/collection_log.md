# 采集日志（自动生成，勿手改）

> 本文件由 scripts/collect.py 依据 collection_state.json 重新生成。

## 组: fixed（最近运行 2026-09-10T16:25:22+00:00 UTC，保存 30 页）

| 站点 | 目标 | 成功 | 失败 | 运行时间(UTC) |
|---|---|---|---|---|
| chinadaily | 10 | 10 | 0 | 2026-09-10T16:25:22+00:00 |
| gov_cn | 10 | 10 | 0 | 2026-09-10T16:25:22+00:00 |
| news_cn | 10 | 10 | 0 | 2026-09-10T16:25:22+00:00 |

## 组: negative（最近运行 2026-09-10T16:25:26+00:00 UTC，保存 4 页）

| 站点 | 目标 | 成功 | 失败 | 运行时间(UTC) |
|---|---|---|---|---|
| chinanews_list | 1 | 1 | 0 | 2026-09-10T16:25:26+00:00 |
| people_list | 1 | 1 | 0 | 2026-09-10T16:25:26+00:00 |
| sina_list | 1 | 1 | 0 | 2026-09-10T16:25:26+00:00 |
| sohu_list | 1 | 1 | 0 | 2026-09-10T16:25:26+00:00 |

## 组: generic（最近运行 2026-09-10T16:27:01+00:00 UTC，保存 55 页）

| 站点 | 目标 | 成功 | 失败 | 运行时间(UTC) |
|---|---|---|---|---|
| caixin | 5 | 5 | 0 | 2026-09-10T16:26:14+00:00 |
| chinanews | 6 | 6 | 0 | 2026-09-10T16:26:14+00:00 |
| cnblogs | 7 | 7 | 0 | 2026-09-10T16:27:01+00:00 |
| github_blog | 4 | 4 | 0 | 2026-09-10T16:27:01+00:00 |
| ifeng | 5 | 5 | 4 | 2026-09-10T16:26:14+00:00 |
| people | 6 | 6 | 1 | 2026-09-10T16:27:01+00:00 |
| python_docs | 5 | 5 | 0 | 2026-09-10T16:27:01+00:00 |
| segmentfault | 5 | 5 | 0 | 2026-09-10T16:27:01+00:00 |
| sina | 6 | 6 | 0 | 2026-09-10T16:26:14+00:00 |
| sohu | 6 | 6 | 0 | 2026-09-10T16:26:14+00:00 |

## 组: test（最近运行 2026-09-10T16:35:27+00:00 UTC，保存 28 页）

| 站点 | 目标 | 成功 | 失败 | 运行时间(UTC) |
|---|---|---|---|---|
| 51cto | 2 | 0 | 1 | 2026-09-10T16:35:27+00:00 |
| csdn | 5 | 5 | 0 | 2026-09-10T16:28:12+00:00 |
| devto | 2 | 2 | 0 | 2026-09-10T16:28:12+00:00 |
| en_people | 4 | 4 | 0 | 2026-09-10T16:27:20+00:00 |
| gmw | 4 | 4 | 0 | 2026-09-10T16:27:20+00:00 |
| mdn | 3 | 3 | 0 | 2026-09-10T16:28:12+00:00 |
| mslearn | 3 | 3 | 0 | 2026-09-10T16:28:12+00:00 |
| netease | 4 | 4 | 0 | 2026-09-10T16:33:37+00:00 |
| oschina | 3 | 0 | 13 | 2026-09-10T16:28:12+00:00 |
| stdaily | 3 | 3 | 1 | 2026-09-10T16:27:20+00:00 |

**累计保存：117 页**

## 失败明细

| 组 | 站点 | URL | 原因 |
|---|---|---|---|
| generic | ifeng | https://gentie.ifeng.com/view.html?docUrl=ucms_8wJVOS2esyy&docName=冰岛准备永久停止捕鲸，压力给到挪威和日本&skey=d8188f&pcUrl=https://news.ifeng.com/c/8wJVOS2esyy | ValueError:empty_shell_suspected:visible_text=39 |
| generic | ifeng | https://gentie.ifeng.com/view.html?docUrl=ucms_8wJZYLKbvIH&docName=女子被毒蛇咬伤身亡，养蛇场负责人：无法证明蛇来自我这儿，最多补偿2万元&skey=cbf785&pcUrl=https://news.ifeng.com/c/8wJZYLKbvIH | ValueError:empty_shell_suspected:visible_text=39 |
| generic | ifeng | https://gentie.ifeng.com/view.html?docUrl=ucms_8vkUL3aoVho&docName=平安半年报超预期！净利润大增36%&skey=dde3e5&pcUrl=https://news.ifeng.com/c/8vkUL3aoVho | ValueError:empty_shell_suspected:visible_text=39 |
| generic | ifeng | https://gentie.ifeng.com/view.html?docUrl=ucms_8wJZw7qn5d4&docName=尼泊尔泥石流灾害已致1382人遇难&skey=96bf82&pcUrl=https://news.ifeng.com/c/8wJZw7qn5d4 | ValueError:empty_shell_suspected:visible_text=39 |
| generic | people | http://politics.people.com.cn/ | seed_fetch:HTTPError:403 Client Error: Forbidden for url: http://politics.people.com.cn/ |
| test | stdaily | https://www.stdaily.com/index/kejixinwen/ | seed_fetch:HTTPError:404 Client Error: Not Found for url: https://www.stdaily.com/index/kejixinwen/ |
| test | oschina | https://www.oschina.net/news/502409 | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502408 | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502405/deepseek-v4-1-flash-ga | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502404/tailwind-is-joining-shopify | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502402 | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502401/gpt-6-astra-looped-transformers-and | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502400 | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502399 | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502398 | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502395 | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502394 | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502393/openai-chatgpt-images-2-5 | ValueError:empty_shell_suspected:visible_text=27 |
| test | oschina | https://www.oschina.net/news/502392/meta-ai-muse | ValueError:empty_shell_suspected:visible_text=27 |
| test | 51cto | https://www.51cto.com/|https://blog.51cto.com/ | no_article_links_extracted:种子页可访问但提取到0个文章链接(JS壳或模式不匹配) |

## 实际构成与原计划的偏差（如实说明）

1. **fixed 组发现方式改变**：news.cn、chinadaily.com.cn、gov.cn 的栏目/索引页实测均为
   JS 动态加载的静态壳（news.cn politics 页只能提取到 2022 年陈旧静态兜底链接；
   chinadaily 频道页提取到 0 个文章链接；gov.cn yaowen/liebiao 页只有 2023 年及更早的
   /home/ 兜底链接）。因此 fixed 组改用「搜索引擎发现同站同模板近期文章 URL + 直取」，
   未按计划「抓栏目页提链接」。同站模板一致性由人工核对 URL 形态保证。
2. **test 组 cctv 整站替换**：news.cctv.com 可提取的文章链接极少，且实际抓到的 4 页
   全部为视频稿（静态 HTML 中正文为视频播放器、无文本正文，已逐页实测确认），按
   「需要 JS 渲染/无语义内容则跳过并记录」规则整组剔除（已保存的 cctv__01~04.html
   已删除），中文新闻缺口改由网易新闻（netease，4 页，dy/article 模板）补齐。
   cctv 由此记为"视频稿无静态正文"的失败站点。
3. **test 组 oschina 整站失败**：文章页全部返回 ~3.6KB SPA 空壳（可见文本 27 字符，
   需 JS 渲染），13 次尝试全部失败，已逐条记录。博客类缺口由 CSDN（5 页）补齐。
4. **test 组 51cto 整站失败**：首页与 blog 首页可访问但提取到 0 个文章链接（JS 壳）；
   另经手工诊断确认其文章页（如 /article/819776.html）对脚本请求只返回 ~1KB 反爬壳。
   未采集到任何 51cto 页面。
5. **test 组 mslearn 改直取**：training/browse 索引页为 JS 壳，改用搜索发现的 3 篇
   静态 quickstart 文档直取。
6. **negative 组两处替换**：politics.people.com.cn 与 www.chinanews.com.cn/gn/ 对脚本
   UA 返回 403，分别替换为 finance.people.com.cn 频道页与 chinanews 滚动新闻列表页。
7. **generic 组 chinanews 种子页替换**：/gn/、/cj/ 频道页 403，改用首页 + 滚动新闻页
   提取文章链接。
8. **数量结构**：总数 117 = fixed 30 + generic 55 + negative 4 + test 28，与计划一致。
   test 组内：新闻 15（中文 netease 4 + gmw 4 + stdaily 3 = 11，英文 en_people 4）、
   博客 7（csdn 5 + devto 2，其中 csdn 为 oschina/51cto 失败后的替代站）、
   文档 6（mdn 3 + mslearn 3）。
9. **已知样本质量注记**：python_docs__02 为 library 索引页（文档目录性质）；
   ifeng 的 4 个 gentie.ifeng.com 跟贴页被空壳检测正确拦截（记为失败而非样本）；
   sohu 部分页面为快讯短稿（正文容器实测 102~1485 字符，静态 HTML 中确有正文，
   非空壳，予以保留）；news_cn__05、ifeng__04 同为真实短讯稿。
