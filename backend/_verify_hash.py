"""多哈希 OR 投票聚类单元测试。"""
import io

import numpy as np
from PIL import Image, ImageDraw

import sys
sys.path.insert(0, r"d:\个人\workbuddy工作区\travel-photo\backend")

from app.ai.screener_real import RealScreener
from app.core.config import get_settings

settings = get_settings()


def make_image(seed: int, mode: str, w: int = 400, h: int = 400) -> Image.Image:
    rng = np.random.default_rng(seed)
    if mode == "face_bright":
        img = Image.new("RGB", (w, h), (220, 200, 180))
        d = ImageDraw.Draw(img)
        d.ellipse([130, 100, 270, 320], fill=(245, 220, 200))
        d.ellipse([155, 180, 175, 200], fill=(50, 40, 30))
        d.ellipse([225, 180, 245, 200], fill=(50, 40, 30))
        d.arc([180, 240, 220, 280], 0, 180, fill=(150, 80, 70), width=3)
        for _ in range(40):
            x, y = rng.integers(0, w), rng.integers(0, h)
            d.ellipse([x, y, x + 8, y + 8], fill=(220, 150, 180))
    elif mode == "face_dark":
        img = Image.new("RGB", (w, h), (50, 40, 60))
        d = ImageDraw.Draw(img)
        d.ellipse([130, 100, 270, 320], fill=(230, 200, 180))
        d.ellipse([155, 180, 175, 200], fill=(40, 30, 25))
        d.ellipse([225, 180, 245, 200], fill=(40, 30, 25))
        d.arc([180, 240, 220, 280], 0, 180, fill=(120, 60, 50), width=3)
        for _ in range(30):
            x, y = rng.integers(0, w), rng.integers(0, h)
            d.ellipse([x, y, x + 4, y + 4], fill=(255, 220, 150))
    elif mode == "face_cropped":
        img = Image.new("RGB", (w, h), (220, 200, 180))
        d = ImageDraw.Draw(img)
        d.ellipse([130, 120, 270, 340], fill=(245, 220, 200))
        d.ellipse([155, 200, 175, 220], fill=(50, 40, 30))
        d.ellipse([225, 200, 245, 220], fill=(50, 40, 30))
        d.arc([180, 260, 220, 300], 0, 180, fill=(150, 80, 70), width=3)
    elif mode == "city":
        img = Image.new("RGB", (w, h), (10, 10, 30))
        d = ImageDraw.Draw(img)
        for i in range(0, w, 30):
            for j in range(0, h, 60):
                d.rectangle([i, j, i + 20, j + 40], fill=(255, 200, 100))
    elif mode == "sea":
        img = Image.new("RGB", (w, h), (30, 100, 180))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 200, w, h], fill=(10, 50, 100))
        d.ellipse([300, 60, 360, 120], fill=(255, 240, 150))
    else:
        img = Image.new("RGB", (w, h), (128, 128, 128))
    return img.convert("L")


def hash_of(mode: str):
    img = make_image(42, mode)
    gray = img.resize((256, 256), Image.Resampling.LANCZOS)
    return {
        "ahash": RealScreener._ahash(gray),
        "dhash": RealScreener._dhash(gray),
        "phash": RealScreener._phash(gray),
    }


def hamming(a, b):
    return bin(a ^ b).count("1")


def vote_same(a, b):
    return any(hamming(a[k], b[k]) <= th for k, th in [("ahash", 10), ("dhash", 12), ("phash", 14)])


print("=" * 60)
print("P0 Unit Test: 3-Hash OR Voting Cluster")
print("=" * 60)

# Test 1: identical images
print("\n[1] Identical images -> same group expected")
h1 = hash_of("face_bright")
h2 = hash_of("face_bright")
distances = {k: hamming(h1[k], h2[k]) for k in ["ahash", "dhash", "phash"]}
print(f"  distances: {distances}")
ok1 = all(distances[k] <= th for k, th in [("ahash", 10), ("dhash", 12), ("phash", 14)])
print(f"  Result: {'PASS' if ok1 else 'FAIL'} (vote_same=True)")

# Test 2: same person, bright vs dark
print("\n[2] Same person + bright->dark background")
h_b = hash_of("face_bright")
h_d = hash_of("face_dark")
distances = {k: hamming(h_b[k], h_d[k]) for k in ["ahash", "dhash", "phash"]}
print(f"  distances: {distances}")
print(f"  vote_same = {vote_same(h_b, h_d)}")
ahash_hit = distances["ahash"] <= 10
phash_hit = distances["phash"] <= 14
print(f"  ahash_hit={ahash_hit}, phash_hit={phash_hit}")
print(f"  Result: {'PASS (phash rescued)' if not ahash_hit and phash_hit else 'FAIL'}")

# Test 3: same person, slight crop
print("\n[3] Same person + slight crop")
h_o = hash_of("face_bright")
h_c = hash_of("face_cropped")
distances = {k: hamming(h_o[k], h_c[k]) for k in ["ahash", "dhash", "phash"]}
print(f"  distances: {distances}")
print(f"  vote_same = {vote_same(h_o, h_c)}")
hits = [k for k, th in [("ahash", 10), ("dhash", 12), ("phash", 14)] if distances[k] <= th]
print(f"  hits: {hits}")
print(f"  Result: {'PASS' if hits else 'FAIL'}")

# Test 4: completely different scenes
print("\n[4] Completely different scenes -> different groups expected")
h_face = hash_of("face_bright")
h_city = hash_of("city")
h_sea = hash_of("sea")
print(f"  face vs city distances: { {k: hamming(h_face[k], h_city[k]) for k in ['ahash','dhash','phash']} }")
print(f"  vote_same (face, city) = {vote_same(h_face, h_city)}")
print(f"  vote_same (face, sea) = {vote_same(h_face, h_sea)}")
ok4 = not vote_same(h_face, h_city) and not vote_same(h_face, h_sea)
print(f"  Result: {'PASS' if ok4 else 'FAIL (false positive)'}")

print("\n" + "=" * 60)
print("P0 Unit Test Summary")
print("=" * 60)
results = {
    "Test 1 identical": ok1,
    "Test 2 bright->dark": not ahash_hit and phash_hit,
    "Test 3 slight crop": bool(hits),
    "Test 4 diff scenes": ok4,
}
for name, ok in results.items():
    print(f"  {name}: {'PASS' if ok else 'FAIL'}")
all_pass = all(results.values())
print(f"\n  OVERALL: {'ALL PASS' if all_pass else 'SOME FAILED'}")