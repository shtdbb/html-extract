# 环境记录（本地复现 · 数据与环境部分）

本文件所有版本号均来自真实安装后的 `pip freeze` / 实际运行输出，非凭记忆填写。

## Python

- 项目 venv：`html-extract/venv`（**非隐藏目录**；教训：隐藏目录 `.venv` 易丢失/被忽略，故按要求使用可见目录名 `venv`）
- 解释器版本：Python 3.12.14
- venv 底座解释器：Kimi Work 托管 Python
  `/Users/shtdbb/Library/Application Support/kimi-desktop/daimon-share/daimon/runtime/python/.venv/bin/python3`

## 创建与安装命令（真实执行）

```bash
cd /Users/shtdbb/Documents/Kimi/Workspaces/网页解析
"<托管 Python>/python3" -m venv html-extract/venv
html-extract/venv/bin/pip install --upgrade pip
html-extract/venv/bin/pip install trafilatura readability-lxml beautifulsoup4 lxml chardet requests
```

## 直接依赖版本（实测）

| 包 | 版本 |
|---|---|
| trafilatura | 2.2.0 |
| readability-lxml | 0.9 |
| beautifulsoup4 | 4.15.0 |
| lxml | 6.1.3 |
| chardet | 5.2.0 |
| requests | 2.34.2 |

## 验收命令（已通过）

```bash
html-extract/venv/bin/python -c "import trafilatura, readability, bs4, lxml, chardet; print(trafilatura.__version__)"
# 输出: 2.2.0
```

## pip freeze 完整摘要（安装当时真实输出）

```
babel==2.18.0
beautifulsoup4==4.15.0
certifi==2026.7.22
chardet==5.2.0
charset-normalizer==3.5.1
courlan==1.4.0
cssselect==1.3.0
dateparser==1.4.3
htmldate==1.10.0
idna==3.19
jusText==3.0.2
lxml==6.1.3
lxml_html_clean==0.4.5
python-dateutil==2.9.0.post0
pytz==2026.3.post1
readability-lxml==0.9
regex==2026.9.10
requests==2.34.2
six==1.17.0
soupsieve==2.9.2
tld==0.13.2
trafilatura==2.2.0
typing_extensions==4.16.0
tzlocal==5.4.4
urllib3==2.7.0
```

## 备注

- trafilatura 2.2.0 注意点：自 1.11 起 `extract()` 的元数据默认关闭，需要 `with_metadata=True` 才有 title/author/date（此为官方文档声明，后续 baseline 阶段实测核实）。
- readability-lxml 0.9：API 为 `Document(html).summary()` / `short_title()`，官方声明无 author/date 提取能力。
