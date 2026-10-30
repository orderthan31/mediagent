"""Purpose-pinned vocal decisions with durable per-call intent; no default egress."""

import hashlib
import json
from copy import deepcopy

from psycopg.types.json import Jsonb

from video_service.canonical import canonical, digest
from ..model_endpoints import EndpointFailure
from ..model_profile import supports_vocalization
from ..vocalization_endpoints import GeminiVocalizationAdapter
from ..vocalization_proposals import analyze
from .model_batches import ModelBatchLedger, ModelCallBudgetExceeded
from .translation import TranslationRuntime


class _Stop(ValueError):
    def __init__(self, status, error=None):
        self.status, self.error = status, error


class VocalizationRuntime(TranslationRuntime):
    role = "vocalization"

    def available(self, pin):
        return supports_vocalization(
            pin, pin["protocol"], pin["remote_model"]
        ) and super().available(pin)

    def make_adapter(self, pin, key):
        return GeminiVocalizationAdapter(
            pin["endpoint"],
            transport=self.transport_factory(),
            approved_origins=self.approved_origins,
            api_key=key,
        )

    def analyze(
        self,
        pins,
        audio,
        *,
        ledger,
        cancelled,
        record,
        persist,
        load,
        paid_authorized=False,
    ):
        config = ledger.command["vocalization"]
        if (
            ledger.kind != "vocalization"
            or pins != config["candidates"]
            or hashlib.sha256(audio).hexdigest()
            != ledger.command["inputs"]["audio"]["sha256"]
        ):
            raise ValueError("vocalization_requires_exact_frozen_command")
        binding = digest(config)
        receipts = []
        reused = 0

        def invoke(context, clips, schema):
            nonlocal reused
            if cancelled():
                raise _Stop("cancelled")
            bounded = {
                "version": 1,
                "role": "vocalization",
                "purpose": config["purpose"],
                "binding_sha256": binding,
                "source_sha256": context["source_sha256"],
                "input_sha256": digest(
                    {
                        "clips": context["clips"],
                        "instruction": context["instruction"],
                        "schema": schema,
                    }
                ),
                "clock_sha256": None,
                "span_unit": "pcm_frame",
                "span_start": min(x["start_frame"] for x in context["clips"]),
                "span_end": max(x["end_frame"] for x in context["clips"]),
                "source_language": config["source_language"],
                "target_language": None,
                "phase": context["phase"],
                "clips": context["clips"],
                "candidates": pins,
            }

            def verify(ref):
                return load(ref)

            with ledger.chunk(bounded, verify=verify) as chunk:
                cached = chunk.output is not None
                if cached:
                    answer = load(chunk.output)
                    reused += 1
                else:
                    used = {a["candidate_index"] for a in chunk.attempts}
                    indices = [i for i in range(len(pins)) if i not in used]
                    if not indices:
                        raise _Stop("failed", "model_candidates_already_settled")

                    def intent(values):
                        if values:
                            last = values[-1]
                            index = indices[last["index"]]
                            if last["status"] == "started" and chunk.call_id is None:
                                chunk.start(index, pins[index])
                            elif (
                                last["status"] == "failed" and chunk.call_id is not None
                            ):
                                chunk.fail(last["error"])
                            elif (
                                last["status"] == "cancelled"
                                and chunk.call_id is not None
                            ):
                                chunk.fail("cancelled")
                        record(
                            deepcopy(
                                receipts
                                + [
                                    {
                                        "phase": context["phase"],
                                        "call_index": context["call_index"],
                                        "attempts": values,
                                    }
                                ]
                            )
                        )

                    def send(adapter, pin):
                        if not self.available(pin):
                            raise EndpointFailure(
                                "Frozen vocal model is no longer available",
                                code="unavailable",
                            )
                        chunk.before_http()
                        return adapter.classify(
                            pin["remote_model"], context, clips, schema
                        )

                    try:
                        response = self._run(
                            [pins[i] for i in indices],
                            invoke=send,
                            decode=lambda value: value,
                            cancelled=cancelled,
                            record=intent,
                            paid_authorized=paid_authorized,
                            before_http=chunk.before_http,
                        )
                    except ModelCallBudgetExceeded:
                        raise _Stop("failed", "model_call_budget_exhausted") from None
                    if response["status"] != "completed":
                        errors = [
                            x.get("error")
                            for x in response["attempts"]
                            if x.get("error")
                        ]
                        raise _Stop(response["status"], errors[-1] if errors else None)
                    if cancelled():
                        chunk.fail("cancelled")
                        raise _Stop("cancelled")
                    answer = response["segments"]
                    ref = persist(context["call_index"], answer)
                    chunk.complete(ref, chunk.active_pin)
                receipts.append(
                    {
                        "phase": context["phase"],
                        "call_index": context["call_index"],
                        "output": deepcopy(chunk.output),
                        "selected": {
                            k: chunk.selected[k]
                            for k in (
                                "model_id",
                                "revision",
                                "connection_id",
                                "connection_revision",
                                "remote_model",
                                "protocol",
                            )
                        },
                        "reused": cached,
                        "status": "completed",
                    }
                )
                record(deepcopy(receipts))
                return answer

        try:
            outcome = analyze(
                audio,
                language=config["source_language"],
                strength=config["strength"],
                binding_sha256=binding,
                max_calls=config["max_model_calls"],
                invoke=invoke,
                cancelled=cancelled,
            )
            status, error = "completed", None
        except _Stop as stop:
            outcome = None
            status, error = stop.status, stop.error
        except ValueError as exc:
            if str(exc) not in {
                "vocalization_cancelled",
                "vocalization_call_budget_exhausted",
            }:
                raise
            outcome = None
            status = "cancelled" if str(exc) == "vocalization_cancelled" else "failed"
            error = str(exc)
        if cancelled():
            status, outcome = "cancelled", None
        return {
            "status": status,
            "error": error,
            "held": error
            in {"delivery_unknown", "transport_unknown", "timeout", "outcome_unknown"},
            "document": outcome["document"] if outcome else None,
            "chunks": deepcopy(receipts),
            "call_count": ledger.call_count(),
            "reused_chunks": reused,
            "purpose": config["purpose"],
            "scope": self.mode,
        }


def execute_vocalization(runtime, owner, command):
    config = command["vocalization"]
    executor = runtime.vocalization_runtime
    if executor is None:
        raise ValueError("registered_vocalization_not_enabled")

    def cancelled():
        with runtime.database.connection() as db:
            row = db.execute(
                "SELECT j.cancel_requested,j.generation,j.active_claim_id,n.claim_id,n.status,n.generation AS run_generation,n.request_sha256,n.lease_expires_at>now() AS live FROM jobs j JOIN node_runs n ON n.owner_id=j.owner_id AND n.job_id=j.id WHERE j.owner_id=%s AND j.id=%s AND n.id=%s",
                (owner, command["run_id"], command["attempt_id"]),
            ).fetchone()
        return (
            not row
            or row["cancel_requested"]
            or row["generation"] != command["generation"]
            or row["run_generation"] != command["generation"]
            or row["active_claim_id"] != row["claim_id"]
            or row["status"] != "running"
            or not row["live"]
            or row["request_sha256"] != digest(command)
        )

    def record(values):
        with runtime.database.connection() as db:
            changed = db.execute(
                "UPDATE agent_deliveries SET result=%s WHERE owner_id=%s AND job_id=%s AND node_run_id=%s AND status='started'",
                (
                    Jsonb({"vocalization": {"chunks": values}}),
                    owner,
                    command["run_id"],
                    command["attempt_id"],
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("vocalization_delivery_intent_missing")

    audio = runtime.store.read(
        owner, command["inputs"]["audio"], limit=300 * 32000 + 65536
    )
    ledger = ModelBatchLedger(
        runtime.database, owner, command, max_calls=config["max_model_calls"]
    )
    value = executor.analyze(
        config["candidates"],
        audio,
        ledger=ledger,
        cancelled=cancelled,
        record=record,
        persist=lambda index, answer: runtime.store.put(
            owner, [canonical(answer)], "metadata"
        ),
        load=lambda ref: json.loads(runtime.store.read(owner, ref)),
        paid_authorized=config["paid_authorized"],
    )
    outputs = {}
    if value["status"] == "completed" and not cancelled():
        outputs["regions"] = runtime.store.put(
            owner, [canonical(value["document"])], "audio_regions"
        )
    if cancelled():
        value.update(status="cancelled")
        outputs = {}
    return {
        **{
            k: command[k]
            for k in ("protocol_version", "run_id", "attempt_id", "generation", "agent")
        },
        "request_sha256": digest(command),
        "status": value["status"],
        "outputs": outputs,
        "transport": "registered_http",
        "vocalization": {k: v for k, v in value.items() if k != "document"},
    }
