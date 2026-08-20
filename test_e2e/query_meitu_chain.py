# -*- coding: utf-8 -*-
"""从后端日志提取美图云修接口调用记录

提取:
- chain_id (美图任务链ID)
- 接口调用时间 (submit/API响应时间)
- 接口返回结果时间 (callback回调时间)
"""
import re
import os
from datetime import datetime
from collections import defaultdict

LOG_DIR = "backend"

# 美图日志模式
SUBMIT_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?\[meitu_pro\] API 响应:.*?"chain_id":\s*"(\d+)"'
)
CALLBACK_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?回调原始数据:.*?"chain_id":\s*"(\d+)"'
)
# 也匹配失败回调
CALLBACK_FAIL_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?callback_failed.*?photo_id=(\d+).*?error'
)


def parse_logs():
    """从所有 backend 日志中提取美图调用记录"""
    submit_records = {}  # chain_id -> submit_time
    callback_records = defaultdict(list)  # chain_id -> [callback_times]

    log_files = []
    for f in os.listdir(LOG_DIR):
        if f.endswith(".log") or f.endswith(".copy.log"):
            log_files.append(os.path.join(LOG_DIR, f))

    for logf in log_files:
        try:
            with open(logf, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    # 提交记录 (API 响应包含 chain_id)
                    m = SUBMIT_RE.search(line)
                    if m:
                        ts, chain_id = m.group(1), m.group(2)
                        submit_records[chain_id] = ts
                        continue

                    # 回调记录
                    m = CALLBACK_RE.search(line)
                    if m:
                        ts, chain_id = m.group(1), m.group(2)
                        callback_records[chain_id].append(ts)
                        continue
        except Exception as e:
            print(f"WARN: failed to read {logf}: {e}")

    return submit_records, callback_records


def main():
    print(f"\n{'='*100}")
    print(f"  美图云修接口调用记录 (最近30次任务关联)")
    print(f"{'='*100}")

    submit_records, callback_records = parse_logs()

    if not submit_records:
        print("\n  未找到任何美图接口调用记录")
        print("  提示: 检查 backend/ 目录下是否有包含 [meitu_pro] 的日志文件")
        return

    # 按提交时间排序
    sorted_submits = sorted(submit_records.items(), key=lambda x: x[1], reverse=True)

    print(f"\n  共找到 {len(sorted_submits)} 次美图接口提交记录")
    print(f"  共找到 {sum(len(v) for v in callback_records.values())} 次回调记录\n")

    print(f"  {'#':<4} {'chain_id':<20} {'调用时间':<22} {'返回结果时间':<22} {'耗时':<10}")
    print(f"  {'-'*80}")

    for i, (chain_id, submit_time) in enumerate(sorted_submits[:30]):
        cbs = callback_records.get(chain_id, [])
        if cbs:
            # 取最早的回调时间
            cb_time = min(cbs)
            try:
                st = datetime.strptime(submit_time, "%Y-%m-%d %H:%M:%S")
                ct = datetime.strptime(cb_time, "%Y-%m-%d %H:%M:%S")
                duration = (ct - st).total_seconds()
                dur_str = f"{duration:.0f}s"
            except ValueError:
                dur_str = "N/A"
            cb_display = cb_time
        else:
            cb_display = "未收到回调"
            dur_str = "超时/失败"

        print(f"  {i+1:<4} {chain_id:<20} {submit_time:<22} {cb_display:<22} {dur_str:<10}")

    print(f"\n{'='*100}")
    print(f"  说明:")
    print(f"  - chain_id: 美图云修接口返回的任务链ID")
    print(f"  - 调用时间: 提交照片到美图接口的时间 (API 响应包含 chain_id)")
    print(f"  - 返回结果时间: 美图回调通知处理完成的时间")
    print(f"  - 若显示'未收到回调', 说明该次调用超时或失败 (如90002鉴权错误)")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()
