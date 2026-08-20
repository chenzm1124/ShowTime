"""WebSocket 实时精修进度推送端点。

路由：/api/v1/ws/tasks/{task_id}
小程序端用 wx.connectSocket 连接，后端每完成一张推送 photo_done，
全部完成推送 task_completed（均带完整结果，前端无需再查接口）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.ws_manager import ws_manager

logger = logging.getLogger("ws")

router = APIRouter(prefix="/ws", tags=["ws"])

# 前端订阅后，后端先回一条 hello 确认连接已建立（便于前端判断连接可用性）
_HELLO = {
    "type": "connected",
    "message": "ws connected, waiting for retouch progress",
}


@router.websocket("/tasks/{task_id}")
async def task_ws(websocket: WebSocket, task_id: str) -> None:
    await websocket.accept()
    await ws_manager.connect(task_id, websocket)
    try:
        # 连接建立后先发 hello，确认链路
        await websocket.send_json(_HELLO)
        # 后端是「事件驱动」推送，这里只保持连接、消费前端可能发来的心跳/指令。
        # 前端若发送任意文本（如 ping），原样忽略即可。
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:  # noqa: BLE001
                # 前端不保证发心跳；receive 超时/异常即视为连接空闲，继续保活
                break
    finally:
        await ws_manager.disconnect(task_id, websocket)
