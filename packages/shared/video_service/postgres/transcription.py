"""Registered timed ASR uses the already-admitted finite candidate runner."""

import re

from ..audio_contract import audio_info, timed_segments
from ..model_endpoints import GeminiAudioAdapter, OpenAIAudioAdapter
from ..model_profile import supports_transcription
from .translation import TranslationRuntime


class TranscriptionRuntime(TranslationRuntime):
    role = "transcription"

    def available(self, pin):
        return supports_transcription(
            pin, pin["protocol"], pin["remote_model"]
        ) and super().available(pin)

    def make_adapter(self, pin, key):
        adapter_type = (
            GeminiAudioAdapter if pin["protocol"] == "gemini" else OpenAIAudioAdapter
        )
        return adapter_type(
            pin["endpoint"],
            transport=self.transport_factory(),
            approved_origins=self.approved_origins,
            api_key=key,
        )

    def transcribe(
        self, pins, audio, *, source_language, cancelled, record, paid_authorized=False
    ):
        info = audio_info(audio)
        if not isinstance(source_language, str) or not re.fullmatch(
            r"auto|[a-z]{2,3}", source_language
        ):
            raise ValueError("지원되는 전사 언어를 선택하세요.")
        return self._run(
            pins,
            invoke=lambda adapter, pin: adapter.transcribe(
                pin["remote_model"], audio, source_language
            ),
            decode=lambda result: timed_segments(result, info["duration_seconds"]),
            cancelled=cancelled,
            record=record,
            paid_authorized=paid_authorized,
        )

    def transcribe_batched(
        self,
        pins,
        audio,
        *,
        source_language,
        cancelled,
        record,
        persist,
        load,
        ledger,
        max_calls,
        paid_authorized=False,
    ):
        """Explicit batched path; persistent ledger required, short wire unchanged."""
        import hashlib
        from copy import deepcopy

        from ..audio_batches import RATE, split_normalized_audio
        from ..cpu_agents import canonical
        from ..model_endpoints import EndpointFailure
        from ..transcript_input import parse_segments
        from .model_batches import ModelCallBudgetExceeded

        if (
            pins != ledger.command["transcription"]["candidates"]
            or max_calls != ledger.max_calls
        ):
            raise ValueError("batched_audio_requires_exact_frozen_budget_and_models")
        if not isinstance(source_language, str) or not re.fullmatch(
            r"auto|[a-z]{2,3}", source_language
        ):
            raise ValueError("지원되는 전사 언어를 선택하세요.")
        source_sha = hashlib.sha256(audio).hexdigest()
        if source_sha != ledger.command["inputs"]["audio"]["sha256"]:
            raise ValueError("batched_audio_source_does_not_match_formal_command")
        receipts, attempts, combined = [], [], []
        reused, previous_end = 0, 0

        def result(status, error=None):
            selected = receipts[-1]["selected"] if receipts else None
            return {
                "status": status,
                "attempts": deepcopy(attempts),
                "selected": selected,
                "segments": combined if status == "completed" else None,
                "chunks": deepcopy(receipts),
                "call_count": ledger.call_count(),
                "reused_chunks": reused,
                "input_error": error,
            }

        for batch in split_normalized_audio(audio):
            if cancelled():
                return result("cancelled")
            start, end = round(batch.start * RATE), round(batch.end * RATE)
            if start != previous_end or end <= start:
                raise ValueError("audio_frame_coverage_gap_or_overlap")
            previous_end = end
            context = {
                "version": 1,
                "role": "transcription",
                "source_sha256": source_sha,
                "input_sha256": batch.sha256,
                "clock_sha256": ledger.command["inputs"]["timeline"]["sha256"],
                "span_unit": "pcm_frame",
                "span_start": start,
                "span_end": end,
                "source_language": source_language,
                "target_language": None,
                "candidates": pins,
            }

            def validated(value, batch=batch):
                rows = timed_segments(value, batch.end - batch.start)
                previous = 0
                for row in rows:
                    if row["start"] < previous:
                        raise EndpointFailure("전사 구간이 중복되거나 순서가 다릅니다.")
                    previous = row["end"]
                return rows

            with ledger.chunk(
                context, verify=lambda reference: validated(load(reference))
            ) as chunk:
                cached = chunk.output is not None
                if cached:
                    local = validated(load(chunk.output))
                    reused += 1
                else:
                    already = {item["candidate_index"] for item in chunk.attempts}
                    indices = [
                        index for index in range(len(pins)) if index not in already
                    ]
                    if not indices:
                        return result("failed", "model_candidates_already_settled")
                    pending = [pins[index] for index in indices]

                    def intent(
                        values,
                        indices=tuple(indices),
                        chunk=chunk,
                        batch=batch,
                        start=start,
                        end=end,
                    ):
                        if values:
                            last = values[-1]
                            original = indices[last["index"]]
                            if last["status"] == "started" and chunk.call_id is None:
                                chunk.start(original, pins[original])
                            elif (
                                last["status"] == "failed" and chunk.call_id is not None
                            ):
                                chunk.fail(last["error"])
                            elif (
                                last["status"] == "cancelled"
                                and chunk.call_id is not None
                            ):
                                chunk.fail("cancelled")
                            progress = [
                                {
                                    **item,
                                    "index": indices[item["index"]],
                                    "chunk_index": batch.chunk_index,
                                    "status": "response_received"
                                    if item["status"] == "completed"
                                    else item["status"],
                                }
                                for item in values
                            ]
                            record(
                                deepcopy(
                                    receipts
                                    + [
                                        {
                                            "chunk_index": batch.chunk_index,
                                            "span_start": start,
                                            "span_end": end,
                                            "input_sha256": batch.sha256,
                                            "status": "in_progress",
                                            "attempts": progress,
                                        }
                                    ]
                                )
                            )

                    try:
                        response = self._run(
                            pending,
                            invoke=lambda adapter, pin, batch=batch: adapter.transcribe(
                                pin["remote_model"], batch.audio, source_language
                            ),
                            decode=validated,
                            cancelled=cancelled,
                            record=intent,
                            paid_authorized=paid_authorized,
                            before_http=chunk.before_http,
                        )
                    except ModelCallBudgetExceeded:
                        return result("failed", "model_call_budget_exhausted")
                    attempts.extend(
                        {
                            **item,
                            "index": indices[item["index"]],
                            "chunk_index": batch.chunk_index,
                        }
                        for item in response["attempts"]
                    )
                    if response["status"] != "completed":
                        return result(response["status"])
                    if cancelled():
                        chunk.fail("cancelled")
                        return result("cancelled")
                    local = validated(response["segments"])
                    output = persist(batch.chunk_index, local)
                    chunk.complete(output, chunk.active_pin)
                identity = {
                    key: chunk.selected[key]
                    for key in (
                        "model_id",
                        "revision",
                        "connection_id",
                        "connection_revision",
                        "remote_model",
                        "protocol",
                    )
                }
                receipts.append(
                    {
                        "chunk_index": batch.chunk_index,
                        "span_start": start,
                        "span_end": end,
                        "input_sha256": batch.sha256,
                        "output": deepcopy(chunk.output),
                        "selected": identity,
                        "status": "completed",
                        "reused": cached,
                    }
                )
                record(deepcopy(receipts))
                combined.extend(
                    {
                        **row,
                        "id": hashlib.sha256(
                            (chunk.key + ":" + str(index)).encode()
                        ).hexdigest()[:32],
                        "start": row["start"] + batch.start,
                        "end": row["end"] + batch.start,
                    }
                    for index, row in enumerate(local)
                )
                parse_segments(canonical(combined))
        return result("completed")
