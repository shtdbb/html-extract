#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrate_refusal.py — v9 拒识阈值的 dev 侧标定（纪律：绝不读取 test 页）。

三路样本：
  A. dev 全量 85 个评分页 —— 约束：零误拒（python_docs__02 除外，它应拒识）；
  B. 合成 photo_set —— 以 dev 文章页 HTML 为壳，把正文容器替换为
     「图片+图说序列」图集（正文=图+图说是图集页的一般形态定义，
     不来自任何 test 页面）；约束：全部拒识；
  C. negative 4 页 —— 约束：全部拒识（sina_list__01 为当前漏拒页）。

用法：venv/bin/python loop/calibrate_refusal.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import extract as E  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

CAPTION = "这是图说文字，描述本张新闻图片的现场画面与人物。"
LONG_CAPTION = ("这是一段较长的图说文字，详细描述本张新闻图片拍摄的现场环境、"
                "人物动作、活动背景以及相关信息，字数接近真实图集页的图说长度。")


def synth_photoset(raw: bytes, n_imgs: int, caption: str, intro: str = ""):
    """以真实文章页为壳，正文容器替换为图集结构。"""
    html, *_ = E.decode_declared_first(raw)
    soup = BeautifulSoup(html, "lxml")
    # 找当前正文容器（容器先验或最大文本 div），替换为图集
    target = None
    for sel, _ in E.CONTAINER_PRIORS:
        target = soup.select_one(sel)
        if target:
            break
    if target is None:
        best, bl = None, 0
        for el in soup.find_all("div"):
            tl = len(el.get_text(strip=True))
            if tl > bl:
                best, bl = el, tl
        target = best
    gallery = soup.new_tag("div", attrs={"class": "photo-gallery"})
    if intro:
        p = soup.new_tag("p")
        p.string = intro
        gallery.append(p)
    for i in range(n_imgs):
        fig = soup.new_tag("figure")
        img = soup.new_tag("img", attrs={"src": f"https://example.com/p{i}.jpg"})
        cap = soup.new_tag("figcaption")
        cap.string = caption
        fig.append(img)
        fig.append(cap)
        gallery.append(fig)
    target.replace_with(gallery)
    return str(soup).encode("utf-8")


def run_one(raw: bytes, site: str):
    html, *_ = E.decode_declared_first(raw)
    soup = BeautifulSoup(html, "lxml")
    try:
        import trafilatura
        doc = trafilatura.bare_extraction(
            html, with_metadata=True, include_comments=False,
            include_tables=True, include_images=True)
    except Exception:  # noqa: BLE001
        doc = None
    tl = len((doc.text or "").strip()) if doc is not None else 0
    return E.check_refusal(soup, site, tl)


def main():
    index = [json.loads(l) for l in open(ROOT / "dataset_index.jsonl")]
    gold = {r["id"]: r for r in json.load(open(ROOT / "results" / "dev_gold.json"))}

    # A. dev 全量（fixed+generic）：除应拒识页外零误拒
    false_refuse, should_refuse = [], []
    for r in index:
        if r["group"] not in ("fixed", "generic"):
            continue
        raw = (ROOT / r["path"]).read_bytes()
        rejected, reason, _ = run_one(raw, r["site"])
        expect = bool(gold[r["id"]].get("expect_refusal"))
        if rejected and not expect:
            false_refuse.append((r["id"], reason))
        if expect:
            should_refuse.append((r["id"], rejected, reason))
    print(f"A. dev 文章页误拒: {len(false_refuse)}")
    for x in false_refuse:
        print(f"   误拒 {x[0]}: {x[1]}")
    print(f"   应拒识页: {[(i, ok) for i, ok, _ in should_refuse]}")

    # B. 合成 photo_set（以 3 个不同模板文章页为壳 × 3 种图集形态）
    shells = ["chinadaily__01", "sina__01", "people__01"]
    variants = [
        ("短图说×12图", 12, CAPTION, ""),
        ("长图说×10图", 10, LONG_CAPTION, ""),
        ("长图说×9图+导语", 9, LONG_CAPTION, "本图集记录活动现场精彩瞬间。" * 8),
    ]
    n_miss = 0
    for shell in shells:
        raw = (ROOT / index[[r["id"] for r in index].index(shell)]["path"]).read_bytes()
        for vname, n, cap, intro in variants:
            sraw = synth_photoset(raw, n, cap, intro)
            rejected, reason, cs = run_one(sraw, "synth")
            if not rejected:
                n_miss += 1
                print(f"   漏拒 synth[{shell}/{vname}]")
    print(f"B. 合成 photo_set 漏拒: {n_miss}/{len(shells) * len(variants)}")

    # C. negative 4 页
    n_neg = 0
    for r in index:
        if r["group"] != "negative":
            continue
        raw = (ROOT / r["path"]).read_bytes()
        rejected, reason, _ = run_one(raw, r["site"])
        if not rejected:
            n_neg += 1
            print(f"   漏拒 negative {r['id']}")
        else:
            print(f"   ok {r['id']}: {reason}")
    print(f"C. negative 漏拒: {n_neg}/4")


if __name__ == "__main__":
    main()
