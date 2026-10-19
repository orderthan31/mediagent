# API-only image. FFmpeg remains an API dependency for legacy upload/preview paths.
# It does not install any agent package, FaceFusion, Torch or provider SDK.
FROM python:3.12-slim-bookworm AS api
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*
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

# Default builds remain API-only, not the legacy compatibility image.
FROM api AS runtime
