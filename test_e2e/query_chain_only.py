# -*- coding: utf-8 -*-
"""仅从日志提取最近30次美图云修接口调用记录

不依赖数据库任务匹配，直接按日志出现顺序提取:
- chain_id (美图任务链ID)
- 调用时间 (提交到美图接口 / API 响应时间)
- 返回结果时间 (回调时间 / 成功或失败)
- 结果状态
"""
import re
import os

LOG_DIR = "backend"

SUBMIT_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?\[meitu_pro\] API 响应:.*?"chain_id":\s*"(\d+)"'
)
CALLBACK_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?回调原始数据:.*?"chain_id":\s*"(\d+)"'
    r'.*?"status":\s*"(\w+)"(?:.*?"error_code":\s*(\d+))?'
)


def load_logs():
    submits = {}       # chain_id -> submit_time
    callbacks = {}     # chain_id -> (time, status, error_code)
    photo_map = {}     # chain_id -> photo_id (from trace logs)

    for f in sorted(os.listdir(LOG_DIR)):
        if not (f.endswith(".log") or f.endswith(".copy.log")):
            continue
        try:
            with open(os.path.join(LOG_DIR, f), "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    m = SUBMIT_RE.search(line)
                    if m:
                        submits[m.group(2)] = m.group(1)
                        continue
                    m = CALLBACK_RE.search(line)
                    if m:
                        cid, ts, status, errcode = m.group(2), m.group(1), m.group(3), m.group(4)
                        callbacks[cid] = (ts, status, errcode or "")
                        continue
                    # photo_id 映射
                    pm = re.search(r'photo_id=(\d+).*?event=submit', line)
                    if pm:
                        pass  # 可选
        except Exception:
            pass

    return submits, callbacks


def main():
    print(f"\n{'='*100}")
    print(f"  美图云修接口调用记录 (按日志时间倒序, 最近30次)")
    print(f"{'='*100}")

    submits, callbacks = load_logs()

    # 合并所有 chain_id，按提交时间排序
    all_cids = set(submits.keys()) | set(callbacks.keys())
    sorted_cids = sorted(all_cids, key=lambda c: submits.get(c, "0000"), reverse=True)

    print(f"\n  总提交记录: {len(submits)} | 总回调记录: {len(callbacks)}\n")

    print(f"  {'#':<4} {'chain_id':<20} {'调用时间':<21} {'结果时间':<21} {'状态':<12} {'耗时'}")
    print(f"  {'-'*90}")

    shown = 0
    for cid in sorted_cids:
        if shown >= 30:
            break
        st = submits.get(cid, "N/A")
        if cid in callbacks:
            cb_time, status, errcode = callbacks[cid]
            if st != "N/A" and cb_time != "N/A":
                try:
                    from datetime import datetime
                    d1 = datetime.strptime(st, "%Y-%m-%d %H:%M:%S")
                    d2 = datetime.strptime(cb_time, "%Y-%m-%d %H:%M:%S")
                    dur = f"{(d2-d1).total_seconds():.0f}s"
                except ValueError:
                    dur = "-"
            else:
                dur = "-"
            status_disp = f"{status}" + (f"({errcode})" if errcode else "")
        else:
            cb_time = "未收到回调"
            status_disp = "TIMEOUT/FAIL"
            dur = "-"

        shown += 1
        print(f"  {shown:<4} {cid:<20} {st:<21} {cb_time:<21} {status_disp:<12} {dur}")

    print(f"\n{'='*100}")
    print(f"  说明:")
    print(f"  - 每次调用美图接口都会记录日志 (meitu_pro.py 的 _trace / process_meitu_callback)")
    print(f"  - chain_id: 美图云修接口返回的任务链ID，用于追踪单次精修请求")
    print(f"  - 调用时间: 提交照片到美图接口并收到 chain_id 的时间")
    print(f"  - 结果时间: 美图回调通知处理完成（成功或失败）的时间")
    print(f"  - 90002 = GATEWAY_AUTHORIZED_ERROR (美图网关鉴权失败，需检查API Key/Account)")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()
