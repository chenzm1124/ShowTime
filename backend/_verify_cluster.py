"""完整聚类单元测试：embedding + 多哈希 OR 投票 + 合并。"""
import asyncio
import sys
sys.path.insert(0, r"d:\个人\workbuddy工作区\travel-photo\backend")

from app.ai.screener_real import RealScreener
from app.ai.qwen_embedding import cosine_similarity

# 构造 6 张照片的虚拟 analyses（无 embedding）
def make_analyses():
    return [
        {"photo_id": "p1", "original_url": "u1", "ahash": 0b11110000, "dhash": 0b10101010, "phash": 0b00001111},
        {"photo_id": "p2", "original_url": "u2", "ahash": 0b11110001, "dhash": 0b10101011, "phash": 0b00001111},  # 极相似于 p1
        {"photo_id": "p3", "original_url": "u3", "ahash": 0b00001111, "dhash": 0b01010101, "phash": 0b11110000},  # 与 p1 不同
        {"photo_id": "p4", "original_url": "u4", "ahash": 0b11110000, "dhash": 0b00000000, "phash": 0b00000000},  # aHash 似 p1
        {"photo_id": "p5", "original_url": "u5", "ahash": 0b00000000, "dhash": 0b00000000, "phash": 0b00000000},  # 完全独立
        {"photo_id": "p6", "original_url": "u6", "ahash": None,   "dhash": None,   "phash": None},          # 失败图
    ]

# 模拟 embedding 向量（用 4 维向量方便构造相似度）
# p1/p2 高相似（同人物），p3/p4 中相似（同风景），p5/p6 独立
def make_embeddings():
    return [
        [1.0, 0.1, 0.0, 0.0],   # p1
        [0.99, 0.1, 0.0, 0.0], # p2 - 与 p1 极相似
        [0.0, 0.0, 1.0, 0.1],   # p3
        [0.0, 0.0, 0.99, 0.1], # p4 - 与 p3 极相似
        [0.5, 0.5, 0.5, 0.5],   # p5 - 完全独立
        None,                   # p6 - 失败
    ]

print("=" * 60)
print("P1/P2 Unit Test: Qwen Embedding + Hash OR Vote + Merge")
print("=" * 60)

# Test 1: 多哈希聚类
print("\n[1] _cluster_by_hash")
analyses = make_analyses()
screener = RealScreener()
clusters = screener._cluster_by_hash(analyses)
for cid, members in enumerate(clusters):
    pids = [analyses[i]["photo_id"] for i in members]
    print(f"  cluster {cid}: {pids}")
# 期望: {p1, p2, p4} / {p3} / {p5} / {p6}（p4 的 aHash==p1，p1/p2 也相似）

# Test 2: Embedding 聚类
print("\n[2] _cluster_by_embedding")
embeddings = make_embeddings()
clusters = RealScreener._cluster_by_embedding(analyses, embeddings)
for cid, members in enumerate(clusters):
    pids = [analyses[i]["photo_id"] for i in members]
    print(f"  cluster {cid}: {pids}")
# 期望: {p1, p2} / {p3, p4} / {p5} / {p6}

# Test 3: 合并
print("\n[3] _merge_clusters")
hash_clusters = screener._cluster_by_hash(analyses)
emb_clusters = RealScreener._cluster_by_embedding(analyses, embeddings)
mapping, total = RealScreener._merge_clusters(analyses, hash_clusters, emb_clusters)
print(f"  mapping: {mapping}")
print(f"  total groups: {total}")
# 期望: p1+p2+p4 同组, p3+p4 可能合并(若 hash 命中), 最终约 3-4 组

# Test 4: cosine_similarity
print("\n[4] cosine_similarity sanity")
print(f"  similar: {cosine_similarity([1,0],[0.99,0.1]):.4f}")
print(f"  orthogonal: {cosine_similarity([1,0,0],[0,1,0]):.4f}")
print(f"  opposite: {cosine_similarity([1,0],[-1,0]):.4f}")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)