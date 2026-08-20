"""启动 FastAPI 后端（Windows 友好的 PowerShell 包装）。"""
import logging
import os
import sys

os.chdir(r"d:\个人\workbuddy工作区\travel-photo\backend")
sys.path.insert(0, r"d:\个人\workbuddy工作区\travel-photo\backend")

LOG_FILE = r"d:\个人\workbuddy工作区\travel-photo\backend\backend-restart.log"

# 关键：用 log_config=None 让 uvicorn 不接管 logger，
# 我们自己配置 root logger 把所有 INFO 输出到文件。
logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    encoding="utf-8",
    force=True,
)

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        workers=1,
        log_level="info",
        log_config=None,   # 禁用 uvicorn 接管 logger
    )