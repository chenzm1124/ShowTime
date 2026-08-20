# -*- coding: utf-8 -*-
"""
E2E Test: Person photo dedup + scoring + retouching pipeline
Usage: set PYTHONIOENCODING=utf-8 && python test_e2e/run_e2e_test.py
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8000"
API_PREFIX = "/api/v1"
TEST_CODE = "e2e_test_code_001"
TEST_PHOTOS_DIR = Path(__file__).parent / "test_photos"
OUTPUT_DIR = Path(__file__).parent / "output"
RETOUCH_STYLE = "auto"
LOCATION = "Beijing"


def unwrap(resp_json: dict) -> dict:
    """API wraps in {code, data, message}"""
    return resp_json.get("data", resp_json)


def psec(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def run():
    psec("Travel Photo AI - E2E Test")
    print(f"  Backend: {BASE_URL}")
    print(f"  Photos:  {TEST_PHOTOS_DIR}")
    print(f"  Output:  {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=120.0) as cli:
        # Step 1: Login
        psec("Step 1/6: Login (mock mode)")
        r = await cli.post(f"{BASE_URL}{API_PREFIX}/auth/wx-login", json={
            "code": TEST_CODE,
            "device_info": {"model": "e2e", "platform": "windows"}
        })
        r.raise_for_status()
        info = unwrap(r.json())
        token = info["token"]
        uid = info["user_id"]
        hdr = {"Authorization": f"Bearer {token}"}
        print(f"  OK login: uid={uid} token={token[:16]}...")

        # Step 2: Presigned URLs
        psec("Step 2/6: Get presigned COS upload URLs")
        photo_files = sorted([
            f for f in os.listdir(TEST_PHOTOS_DIR)
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
        ])
        if not photo_files:
            print("  FAIL: no test photos found!")
            return

        print(f"  Found {len(photo_files)} photos:")
        for i, fn in enumerate(photo_files):
            sz = os.path.getsize(TEST_PHOTOS_DIR / fn) / 1024
            print(f"    {i+1}. {fn[:60]} ({sz:.0f} KB)")

        today = time.strftime("%Y%m%d")
        keys = [f"uploads/{uid}/{today}/{uuid.uuid4().hex[:8]}.jpg" for _ in photo_files]

        r = await cli.post(f"{BASE_URL}{API_PREFIX}/photos/presign/batch",
                           json={"object_keys": keys}, headers=hdr)
        r.raise_for_status()
        items = unwrap(r.json())["items"]
        print(f"  OK got {len(items)} presigned URLs")

        # Step 3: Upload to COS
        psec(f"Step 3/6: Upload {len(photo_files)} photos to COS")
        access_urls = []
        for i, (item, fn) in enumerate(zip(items, photo_files)):
            fpath = TEST_PHOTOS_DIR / fn
            with open(fpath, "rb") as f:
                raw = f.read()
            put_r = await cli.put(item["presigned_url"], content=raw,
                                  headers={"Content-Type": "image/jpeg"}, timeout=60.0)
            if put_r.status_code not in (200, 201, 204):
                print(f"  FAIL upload [{i+1}] {fn[:40]}: HTTP {put_r.status_code}")
            else:
                access_urls.append(item["access_url"])
                print(f"  OK [{i+1}/{len(photo_files)}] {fn[:40]} -> COS")

        print(f"\n  Uploaded {len(access_urls)}/{len(photo_files)} successfully")

        # Step 4: Create task
        psec("Step 4/6: Create processing task")
        r = await cli.post(f"{BASE_URL}{API_PREFIX}/tasks", json={
            "photo_urls": access_urls,
            "options": {
                "retouch_styles": [RETOUCH_STYLE],
                "location": LOCATION,
            }
        }, headers=hdr)
        r.raise_for_status()
        task = unwrap(r.json())
        task_id = task["task_id"]
        print(f"  OK task_id={task_id} status={task['status']}")

        # Step 5: Poll for completion
        psec("Step 5/6: Wait for task completion")
        max_wait, interval = 600, 5
        elapsed = 0
        status = "processing"
        while elapsed < max_wait:
            await asyncio.sleep(interval)
            elapsed += interval
            r = await cli.get(f"{BASE_URL}{API_PREFIX}/tasks/{task_id}/status", headers=hdr)
            r.raise_for_status()
            st = unwrap(r.json())
            status = st["status"]
            progress = st.get("progress", 0)
            processed = st.get("processed_photos", 0)
            print(f"  [{elapsed}s] status={status} progress={progress}% processed={processed}")
            if status in ("completed", "failed"):
                break
        else:
            print(f"  WARN: timeout after {max_wait}s, status={status}")

        if status == "failed":
            print("  FAIL: task failed!")
            return

        print(f"\n  OK task completed in {elapsed}s!")

        # Step 6: Get result & download
        psec("Step 6/6: Get result & download photos")
        r = await cli.get(f"{BASE_URL}{API_PREFIX}/tasks/{task_id}/result", headers=hdr)
        r.raise_for_status()
        res = unwrap(r.json())

        # Save raw JSON
        (OUTPUT_DIR / "result_summary.json").write_text(
            json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")

        selected = res.get("selected_photos", [])
        groups = res.get("groups", [])
        print(f"\n  Summary:")
        print(f"    total_photos:   {res.get('total_photos', '?')}")
        print(f"    total_groups:   {res.get('total_groups', '?')}")
        print(f"    selected kept:  {len(selected)}")
        print(f"    dropped:        {res.get('total_photos', 0) - len(selected)}")

        if groups:
            print(f"\n  Groups detail:")
            for g in groups:
                gid = g.get("group_id", "?")
                gt = g.get("group_type", "portrait")
                ps = g.get("photos", [])
                print(f"    Group #{gid} ({gt}): {len(ps)} photos")
                for p in ps:
                    s = p.get("quality_score", "-")
                    fc = p.get("face_count", "-")
                    cat = p.get("category", "-")
                    cl = p.get("cluster_group_id", "?")
                    rk = p.get("rank_in_group", "?")
                    pu = p.get("processed_url", "")
                    ok = "RETOUCHED" if pu and "_retouch_failed" not in pu else "NO_RETOUCH"
                    print(f"      cluster={cl} rank={rk} score={s} face={fc} cat={cat} {ok}")

        if selected:
            print(f"\n  Selected photos list ({len(selected)}):")
            for i, p in enumerate(selected):
                s = p.get("quality_score", "-")
                fc = p.get("face_count", "-")
                cat = p.get("category", "-")
                cl = p.get("cluster_group_id", "?")
                rk = p.get("rank_in_group", "?")
                pu = p.get("processed_url", "")
                ok = "RETOUCHED" if pu and "_retouch_failed" not in pu else "NO_RETOUCH"
                print(f"    {i+1}. cluster={cl} rank={rk} score={s} face={fc} cat={cat} {ok}")

        # Download all photos
        print(f"\n  Downloading photos to {OUTPUT_DIR}...")
        total = 0
        for i, p in enumerate(selected):
            # Original
            orig_url = p.get("original_url", "")
            if orig_url:
                try:
                    r2 = await cli.get(orig_url, timeout=30.0)
                    if r2.status_code == 200:
                        (OUTPUT_DIR / f"photo_{i+1:02d}_original.jpg").write_bytes(r2.content)
                        total += 1
                        print(f"    [{i+1:02d}] original OK ({len(r2.content)/1024:.0f} KB)")
                    else:
                        print(f"    [{i+1:02d}] original HTTP {r2.status_code}")
                except Exception as e:
                    print(f"    [{i+1:02d}] original error: {e}")

            # Retouched
            proc_url = p.get("processed_url", "")
            if proc_url:
                try:
                    r2 = await cli.get(proc_url, timeout=30.0)
                    if r2.status_code == 200:
                        (OUTPUT_DIR / f"photo_{i+1:02d}_retouched.jpg").write_bytes(r2.content)
                        total += 1
                        print(f"    [{i+1:02d}] retouched OK ({len(r2.content)/1024:.0f} KB)")
                    else:
                        print(f"    [{i+1:02d}] retouched HTTP {r2.status_code}")
                except Exception as e:
                    print(f"    [{i+1:02d}] retouched error: {e}")

        print(f"\n{'='*60}")
        print(f"  E2E Test Complete!")
        print(f"  Output:  {OUTPUT_DIR}")
        print(f"  JSON:    result_summary.json")
        print(f"  Downloaded: {total} files")
        print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(run())
