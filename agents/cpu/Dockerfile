# CPU media family. No API, database driver, Google SDK, FaceFusion or Torch.
FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY packages/shared /app/packages/shared
COPY agents/cpu /app/agents/cpu
RUN pip install --no-cache-dir /app/packages/shared /app/agents/cpu \
    && useradd --uid 10001 --create-home media \
    && mkdir -p /data/content && chown -R media:media /data
USER media
# JSON-line instances receive explicit commands on private stdin, never scan a queue.
ENTRYPOINT ["mideagent-cpu-instance"]
