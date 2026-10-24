"""Trusted application-side per-chunk cache and intent-before-HTTP budget ledger.

No provider keys, HTTP calls, automatic retries, or operating activation here.
"""

from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

from psycopg.types.json import Jsonb

from ..cpu_agents import digest
from . import Conflict
from .registry import resource_id


class ModelCallBudgetExceeded(ValueError):
    pass


class ModelBatchLedger:
    def __init__(self, database, owner, command, *, max_calls):
        resource_id(owner)
        if type(max_calls) is not int or not 1 <= max_calls <= 4096:
            raise ValueError("invalid_model_call_budget")
        self.database, self.owner, self.command = database, owner, deepcopy(command)
        self.job, self.attempt = command["run_id"], command["attempt_id"]
        self.command_sha = digest(command)
        self.max_calls = max_calls
        self.kind = {"transcribe": "transcription", "translate": "translation"}.get(
            command["agent"]["id"]
        )
        if self.kind is None or self.kind not in command:
            raise ValueError("model_budget_requires_registered_command")
        expected_policy = (
            "bounded_60s_v1" if self.kind == "transcription" else "bounded_100x16k_v1"
        )
        frozen = command[self.kind]
        if (
            frozen.get("batch_policy") != expected_policy
            or frozen.get("max_model_calls") != max_calls
        ):
            raise ValueError("model_call_budget_must_match_frozen_request")
        with database.connection() as db:
            self._live(db)
            row = db.execute(
                "SELECT snapshot FROM jobs WHERE owner_id=%s AND id=%s",
                (owner, self.job),
            ).fetchone()
            original = row["snapshot"]["inputs"]
            self.original_sha = (original.get("video") or original["transcript"])[
                "sha256"
            ]
            db.execute(
                "INSERT INTO model_call_budgets(owner_id,job_id,node_run_id,command_sha256,max_calls) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (owner, self.job, self.attempt, self.command_sha, max_calls),
            )
            budget = db.execute(
                "SELECT command_sha256,max_calls FROM model_call_budgets WHERE owner_id=%s AND job_id=%s AND node_run_id=%s",
                (owner, self.job, self.attempt),
            ).fetchone()
            if budget != {"command_sha256": self.command_sha, "max_calls": max_calls}:
                raise Conflict("호출 상한/정식 명령이 기존 실행과 다릅니다.")

    def _live(self, db):
        row = db.execute(
            "SELECT j.cancel_requested,j.generation AS job_generation,j.active_claim_id,n.generation,n.claim_id,n.status,n.request_sha256,n.lease_expires_at>now() AS live FROM jobs j JOIN node_runs n ON n.owner_id=j.owner_id AND n.job_id=j.id WHERE j.owner_id=%s AND j.id=%s AND n.id=%s",
            (self.owner, self.job, self.attempt),
        ).fetchone()
        if (
            not row
            or row["cancel_requested"]
            or row["generation"] != self.command["generation"]
            or row["job_generation"] != row["generation"]
            or row["active_claim_id"] != row["claim_id"]
            or row["status"] != "running"
            or not row["live"]
            or row["request_sha256"] != self.command_sha
        ):
            raise Conflict("취소/만료/변경된 모델 실행은 호출하지 않습니다.")

    def call_count(self):
        with self.database.connection() as db:
            return db.execute(
                "SELECT issued_count FROM model_call_budgets WHERE owner_id=%s AND job_id=%s AND node_run_id=%s",
                (self.owner, self.job, self.attempt),
            ).fetchone()["issued_count"]

    @contextmanager
    def chunk(self, context, *, verify):
        if (
            context.get("role") != self.kind
            or context.get("candidates") != self.command[self.kind]["candidates"]
        ):
            raise ValueError("chunk_context_does_not_match_frozen_model_pins")
        frozen = self.command[self.kind]
        port = "audio" if self.kind == "transcription" else "transcript"
        unit = "pcm_frame" if self.kind == "transcription" else "segment_index"
        clock = (
            self.command["inputs"]["timeline"]["sha256"]
            if self.kind == "transcription"
            else None
        )
        start, end = context.get("span_start"), context.get("span_end")
        maximum = 60 * 16000 if self.kind == "transcription" else 100
        total = 6 * 60 * 60 * 16000 if self.kind == "transcription" else 10000
        if (
            context.get("source_sha256") != self.command["inputs"][port]["sha256"]
            or context.get("clock_sha256") != clock
            or context.get("span_unit") != unit
            or context.get("source_language", frozen["source_language"])
            != frozen["source_language"]
            or context.get("target_language", frozen.get("target_language"))
            != frozen.get("target_language")
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= total
            or end - start > maximum
        ):
            raise ValueError("frozen_chunk_source_language_or_span_mismatch")
        context = {
            **deepcopy(context),
            "original_sha256": self.original_sha,
            "source_language": frozen["source_language"],
            "target_language": frozen.get("target_language"),
        }

        key = digest(context)
        lock = "model-chunk:" + self.owner + ":" + key
        with self.database.connection() as db:
            locked = db.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(current_schema()||%s,0)) AS locked",
                (lock,),
            ).fetchone()["locked"]
            if not locked:
                raise Conflict(
                    "동일 구간의 호출/저장이 진행 중입니다. 다시 호출하지 않습니다."
                )
            try:
                db.execute(
                    "INSERT INTO model_chunk_cache(owner_id,context_sha256,context) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                    (self.owner, key, Jsonb(context)),
                )
                row = db.execute(
                    "SELECT * FROM model_chunk_cache WHERE owner_id=%s AND context_sha256=%s",
                    (self.owner, key),
                ).fetchone()
                db.commit()
                if row["context"] != context:
                    raise Conflict("구간의 고정 문맥이 일치하지 않습니다.")
                if row["status"] == "started":
                    # Owning the same session guard proves no live caller still
                    # owns this intent. It does not prove whether it was billed.
                    db.execute(
                        "UPDATE model_chunk_attempts SET status='unknown',error_code='orphaned_model_intent',settled_at=now() WHERE owner_id=%s AND context_sha256=%s AND status='started'",
                        (self.owner, key),
                    )
                    db.execute(
                        "UPDATE model_chunk_cache SET status='held',updated_at=now() WHERE owner_id=%s AND context_sha256=%s AND status='started'",
                        (self.owner, key),
                    )
                    db.commit()
                if row["status"] not in ("prepared", "completed"):
                    raise Conflict(
                        "이 구간 응답/저장이 불명 또는 중단 상태입니다. 자동 재호출하지 않습니다."
                    )
                if row["status"] == "completed":
                    verify(row["output_ref"])
                yield _Chunk(self, db, key, context, row, verify)
            finally:
                db.rollback()
                db.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(current_schema()||%s,0))",
                    (lock,),
                )
                db.commit()


class _Chunk:
    def __init__(self, ledger, db, key, context, row, verify):
        self.ledger, self.db, self.key, self.context, self.verify = (
            ledger,
            db,
            key,
            context,
            verify,
        )
        self.output, self.selected = row["output_ref"], row["selected_pin"]
        self.call_id = None
        self.status = row["status"]
        self.active_pin = None
        self.attempts = self._attempts()

    def _attempts(self):
        return self.db.execute(
            "SELECT candidate_index,call_id,model_id,model_revision,connection_id,connection_revision,status,outcome_ref,error_code FROM model_chunk_attempts WHERE owner_id=%s AND context_sha256=%s ORDER BY candidate_index",
            (self.ledger.owner, self.key),
        ).fetchall()

    def before_http(self):
        if self.call_id is None or self.status != "started":
            raise Conflict("호출 전 영속 intent가 필요합니다.")
        self.ledger._live(self.db)
        lock = "model-chunk:" + self.ledger.owner + ":" + self.key
        row = self.db.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
            "AND pid=pg_backend_pid() AND granted AND objsubid=1 "
            "AND classid::bigint=((hashtextextended(current_schema()||%s,0)>>32)&4294967295) "
            "AND objid::bigint=(hashtextextended(current_schema()||%s,0)&4294967295)) AS owned",
            (lock, lock),
        ).fetchone()
        if not row["owned"]:
            raise Conflict("호출 전 원 guard 소유권이 유실되어 보류합니다.")

    def start(self, candidate_index, pin):
        if (
            self.status != "prepared"
            or self.call_id is not None
            or self.output is not None
            or type(candidate_index) is not int
            or not 0 <= candidate_index < len(self.context["candidates"])
            or pin != self.context["candidates"][candidate_index]
        ):
            raise Conflict("완료 구간/변경된 후보는 새로 호출하지 않습니다.")
        self.ledger._live(self.db)
        existing = self.db.execute(
            "SELECT status FROM model_chunk_attempts WHERE owner_id=%s AND context_sha256=%s AND candidate_index=%s",
            (self.ledger.owner, self.key, candidate_index),
        ).fetchone()
        if existing:
            raise Conflict("기록된 후보 호출은 자동 반복하지 않습니다.")
        spent = self.db.execute(
            "UPDATE model_call_budgets SET issued_count=issued_count+1 WHERE owner_id=%s AND job_id=%s AND node_run_id=%s AND issued_count<max_calls RETURNING issued_count",
            (self.ledger.owner, self.ledger.job, self.ledger.attempt),
        ).fetchone()
        if not spent:
            raise ModelCallBudgetExceeded("승인된 모델 호출 상한에 도달했습니다.")
        call_id = uuid4().hex
        self.db.execute(
            "INSERT INTO model_chunk_attempts(owner_id,context_sha256,candidate_index,call_id,job_id,node_run_id,model_id,model_revision,connection_id,connection_revision,pin_sha256,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.ledger.owner,
                self.key,
                candidate_index,
                call_id,
                self.ledger.job,
                self.ledger.attempt,
                pin["model_id"],
                pin["revision"],
                pin["connection_id"],
                pin["connection_revision"],
                digest(pin),
                "started",
            ),
        )
        self.db.execute(
            "UPDATE model_chunk_cache SET status='started',updated_at=now() WHERE owner_id=%s AND context_sha256=%s AND status='prepared'",
            (self.ledger.owner, self.key),
        )
        self.db.commit()
        self.call_id = call_id
        self.active_pin = deepcopy(pin)
        self.status = "started"
        return call_id

    def complete(self, output, selected):
        if self.call_id is None or selected != self.active_pin:
            raise Conflict("완료 전 호출 intent가 필요합니다.")
        self.verify(output)
        self.before_http()
        self.db.execute(
            "UPDATE model_chunk_attempts SET status='completed',outcome_ref=%s,settled_at=now() WHERE owner_id=%s AND call_id=%s AND status='started'",
            (Jsonb(output), self.ledger.owner, self.call_id),
        )
        self.db.execute(
            "UPDATE model_chunk_cache SET status='completed',output_ref=%s,selected_pin=%s,updated_at=now() WHERE owner_id=%s AND context_sha256=%s AND status='started'",
            (Jsonb(output), Jsonb(selected), self.ledger.owner, self.key),
        )
        self.db.commit()
        self.output, self.selected = deepcopy(output), deepcopy(selected)
        self.status, self.call_id = "completed", None
        self.attempts = self._attempts()

    def fail(self, code):
        from .translation import ADVANCE

        if self.call_id is None or self.status != "started":
            raise Conflict("호출 전 intent 없는 결과는 정산하지 않습니다.")
        if not isinstance(code, str) or not code or len(code) > 100:
            raise ValueError("invalid_model_failure_code")
        if code == "cancelled":
            outcome, state = "cancelled", "cancelled"
        elif code in {"delivery_unknown", "transport_unknown", "timeout"}:
            outcome, state = "unknown", "held"
        else:
            self.ledger._live(self.db)
            outcome, state = "failed", "prepared" if code in ADVANCE else "held"
        changed = self.db.execute(
            "UPDATE model_chunk_attempts SET status=%s,error_code=%s,settled_at=now() WHERE owner_id=%s AND call_id=%s AND status=%s",
            (outcome, code, self.ledger.owner, self.call_id, "started"),
        ).rowcount
        updated = self.db.execute(
            "UPDATE model_chunk_cache SET status=%s,updated_at=now() WHERE owner_id=%s AND context_sha256=%s AND status=%s",
            (state, self.ledger.owner, self.key, "started"),
        ).rowcount
        if changed != 1 or updated != 1:
            raise Conflict("구간 정산 상태가 변경됐습니다.")
        self.db.commit()
        self.call_id, self.active_pin, self.status = None, None, state
        self.attempts = self._attempts()
