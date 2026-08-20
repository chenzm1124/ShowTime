#!/usr/bin/env python3
"""把所有 emoji（4 字节 UTF-8 / surrogate pair）替换回 Unicode 单码点符号，
避免 WXML 渲染层 `Framework inner error (expect END descriptor with depth 1 but get FLOW_ALLOC_NODE_ID)`。

桃粉色配色保留（只换字符，不换颜色）。
"""
import os

ROOT = r"d:\个人\workbuddy工作区\travel-photo\travel-photo-miniprogram\src"

# emoji → Unicode 单码点字符映射
# 用单码点字符避免 WXML 模板的 surrogate pair 渲染问题
REPLACEMENTS = {
    "🏠": "⌂",   # 房子 → house
    "📋": "⎘",   # 剪贴板 → next page
    "✨": "◆",   # 火花 → black diamond
    "💡": "◇",   # 灯泡 → white diamond
    "🌸": "✿",   # 樱花 → floral heart
    "🌫️": "◌",   # 雾 → dotted circle
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
    print(f"\nTOTAL = {total} 处 emoji 替换为 Unicode 单码点字符")
    print("桃粉色配色保留未动；WXML 渲染层错误应当消失。")


if __name__ == "__main__":
    main()