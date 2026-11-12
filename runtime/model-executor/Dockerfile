ARG BASE_IMAGE=mideagent-model-graph-base:85a311cb
FROM ${BASE_IMAGE}
ARG REVISION
LABEL org.opencontainers.image.revision=${REVISION}
USER 0
# Constrain every pre-existing distribution before resolving graph dependencies.
# A conflict with the declared pins must fail rather than upgrade the base stack.
RUN python -m pip freeze --all > /tmp/model-role-base-constraints.txt
COPY runtime/model-executor/requirements.txt /app/runtime/model-executor/requirements.txt
RUN python -m pip install --no-cache-dir \
    --constraint /tmp/model-role-base-constraints.txt \
    --requirement /app/runtime/model-executor/requirements.txt
COPY packages/shared /app/packages/shared
COPY packages/tool-hub /app/packages/tool-hub
COPY agents /app/agents
COPY tools/media /app/tools/media
COPY tools/models /app/tools/models
COPY runtime/model-executor /app/runtime/model-executor
# Provision PEP 517 backends in temporary build environments, not the base stack.
RUN python -m pip install --no-cache-dir --no-deps --force-reinstall \
    /app/packages/shared /app/packages/tool-hub /app/agents \
    /app/tools/media /app/tools/models /app/runtime/model-executor
ENV PYTHONPATH="" LANGSMITH_TRACING=false LANGGRAPH_STRICT_MSGPACK=true
USER 10001:10001
RUN python -I -c "import mideagent_model_runtime.broker, mideagent_agents.transcription.model_graph, mideagent_agents.translation.model_graph"
ENTRYPOINT ["python", "-m", "mideagent_model_runtime.broker"]
CMD []
