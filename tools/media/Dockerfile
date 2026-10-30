# CPU media family. BuildKit media_base context is the root media-base stage.
# No API, database driver, Google SDK, FaceFusion or Torch.
FROM media_base AS runtime
COPY packages/shared /app/packages/shared
COPY packages/tool-hub /app/packages/tool-hub
COPY agents /app/agents
COPY tools/media /app/tools/media
COPY tools/models /app/tools/models
RUN pip install --no-cache-dir /app/packages/shared /app/packages/tool-hub /app/agents /app/tools/media \
    && useradd --uid 10001 --create-home media \
    && mkdir -p /data/content && chown -R media:media /data
USER media
# JSON-line instances receive explicit commands on private stdin, never scan a queue.
ENTRYPOINT ["mideagent-media-instance"]

# Optional network transport; the default CPU image remains SDK-free.
FROM runtime AS amqp
USER root
RUN pip install --no-cache-dir '/app/packages/shared[objects,amqp]'
USER media
ENTRYPOINT ["mideagent-media-amqp"]

FROM amqp AS local-models
USER root
RUN pip install --no-cache-dir /app/tools/models '/app/tools/media[local-models]'
ENV HOME=/tmp HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
USER media
ENTRYPOINT ["mideagent-local-models"]

FROM runtime AS default
