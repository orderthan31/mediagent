import hashlib
import io
import wave

import pytest


def speech_case():
    memory = io.BytesIO()
    with wave.open(memory, "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        out.writeframes(b"\0\0" * 16000)
    raw = memory.getvalue()
    task = {"version": 2, "role_policy_version": 2, "task_id": "a" * 32, "role": "transcription",
            "audio": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
            "models": [{"model_id": "b" * 32, "revision": 1, "pin_sha256": "d" * 64},
                       {"model_id": "c" * 32, "revision": 2, "pin_sha256": "e" * 64}],
            "chunk_frames": 16000, "max_calls": 2,
            "timeline": [{"packed_start": 0, "packed_end": 1, "source_start": 3, "source_end": 4}]}
    calls = [{"chunk_index": 0, "input_sha256": hashlib.sha256(raw).hexdigest(), "model": task["models"][0], "status": "failed", "error_code": "rate_limited"},
             {"chunk_index": 1, "input_sha256": hashlib.sha256(raw).hexdigest(), "model": task["models"][1], "status": "completed", "response": []}]
    return task, raw, calls


def test_receiver_reconstructs_actual_asr_candidate_and_rejects_fabricated_model():
    from video_service.role_receipts import speech_receipts

    task, raw, calls = speech_case()
    packed, chunks = speech_receipts(task, raw, calls)
    assert packed == []
    assert chunks[0]["candidate_index"] == 1
    assert chunks[0]["model"] == task["models"][1]
    for tamper in [{"status": "unknown"}, {"status": "started"}, {"status": "completed", "response": []}, {"error_code": "auth"}, {"model": task["models"][1]}]:
        with pytest.raises(ValueError):
            speech_receipts(task, raw, [{**calls[0], **tamper}, calls[1]])


def test_receiver_empty_translation_has_no_provider_receipt_or_selection():
    from video_service.role_receipts import translation_receipts

    task = {"models": [{"model_id": "a"}], "max_calls": 1}
    assert translation_receipts(task, [], []) == ([], [])
    with pytest.raises(ValueError):
        translation_receipts(task, [], [{"chunk_index": 0, "status": "completed"}])


def test_receiver_translation_revalidates_expansion_from_known_response():
    import json
    from video_service.role_receipts import translation_receipts
    from video_service.transcript_batches import split_transcript

    source = [{"id": 1, "start": 0, "end": 1, "speaker": "A", "text": "hi"}]
    batch = list(split_transcript(source, policy_version=2))[0]
    task = {"models": [{"model_id": "a"}, {"model_id": "b"}], "max_calls": 2}
    text = "한" * 7000
    calls = [{"chunk_index": 0, "input_sha256": batch.sha256, "model": task["models"][0], "status": "completed", "response": json.dumps([text], ensure_ascii=False)}]
    rows, chunks = translation_receipts(task, source, calls)
    assert rows == [{**source[0], "text": text}] and chunks[0]["candidate_index"] == 0
    assert translation_receipts(task, source, calls) == (rows, chunks)
    assert len(calls) == 1
