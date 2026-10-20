# Optional GPU tools. Never part of default API/CPU builds; never a queue consumer.
FROM media_base AS runtime
ARG WITH_NVIDIA_VAD=0
ARG WITH_FACEFUSION=0
# A GPU operator must select a matching torch/torchaudio/CUDA wheel set explicitly.
# Old mismatched CPU defaults have intentionally been removed.
ARG VAD_TORCH_VERSION
ARG VAD_TORCHAUDIO_VERSION
ARG VAD_TORCH_INDEX_URL
COPY agents/gpu/models.py /app/gpu-model-install.py
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
      test -n "$VAD_TORCH_VERSION" && test -n "$VAD_TORCHAUDIO_VERSION" && test -n "$VAD_TORCH_INDEX_URL" \
      && apt-get update && apt-get install -y --no-install-recommends build-essential libsndfile1 \
      && rm -rf /var/lib/apt/lists/* \
      && pip install --no-cache-dir "torch==$VAD_TORCH_VERSION" "torchaudio==$VAD_TORCHAUDIO_VERSION" --index-url "$VAD_TORCH_INDEX_URL" \
      && pip install --no-cache-dir 'nemo_toolkit[asr]==3.0.0' \
      && python /app/gpu-model-install.py /opt/models/vad_multilingual_marblenet.nemo; \
    fi
COPY agents/gpu /app/agents/gpu
RUN pip install --no-cache-dir /app/agents/gpu \
    && useradd --uid 10001 --create-home media
USER media
# Entry points consume an explicit engine request, never inspect DBs or poll jobs.
CMD ["mideagent-gpu-vad", "--help"]
