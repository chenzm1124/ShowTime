FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 系统依赖（asyncpg / cryptography / wechatpy 等需要的编译工具）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Poetry
ENV POETRY_VERSION=1.8.4 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry

# 复制依赖文件
COPY pyproject.toml ./

# 安装依赖（不安装 dev 依赖以减小体积）
RUN poetry install --only main --no-root

# 复制源码
COPY . .

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令（生产模式：无 --reload 热重载；需要更高并发时可用 gunicorn 替换）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
