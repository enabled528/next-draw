FROM public.ecr.aws/docker/library/node:24-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run typecheck && npm run build

FROM ghcr.io/astral-sh/uv:0.11.14 AS uv
FROM public.ecr.aws/docker/library/python:3.11-slim-bookworm AS runtime
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 nextdraw && useradd --uid 10001 --gid nextdraw --create-home nextdraw
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend PATH=/app/.ExData/bin:$PATH \
    NEXT_DRAW_DATA=/app/data NEXT_DRAW_LAYA_DIR=/app/vendor/laya \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
    UV_CACHE_DIR=/tmp/uv-cache TZ=Asia/Shanghai
COPY requirements-linux-arm64.txt ./
RUN --mount=type=cache,target=/tmp/uv-cache uv venv --python /usr/local/bin/python .ExData \
    && uv pip install --python .ExData/bin/python --require-hashes --torch-backend cpu -r requirements-linux-arm64.txt
COPY backend/ ./backend/
COPY seed/ ./seed/
COPY vendor/laya/ ./vendor/laya/
COPY scripts/download_model.py ./scripts/download_model.py
RUN --mount=type=cache,target=/model-cache python scripts/download_model.py --cache-dir /model-cache
COPY --from=frontend /frontend/dist/client/ ./frontend/dist/client/
RUN mkdir /app/data && chown nextdraw:nextdraw /app/data
USER nextdraw
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()"
CMD ["uvicorn", "next_draw.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
