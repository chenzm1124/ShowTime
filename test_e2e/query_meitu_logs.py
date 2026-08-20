# -*- coding: utf-8 -*-
"""查询最近30次图片处理任务的美图云修接口调用记录

输出:
- 任务ID / 创建时间
- 美图 chain_id (从 extra_params 中提取)
- 接口调用时间 (task.created_at / started_at)
- 接口返回结果时间 (finished_at / photo 处理时间)
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join("backend", "travel_photo.db")

# 从 extra_params 中提取 meitu 相关信息
def extract_meitu_info(extra_params: str):
    """从任务 extra_params 中提取美图相关信息"""
    if not extra_params:
        return None
    try:
        extra = json.loads(extra_params)
    except (json.JSONDecodeError, TypeError):
        return None

    # 收集所有 selected_photos / groups 中的 processed_url 相关信息
    # meitu chain_id 可能不会直接存储，但我们可以从回调/提交日志中找
    info = {
        "selected_count": len(extra.get("selected_photos", [])),
        "group_count": len(extra.get("groups", [])),
    }
    return info


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 检查表结构
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
    if not cur.fetchone():
        print("ERROR: tasks table not found")
        conn.close()
        return

    # 查询最近30次任务
    cur.execute("""
        SELECT id, user_id, status, total_count, processed_count, failed_count,
               location, retouch_style, extra_params, created_at, started_at, finished_at
        FROM tasks
        ORDER BY created_at DESC
        LIMIT 30
    """)
    rows = cur.fetchall()

    print(f"\n{'='*100}")
    print(f"  最近30次图片处理任务 - 美图云修接口调用记录")
    print(f"{'='*100}")
    print(f"  数据库: {DB_PATH}")
    print(f"  查询到任务数: {len(rows)}\n")

    for i, row in enumerate(rows):
        (task_id, user_id, status, total_count, processed_count, failed_count,
         location, retouch_style, extra_params, created_at, started_at, finished_at) = row

        meitu_info = extract_meitu_info(extra_params)

        print(f"  [{i+1:02d}] Task ID: {task_id}")
        print(f"       用户: {user_id} | 状态: {status}")
        print(f"       创建时间:   {created_at}")
        print(f"       开始处理:   {started_at or 'N/A'}")
        print(f"       完成时间:   {finished_at or 'N/A'}")
        print(f"       照片数: {total_count} | 成功: {processed_count} | 失败: {failed_count}")
        print(f"       地点: {location or 'N/A'} | 风格: {retouch_style or 'N/A'}")

        # 从 extra_params 提取更多信息
        if extra_params:
            try:
                extra = json.loads(extra_params)
                # 查找是否有 meitu 相关的 chain_id 或 reqid 信息
                sp = extra.get("selected_photos", [])
                if sp:
                    print(f"       精选照片数: {len(sp)}")
                    # 检查第一张是否有 meitu 字段
                    first = sp[0]
                    meitu_fields = {k: v for k, v in first.items()
                                  if 'meitu' in k.lower() or 'chain' in k.lower() or 'reqid' in k.lower()}
                    if meitu_fields:
                        print(f"       美图字段: {meitu_fields}")
            except json.JSONDecodeError:
                print(f"       extra_params 解析失败")

        print()

    conn.close()


if __name__ == "__main__":
    main()
