# Shared CPU-media stage: immutable build layers, not a running media service.
ARG PYTHON_BASE_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_BASE_IMAGE} AS media-base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# API composition includes deterministic business goals, not an LLM framework/inference engine.
FROM media-base AS api
ENV LITELLM_LOCAL_MODEL_COST_MAP=True CUSTOM_TIKTOKEN_CACHE_DIR=/opt/mideagent/tokenizers
COPY packages/shared /app/packages/shared
COPY packages/tool-hub /app/packages/tool-hub
COPY agents /app/agents
COPY tools/media /app/tools/media
COPY tools/models /app/tools/models
COPY apps/orchestrator /app/apps/orchestrator
COPY runtime/controlnet /app/runtime/controlnet
COPY apps/api /app/apps/api
RUN pip install --no-cache-dir '/app/packages/shared[postgres,models]' /app/packages/tool-hub /app/agents /app/tools/media /app/tools/models /app/apps/orchestrator /app/runtime/controlnet /app/apps/api \
    && python -m mideagent_model_tools.sdk_cache /opt/mideagent/tokenizers \
    && useradd --uid 10001 --create-home media \
    && mkdir -p /data/content && chown -R media:media /data
USER media
# No automatic migration, provider or queue consumer is started by this image.
CMD ["python", "-m", "app.server", "--bootstrap-file", "/run/bootstrap/api.json"]

# Explicit broker/object transport image; API startup still consumes no queue.
FROM api AS broker
USER root
RUN pip install --no-cache-dir '/app/packages/shared[objects,amqp]'
USER media

# Default builds remain API-only, not the explicit broker image.
FROM api AS runtime
