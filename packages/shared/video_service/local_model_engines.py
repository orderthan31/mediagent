"""Explicit offline model engines; no registry lookup, env key or remote fallback.

Callers must supply a pinned model digest from their admitted runtime descriptor.
These engine functions alone are not an AMQP adapter or workflow admission.
"""

import hashlib
import json
from pathlib import Path
from .transcript_input import parse_segments


ALLOWED = {
    "model.bin",
    "config.json",
    "tokenizer.json",
    "vocabulary.txt",
    "shared_vocabulary.json",
    "source.spm",
    "target.spm",
}


def model_identity(directory):
    root = Path(directory)
    if root.is_symlink() or not (root / "model.bin").is_file():
        raise ValueError("explicit_local_model_required")
    value = hashlib.sha256()
    for path in sorted(root.iterdir()):
        if path.name not in ALLOWED:
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("invalid_model_artifact")
        value.update(path.name.encode())
        with path.open("rb") as stream:
            value.update(
                bytes.fromhex(hashlib.file_digest(stream, "sha256").hexdigest())
            )
    return value.hexdigest()


def checked(directory, expected):
    root = Path(directory).resolve()
    if model_identity(root) != expected:
        raise ValueError("local_model_pin_changed")
    return root


def transcribe(audio, *, model_dir, model_digest, language):
    root = checked(model_dir, model_digest)
    if language != "en" or not Path(audio).is_file():
        raise ValueError("tiny_en_requires_explicit_english_audio")
    import wave
    import numpy as np

    # The agent input contract is normalized PCM16 mono/16kHz, not arbitrary
    # media decoding. Feed the supported ndarray API; PyAV19 removed the file
    # metadata_errors option used by faster-whisper1.2.1's generic decoder.
    with wave.open(str(audio), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (
            1,
            2,
            16000,
        ) or not 0 < stream.getnframes() <= 16000 * 300:
            raise ValueError("bounded_16khz_mono_pcm16_required")
        samples = (
            np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(
                np.float32
            )
            / 32768
        )
    from faster_whisper import WhisperModel

    model = WhisperModel(
        str(root),
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        num_workers=1,
        local_files_only=True,
    )
    segments, information = model.transcribe(
        samples,
        language=language,
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    result = [
        {
            "start": float(segment.start),
            "end": float(segment.end),
            "text": segment.text.strip(),
        }
        for segment in segments
        if segment.text.strip()
    ]
    parse_segments(json.dumps(result).encode())
    if model_identity(root) != model_digest:
        raise ValueError("local_model_changed_during_inference")
    return result


def translate(
    segments,
    *,
    model_dir,
    model_digest,
    source_tokenizer,
    target_tokenizer,
    source_language,
    target_language,
):
    root = checked(model_dir, model_digest)
    if (source_language, target_language) != ("en", "de"):
        raise ValueError("installed_opus_model_supports_en_de_only")
    paths = [Path(source_tokenizer).resolve(), Path(target_tokenizer).resolve()]
    if any(
        path.parent != root or path.name not in {"source.spm", "target.spm"}
        for path in paths
    ):
        raise ValueError("tokenizer_must_belong_to_pinned_model")
    source_segments = parse_segments(json.dumps(segments).encode())
    import ctranslate2
    import sentencepiece

    source = sentencepiece.SentencePieceProcessor(model_file=str(paths[0]))
    target = sentencepiece.SentencePieceProcessor(model_file=str(paths[1]))
    engine = ctranslate2.Translator(
        str(root), device="cpu", compute_type="int8", inter_threads=1, intra_threads=2
    )
    results = engine.translate_batch(
        [source.encode(segment.text, out_type=str) for segment in source_segments],
        beam_size=4,
        max_batch_size=8,
    )
    translated = [
        {**row, "text": target.decode(result.hypotheses[0])}
        for row, result in zip(segments, results)
    ]
    parse_segments(json.dumps(translated).encode())
    if model_identity(root) != model_digest:
        raise ValueError("local_model_changed_during_inference")
    return translated
