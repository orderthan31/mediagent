ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG REVISION
LABEL org.opencontainers.image.revision=${REVISION}
USER 0
COPY packages/shared/video_service/audio_contract.py packages/shared/video_service/packed_projection.py packages/shared/video_service/transcript_input.py packages/shared/video_service/object_store.py /usr/local/lib/python3.12/site-packages/video_service/
COPY agents/models /opt/mideagent-models
USER 10001:10001
RUN python -m pip install --no-cache-dir --user --no-deps --no-build-isolation /opt/mideagent-models
ENV PYTHONPATH="" LANGSMITH_TRACING=false LANGGRAPH_STRICT_MSGPACK=true
ENTRYPOINT ["python", "-m", "mideagent_models.broker"]
CMD []
