#!/usr/bin/env python3
"""反向操作：把 Unicode 单码点字符换回 emoji（4 字节 UTF-8）。
注意：emoji 会再次触发 WXML 渲染层 Framework inner error。
"""
import os

ROOT = r"d:\个人\workbuddy工作区\travel-photo\travel-photo-miniprogram\src"

# 与 _emoji_to_unicode.py 完全相反的映射
REPLACEMENTS = {
    "⌂": "🏠",   # house → 房子
    "⎘": "📋",   # next page → 剪贴板
    "◆": "✨",   # black diamond → 火花
    "◇": "💡",   # white diamond → 灯泡
    "✿": "🌸",   # floral heart → 樱花
    "◌": "🌫️",  # dotted circle → 雾
}

TARGETS = [
    "utils/mock.ts",
    "pages/caption/caption.vue",
    "pages/upload/upload.vue",
    "pages/mine/mine.vue",
]


def patch(path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    orig = text
    n = 0
    for old, new in REPLACEMENTS.items():
        cnt = text.count(old)
        if cnt:
            text = text.replace(old, new)
            n += cnt
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
        print(f"[{flag}] {rel:40s}  replacements={n}")
        total += n
    print(f"\nTOTAL = {total} 处 Unicode 单码点已恢复为 emoji")
    print("⚠️  预期 WXML 渲染层错误会再次出现（如 `Framework inner error (expect END descriptor ...)`）")
    print("   出错后回退方案：再执行一次 _emoji_to_unicode.py 即可反向")


if __name__ == "__main__":
    main()