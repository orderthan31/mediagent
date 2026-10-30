ARG BASE_IMAGE=mideagent-model-graph-base:85a311cb
FROM ${BASE_IMAGE}
ARG REVISION
LABEL org.opencontainers.image.revision=${REVISION}
USER 0
COPY packages/shared /app/packages/shared
COPY packages/tool-hub /app/packages/tool-hub
COPY agents /app/agents
COPY tools/media /app/tools/media
COPY tools/models /app/tools/models
COPY runtime/model-executor /app/runtime/model-executor
RUN pip install --no-cache-dir --no-deps /app/packages/shared /app/packages/tool-hub /app/agents /app/tools/media /app/tools/models /app/runtime/model-executor
USER 10001:10001
RUN python -c "import mideagent_model_runtime.broker, mideagent_agents.transcription.model_graph"
ENV PYTHONPATH="" LANGSMITH_TRACING=false LANGGRAPH_STRICT_MSGPACK=true
ENTRYPOINT ["python", "-m", "mideagent_model_runtime.broker"]
CMD []
