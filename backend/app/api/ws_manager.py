"""WebSocket 推送管理器（实时精修进度推送）。

设计目标（用户需求）：
- 后端每完成一张照片精修，立即向前端推送该张完成事件（带完整结果）。
- 当该次任务所有被挑选出的照片都精修完成，推送一个「总任务完成」信号。

小程序端用 wx.connectSocket 原生支持 WebSocket；
后端用 FastAPI 的 websockets 支持。按 task_id 维度维护连接，
一个 task 可被多个前端（多端/重连）订阅。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Set

logger = logging.getLogger("ws_manager")


class WsManager:
    """按 task_id 维护 WebSocket 连接的轻量管理器。

    结构：{task_id(str): {WebSocket, ...}}。
    所有发送都是 fire-and-forget（best effort），单条发送失败不影响其它连接。
    """

    def __init__(self) -> None:
        self._conns: Dict[str, Set[object]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, task_id: str, ws: object) -> None:
        async with self._lock:
            self._conns.setdefault(task_id, set()).add(ws)
        logger.info(f"[ws] task_id={task_id} 新连接，当前连接数={len(self._conns[task_id])}")

    async def disconnect(self, task_id: str, ws: object) -> None:
        async with self._lock:
            conns = self._conns.get(task_id)
            if conns:
                conns.discard(ws)
                if not conns:
                    self._conns.pop(task_id, None)
        logger.info(f"[ws] task_id={task_id} 断开连接")

    async def send_to_task(self, task_id: str, payload: dict) -> None:
        """向某个 task 的所有订阅连接推送一条消息（best effort）。

        payload 必须是可 JSON 序列化的 dict。
        """
        msg = json.dumps(payload, ensure_ascii=False)
        async with self._lock:
            conns = set(self._conns.get(task_id, set()))
        if not conns:
            return
        dead: list[object] = []
        for ws in conns:
            try:
                await ws.send_text(msg)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[ws] 发送失败 task_id={task_id}: {e}")
                dead.append(ws)
        # 清理已失效连接
        if dead:
            async with self._lock:
                for ws in dead:
                    self._conns.get(task_id, set()).discard(ws)

    def has_subscriber(self, task_id: str) -> bool:
        return bool(self._conns.get(task_id))


# 全局单例
ws_manager = WsManager()
