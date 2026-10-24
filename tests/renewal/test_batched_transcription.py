"""Formal PG attempt + real >60s media, controlled Gemini wire; not ASR quality."""

import base64
import json
import subprocess
from copy import deepcopy

import httpx
from test_audio_batches import wav
from test_model_batch_ledger import admin as _admin
from test_model_batch_ledger import db as _db
from test_model_batch_ledger import formal_attempt
from video_service.audio_contract import audio_info
from video_service.cpu_agents import canonical
from video_service.postgres.model_batches import ModelBatchLedger
from video_service.postgres.transcription import TranscriptionRuntime

admin, db = _admin, _db


def test_long_gemini_sends_each_exact_wav_after_recording_intent_and_preserves_completed_chunk_files(
    db, admin, tmp_path
):
    assert callable(getattr(TranscriptionRuntime, "transcribe_batched", None))
    speech = tmp_path / "long-normalized.wav"
    speech.write_bytes(wav(121))
    video = tmp_path / "long-synthetic.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=5:d=121",
            "-i",
            str(speech),
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "pcm_s16le",
            "-shortest",
            str(video),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    (tmp_path / "store").mkdir()
    runtime, owner, command = formal_attempt(
        db, admin, video.read_bytes(), tmp_path / "store", filename=video.name
    )
    pins = command["transcription"]["candidates"]
    events, calls = [], []
    ledger = ModelBatchLedger(db, owner, command, max_calls=3)
    full_audio = runtime.store.read(
        owner, command["inputs"]["audio"], limit=16 * 1024 * 1024
    )

    def provider(request):
        assert request.method == "POST" and request.url.path.endswith(
            "/models/gemini-3.8-flash:generateContent"
        )
        with db.connection() as observer:
            started = observer.execute(
                "SELECT count(*) AS count FROM model_chunk_attempts WHERE owner_id=%s AND status='started'",
                (owner,),
            ).fetchone()["count"]
        assert started == 1, "real PG intent must commit before any outbound audio"
        body = json.loads(request.content)
        audio = base64.b64decode(body["contents"][0]["parts"][0]["inlineData"]["data"])
        duration = audio_info(audio)["duration_seconds"]
        calls.append(audio)
        result = [
            {"start": 0, "end": duration, "text": "controlled chunk " + str(len(calls))}
        ]
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": json.dumps(result)}]},
                    }
                ]
            },
        )

    runtime.transcription_runtime.transport_factory = lambda: httpx.MockTransport(
        provider
    )
    kwargs = {
        "source_language": "en",
        "cancelled": lambda: False,
        "record": lambda value: events.append(deepcopy(value)),
        "persist": lambda index, segments: runtime.store.put(
            owner, [canonical(segments)], "transcript"
        ),
        "load": lambda reference: json.loads(runtime.store.read(owner, reference)),
        "ledger": ledger,
        "max_calls": 3,
        "paid_authorized": False,
    }
    result = runtime.transcription_runtime.transcribe_batched(
        pins, full_audio, **kwargs
    )
    assert (
        result["status"] == "completed"
        and result["call_count"] == 3
        and len(calls) == 3
    )
    assert [(row["start"], row["end"]) for row in result["segments"]] == [
        (0, 60),
        (60, 120),
        (120, 121),
    ]
    assert len(result["chunks"]) == 3
    assert len({row["id"] for row in result["segments"]}) == len(result["segments"])
    assert all(len(row["id"]) == 32 for row in result["segments"])
    for chunk in result["chunks"]:
        assert chunk["status"] == "completed"
        assert json.loads(runtime.store.read(owner, chunk["output"]))
    reused = runtime.transcription_runtime.transcribe_batched(
        pins, full_audio, **kwargs
    )
    assert (
        reused["status"] == "completed"
        and reused["reused_chunks"] == 3
        and len(calls) == 3
    )
    assert reused["segments"] == result["segments"]


def test_batched_adapter_rechecks_original_guard_after_intent_before_sending_any_http(
    db, admin, tmp_path
):
    from contextlib import contextmanager

    import psycopg
    import pytest
    from test_execution import movie as movie_factory

    runtime, owner, command = formal_attempt(
        db, admin, movie_factory.__wrapped__(tmp_path), tmp_path
    )
    calls = []

    def provider(request):
        calls.append(True)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        [
                                            {
                                                "start": 0.1,
                                                "end": 0.2,
                                                "text": "unexpected after lost guard",
                                            }
                                        ]
                                    )
                                }
                            ]
                        },
                    }
                ]
            },
        )

    runtime.transcription_runtime.transport_factory = lambda: httpx.MockTransport(
        provider
    )

    class LostGuardLedger(ModelBatchLedger):
        @contextmanager
        def chunk(self, context, *, verify):
            with super().chunk(context, verify=verify) as guarded:
                start = guarded.start

                def intent_then_lose(*args):
                    call = start(*args)
                    with db.connection() as operator:
                        assert operator.execute(
                            "SELECT pg_terminate_backend(%s) AS terminated",
                            (guarded.db.info.backend_pid,),
                        ).fetchone()["terminated"]
                    return call

                guarded.start = intent_then_lose
                yield guarded

    ledger = LostGuardLedger(db, owner, command, max_calls=3)
    audio = runtime.store.read(owner, command["inputs"]["audio"])
    with pytest.raises(psycopg.Error):
        runtime.transcription_runtime.transcribe_batched(
            command["transcription"]["candidates"],
            audio,
            source_language="en",
            cancelled=lambda: False,
            record=lambda value: None,
            persist=lambda index, rows: runtime.store.put(
                owner, [canonical(rows)], "transcript"
            ),
            load=lambda reference: json.loads(runtime.store.read(owner, reference)),
            ledger=ledger,
            max_calls=3,
        )
    assert calls == [], (
        "a released/dead owner may not enter the real adapter after its SQL intent"
    )
    assert ledger.call_count() == 1
