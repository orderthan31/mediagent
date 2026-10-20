# Shared CPU-media stage: immutable build layers, not a running media service.
ARG PYTHON_BASE_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_BASE_IMAGE} AS media-base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# API still invokes upload/preview FFmpeg. No agent package or heavy engine here.
FROM media-base AS api
COPY packages/shared /app/packages/shared
COPY apps/api /app/apps/api
RUN pip install --no-cache-dir /app/packages/shared /app/apps/api \
    && useradd --uid 10001 --create-home media \
    && mkdir -p /data/video-jobs /data/job-databases && chown -R media:media /data
USER media
ENV VIDEO_STORAGE_ROOT=/data/video-jobs
# No automatic migration, provider or queue consumer is started by this image.
CMD ["python", "-m", "app.renewal_server"]

# Explicit compatibility target for the existing paused legacy Compose only.
# Its optional import coupling is retained until legacy admission is retired.
FROM api AS legacy-api
USER root
COPY agents/media /app/agents/media
RUN pip install --no-cache-dir /app/agents/media
USER media
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Explicit broker/object transport image; API startup still consumes no queue.
FROM api AS broker
USER root
RUN pip install --no-cache-dir '/app/packages/shared[objects,amqp]'
USER media

# Default builds remain API-only, not the legacy compatibility/broker image.
FROM api AS runtime
