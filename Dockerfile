# syntax=docker/dockerfile:1
# TravelMind 运行镜像：FastAPI + SSE + 静态前端（前端无需构建，直接由后端挂载）
# 构建：docker build -t travelmind:latest .
# 运行：docker run --rm -p 8766:8766 --env-file .env.local -v travelmind-data:/app/data travelmind:latest

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 依赖单独一层：只改业务代码时不会触发重装
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 运行期只需要 app / frontend / run.py；tests、evaluation、docs 不进镜像
COPY app ./app
COPY frontend ./frontend
COPY run.py ./

# SQLite 落在 /app/data，必须在切换非 root 用户前建好并授权
RUN mkdir -p /app/data \
    && useradd --create-home --uid 10001 travelmind \
    && chown -R travelmind:travelmind /app

USER travelmind

EXPOSE 8766

# slim 镜像没有 curl，用标准库探活
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8766/api/health', timeout=3).getcode() == 200 else 1)"

# 配置通过 --env-file / -e 传入（AMAP_API_KEY、DEEPSEEK_API_KEY、JWT_SECRET 等）；
# 不要把 .env.local 烘进镜像。
CMD ["python", "run.py"]
