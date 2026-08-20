# -*- coding: utf-8 -*-
"""综合查询: 最近30次任务 + 美图接口调用记录

关联:
1. SQLite 数据库 tasks 表 (任务基本信息 + 时间戳)
2. backend/*.log 日志 (美图 chain_id + 调用/回调时间)
"""
import sqlite3
import re
import os
from datetime import datetime
from collections import defaultdict

DB_PATH = os.path.join("backend", "travel_photo.db")
LOG_DIR = "backend"

SUBMIT_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?\[meitu_pro\] API 响应:.*?"chain_id":\s*"(\d+)"'
)
CALLBACK_OK_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?回调原始数据:.*?"chain_id":\s*"(\d+)"'
    r'.*?"status":\s*"success"'
)
CALLBACK_FAIL_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?回调原始数据:.*?"chain_id":\s*"(\d+)"'
    r'.*?error_code.*?(900\d+)'
)


def load_meitu_logs():
    """从日志加载美图调用记录，按时间排序"""
    submits = {}       # chain_id -> submit_time
    cbs_ok = defaultdict(list)   # chain_id -> [ok_times]
    cbs_fail = defaultdict(list) # chain_id -> [(time, error_code)]

    for f in os.listdir(LOG_DIR):
        if not (f.endswith(".log") or f.endswith(".copy.log")):
            continue
        try:
            with open(os.path.join(LOG_DIR, f), "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    m = SUBMIT_RE.search(line)
                    if m:
                        submits[m.group(2)] = m.group(1)
                        continue
                    m = CALLBACK_FAIL_RE.search(line)
                    if m:
                        cbs_fail[m.group(2)].append((m.group(1), m.group(3)))
                        continue
                    m = CALLBACK_OK_RE.search(line)
                    if m:
                        cbs_ok[m.group(2)].append(m.group(1))
        except Exception:
            pass

    return submits, cbs_ok, cbs_fail


def main():
    print(f"\n{'='*110}")
    print(f"  最近30次图片处理任务 - 美图云修接口调用记录")
    print(f"{'='*110}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, status, total_count, processed_count, failed_count,
               created_at, started_at, finished_at
        FROM tasks ORDER BY created_at DESC LIMIT 30
    """)
    tasks = cur.fetchall()
    conn.close()

    submits, cbs_ok, cbs_fail = load_meitu_logs()

    # 将美图调用记录按提交时间排序
    all_submits = sorted(submits.items(), key=lambda x: x[1], reverse=True)

    print(f"\n  数据库任务数: {len(tasks)}")
    print(f"  美图接口提交总数: {len(all_submits)}")
    print(f"  美图成功回调: {sum(len(v) for v in cbs_ok.values())}")
    print(f"  美图失败回调: {sum(len(v) for v in cbs_fail.values())}\n")

    print(f"  {'#':<4} {'TaskID':<8} {'时间':<20} {'美图chain_id':<20} {'调用时间':<20} {'结果时间':<20} {'状态'}")
    print(f"  {'-'*100}")

    # 匹配每个 task 的美图记录: 用 started_at 到 finished_at 时间窗口匹配
    for i, t in enumerate(tasks):
        (tid, uid, status, total, proc, fail, created, started, finished) = t
        started_s = (started or created or "")[:19]
        finished_s = (finished or "")[:19]

        # 找到该时间窗口内的美图调用
        window_chains = []
        for chain_id, st in all_submits:
            if started_s <= st <= (finished_s or st):
                window_chains.append(chain_id)

        if window_chains:
            for j, cid in enumerate(window_chains[:5]):  # 最多显示5个
                cb_ok = cbs_ok.get(cid, [])
                cb_fail = cbs_fail.get(cid, [])
                if cb_ok:
                    result_time = min(cb_ok)
                    result_status = "OK"
                elif cb_fail:
                    result_time = cb_fail[0][0]
                    result_status = f"FAIL({cb_fail[0][1]})"
                else:
                    result_time = "未回调"
                    result_status = "TIMEOUT"

                if j == 0:
                    print(f"  {i+1:<4} {tid:<8} {started_s:<20} {cid:<20} {submits[cid]:<20} {result_time:<20} {result_status}")
                else:
                    print(f"  {'':<4} {'':<8} {'':<20} {cid:<20} {submits[cid]:<20} {result_time:<20} {result_status}")
        else:
            print(f"  {i+1:<4} {tid:<8} {started_s:<20} {'无美图记录':<20} {'-':<20} {'-':<20} {'N/A'}")

    print(f"\n{'='*110}")
    print(f"  说明:")
    print(f"  - 数据库记录所有任务执行动作 (tasks 表)，含创建/开始/完成时间戳")
    print(f"  - 美图 chain_id 仅记录在运行日志 (backend/*.log)，未持久化到数据库")
    print(f"  - 调用时间 = 提交照片到美图接口的时间；结果时间 = 美图回调时间")
    print(f"  - 日志保留有限，较早任务的 chain_id 可能被覆盖")
    print(f"{'='*110}")


if __name__ == "__main__":
    main()
