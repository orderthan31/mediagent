# Optional legacy media image. Heavy engines never enter the API/CPU images.
FROM media_base AS runtime
ARG WITH_NVIDIA_VAD=0
ARG WITH_FACEFUSION=0
ARG VAD_TORCH_VERSION=2.14.0+cpu
ARG VAD_TORCHAUDIO_VERSION=2.11.0+cpu
ARG VAD_TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
COPY scripts/download-vad-model.py /app/scripts/download-vad-model.py
RUN if [ "$WITH_FACEFUSION" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends curl git libgl1 libglib2.0-0 \
      && rm -rf /var/lib/apt/lists/* \
      && git clone --depth 1 --branch 3.9.0 https://github.com/facefusion/facefusion.git /opt/facefusion \
      && test "$(git -C /opt/facefusion rev-parse HEAD)" = "6b318a94a64c1e4300e8ed03efbc3151114bc4e6" \
      && python -m venv /opt/facefusion-env \
      && sed '/^onnxruntime==/d' /opt/facefusion/requirements.txt > /tmp/facefusion-requirements.txt \
      && /opt/facefusion-env/bin/pip install --no-cache-dir -r /tmp/facefusion-requirements.txt \
      && /opt/facefusion-env/bin/pip install --no-cache-dir 'onnxruntime-gpu[cuda,cudnn]==1.24.4' 'nvidia-cublas-cu12==12.9.1.4'; \
    fi
RUN if [ "$WITH_NVIDIA_VAD" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends build-essential libsndfile1 \
      && rm -rf /var/lib/apt/lists/* \
      && pip install --no-cache-dir "torch==$VAD_TORCH_VERSION" "torchaudio==$VAD_TORCHAUDIO_VERSION" --index-url "$VAD_TORCH_INDEX_URL" \
      && pip install --no-cache-dir 'nemo_toolkit[asr]==3.0.0' \
      && python /app/scripts/download-vad-model.py /opt/models/vad_multilingual_marblenet.nemo; \
    fi
COPY packages/shared /app/packages/shared
COPY agents/media /app/agents/media
RUN pip install --no-cache-dir /app/packages/shared /app/agents/media \
    && useradd --uid 10001 --create-home media \
    && mkdir -p /data/video-jobs /data/job-databases && chown -R media:media /data
USER media
ENV VIDEO_STORAGE_ROOT=/data/video-jobs
# Legacy consumer's own safety gate still applies; this is not renewal fleet control.
CMD ["python", "-m", "media_agent.agent"]
