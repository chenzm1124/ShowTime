"""统一响应包装中间件

将所有 2xx JSON 响应自动包装为 { code: 0, message: "success", data: <body> } 格式，
与前端 request.ts 的 ApiResponse 约定对齐。

- 异常响应（全局异常处理器已返回 { code: -1, message, data: None }）不会被重复包装
- /docs /redoc /openapi.json 等文档路径跳过
- 非 JSON 响应（文件下载等）跳过
"""

import json

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_SKIP_PATHS = ("/docs", "/redoc", "/openapi.json")


class UnifiedResponseMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        if any(request.url.path.startswith(p) for p in _SKIP_PATHS):
            return response

        if not (200 <= response.status_code < 300):
            return response

        # 读取响应体
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # 已经是统一格式（含 code 字段）则不重复包装
        if isinstance(data, dict) and "code" in data:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        wrapped = {"code": 0, "message": "success", "data": data}
        # 清除原始 Content-Length，让 Response 根据新 body 自动计算
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=json.dumps(wrapped, ensure_ascii=False, default=str),
            status_code=response.status_code,
            headers=headers,
            media_type="application/json",
        )
