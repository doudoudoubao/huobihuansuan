FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 先装依赖，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY scripts/ ./scripts/
COPY run.py ./

RUN mkdir -p /app/data
VOLUME ["/app/data"]
ENV DB_PATH=/app/data/bot.db

# 非 root 运行
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

CMD ["python", "run.py"]
