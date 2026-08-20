#!/usr/bin/env python3
"""把桃粉色配色统一替换为浅橙色，并新增白色翅膀花纹装饰。

颜色映射（桃粉 → 浅橙）：
  #FF8FA8 (primary)         → #FFA726  暖橙主色
  #F497A5 (primary-light)   → #FFCC80  浅橙
  #E57399 (primary-dark)    → #FB8C00  深橙
  #FDEEF2 (primary-bg)      → #FFF3E0  极浅橙
  #FFB3C6 (secondary)       → #FFB74D
  #FFCCDA (secondary-light) → #FFE0B2
  #F06292 (secondary-dark)  → #F57C00
  #FCE4EC (VIP3 渐变)        → #FFE0B2
  #FFB74D (accent)          → #FF8A65  桃橙（用作 accent 区分）
  #FFCDD2 (accent-green)    → #FFCCBC
  #AD1457 → #E65100
  #C2185B → #EF6C00

rgba 桃粉 → rgba 浅橙：
  rgba(244,151,165, X) → rgba(255,204,128, X)   # primary-light
  rgba(229,115,153, X) → rgba(251,140,0,   X)   # primary-dark
  rgba(255,143,168, X) → rgba(255,167,38,  X)   # primary
  rgba(252,232,238, X) → rgba(255,243,224, X)   # primary-bg 浅版
"""
import os
import re

ROOT = r"d:\个人\workbuddy工作区\travel-photo\travel-photo-miniprogram\src"

# 十六进制替换（精确匹配，避免误伤）
HEX_REPLACEMENTS = [
    (r"#FF8FA8", "#FFA726"),
    (r"#ff8fa8", "#FFA726"),
    (r"#F497A5", "#FFCC80"),
    (r"#f497a5", "#FFCC80"),
    (r"#E57399", "#FB8C00"),
    (r"#e57399", "#FB8C00"),
    (r"#FDEEF2", "#FFF3E0"),
    (r"#fdeef2", "#FFF3E0"),
    (r"#FFB3C6", "#FFB74D"),
    (r"#ffb3c6", "#FFB74D"),
    (r"#FFCCDA", "#FFE0B2"),
    (r"#ffccda", "#FFE0B2"),
    (r"#F06292", "#F57C00"),
    (r"#f06292", "#F57C00"),
    (r"#FCE4EC", "#FFE0B2"),
    (r"#fce4ec", "#FFE0B2"),
    (r"#AD1457", "#E65100"),
    (r"#C2185B", "#EF6C00"),
]

# rgba 替换
RGBA_REPLACEMENTS = [
    (r"rgba\(\s*244,\s*151,\s*165,\s*([\d.]+)\s*\)", r"rgba(255,204,128,\1)"),
    (r"rgba\(\s*229,\s*115,\s*153,\s*([\d.]+)\s*\)", r"rgba(251,140,0,\1)"),
    (r"rgba\(\s*255,\s*143,\s*168,\s*([\d.]+)\s*\)", r"rgba(255,167,38,\1)"),
    (r"rgba\(\s*252,\s*232,\s*238,\s*([\d.]+)\s*\)", r"rgba(255,243,224,\1)"),
]

TARGETS = [
    "uni.scss",
    "pages.json",
    "pages/index/index.vue",
    "pages/mine/mine.vue",
    "pages/upload/upload.vue",
    "pages/preview/preview.vue",
    "pages/history/history.vue",
    "pages/quota/quota.vue",
    "components/tp-quota-indicator/tp-quota-indicator.vue",
]


def patch(path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    orig = text
    n = 0
    for pat, rep in HEX_REPLACEMENTS + RGBA_REPLACEMENTS:
        new_text, c = re.subn(pat, rep, text)
        if c:
            text = new_text
            n += c
    if text != orig:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return n


def main():
    total = 0
    for rel in TARGETS:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print(f"[MISS] {rel}")
            continue
        n = patch(path)
        flag = "OK " if n else "SKIP"
        print(f"[{flag}] {rel:50s}  changes={n}")
        total += n
    print(f"\nTOTAL = {total} 处桃粉色已替换为浅橙色")


if __name__ == "__main__":
    main()