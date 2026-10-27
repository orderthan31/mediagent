ARG BASE_IMAGE=mideagent-model-graph-base:85a311cb
FROM ${BASE_IMAGE}
ARG REVISION
LABEL org.opencontainers.image.revision=${REVISION}
USER 0
COPY packages/shared/video_service/audio_contract.py packages/shared/video_service/packed_projection.py packages/shared/video_service/transcript_input.py packages/shared/video_service/object_store.py /usr/local/lib/python3.12/site-packages/video_service/
COPY agents/models/src/mideagent_models /usr/local/lib/python3.12/site-packages/mideagent_models
USER 10001:10001
RUN python -c "import mideagent_models.broker, mideagent_models.transcription"
ENV PYTHONPATH="" LANGSMITH_TRACING=false LANGGRAPH_STRICT_MSGPACK=true
ENTRYPOINT ["python", "-m", "mideagent_models.broker"]
CMD []
