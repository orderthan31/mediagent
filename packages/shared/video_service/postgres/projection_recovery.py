"""Explicit model-free reprojection of committed held transcripts. Never resumes source jobs."""

import hashlib
import json
import wave
from pathlib import Path
from uuid import uuid4

from psycopg.types.json import Jsonb

from .. import packed_projection
from ..audio_clock import registered_clock
from ..cpu_agents import canonical, digest
from ..long_audio_budget import read_clock, validate_command
from . import Conflict, Missing
from .execution import public
from .registry import resource_id

LIMIT = 16 * 1024 * 1024


class ProjectionRecovery:
    def __init__(self, runtime):
        self.runtime = runtime

    def _facts(self, job_id, run_id):
        with self.runtime.database.connection() as db:
            job = self.runtime._shared_job(db, job_id)
            run = db.execute(
                "SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (job["owner_id"], job_id, resource_id(run_id)),
            ).fetchone()
            if not run or run["node_type"] != "transcribe":
                raise Missing("보존된 전사 실행을 찾을 수 없습니다.")
            command = run["request"]
            result = run.get("result") or {}
            meta = result.get("transcription", {})
            held = meta.get("projection", {})
            if (
                job["status"] != "failed"
                or job["cancel_requested"]
                or run["status"] != "failed"
                or job["generation"] != run["generation"]
                or meta.get("input_error") != "packed_projection_failed"
                or held.get("status") != "held"
                or meta.get("status") != "failed"
                or digest(command) != run["request_sha256"]
            ):
                raise Conflict("확정된 후처리 실패 전사만 별도 재투영할 수 있습니다.")
            delivery = db.execute(
                "SELECT * FROM agent_deliveries WHERE owner_id=%s AND job_id=%s AND node_run_id=%s",
                (job["owner_id"], job_id, run_id),
            ).fetchone()
            inbox = db.execute(
                "SELECT payload_sha256 FROM message_inbox WHERE consumer=%s AND message_id=%s",
                ("result:" + job["owner_id"], run_id),
            ).fetchone()
            raw = (delivery or {}).get("result") or {}
            if (
                not delivery
                or delivery["status"] != "completed"
                or delivery["command_sha256"] != run["request_sha256"]
                or raw.get("request_sha256") != run["request_sha256"]
                or any(
                    raw.get(key) != command[key]
                    for key in ["run_id", "attempt_id", "generation", "agent"]
                )
                or digest(raw.get("transcription", {})) != digest(meta)
                or not inbox
                or inbox["payload_sha256"] != digest(raw)
            ):
                raise Conflict("응답/commit이 불명인 전사는 자동 복구하지 않습니다.")
            uncertain = db.execute(
                "SELECT count(*) AS count FROM model_chunk_attempts a JOIN model_chunk_cache c USING(owner_id,context_sha256) WHERE a.owner_id=%s AND a.job_id=%s AND a.node_run_id=%s AND (a.status NOT IN ('completed','failed') OR c.status<>'completed')",
                (job["owner_id"], job_id, run_id),
            ).fetchone()["count"]
            if uncertain:
                raise Conflict("응답/commit이 불명인 구간이 남아 있습니다.")
            policy = command.get("transcription", {}).get("clock_policy")
            if policy not in {
                "packed_projection_v2",
                "packed_projection_v5",
            } or policy != command["options"].get("clock_policy"):
                raise Conflict(
                    "원래 명시된 projection 정책이 필요합니다. 옛 티켓은 승격하지 않습니다."
                )
            budget = validate_command(command)
            if bool(budget) != (policy == "packed_projection_v5"):
                raise Conflict("원래 clock/역할 예산이 맞지 않습니다.")
            binding = {
                "job_id": job_id,
                "source_run_id": run_id,
                "source_generation": run["generation"],
                "snapshot_sha256": job["snapshot_sha256"],
                "request_sha256": run["request_sha256"],
                "source_result_sha256": digest(result),
                "accepted_result_sha256": inbox["payload_sha256"],
                "policy": policy,
                "packed_transcript": held["packed_transcript"],
                "clock": command["inputs"]["timeline"],
                "audio": command["inputs"]["audio"],
                "projector_sha256": hashlib.sha256(
                    Path(packed_projection.__file__).read_bytes()
                ).hexdigest(),
                "limits": {
                    "transcript_bytes": LIMIT,
                    "trace_bytes": LIMIT,
                    "audio_bytes": budget["inputs"]["audio"]
                    if budget
                    else 256 * 1024 * 1024,
                    "clock_bytes": budget["inputs"]["timeline"]
                    if budget
                    else 1024 * 1024,
                },
                "original_failure": "packed_projection_failed",
                "model_calls": 0,
                "source_job_unchanged": True,
            }
            if (
                meta.get("timeline_sha256") != binding["clock"]["sha256"]
                or meta.get("audio", {}).get("sha256") != binding["audio"]["sha256"]
            ):
                raise Conflict("원래 전사 입력 SHA 결속을 확인할 수 없습니다.")
            return job["owner_id"], binding

    def _compute(self, owner, binding):
        refs = {
            "packed_transcript": "transcript",
            "clock": "timeline_map",
            "audio": "audio",
        }
        caps = {
            "packed_transcript": LIMIT,
            "clock": binding["limits"]["clock_bytes"],
            "audio": binding["limits"]["audio_bytes"],
        }
        for key, kind in refs.items():
            ref = binding[key]
            if (
                not isinstance(ref, dict)
                or ref.get("type") != kind
                or type(ref.get("bytes")) is not int
                or not 0 < ref["bytes"] <= caps[key]
            ):
                raise Conflict("보존 자료의 역할별 크기/종류가 맞지 않습니다.")
        # Store verifies complete bytes/SHA; streaming WAV checks run outside source job locks.
        path = self.runtime.store.path(owner, binding["audio"])
        with wave.open(str(path), "rb") as audio:
            frames = audio.getnframes()
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (
                1,
                2,
                16000,
            ):
                raise Conflict("원래 PCM 오디오 계약과 다릅니다.")
            maximum = 21600 if binding["policy"] == "packed_projection_v5" else 300
            if not 0 < frames <= maximum * 16000:
                raise Conflict("원래 오디오 프레임 한도를 넘었습니다.")
            remaining = frames
            while remaining:
                size = min(remaining, 16000)
                if len(audio.readframes(size)) != size * 2:
                    raise Conflict("오디오 프레임이 불완전합니다.")
                remaining -= size
        clock_value = json.loads(
            self.runtime.store.read(owner, binding["clock"], limit=caps["clock"])
        )
        spans = (
            read_clock(clock_value, audio_sha256=binding["audio"]["sha256"])
            if binding["policy"] == "packed_projection_v5"
            else registered_clock(clock_value, audio_sha256=binding["audio"]["sha256"])
        )
        if (
            round(
                packed_projection.validate_projection_clock(
                    spans, policy=binding["policy"]
                )
                * 16000
            )
            != frames
        ):
            raise Conflict("clock과 실제 PCM 프레임이 다릅니다.")
        source = json.loads(
            self.runtime.store.read(owner, binding["packed_transcript"], limit=LIMIT)
        )
        rows, trace = packed_projection.project(source, spans, policy=binding["policy"])
        trace.update(
            packed_transcript=binding["packed_transcript"],
            audio_sha256=binding["audio"]["sha256"],
            timeline_sha256=binding["clock"]["sha256"],
            recovery_source_run_id=binding["source_run_id"],
            source_result_sha256=binding["source_result_sha256"],
            projector_sha256=binding["projector_sha256"],
        )
        raw = canonical(rows)
        trace["output_transcript_sha256"] = hashlib.sha256(raw).hexdigest()
        trace_raw = canonical(trace)
        if not 0 < len(raw) <= LIMIT or not 0 < len(trace_raw) <= LIMIT:
            raise Conflict("재투영 산출물의 직렬화 한도를 넘었습니다.")
        return {"transcript": raw, "trace": trace_raw}, len(rows)

    def _get(self, db, owner, job, identity, *, lock=False):
        row = db.execute(
            "SELECT * FROM projection_recoveries WHERE owner_id=%s AND job_id=%s AND id=%s"
            + (" FOR UPDATE" if lock else ""),
            (owner, job, resource_id(identity)),
        ).fetchone()
        if not row:
            raise Missing("재투영 확인 기록을 찾을 수 없습니다.")
        return row

    def list(self, actor, job_id):
        with self.runtime.database.connection() as db:
            job = self.runtime._shared_job(db, job_id)
            sources = db.execute(
                "SELECT id FROM node_runs WHERE owner_id=%s AND job_id=%s AND node_type='transcribe' AND result->'transcription'->'projection'->>'status'='held' ORDER BY id",
                (job["owner_id"], job_id),
            ).fetchall()
            history = db.execute(
                "SELECT * FROM projection_recoveries WHERE owner_id=%s AND job_id=%s ORDER BY created_at",
                (job["owner_id"], job_id),
            ).fetchall()
        candidates = []
        for row in sources:
            try:
                _, binding = self._facts(job_id, row["id"])
                candidates.append(
                    {"source_run_id": row["id"], "eligible": True, "binding": binding}
                )
            except (Conflict, Missing):
                candidates.append(
                    {
                        "source_run_id": row["id"],
                        "eligible": False,
                        "reason": "확정된 보존 전사/clock/실패 결속을 확인해야 합니다. 자동 재호출하지 않습니다.",
                    }
                )
        return {
            "can_manage": actor == job["owner_id"],
            "candidates": candidates,
            "operations": [public(row) for row in history],
        }

    def preview(self, actor, job_id, run_id, *, policy):
        owner, binding = self._facts(job_id, run_id)
        if actor != owner:
            raise PermissionError("실행자만 별도 재투영을 확인할 수 있습니다.")
        if policy != binding["policy"]:
            raise Conflict("원래 정책만 재투영합니다. 자동 승격하지 않습니다.")
        raw, count = self._compute(owner, binding)
        binding["expected_outputs"] = {
            key: {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
            for key, value in raw.items()
        }
        binding["segment_count"] = count
        context = digest(binding)
        if self._facts(job_id, run_id)[1] != {
            key: value
            for key, value in binding.items()
            if key not in {"expected_outputs", "segment_count"}
        }:
            raise Conflict("원본 실패 기록이 바뀌었습니다.")
        with self.runtime.database.connection() as db:
            db.execute(
                "INSERT INTO projection_recoveries(owner_id,job_id,id,source_node_run_id,context_sha256,binding) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(owner_id,job_id,context_sha256) DO NOTHING",
                (owner, job_id, uuid4().hex, run_id, context, Jsonb(binding)),
            )
            row = db.execute(
                "SELECT * FROM projection_recoveries WHERE owner_id=%s AND job_id=%s AND context_sha256=%s",
                (owner, job_id, context),
            ).fetchone()
        return public(row)

    def confirm(self, actor, job_id, identity, *, context_sha256, acknowledge):
        if acknowledge is not True:
            raise Conflict(
                "원래 실패 유지와 모델 호출 없는 재투영을 명시적으로 확인하세요."
            )
        with self.runtime.database.connection() as db:
            job = self.runtime._shared_job(db, job_id)
            if actor != job["owner_id"]:
                raise PermissionError("실행자만 별도 재투영을 확인할 수 있습니다.")
            row = self._get(db, job["owner_id"], job_id, identity)
        if row["context_sha256"] != context_sha256:
            raise Conflict("미리보기 결속이 다릅니다.")
        if row["status"] != "prepared":
            return public(row)  # Completed exact reuse; running/held NEVER replay.
        owner, current = self._facts(job_id, row["source_node_run_id"])
        original = {
            key: value
            for key, value in row["binding"].items()
            if key not in {"expected_outputs", "segment_count"}
        }
        if current != original:
            raise Conflict("원본/정책/코드가 바뀌었습니다. 다시 확인하세요.")
        raw, count = self._compute(owner, current)
        if count != row["binding"]["segment_count"] or any(
            {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
            != row["binding"]["expected_outputs"][key]
            for key, value in raw.items()
        ):
            raise Conflict("미리보기 결과 SHA와 다릅니다.")
        # Own row only. Commit durable one-shot admission BEFORE CAS writes, never source mutation.
        with self.runtime.database.connection() as db:
            locked = self._get(db, owner, job_id, identity, lock=True)
            if locked["status"] != "prepared":
                return public(locked)
            db.execute(
                "UPDATE projection_recoveries SET status='running',admitted_by=%s,admitted_at=now() WHERE owner_id=%s AND job_id=%s AND id=%s",
                (actor, owner, job_id, identity),
            )
        try:
            outputs = {
                key: self.runtime.store.put(
                    owner,
                    [value],
                    "transcript" if key == "transcript" else "metadata",
                    max_bytes=LIMIT,
                )
                for key, value in raw.items()
            }
            if self._facts(job_id, row["source_node_run_id"])[1] != current:
                raise Conflict("원래 실패 기록이 바뀌었습니다.")
            with self.runtime.database.connection() as db:
                result = db.execute(
                    "UPDATE projection_recoveries SET status='completed',outputs=%s,completed_at=now() WHERE owner_id=%s AND job_id=%s AND id=%s AND status='running' RETURNING *",
                    (Jsonb(outputs), owner, job_id, identity),
                ).fetchone()
            return public(result)
        except (ValueError, OSError):
            with self.runtime.database.connection() as db:
                result = db.execute(
                    "UPDATE projection_recoveries SET status='held',error_code='projection_recovery_unverified',completed_at=now() WHERE owner_id=%s AND job_id=%s AND id=%s AND status='running' RETURNING *",
                    (owner, job_id, identity),
                ).fetchone()
            return public(result)

    def file(self, actor, job_id, identity, port):
        if port not in {"transcript", "trace"}:
            raise Missing("지원되는 복구 산출물이 아닙니다.")
        with self.runtime.database.connection() as db:
            job = self.runtime._shared_job(db, job_id)
            row = self._get(db, job["owner_id"], job_id, identity)
        if row["status"] != "completed":
            raise Conflict("확정된 복구 산출물이 아닙니다.")
        return self.runtime.store.path(job["owner_id"], row["outputs"][port])

    def material(self, actor, job_id, run_id, part):
        if part not in {"packed_transcript", "clock", "audio"}:
            raise Missing("지원되는 보존 자료가 아닙니다.")
        owner, binding = self._facts(job_id, run_id)
        return self.runtime.store.path(owner, binding[part])
