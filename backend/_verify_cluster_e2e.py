"""A+C 聚类方案端到端对比测试。

测试场景（模拟你最近一次上传的真实问题）：
- 4 张照片：同人物 + 不同背景（亮花海 / 暗夕阳 / 室内白墙 / 雪山）
- 1 张照片：另一个人物 + 不同背景
- 1 张照片：完全无关的海景

预期聚类：
- 老算法（仅 aHash）：可能判 5~6 组（人物同但背景亮度差大 → aHash 距离远）
- 新算法（embedding + 三哈希）：3 组（人物 A 的 4 张 / 人物 B / 海景）

需要：
1. 后端已启动（让 LLM_API_KEY 加载）
2. LLM_API_KEY 已充值（用于调 multimodal-embedding-v1）

用法：
    python _verify_cluster_e2e.py
"""
import asyncio
import base64
import io
import sys
sys.path.insert(0, r"d:\个人\workbuddy工作区\travel-photo\backend")

import numpy as np
from PIL import Image, ImageDraw

from app.ai.qwen_embedding import embed_images
from app.ai.screener_real import RealScreener
from app.core.config import get_settings

settings = get_settings()
print(f"LLM_API_KEY configured: {bool(settings.LLM_API_KEY)} (len={len(settings.LLM_API_KEY)})")
print(f"CLUSTER_USE_QWEN_EMBEDDING: {settings.CLUSTER_USE_QWEN_EMBEDDING}")
print(f"CLUSTER_QWEN_SIM_THRESHOLD: {settings.CLUSTER_QWEN_SIM_THRESHOLD}")


# ===== 合成 6 张测试图 =====
def make_person_a(bg_mode: str, w: int = 400, h: int = 400) -> Image.Image:
    """合成人物 A 的照片：脸位置/形状固定，只改背景。"""
    rng = np.random.default_rng(42)
    bg_colors = {
        "flower_bright": (220, 200, 180),   # 亮花海背景
        "sunset_dark":   (50, 40, 60),      # 暗夕阳背景
        "indoor_white":  (240, 240, 240),   # 室内白墙
        "snow_mountain": (200, 210, 220),   # 雪山冷色
    }
    img = Image.new("RGB", (w, h), bg_colors[bg_mode])
    d = ImageDraw.Draw(img)
    # 脸（位置/形状完全相同）
    d.ellipse([130, 100, 270, 320], fill=(245, 220, 200))
    d.ellipse([155, 180, 175, 200], fill=(50, 40, 30))
    d.ellipse([225, 180, 245, 200], fill=(50, 40, 30))
    d.arc([180, 240, 220, 280], 0, 180, fill=(150, 80, 70), width=3)
    # 头发（不同背景颜色有微调）
    if bg_mode == "sunset_dark":
        d.ellipse([125, 95, 275, 200], fill=(20, 15, 25))
    else:
        d.ellipse([125, 95, 275, 200], fill=(40, 30, 25))
    # 装饰（背景相关）
    if bg_mode == "flower_bright":
        for _ in range(40):
            x, y = rng.integers(0, w), rng.integers(0, h)
            d.ellipse([x, y, x + 8, y + 8], fill=(220, 150, 180))
    elif bg_mode == "sunset_dark":
        for _ in range(30):
            x, y = rng.integers(0, w), rng.integers(0, h)
            d.ellipse([x, y, x + 4, y + 4], fill=(255, 220, 150))
    elif bg_mode == "snow_mountain":
        for _ in range(20):
            x, y = rng.integers(0, w), rng.integers(0, h)
            d.ellipse([x, y, x + 5, y + 5], fill=(255, 255, 255))
    return img.convert("RGB")


def make_person_b(w: int = 400, h: int = 400) -> Image.Image:
    """合成人物 B：脸位置不同 + 不同发型（防止被当成人物 A）。"""
    img = Image.new("RGB", (w, h), (180, 200, 160))   # 绿色背景
    d = ImageDraw.Draw(img)
    d.ellipse([120, 120, 240, 280], fill=(230, 200, 170))  # 脸位置不同
    d.ellipse([145, 180, 165, 200], fill=(40, 30, 20))
    d.ellipse([205, 180, 225, 200], fill=(40, 30, 20))
    d.arc([170, 220, 200, 250], 0, 180, fill=(120, 60, 50), width=3)
    # 长头发（区别于人物 A）
    d.rectangle([115, 95, 245, 130], fill=(80, 50, 30))
    return img.convert("RGB")


def make_sea(w: int = 400, h: int = 400) -> Image.Image:
    """海景：完全无关"""
    img = Image.new("RGB", (w, h), (30, 100, 180))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 200, w, h], fill=(10, 50, 100))
    d.ellipse([300, 60, 360, 120], fill=(255, 240, 150))
    return img.convert("RGB")


def img_to_data_url(img: Image.Image) -> str:
    """PIL Image → base64 data URL（Qwen embedding 支持）"""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


# 准备 6 张图
photos = [
    ("p1_person_a_flower",   make_person_a("flower_bright")),
    ("p2_person_a_sunset",   make_person_a("sunset_dark")),
    ("p3_person_a_indoor",   make_person_a("indoor_white")),
    ("p4_person_a_snow",     make_person_a("snow_mountain")),
    ("p5_person_b",          make_person_b()),
    ("p6_sea",               make_sea()),
]

print("\n" + "=" * 60)
print("Synthesized 6 test images:")
for name, _ in photos:
    print(f"  - {name}")

urls = [img_to_data_url(img) for _, img in photos]


# ===== 计算每张图的三哈希（用于对比"只哈希"vs"embedding+哈希"） =====
def get_hashes(img: Image.Image):
    gray = img.convert("L").resize((256, 256), Image.Resampling.LANCZOS)
    return {
        "ahash": RealScreener._ahash(gray),
        "dhash": RealScreener._dhash(gray),
        "phash": RealScreener._phash(gray),
    }


def hamming(a, b):
    return bin(a ^ b).count("1")


print("\n" + "=" * 60)
print("Step 1: Multi-hash distances (only aHash / dHash / pHash)")
print("=" * 60)

hashes = {name: get_hashes(img) for name, img in photos}
labels = [n for n, _ in photos]
n = len(labels)
print(f"  {'':18s} | {' | '.join(f'{l[:8]:>8s}' for l in labels)}")
print(f"  {'-'*18}-+-{'-'*(11*n-1)}")
for kind in ["ahash", "dhash", "phash"]:
    row = f"  {kind:18s} | "
    cells = []
    for i in range(n):
        cell = []
        for j in range(n):
            if i == j:
                cell.append("    .    ")
            else:
                d = hamming(hashes[labels[i]][kind], hashes[labels[j]][kind])
                # 颜色标记：≤阈值=同组
                th = {"ahash": 10, "dhash": 12, "phash": 14}[kind]
                mark = "*" if d <= th else " "
                cell.append(f"{d:>4d}{mark}")
        cells.append(" ".join(cell))
    print(row + " | ".join(cells))

print("\n  Note: * means hash-distance <= threshold (would be clustered same group)")
print("  Thresholds: ahash=10, dhash=12, phash=14")

# ===== Step 2: Qwen embedding =====
print("\n" + "=" * 60)
print("Step 2: Qwen multimodal-embedding-v1")
print("=" * 60)

async def run_embedding():
    embeddings = await embed_images(urls)
    return embeddings


embeddings = asyncio.run(run_embedding())
print(f"\n  Got {sum(1 for e in embeddings if e)}/{len(embeddings)} embeddings")

# ===== Step 3: 余弦相似度矩阵 =====
print("\n" + "=" * 60)
print("Step 3: Cosine similarity matrix")
print("=" * 60)

from app.ai.qwen_embedding import cosine_similarity

sim_matrix = np.zeros((n, n))
for i in range(n):
    for j in range(n):
        if embeddings[i] is not None and embeddings[j] is not None:
            sim_matrix[i, j] = cosine_similarity(embeddings[i], embeddings[j])

print(f"  {'':18s} | {' | '.join(f'{l[:8]:>8s}' for l in labels)}")
print(f"  {'-'*18}-+-{'-'*(11*n-1)}")
for i, l in enumerate(labels):
    cells = []
    for j in range(n):
        if i == j:
            cells.append("   1.000")
        elif embeddings[i] is None or embeddings[j] is None:
            cells.append("    N/A ")
        else:
            cells.append(f"  {sim_matrix[i,j]:.3f}")
    print(f"  {l:18s} | " + " | ".join(cells))

print("\n  Threshold: cosine_sim >= 0.7 -> same group")

# ===== Step 4: 对比聚类结果 =====
print("\n" + "=" * 60)
print("Step 4: Cluster comparison (hash-only vs hash+embedding)")
print("=" * 60)

# 构造 analyses（模拟 screener 内部产物）
analyses = []
for name, img in photos:
    hashes_ = get_hashes(img)
    analyses.append({
        "photo_id": name,
        "original_url": img_to_data_url(img),  # 这里仅占位
        **hashes_,
        "embedding": None,
    })

# 给 analyses 注入真实 embedding
for i, a in enumerate(analyses):
    a["embedding"] = embeddings[i]

# Hash-only 聚类
screener = RealScreener()
hash_clusters = screener._cluster_by_hash(analyses)
hash_cluster_of = {}
for cid, members in enumerate(hash_clusters):
    for m in members:
        hash_cluster_of[analyses[m]["photo_id"]] = cid

print("\n  [A] Only multi-hash (aHash+dHash+pHash OR vote):")
for cid, members in enumerate(hash_clusters):
    pids = [analyses[m]["photo_id"] for m in members]
    print(f"    cluster {cid}: {pids}")

# Embedding 聚类
emb_clusters = RealScreener._cluster_by_embedding(analyses, embeddings)
emb_cluster_of = {}
for cid, members in enumerate(emb_clusters):
    for m in members:
        emb_cluster_of[analyses[m]["photo_id"]] = cid

print("\n  [B] Embedding only (cosine >= 0.7 + Union-Find):")
for cid, members in enumerate(emb_clusters):
    pids = [analyses[m]["photo_id"] for m in members]
    print(f"    cluster {cid}: {pids}")

# 合并
merged_mapping, total = RealScreener._merge_clusters(analyses, hash_clusters, emb_clusters)
merged_groups: dict[int, list[str]] = {}
for pid, cid in merged_mapping.items():
    merged_groups.setdefault(cid, []).append(pid)

print("\n  [C] Combined (hash OR embedding):")
for cid, pids in sorted(merged_groups.items()):
    print(f"    cluster {cid}: {pids}")
print(f"    TOTAL: {total} groups")

print("\n" + "=" * 60)
print("Summary")
print("=" * 60)
print(f"  Expected: 3 groups (person A x4 / person B / sea)")
print(f"  Hash-only: {len(hash_clusters)} groups")
print(f"  Embedding-only: {len(emb_clusters)} groups")
print(f"  Combined: {total} groups")

# 计算每张图被分到正确组的概率（粗略评估）
print("\n  Group breakdown:")
for cid, pids in sorted(merged_groups.items()):
    expected_person = "Person A" if all("person_a" in p for p in pids) and "person_b" not in " ".join(pids) else (
        "Person B" if "person_b" in " ".join(pids) else "Other"
    )
    print(f"    {cid}: {pids} -> {expected_person}")