"""Durable opt-in CPU orchestration. All effects require an exact owner/job claim.

No default DSN, legacy settings, background thread, queue scan or provider call.
Agents receive immutable commands, never a workflow or downstream agent address.
"""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

from psycopg.types.json import Jsonb

from ..cpu_agents import CPU_AGENTS, canonical, digest
from ..renewal_contracts import spec
from . import Conflict, Missing
from .intake import Intake, public_asset, request_id
from .registry import resource_id

CONTROL = frozenset({"select", "join", "review", "control_if", "control_switch"})
TERMINAL = frozenset(
    {"completed", "failed", "cancelled", "skipped", "blocked", "quarantined"}
)


def public(row):
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in row.items()}


class Execution(Intake):
    def __init__(
        self,
        database,
        store,
        *,
        agent_executor=None,
        fleet=None,
        engine_runtime_enabled=False,
        translation_runtime=None,
        transcription_runtime=None,
    ):
        super().__init__(database, store)
        self.agent_executor = agent_executor
        self.fleet = fleet
        self.engine_runtime_enabled = bool(engine_runtime_enabled)
        self.translation_runtime = translation_runtime
        self.transcription_runtime = transcription_runtime
        from .ticket_artifacts import TicketArtifacts
        self.ticket_artifacts = TicketArtifacts(store)

    def catalog(self):
        from ..renewal_contracts import catalog
        from .engine_runtimes import EngineRuntimes

        value = catalog()
        value["local_engine_transport_enabled"] = self.engine_runtime_enabled
        if not self.engine_runtime_enabled:
            return value
        with self.database.connection() as db:
            for node in value["nodes"]:
                if node["id"] not in {
                    "transcribe",
                    "translate",
                    "preprocess_audio",
                    "faceswap",
                }:
                    continue
                try:
                    row = EngineRuntimes.resolve_in(db, node["id"])
                except ValueError:
                    continue
                node["engine_runtime"] = {
                    key: row[key] for key in ["revision", "sha256", "descriptor"]
                }
                node["runtime_scope"] = "configuration_not_inference_readiness"
                node["workflow_binding"] = node["id"] != "faceswap"
                if node["id"] in {"transcribe", "translate"}:
                    node["execution"] = "engine_amqp"
        return value

    @staticmethod
    def _engine_role(node):
        if node["type"] in {"translate", "transcribe"} and node.get("model_ref"):
            return None
        if node["type"] in {"transcribe", "translate", "faceswap"}:
            return node["type"]
        if (
            node["type"] == "preprocess_audio"
            and node.get("options", {}).get("vad_mode") == "nvidia"
        ):
            return "preprocess_audio"
        return None

    def _engine_bindings(self, db, definition):
        from .engine_runtimes import EngineRuntimes

        bindings = {}
        if not self.engine_runtime_enabled:
            return bindings
        for node in definition["nodes"]:
            role = self._engine_role(node)
            if role:
                try:
                    row = EngineRuntimes.resolve_in(db, role)
                except ValueError:
                    continue
                bindings[node["id"]] = {
                    key: row[key] for key in ["revision", "sha256", "descriptor"]
                }
        return bindings

    def _execution_reasons(self, db, definition, bindings, options, done_nodes=(), model_bindings=None):
        from .engine_runtimes import EngineRuntimes

        reasons = []
        for node in definition["nodes"]:
            if node["id"] in done_nodes:
                continue
            role = self._engine_role(node)
            if node.get("model_ref"):
                pin = (model_bindings or {}).get(node["id"])
                kind = {"translate": "translation", "transcribe": "transcription"}.get(node["type"])
                executor = getattr(self, (kind or "unsupported") + "_runtime", None)
                if (executor is None or not pin
                        or not any(executor.available(p) for p in [pin, *pin.get("fallbacks", [])])):
                    reasons.append("등록 모델의 실행 transport/사용 가능한 후보 없음: " + node["id"])
            elif role:
                pin = bindings.get(node["id"])
                if not self.engine_runtime_enabled or not pin:
                    reasons.append("로컬 engine runtime 미설정: " + node["id"])
                    continue
                try:
                    row = EngineRuntimes.resolve_in(db, role, sha256=pin["sha256"])
                    if (
                        row["descriptor"] != pin["descriptor"]
                        or row["revision"] != pin["revision"]
                    ):
                        raise ValueError("runtime_revision_changed")
                except (ValueError, KeyError):
                    reasons.append("engine runtime pin/가용성 변경: " + node["id"])
                    continue
                descriptor = pin["descriptor"]
                if (
                    options is not None
                    and descriptor["source_language"] is not None
                    and options.get("source_language") != descriptor["source_language"]
                ):
                    reasons.append("설치 engine의 원문 언어 미지원: " + node["id"])
                if (
                    options is not None
                    and descriptor["target_language"] is not None
                    and options.get("target_language") != descriptor["target_language"]
                ):
                    reasons.append("설치 engine의 대상 언어 미지원: " + node["id"])
            elif node["type"] not in CPU_AGENTS | CONTROL:
                reasons.append("미지원 모델/제어 실행 경로: " + node["id"])
            elif (
                node["type"] == "preprocess_audio"
                and node.get("options", {}).get("audio_filter", "off") != "off"
            ):
                reasons.append("CPU 전처리는 필터 off만 지원: " + node["id"])
        return reasons

    def _job(self, db, owner, identity, *, lock=False):
        row = db.execute(
            "SELECT * FROM jobs WHERE owner_id=%s AND id=%s"
            + (" FOR UPDATE" if lock else ""),
            (owner, resource_id(identity)),
        ).fetchone()
        if not row:
            raise Missing("작업을 찾을 수 없습니다.")
        if digest(row["snapshot"]) != row["snapshot_sha256"]:
            raise Conflict("작업 snapshot 무결성 오류")
        return row

    def _runs(self, db, owner, identity):
        rows = db.execute(
            "SELECT n.*,d.result AS delivery_result FROM node_runs n LEFT JOIN agent_deliveries d ON d.owner_id=n.owner_id AND d.job_id=n.job_id AND d.node_run_id=n.id WHERE n.owner_id=%s AND n.job_id=%s ORDER BY n.started_at NULLS LAST,n.id",
            (owner, identity),
        ).fetchall()
        for row in rows:
            delivery = row.pop("delivery_result") or {}
            for kind in ("translation", "transcription"):
                if kind in delivery:
                    row[kind] = delivery[kind]
        return rows

    def _view(self, db, job):
        owner, identity = job["owner_id"], job["id"]
        from .dispatch_queue import DispatchQueue
        from .job_processing_review import JobProcessingReview
        processing_review = JobProcessingReview(self).capture_in(db, job)
        runs = DispatchQueue.decorate_in(db, self._runs(db, owner, identity))
        return {
            **public(job),
            "processing_review": processing_review,
            "runs": [public(r) for r in runs],
            "artifact_manifest": self.ticket_artifacts.summary(job, runs),
            "reviews": [
                public(r)
                for r in db.execute(
                    "SELECT * FROM review_tasks WHERE owner_id=%s AND job_id=%s ORDER BY id",
                    (owner, identity),
                )
            ],
        }

    def get(self, owner, identity):
        with self.database.connection() as db:
            return self._view(db, self._job(db, owner, identity, lock=True))

    def _shared_job(self, db, identity):
        rows = db.execute("SELECT * FROM jobs WHERE id=%s LIMIT 2 FOR UPDATE", (resource_id(identity),)).fetchall()
        if not rows:
            raise Missing("작업을 찾을 수 없습니다.")
        if len(rows) != 1:
            raise Conflict("작업 식별자가 중복되어 공용 조회할 수 없습니다.")
        if digest(rows[0]["snapshot"]) != rows[0]["snapshot_sha256"]:
            raise Conflict("작업 snapshot 무결성 오류")
        return rows[0]

    @staticmethod
    def _shared_view(state, actor):
        # Media/graph data is shared; credentials, execution claims and locators are not.
        keys = {"id", "ticket_number", "owner_id", "asset_id", "asset_owner_id", "workflow_id",
                "workflow_revision", "status", "revision", "generation", "snapshot_sha256",
                "parent_id", "created_at", "updated_at", "processing_review", "artifact_manifest"}
        value = {k: state[k] for k in keys if k in state}
        value["snapshot"] = {k: v for k, v in state["snapshot"].items()
                             if k in {"version", "asset", "inputs", "definition", "options", "recovery", "artifact_layout"}}
        value["snapshot_redacted"] = True
        value["executed_by"] = state["owner_id"]
        value["access"] = {"can_manage": actor == state["owner_id"]}
        run_keys = {"id", "node_id", "node_type", "status", "options", "inputs", "error_code",
                    "input_sha256", "settings_sha256", "attempt", "iteration", "generation",
                    "started_at", "completed_at", "result", "dispatch", "translation", "transcription"}
        value["runs"] = []
        for run in state.get("runs", []):
            public_run = {k: run[k] for k in run_keys if k in run}
            if run.get("result"):
                public_run["result"] = {k: v for k, v in run["result"].items()
                                        if k in {"status", "outputs", "previews", "reused_from", "translation", "transcription", "ticket_artifacts"}}
            value["runs"].append(public_run)
        review_keys = {"id", "node_run_id", "revision", "status", "draft", "contract"}
        value["reviews"] = [{k: v for k, v in r.items() if k in review_keys} for r in state.get("reviews", [])]
        return value

    def shared_get(self, actor, identity):
        with self.database.connection() as db:
            return self._shared_view(self._view(db, self._shared_job(db, identity)), actor)

    def shared_jobs(self, actor):
        with self.database.connection() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC,id,owner_id").fetchall()
            if len({r["id"] for r in rows}) != len(rows):
                raise Conflict("작업 식별자가 중복되어 공용 조회할 수 없습니다.")
            return [self._shared_view(self._view(db, self._job(db, r["owner_id"], r["id"], lock=True)), actor) for r in rows]

    def shared_file(self, actor, identity, run_id, port, *, inputs=False, preview=False):
        with self.database.connection() as db:
            job = self._shared_job(db, identity)
            state = self._view(db, job)
        run = next((r for r in state["runs"] if r["id"] == run_id), None)
        if not run or (not inputs and run["status"] != "completed"):
            raise Missing("완료된 산출물/고정 입력을 찾을 수 없습니다.")
        reference = run["inputs"].get(port) if inputs else (run["result"] or {}).get("outputs", {}).get(port)
        if not reference or (preview and reference["type"] != "video"):
            raise Missing("산출물/고정 입력을 찾을 수 없습니다.")
        if not inputs and self.ticket_artifacts.enabled(job):
            try:
                return self.ticket_artifacts.output(job, state['runs'], run_id, port, preview=preview)
            except Missing:
                if not preview:
                    raise
                # A verified pass-through output may reuse its preserved source WebM.
                # Manifest/hash failures are not caught and raw MP4 is never substituted.
                return self._video_preview_state(state, reference), reference['type']
        path = self._video_preview_state(state, reference) if preview else self.store.path(job["owner_id"], reference)
        return path, reference["type"]

    def shared_manifest(self, actor, identity):
        with self.database.connection() as db:
            job = self._shared_job(db, identity)
            runs = self._runs(db, job['owner_id'], job['id'])
            return self.ticket_artifacts.read(job, runs)

    def jobs(self, owner):
        with self.database.connection() as db:
            ids=[r['id'] for r in db.execute("SELECT id FROM jobs WHERE owner_id=%s ORDER BY created_at DESC,id",(owner,))]
        # Release each row lock separately; never hold child then parent list locks.
        return [self.get(owner,identity) for identity in ids]

    def inspect(self, owner, identity, revision):
        definition = self.job_definition(owner, identity, revision)
        reasons = []
        with self.database.connection() as db:
            bindings = self._engine_bindings(db, definition)
            workflow_owner, _ = self._job_definition(db, owner, identity, revision)
            models = self._bindings(db, workflow_owner, definition, active=False)
            reasons += [
                {"node_id": None, "message": message}
                for message in self._execution_reasons(db, definition, bindings, None, model_bindings=models)
            ]
        if definition["inputs"] not in ({"video": "video"}, {"transcript": "transcript"}):
            reasons.append(
                {
                    "node_id": None,
                    "message": "현재 작업 입력은 검증된 원본 video 하나입니다. 추가 자료 binding이 필요합니다.",
                }
            )
        if self.fleet is not None:
            with self.database.connection() as db:
                reasons += [
                    {"node_id": None, "message": message}
                    for message in self.fleet.reasons(
                        db,
                        [
                            n["type"]
                            for n in definition["nodes"]
                            if not self._engine_role(n)
                        ],
                    )
                ]
        return {
            "supported": not reasons,
            "definition_revision": revision,
            "model_ready": not reasons,
            "summary": [
                {k: n[k] for k in ("id", "type", "options")}
                for n in definition["nodes"]
            ],
            "reasons": reasons,
            "notice": "포트 계약과 등록된 로컬 runtime 조회입니다. 실제 입력·소유권·언어·엔진 실행 검증은 별도입니다.",
        }

    def create(
        self,
        owner,
        asset_id,
        definition_id,
        definition_revision,
        *,
        request_id,
        options=None,
        parent_id=None,
        paid_confirmed=False,
    ):
        globals()["request_id"](request_id)
        if type(definition_revision) is not int or definition_revision < 1:
            raise ValueError("워크플로우 버전 오류")
        options = options or {}
        if not isinstance(options, dict) or set(options) - {
            "source_language",
            "target_language",
            "video_description",
            "branch_choices",
            "transcript",
        }:
            raise ValueError("작업 옵션 오류")
        if len(canonical(options)) > 20000:
            raise ValueError("작업 옵션 크기 초과")
        creation = {
            "asset_id": asset_id,
            "definition_id": definition_id,
            "definition_revision": definition_revision,
            "options": options,
            "parent_id": parent_id,
            **({"paid_confirmed": True} if paid_confirmed else {}),
        }
        with self.database.connection() as db:
            previous = db.execute(
                "SELECT * FROM jobs WHERE owner_id=%s AND creation_request_id=%s",
                (owner, request_id),
            ).fetchone()
            if previous:
                if previous["creation_sha256"] != digest(creation):
                    raise Conflict("같은 생성 요청 ID에 다른 내용입니다.")
                return self._view(db, previous)
            asset = self._shared_asset(db, asset_id)
            reference = self.asset_reference(asset)
            if asset["owner_id"] != owner:
                reference = {**reference, "source_owner_id": asset["owner_id"]}
            self.store.path(owner, reference)
            workflow_owner, definition = self._job_definition(
                db, owner, definition_id, definition_revision
            )
            bindings = self._bindings(db, workflow_owner, definition, active=False)
            engine_bindings = self._engine_bindings(db, definition)
            input_refs = {"video": reference}
            if definition["inputs"] == {"transcript": "transcript"}:
                from .translation import segments
                text = segments(options.get("transcript"))
                input_refs = {"transcript": self.store.put(owner, [canonical(text)], "transcript")}
            if any(n["type"] in {"translate", "transcribe"} and n.get("model_ref") for n in definition["nodes"]):
                from .translation import languages
                languages(options.get("source_language"), options.get("target_language", "ko"))
            parent = self._job(db, owner, parent_id) if parent_id else None
            from .job_processing_review import JobProcessingReview
            if parent and JobProcessingReview.blocked_in(db, owner, parent_id):
                raise Conflict("관리자 판단에 연결된 새 작업 절차를 사용하세요.")
            if parent and parent["status"] not in ("failed", "cancelled"):
                raise Conflict(
                    "종료된 실패/취소 작업만 새 복구 작업으로 분리할 수 있습니다."
                )
            snapshot = {
                "version": 1,
                "artifact_layout": 1,
                "asset": public_asset(asset),
                "inputs": input_refs,
                "definition": definition,
                "options": options,
                "model_bindings": bindings,
                "engine_bindings": engine_bindings,
                "translation_paid_authorized": bool(paid_confirmed),
                "recovery": {
                    "parent_id": parent_id,
                    "snapshot_sha256": parent["snapshot_sha256"],
                }
                if parent
                else None,
            }
            # Serialize duplicate creation IDs without depending on a unique-error fallback.
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (owner + ":create:" + request_id,),
            )
            previous = db.execute(
                "SELECT * FROM jobs WHERE owner_id=%s AND creation_request_id=%s",
                (owner, request_id),
            ).fetchone()
            if previous:
                if previous["creation_sha256"] != digest(creation):
                    raise Conflict("생성 요청 충돌")
                return self._view(db, previous)
            identity = uuid4().hex
            row = db.execute(
                "INSERT INTO jobs(owner_id,id,asset_id,workflow_id,workflow_revision,status,snapshot,snapshot_sha256,parent_id,creation_request_id,creation_sha256,recovery_ready,workflow_owner_id) VALUES (%s,%s,%s,%s,%s,'draft',%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    owner,
                    identity,
                    asset_id,
                    definition_id,
                    definition_revision,
                    Jsonb(snapshot),
                    digest(snapshot),
                    parent_id,
                    request_id,
                    digest(creation),
                    parent_id is None,
                    workflow_owner,
                ),
            ).fetchone()
            return self._view(db, row)

    def _plan(self, db, job):
        from .job_processing_review import JobProcessingReview
        if JobProcessingReview(self).capture_in(db, job):
            return {'token':digest({'job':job['id'],'processing_review':True}),'ready':False,'reasons':['관리자 처리 확인이 필요합니다.'],'notice':'원 실행을 다시 시작하지 않습니다.'}
        for ref in job["snapshot"]["inputs"].values():
            self.store.path(job["owner_id"], ref)
        runs = self._runs(db, job["owner_id"], job["id"])
        for run in runs:
            if run["status"] == "completed":
                for ref in (run["result"] or {}).get("outputs", {}).values():
                    self.store.path(job["owner_id"], ref)
        reviews = db.execute(
            "SELECT id,revision,status,confirmed_sha256 FROM review_tasks WHERE owner_id=%s AND job_id=%s ORDER BY id",
            (job["owner_id"], job["id"]),
        ).fetchall()
        definition = job["snapshot"]["definition"]
        reasons = []
        if not job["recovery_ready"]:
            reasons.append("복구 receipt 검증이 끝나지 않았습니다.")
        if definition["inputs"] not in ({"video": "video"}, {"transcript": "transcript"}):
            reasons.append("추가 외부 입력 binding이 필요합니다.")
        reasons += self._execution_reasons(
            db,
            definition,
            job["snapshot"].get("engine_bindings", {}),
            job["snapshot"]["options"],
            {r["node_id"] for r in runs if r["status"] in {"completed", "skipped"}},
            job["snapshot"].get("model_bindings", {}),
        )
        if self.fleet is not None:
            done_nodes = {
                r["node_id"] for r in runs if r["status"] in ("completed", "skipped")
            }
            reasons += self.fleet.reasons(
                db,
                [
                    n["type"]
                    for n in definition["nodes"]
                    if n["id"] not in done_nodes and not self._engine_role(n)
                ],
            )
        if job["status"] not in ("draft", "review_required") or job["cancel_requested"]:
            reasons.append("현재 상태에서 새 실행 승인을 만들 수 없습니다.")
        if any(r["status"] != "confirmed" for r in reviews):
            reasons.append("검수 내용을 먼저 저장하고 확정하세요.")
        pending = [n for n in definition["nodes"] if n["type"] == "translate" and n.get("model_ref")
                   and not any(r["node_id"] == n["id"] and r["status"] == "completed" for r in runs)]
        pending_asr = [n for n in definition["nodes"] if n["type"] == "transcribe" and n.get("model_ref")
                       and not any(r["node_id"] == n["id"] and r["status"] == "completed" for r in runs)]
        external_roles = (["translation"] if pending and self.translation_runtime and self.translation_runtime.mode == "external" else []) + (["transcription"] if pending_asr and self.transcription_runtime and self.transcription_runtime.mode == "external" else [])
        external = bool(external_roles)
        if external and not job["snapshot"].get("translation_paid_authorized"):
            reasons.append("전사/번역 후보 전체의 외부 호출 비용 동의가 필요합니다.")
        plan = {
            **({"transcription_mode": self.transcription_runtime.mode if self.transcription_runtime else None,
                "transcription_usage": [self.transcription_runtime.available(p) for n in pending_asr
                                        for pin in [job["snapshot"]["model_bindings"][n["id"]]]
                                        for p in [pin, *pin.get("fallbacks", [])]] if self.transcription_runtime else []} if pending_asr else {}),
            "translation_mode": self.translation_runtime.mode if pending and self.translation_runtime else None,
            "translation_usage": [self.translation_runtime.available(p) for n in pending
                                  for pin in [job["snapshot"]["model_bindings"][n["id"]]]
                                  for p in [pin, *pin.get("fallbacks", [])]] if self.translation_runtime else [],
            "snapshot_sha256": job["snapshot_sha256"],
            "generation": job["generation"],
            "revision": job["revision"],
            "runs": [
                {
                    "id": r["id"],
                    "status": r["status"],
                    "input_sha256": r["input_sha256"],
                    "settings_sha256": r["settings_sha256"],
                    "result": r["result"],
                }
                for r in runs
            ],
            "reviews": reviews,
            "cost": {"classification": "external_unpriced" if external else "verified_no_external_calls", "amount": None},
            "reasons": sorted(set(reasons)),
        }
        return {
            "token": digest(plan),
            "ready": not reasons,
            "reasons": plan["reasons"],
            "paid_roles": external_roles,
            "cost": plan["cost"],
            "notice": "등록 모델 후보의 외부 호출은 비용이 발생할 수 있습니다. 금액은 미산정입니다." if external else "외부 유료 호출 없는 로컬/통제 HTTP 실행입니다. 동의 저장과 실행 요청은 별개입니다.",
            "snapshot_sha256": job["snapshot_sha256"],
            "generation": job["generation"],
        }

    def plan(self, owner, identity):
        with self.database.connection() as db:
            return self._plan(db, self._job(db, owner, identity, lock=True))

    def confirm(self, owner, identity, token, nonce):
        request_id(nonce)
        payload_sha = digest({"job": identity, "token": token})
        with self.database.connection() as db:
            job = self._job(db, owner, identity, lock=True)
            previous = db.execute(
                "SELECT * FROM execution_consents WHERE owner_id=%s AND job_id=%s AND request_id=%s",
                (owner, identity, nonce),
            ).fetchone()
            if previous:
                if previous["request_sha256"] != payload_sha:
                    raise Conflict("같은 확인 요청의 내용이 다릅니다.")
                return public(previous)
            plan = self._plan(db, job)
            if not plan["ready"] or plan["token"] != token:
                raise Conflict("현재 입력/검수/계획을 다시 확인하세요.")
            row = db.execute(
                "INSERT INTO execution_consents(owner_id,job_id,id,request_id,plan_sha256,expires_at,request_sha256) VALUES (%s,%s,%s,%s,%s,now()+interval '15 minutes',%s) RETURNING *",
                (owner, identity, uuid4().hex, nonce, token, payload_sha),
            ).fetchone()
            return public(row)

    def admit(self, owner, identity, consent_id, nonce):
        request_id(nonce)
        resource_id(consent_id)
        payload_sha = digest({"job": identity, "consent": consent_id})
        with self.database.connection() as db:
            job = self._job(db, owner, identity, lock=True)
            previous = db.execute(
                "SELECT * FROM execution_claims WHERE owner_id=%s AND request_id=%s",
                (owner, nonce),
            ).fetchone()
            if previous:
                if (
                    previous["job_id"] != identity
                    or previous["request_sha256"] != payload_sha
                ):
                    raise Conflict("같은 실행 요청의 대상/내용이 다릅니다.")
                return self._view(db, job)
            consent = db.execute(
                "SELECT *,expires_at>now() AS valid FROM execution_consents WHERE owner_id=%s AND job_id=%s AND id=%s FOR UPDATE",
                (owner, identity, consent_id),
            ).fetchone()
            if (
                not consent
                or not consent["valid"]
                or consent["consumed_at"] is not None
            ):
                raise Conflict("승인이 없거나 이미 소비/만료됐습니다.")
            plan = self._plan(db, job)
            if not plan["ready"] or plan["token"] != consent["plan_sha256"]:
                raise Conflict("입력/검수/계획이 바뀌었습니다. 새 확인이 필요합니다.")
            claim = uuid4().hex
            db.execute(
                "INSERT INTO execution_claims(owner_id,job_id,id,consent_id,generation,request_id,request_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    owner,
                    identity,
                    claim,
                    consent_id,
                    job["generation"],
                    nonce,
                    payload_sha,
                ),
            )
            db.execute(
                "UPDATE execution_consents SET consumed_at=now() WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, identity, consent_id),
            )
            job = db.execute(
                "UPDATE jobs SET status='waiting',active_claim_id=%s,revision=revision+1,updated_at=now() WHERE owner_id=%s AND id=%s RETURNING *",
                (claim, owner, identity),
            ).fetchone()
            return self._view(db, job)

    def _result_for(self, job, indexed, edge):
        source = edge["source"]
        if source["node"] == "$input":
            return "completed", job["snapshot"]["inputs"].get(source["port"])
        run = indexed.get(source["node"])
        if run is None:
            return "waiting", None
        return run["status"], (run["result"] or {}).get("outputs", {}).get(
            source["port"]
        )

    def _write_outbox(self, db, owner, identity, kind, payload, message_id=None):
        db.execute(
            "INSERT INTO message_outbox(id,owner_id,aggregate_id,message_type,payload) VALUES (%s,%s,%s,%s,%s)",
            (message_id or uuid4().hex, owner, identity, kind, Jsonb(payload)),
        )

    def _insert_run(self, db, job, node, inputs, status):
        from .dispatch_queue import DispatchQueue
        deferred = (status == "running"
                    and node["type"] in getattr(self, "defer_broker_agents", ())
                    and DispatchQueue.managed_in(db, node["type"]))
        if deferred:
            status = "waiting"
        identity = uuid4().hex
        command = {
            "protocol_version": 1,
            "run_id": job["id"],
            "attempt_id": identity,
            "generation": job["generation"],
            "agent": {"id": node["type"], "revision": "1"},
            "inputs": inputs,
            "options": node["options"],
        }
        if node["type"] in {"translate", "transcribe"} and node.get("model_ref") and status == "running":
            pin = job["snapshot"]["model_bindings"][node["id"]]
            kind = {"translate": "translation", "transcribe": "transcription"}[node["type"]]
            command[kind] = {
                "candidates": [pin, *pin.get("fallbacks", [])],
                "source_language": job["snapshot"]["options"]["source_language"],
                **({"target_language": job["snapshot"]["options"]["target_language"]} if kind == "translation" else {}),
                "paid_authorized": job["snapshot"].get("translation_paid_authorized", False),
            }
        elif self._engine_role(node) and status == "running":
            from ..engine_protocol import make_command

            if not self.engine_runtime_enabled:
                raise Conflict("engine transport가 비활성 상태입니다.")
            pin = job["snapshot"]["engine_bindings"][node["id"]]
            from .engine_runtimes import EngineRuntimes

            try:
                current = EngineRuntimes.resolve_in(
                    db, node["type"], sha256=pin["sha256"]
                )
                if current["revision"] != pin["revision"]:
                    raise ValueError("engine_revision_changed")
            except ValueError:
                raise Conflict("engine runtime pin/가용성이 변경됐습니다.") from None
            descriptor = pin["descriptor"]
            command = make_command(
                node["type"],
                run_id=job["id"],
                attempt_id=identity,
                generation=job["generation"],
                inputs=inputs,
                options=node["options"],
                runtime=descriptor,
            )
        row = db.execute(
            "INSERT INTO node_runs(owner_id,job_id,id,node_id,agent_revision,attempt,generation,status,input_sha256,settings_sha256,inputs,options,node_type,request,request_sha256,claim_id,lease_owner,lease_expires_at,started_at) VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()+interval '120 seconds',now()) RETURNING *",
            (
                job["owner_id"],
                job["id"],
                identity,
                node["id"],
                command["agent"]["revision"],
                job["generation"],
                status,
                digest(inputs),
                digest(node["options"]),
                Jsonb(inputs),
                Jsonb(node["options"]),
                node["type"],
                Jsonb(command),
                digest(command),
                job["active_claim_id"],
                "explicit-local" if status == "running" else None,
            ),
        ).fetchone()
        if deferred:
            row = db.execute("UPDATE node_runs SET started_at=NULL,lease_owner=NULL,lease_expires_at=NULL WHERE id=%s RETURNING *", (identity,)).fetchone()
            DispatchQueue.enqueue_in(db, job, row)
        return row, command

    def _control_outputs(self, owner, kind, inputs, options):
        if kind == "select":
            selection = options.get("selection", "a")
            return {p: inputs["value"] for p in ("a", "b") if selection in (p, "both")}
        if kind == "join":
            manifest = self.store.put(
                owner,
                [
                    canonical(
                        {
                            "items": [
                                {"port": p, "reference": r}
                                for p, r in sorted(inputs.items())
                            ]
                        }
                    )
                ],
                "artifact_manifest",
            )
            return {"manifest": manifest}
        raw = json.loads(self.store.read(owner, inputs["value"]))
        value = raw
        field = options.get("field", "")
        if len(field) > 200 or any(
            not part or not part.replace("_", "").isalnum()
            for part in field.split(".")
            if field
        ):
            raise ValueError("조건 필드 오류")
        for part in field.split(".") if field else []:
            value = value.get(part) if isinstance(value, dict) else None
        if kind == "control_switch":
            cases = options.get("cases", "case_1\ncase_2").splitlines()
            port = next(
                (
                    "case_" + str(i + 1)
                    for i, case in enumerate(cases)
                    if str(value) == case
                ),
                "default",
            )
        else:
            operator = options.get("operator", "equals")
            compare = options.get("compare_value", "")
            if operator in ("greater_than", "less_than"):
                passed = (
                    float(value) > float(compare)
                    if operator == "greater_than"
                    else float(value) < float(compare)
                )
            elif operator == "exists":
                passed = value is not None
            elif operator == "contains":
                passed = compare in str(value)
            else:
                passed = str(value) == compare
                if operator == "not_equals":
                    passed = not passed
            port = "true" if passed else "false"
        return {port: inputs["value"]}

    def claim_next(self, owner, identity):
        with self.database.connection() as db:
            job = self._job(db, owner, identity, lock=True)
            from .job_processing_review import JobProcessingReview
            if JobProcessingReview(self).capture_in(db, job):
                return None
            if (
                job["status"] not in ("waiting", "running")
                or job["cancel_requested"]
                or not job["active_claim_id"]
            ):
                return None
            runs = self._runs(db, owner, identity)
            if sum(r["status"] in ("running", "waiting") for r in runs) >= 2:
                return None
            indexed = {r["node_id"]: r for r in runs}
            definition = job["snapshot"]["definition"]
            for node in definition["nodes"]:
                if node["id"] in indexed:
                    continue
                edges = [
                    e for e in definition["edges"] if e["target"]["node"] == node["id"]
                ]
                states = [(e, *self._result_for(job, indexed, e)) for e in edges]
                if any(status not in TERMINAL for _, status, _ in states):
                    continue
                inputs = {
                    e["target"]["port"]: ref
                    for e, status, ref in states
                    if status == "completed" and ref is not None
                }
                selected = spec(node["type"], node["options"])
                required = set(selected["inputs"]) - set(selected["optional_inputs"])
                missing = required - set(inputs)
                if missing and not (node["type"] == "join" and inputs):
                    status = (
                        "blocked"
                        if any(
                            s in ("failed", "blocked", "quarantined", "cancelled")
                            for _, s, _ in states
                        )
                        else "skipped"
                    )
                    row, _ = self._insert_run(db, job, node, {}, status)
                    indexed[node["id"]] = row
                    continue
                for ref in inputs.values():
                    self.store.path(owner, ref)
                instance = None
                if (
                    self.fleet is not None
                    and node["type"] in CPU_AGENTS
                    and not self._engine_role(node)
                ):
                    instance = self.fleet.reserve(db, node["type"])
                    if instance is None:
                        continue
                row, command = self._insert_run(
                    db,
                    job,
                    node,
                    inputs,
                    "review_required" if node["type"] == "review" else "running",
                )
                if instance is not None:
                    db.execute(
                        "UPDATE node_runs SET agent_instance_id=%s WHERE owner_id=%s AND job_id=%s AND id=%s",
                        (instance, owner, identity, row["id"]),
                    )
                if node["type"] == "review":
                    review_id = uuid4().hex
                    contract = {
                        "version": 1,
                        "type": inputs["value"]["type"],
                        "source": inputs["value"],
                        "phase": "gate",
                        "fields": {
                            "type": "object",
                            "properties": {
                                "approved": {
                                    "type": "boolean",
                                    "title": "자료를 확인했음",
                                }
                            },
                            "required": ["approved"],
                        },
                    }
                    db.execute(
                        "INSERT INTO review_tasks(owner_id,job_id,node_run_id,id,revision,contract,draft,status) VALUES (%s,%s,%s,%s,1,%s,%s,'draft')",
                        (
                            owner,
                            identity,
                            row["id"],
                            review_id,
                            Jsonb(contract),
                            Jsonb({"approved": False}),
                        ),
                    )
                    db.execute(
                        "INSERT INTO review_revisions VALUES (%s,%s,1,%s,%s,now())",
                        (
                            owner,
                            review_id,
                            Jsonb({"approved": False}),
                            digest({"approved": False}),
                        ),
                    )
                    indexed[node["id"]] = row
                    continue
                if node["type"] in CONTROL:
                    try:
                        outputs = self._control_outputs(
                            owner, node["type"], inputs, node["options"]
                        )
                        receipt = self.ticket_artifacts.capture(db, job, row, {
                            "outputs": outputs, "transport": "application_control",
                        })
                        db.execute(
                            "UPDATE node_runs SET status='completed',result=%s,completed_at=now() WHERE owner_id=%s AND job_id=%s AND id=%s",
                            (
                                Jsonb(receipt),
                                owner,
                                identity,
                                row["id"],
                            ),
                        )
                        indexed[node["id"]] = {
                            **row,
                            "status": "completed",
                            "result": receipt,
                        }
                    except (ValueError, KeyError, TypeError):
                        db.execute(
                            "UPDATE node_runs SET status='failed',error_code='control_input_invalid',completed_at=now() WHERE owner_id=%s AND job_id=%s AND id=%s",
                            (owner, identity, row["id"]),
                        )
                        indexed[node["id"]] = {**row, "status": "failed"}
                    continue
                if not (command.get("translation") or command.get("transcription")) and (
                    node["type"] not in CPU_AGENTS and not self._engine_role(node)
                    or node.get("model_ref")
                ):
                    raise Conflict("비활성 실행 경로")
                message_type = (
                    "agent.engine.command.v2"
                    if command["protocol_version"] == 2
                    else "agent.command.v1"
                )
                if command.get('translation') or command.get('transcription'):
                    from ..registered_broker import COMMAND as REGISTERED_COMMAND
                    message_type = REGISTERED_COMMAND
                self._write_outbox(
                    db, owner, identity, message_type, command, row["id"]
                )
                db.execute(
                    "UPDATE jobs SET status=CASE WHEN EXISTS (SELECT 1 FROM node_runs WHERE owner_id=%s AND job_id=%s AND status='running') THEN 'running' ELSE 'waiting' END,revision=revision+1,updated_at=now() WHERE owner_id=%s AND id=%s",
                    (owner, identity, owner, identity),
                )
                return command
            # Application controls are materialized in the same transaction; settle
            # only once no independent runnable command remains in this sweep.
            if not any(r["status"] in ("running", "waiting") for r in indexed.values()):
                if any(r["status"] == "review_required" for r in indexed.values()):
                    status = "review_required"
                elif len(indexed) == len(definition["nodes"]):
                    status = (
                        "failed"
                        if any(
                            r["status"] in ("failed", "blocked", "quarantined")
                            for r in indexed.values()
                        )
                        else "completed"
                    )
                else:
                    status = "waiting"
                if status != job["status"]:
                    db.execute(
                        "UPDATE jobs SET status=%s,revision=revision+1,updated_at=now() WHERE owner_id=%s AND id=%s",
                        (status, owner, identity),
                    )
            return None

    def execute_command(self, owner, command):
        # Reserve the exact delivery before starting a process. A duplicate whose
        # outcome is unknown never automatically launches a second process.
        with self.database.connection() as db:
            job = self._job(db, owner, command["run_id"], lock=True)
            from .job_processing_review import JobProcessingReview
            if JobProcessingReview(self).capture_in(db, job):
                raise Conflict("관리자 확인 중인 원 실행은 다시 시작하지 않습니다.")
            run = db.execute(
                "SELECT *,lease_expires_at>now() AS lease_valid FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, command["run_id"], command["attempt_id"]),
            ).fetchone()
            if not run or run["request_sha256"] != digest(command):
                raise Conflict("실행 요청 무결성 오류")
            previous = db.execute(
                "SELECT * FROM agent_deliveries WHERE owner_id=%s AND job_id=%s AND node_run_id=%s",
                (owner, command["run_id"], command["attempt_id"]),
            ).fetchone()
            if previous:
                if (
                    previous["command_sha256"] != digest(command)
                    or previous["status"] != "completed"
                ):
                    raise Conflict(
                        "동일 시도가 처리 중이거나 결과 불명입니다. 자동 재실행하지 않습니다."
                    )
                return previous["result"]
            if (
                job["cancel_requested"]
                or job["generation"] != run["generation"]
                or run["status"] != "running"
                or not run["lease_valid"]
            ):
                raise Conflict("취소/만료/이전 세대 명령은 새로 실행하지 않습니다.")
            db.execute(
                "INSERT INTO agent_deliveries(owner_id,job_id,node_run_id,command_sha256,status) VALUES (%s,%s,%s,%s,'started')",
                (owner, command["run_id"], command["attempt_id"], digest(command)),
            )
        if command.get("translation") or command.get("transcription"):
            from .translation import execute_translation
            result = execute_translation(self, owner, command)
            with self.database.connection() as db:
                db.execute("UPDATE agent_deliveries SET status='completed',result=%s WHERE owner_id=%s AND job_id=%s AND node_run_id=%s AND status='started'",
                           (Jsonb(result), owner, command["run_id"], command["attempt_id"]))
            return result
        root = self.store.owner_root(owner)
        if self.fleet is not None:
            try:
                if run["agent_instance_id"] is None:
                    raise ValueError("No reserved CPU instance")
                result = self.fleet.execute(run["agent_instance_id"], owner, command)
            except (ValueError, OSError, TimeoutError, KeyError):
                result = {
                    **{
                        k: command[k]
                        for k in (
                            "protocol_version",
                            "run_id",
                            "attempt_id",
                            "generation",
                            "agent",
                        )
                    },
                    "request_sha256": digest(command),
                    "status": "failed",
                    "outputs": {},
                    "transport": "subprocess",
                    "agent_instance_id": run["agent_instance_id"],
                    "error": {"code": "cpu_result_unknown", "retryable": False},
                }
            with self.database.connection() as db:
                db.execute(
                    "UPDATE agent_deliveries SET status='completed',result=%s WHERE owner_id=%s AND job_id=%s AND node_run_id=%s AND status='started'",
                    (Jsonb(result), owner, command["run_id"], command["attempt_id"]),
                )
            return result
        if self.agent_executor is not None:
            try:
                result = self.agent_executor(owner, command)
                expected_transport = (
                    "s3_engine"
                    if command.get("protocol_version") == 2
                    else "s3_subprocess"
                )
                if result.get("transport") != expected_transport:
                    raise ValueError("Unexpected object agent transport")
            except (ValueError, OSError, subprocess.TimeoutExpired):
                result = {
                    "protocol_version": 1,
                    "run_id": command["run_id"],
                    "attempt_id": command["attempt_id"],
                    "generation": command["generation"],
                    "agent": command["agent"],
                    "request_sha256": digest(command),
                    "status": "failed",
                    "outputs": {},
                    "transport": "s3_subprocess",
                    "error": {"code": "object_result_unknown", "retryable": False},
                }
            with self.database.connection() as db:
                db.execute(
                    "UPDATE agent_deliveries SET status='completed',result=%s WHERE owner_id=%s AND job_id=%s AND node_run_id=%s AND status='started'",
                    (Jsonb(result), owner, command["run_id"], command["attempt_id"]),
                )
            return result
        attempts = root / "attempts"
        if attempts.is_symlink():
            raise ValueError("Symlink attempt root denied")
        attempts.mkdir(mode=0o700, exist_ok=True)
        args = [
            sys.executable,
            "-m",
            "video_service.cpu_agents",
            "--agent",
            command["agent"]["id"],
            "--input-root",
            str(root),
            "--output-root",
            str(attempts),
        ]
        try:
            completed = subprocess.run(
                args,
                check=False,
                input=canonical(command),
                capture_output=True,
                timeout=90,
                env={
                    k: v
                    for k, v in __import__("os").environ.items()
                    if k
                    in (
                        "PATH",
                        "LANG",
                        "HOME",
                        "TMPDIR",
                        "PYTHONPATH",
                        "FONTCONFIG_PATH",
                    )
                },
            )
            if len(completed.stdout) > 65536:
                raise ValueError("Agent response size exceeded")
            result = json.loads(completed.stdout)
            result["transport"] = "subprocess"
            result["process_exit_code"] = completed.returncode
            if any(
                result.get(k) != command[k]
                for k in (
                    "protocol_version",
                    "run_id",
                    "attempt_id",
                    "generation",
                    "agent",
                )
            ):
                raise ValueError("Invalid agent response envelope")
        except (subprocess.TimeoutExpired, ValueError):
            # CPU timeout is still an unknown attempt. Do not automatically replay.
            result = {
                "protocol_version": 1,
                "run_id": command["run_id"],
                "attempt_id": command["attempt_id"],
                "generation": command["generation"],
                "agent": command["agent"],
                "request_sha256": digest(command),
                "status": "failed",
                "outputs": {},
                "transport": "subprocess",
                "error": {"code": "cpu_result_unknown", "retryable": False},
            }
        with self.database.connection() as db:
            db.execute(
                "UPDATE agent_deliveries SET status='completed',result=%s WHERE owner_id=%s AND job_id=%s AND node_run_id=%s AND status='started'",
                (Jsonb(result), owner, command["run_id"], command["attempt_id"]),
            )
        return result

    def _import_outputs(self, owner, command, result):
        if command.get("protocol_version") == 2:
            from ..engine_protocol import envelope

            envelope(owner, command, result)
        elif result.get("transport") == "s3_engine":
            raise ValueError("Engine result cannot satisfy a CPU command")
        expected = spec(command["agent"]["id"], command["options"])["outputs"]
        values = result.get("outputs")
        if not isinstance(values, dict) or set(values) != set(expected):
            raise ValueError("Agent output ports differ")
        if result.get("transport") == "registered_http" and (command.get("translation") or command.get("transcription")):
            for port, reference in values.items():
                if reference.get("type") != expected[port]:
                    raise ValueError("Translation output type differs")
                self.store.path(owner, reference)
            return values
        if result.get("transport") in {"s3_subprocess", "s3_engine"}:
            if getattr(self.store, "storage_kind", None) != "s3":
                raise ValueError("Object results require an explicit object store")
            for port, reference in values.items():
                if reference.get("type") != expected[port]:
                    raise ValueError("Object output type differs")
                self.store.path(owner, reference)
            return values
        root = self.store.owner_root(owner) / "attempts"
        outputs = {}
        for port, ref in values.items():
            key = ref.get("storage_key", "")
            prefix = command["run_id"] + "-" + command["attempt_id"] + "/"
            if (
                not isinstance(key, str)
                or not key.startswith(prefix)
                or len(key.split("/")) != 2
                or not key.split("/")[1].replace(".", "").replace("-", "").isalnum()
                or ref["type"] != expected[port]
            ):
                raise ValueError("Agent output reference differs")
            directory, path = root / key.split("/")[0], root / key
            if directory.is_symlink() or path.is_symlink() or not path.is_file():
                raise ValueError("Output file unavailable")
            if path.stat().st_size != ref["bytes"]:
                raise ValueError("Output size differs")
            with path.open("rb") as stream:
                stored = self.store.put(
                    owner, iter(lambda: stream.read(1024 * 1024), b""), ref["type"]
                )
            if stored["sha256"] != ref["sha256"] or stored["bytes"] != ref["bytes"]:
                raise ValueError("Output integrity differs")
            outputs[port] = stored
        return outputs

    def video_preview(self, owner, identity, reference):
        state = self.get(owner, identity)
        return self._video_preview_state(state, reference)

    def _video_preview_state(self, state, reference):
        owner = state["owner_id"]
        source_owner = state.get("asset_owner_id", owner)
        with self.database.connection() as db:
            asset = self._asset(db, source_owner, state["asset_id"])
        candidates = [(source_owner, asset["metadata"].get("web_preview", {}))]
        for run in state["runs"]:
            if run["status"] == "completed":
                candidates.extend((owner, p) for p in (run["result"] or {}).get("previews", {}).values())
        for storage_owner, preview in candidates:
            if (
                preview.get("source_sha256") == reference["sha256"]
                and preview.get("status") == "ready"
            ):
                return self.store.path(storage_owner, preview["reference"])
        raise Missing(
            "웹 전용 WebM이 준비되지 않았습니다. 원본은 다운로드할 수 있습니다."
        )

    def accept(self, owner, command, result):
        response_sha = digest(result)
        identity, run_id = command["run_id"], command["attempt_id"]
        with self.database.connection() as db:
            job = self._job(db, owner, identity, lock=True)
            run = db.execute(
                "SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s FOR UPDATE",
                (owner, identity, run_id),
            ).fetchone()
            if not run or run["request_sha256"] != digest(command):
                raise Conflict("알 수 없는 실행 요청")
            received = db.execute(
                "SELECT payload_sha256 FROM message_inbox WHERE consumer=%s AND message_id=%s",
                ("result:" + owner, run_id),
            ).fetchone()
            if received:
                if received["payload_sha256"] != response_sha:
                    raise Conflict("같은 결과 ID의 내용이 다릅니다.")
                return self._view(db, job)
            valid = (
                all(
                    result.get(k) == command[k]
                    for k in (
                        "protocol_version",
                        "run_id",
                        "attempt_id",
                        "generation",
                        "agent",
                    )
                )
                and result.get("request_sha256") == run["request_sha256"]
            )
            if not valid:
                raise Conflict("결과가 실행 요청과 다릅니다.")
            from .job_processing_review import JobProcessingReview
            processing = JobProcessingReview(self)
            processing.capture_in(db, job)
            if processing.late_in(db, job, run, command, result):
                return self._view(db, job)
            from .dispatch_queue import DispatchQueue
            run = DispatchQueue.received_in(db, job, run, from_result=True)
            lease = db.execute(
                "SELECT lease_expires_at>now() AS valid FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, identity, run_id),
            ).fetchone()
            stale = (
                job["cancel_requested"]
                or job["generation"] != run["generation"]
                or job["active_claim_id"] != run["claim_id"]
                or run["status"] != "running"
                or not lease["valid"]
            )
            if stale:
                db.execute(
                    "INSERT INTO result_quarantine(owner_id,job_id,node_run_id,message_sha256,reason,result) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        owner,
                        identity,
                        run_id,
                        response_sha,
                        "stale_or_cancelled",
                        Jsonb(result),
                    ),
                )
                db.execute(
                    "UPDATE node_runs SET status='quarantined',completed_at=now() WHERE owner_id=%s AND job_id=%s AND id=%s AND status='running'",
                    (owner, identity, run_id),
                )
                remaining = db.execute(
                    "SELECT count(*) n FROM node_runs WHERE owner_id=%s AND job_id=%s AND status='running'",
                    (owner, identity),
                ).fetchone()["n"]
                if not remaining:
                    db.execute(
                        "UPDATE jobs SET status=%s,active_claim_id=NULL WHERE owner_id=%s AND id=%s",
                        (
                            "cancelled" if job["cancel_requested"] else "failed",
                            owner,
                            identity,
                        ),
                    )
            else:
                try:
                    for ref in command["inputs"].values():
                        self.store.path(owner, ref)
                    status = result.get("status")
                    if status != "completed":
                        raise ValueError("Agent did not complete")
                    outputs = self._import_outputs(owner, command, result)
                    # Preserve transport/attempt evidence but replace machine paths with CAS refs.
                    receipt = {
                        k: v
                        for k, v in result.items()
                        if k
                        in (
                            "protocol_version",
                            "run_id",
                            "attempt_id",
                            "generation",
                            "agent",
                            "request_sha256",
                            "status",
                            "transport",
                            "process_exit_code",
                            "agent_instance_id",
                            "translation",
                            "transcription",
                        )
                    }
                    receipt["outputs"] = outputs
                    from ..web_preview import create_preview

                    receipt["previews"] = {
                        port: create_preview(self.store, owner, ref)
                        for port, ref in outputs.items()
                        if ref["type"] == "video"
                    }
                    receipt = self.ticket_artifacts.capture(db, job, run, receipt)
                    db.execute(
                        "UPDATE node_runs SET status='completed',result=%s,completed_at=now(),lease_owner=NULL,lease_expires_at=NULL WHERE owner_id=%s AND job_id=%s AND id=%s",
                        (Jsonb(receipt), owner, identity, run_id),
                    )
                    for port, ref in outputs.items():
                        if self.ticket_artifacts.enabled(job):
                            ref = next(entry['storage'] for entry in receipt['ticket_artifacts']['entries']
                                       if entry['output_port'] == port)
                        db.execute(
                            "INSERT INTO artifacts(owner_id,job_id,node_run_id,id,type,storage_key,bytes,sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                owner,
                                identity,
                                run_id,
                                uuid4().hex,
                                ref["type"],
                                ref["storage_key"],
                                ref["bytes"],
                                ref["sha256"],
                            ),
                        )
                except (ValueError, KeyError, TypeError, OSError):
                    db.execute(
                        "UPDATE node_runs SET status='failed',error_code='agent_failed_or_unknown',result=%s,completed_at=now(),lease_owner=NULL,lease_expires_at=NULL WHERE owner_id=%s AND job_id=%s AND id=%s",
                        (
                            Jsonb(
                                {
                                    "outputs": {},
                                    "transport": "subprocess",
                                    "error": "agent_failed_or_unknown",
                                    "retryable": False,
                                    **{kind: result[kind] for kind in ("translation", "transcription") if command.get(kind) and kind in result},
                                }
                            ),
                            owner,
                            identity,
                            run_id,
                        ),
                    )
            db.execute(
                "INSERT INTO message_inbox(consumer,message_id,payload_sha256) VALUES (%s,%s,%s)",
                ("result:" + owner, run_id, response_sha),
            )
            self._write_outbox(
                db,
                owner,
                identity,
                "agent.result.accepted.v1",
                {
                    "job_id": identity,
                    "node_run_id": run_id,
                    "generation": run["generation"],
                    "quarantined": stale,
                },
            )
            db.execute(
                "UPDATE jobs SET revision=revision+1,updated_at=now() WHERE owner_id=%s AND id=%s",
                (owner, identity),
            )
            return self._view(db, self._job(db, owner, identity))

    def run_local(self, owner, identity):
        # One explicit job only. Never scans/consumes pending jobs or any broker.
        for _ in range(110):
            before = self.get(owner, identity)
            commands = []
            for _ in range(2):
                command = self.claim_next(owner, identity)
                if command:
                    commands.append(command)
            if not commands:
                state = self.get(owner, identity)
                if state["status"] == "waiting" and len(state["runs"]) > len(
                    before["runs"]
                ):
                    continue
                return state
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(lambda c: self.execute_command(owner, c), commands)
                )
            for command, result in zip(commands, results):
                self.accept(owner, command, result)
        raise Conflict("실행 상한을 넘었습니다. 상태를 보존했습니다.")

    def recover(self, owner, identity, nonce, *, acknowledge_duplicate_risk):
        if acknowledge_duplicate_risk is not True:
            raise ValueError("미확정 실행의 중복 처리 위험을 별도로 확인하세요.")
        original = self.get(owner, identity)
        if original["status"] not in ("failed", "cancelled"):
            raise Conflict("종료된 실패/취소 작업만 새 복구 작업을 만들 수 있습니다.")
        definition = original["snapshot"]["definition"]
        # Creation is idempotent and does not admit or start the child.
        child = self.create(
            owner,
            original["asset_id"],
            original["workflow_id"],
            original["workflow_revision"],
            request_id=nonce,
            options=original["snapshot"]["options"],
            parent_id=identity,
        )
        with self.database.connection() as db:
            child_row = self._job(db, owner, child["id"], lock=True)
            if self._runs(db, owner, child["id"]) or child_row["status"] != "draft":
                return self._view(db, child_row)
            if (
                original["snapshot"]["model_bindings"]
                != child_row["snapshot"]["model_bindings"]
            ):
                raise Conflict("고정 모델 근거가 다릅니다. 자동 재사용하지 않습니다.")
            indexed = {}
            remaining = {n["id"]: n for n in definition["nodes"]}
            old_runs = {r["node_id"]: r for r in original["runs"]}
            for _ in range(len(remaining)):
                progress = False
                for node_id, node in list(remaining.items()):
                    old = old_runs.get(node_id)
                    if not old or old["status"] != "completed":
                        continue
                    edges = [
                        e for e in definition["edges"] if e["target"]["node"] == node_id
                    ]
                    states = [
                        (e, *self._result_for(child_row, indexed, e)) for e in edges
                    ]
                    if any(s != "completed" for _, s, _ in states):
                        continue
                    inputs = {
                        e["target"]["port"]: ref
                        for e, _, ref in states
                        if ref is not None
                    }
                    if (
                        old["input_sha256"] != digest(inputs)
                        or old["settings_sha256"] != digest(node["options"])
                        or old["inputs"] != inputs
                        or not old["result"]
                    ):
                        raise Conflict("완료 단계 입력/설정 receipt 무결성 오류")
                    if (
                        old.get("request")
                        and digest(old["request"]) != old["request_sha256"]
                    ):
                        raise Conflict("완료 요청 receipt 무결성 오류")
                    for ref in [
                        *inputs.values(),
                        *old["result"].get("outputs", {}).values(),
                    ]:
                        self.store.path(owner, ref)
                    receipt = {
                        **old["result"],
                        "reused_from": {
                            "job_id": identity,
                            "node_run_id": old["id"],
                            "generation": old["generation"],
                            "receipt_sha256": digest(old["result"]),
                        },
                    }
                    row, _ = self._insert_run(db, child_row, node, inputs, "completed")
                    receipt = self.ticket_artifacts.capture(db, child_row, row, receipt)
                    db.execute(
                        "UPDATE node_runs SET result=%s,completed_at=now() WHERE owner_id=%s AND job_id=%s AND id=%s",
                        (Jsonb(receipt), owner, child["id"], row["id"]),
                    )
                    indexed[node_id] = {**row, "result": receipt}
                    del remaining[node_id]
                    progress = True
                if not progress:
                    break
            child_row = db.execute(
                "UPDATE jobs SET recovery_ready=true WHERE owner_id=%s AND id=%s RETURNING *",
                (owner, child["id"]),
            ).fetchone()
            return self._view(db, child_row)

    def cancel(self, owner, identity, revision):
        with self.database.connection() as db:
            job = self._job(db, owner, identity, lock=True)
            from .job_processing_review import JobProcessingReview
            if JobProcessingReview(self).capture_in(db, job):
                raise Conflict("확인 중인 원 기록은 초기화하거나 취소로 덮어쓰지 않습니다.")
            if job["status"] in ("completed", "failed", "cancelled"):
                return self._view(db, job)
            if job["revision"] != revision:
                raise Conflict("작업 상태가 변경됐습니다.")
            running = db.execute(
                "SELECT count(*) n FROM node_runs r WHERE owner_id=%s AND job_id=%s AND (status='running' OR EXISTS (SELECT 1 FROM broker_dispatch_queue q WHERE q.node_run_id=r.id AND q.phase IN ('sending','sent','received','unknown')))",
                (owner, identity),
            ).fetchone()["n"]
            job = db.execute(
                "UPDATE jobs SET cancel_requested=true,status=%s,generation=generation+1,revision=revision+1,updated_at=now() WHERE owner_id=%s AND id=%s RETURNING *",
                ("cancelling" if running else "cancelled", owner, identity),
            ).fetchone()
            return self._view(db, job)

    def _review(self, db, owner, identity, lock=False):
        row = db.execute(
            "SELECT * FROM review_tasks WHERE owner_id=%s AND id=%s"
            + (" FOR UPDATE" if lock else ""),
            (owner, resource_id(identity)),
        ).fetchone()
        if not row:
            raise Missing("검수 자료를 찾을 수 없습니다.")
        return row

    def review_save(self, owner, identity, revision, draft):
        if draft != {"approved": True} and draft != {"approved": False}:
            raise ValueError("검수 확인 필드 오류")
        with self.database.connection() as db:
            # All review/cancel/admission writes take the job lock before review lock.
            hint = self._review(db, owner, identity)
            job = self._job(db, owner, hint["job_id"], lock=True)
            row = self._review(db, owner, identity, lock=True)
            if (
                row["revision"] != revision
                or row["status"] == "confirmed"
                or job["status"] != "review_required"
            ):
                raise Conflict("검수 상태가 바뀌었습니다. 편집은 보존하세요.")
            next_revision = revision + 1
            db.execute(
                "INSERT INTO review_revisions VALUES (%s,%s,%s,%s,%s,now())",
                (owner, identity, next_revision, Jsonb(draft), digest(draft)),
            )
            row = db.execute(
                "UPDATE review_tasks SET revision=%s,draft=%s,status='draft' WHERE owner_id=%s AND id=%s RETURNING *",
                (next_revision, Jsonb(draft), owner, identity),
            ).fetchone()
            db.execute(
                "UPDATE jobs SET revision=revision+1 WHERE owner_id=%s AND id=%s",
                (owner, row["job_id"]),
            )
            return public(row)

    def review_confirm(self, owner, identity, revision):
        with self.database.connection() as db:
            hint = self._review(db, owner, identity)
            job = self._job(db, owner, hint["job_id"], lock=True)
            row = self._review(db, owner, identity, lock=True)
            if (
                row["revision"] != revision
                or row["draft"] != {"approved": True}
                or job["status"] != "review_required"
            ):
                raise Conflict("저장된 최신 검수 자료를 확인하세요.")
            source = row["contract"]["source"]
            self.store.path(owner, source)
            confirmed_sha = digest(
                {"draft": row["draft"], "source": source, "revision": revision}
            )
            db.execute(
                "UPDATE review_tasks SET status='confirmed',confirmed_sha256=%s WHERE owner_id=%s AND id=%s",
                (confirmed_sha, owner, identity),
            )
            run = db.execute(
                "SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, row['job_id'], row['node_run_id']),
            ).fetchone()
            receipt = self.ticket_artifacts.capture(db, job, run, {
                "outputs": {"value": source}, "transport": "human_gate", "review_id": identity,
                "review_revision": revision, "confirmed_sha256": confirmed_sha,
            })
            db.execute(
                "UPDATE node_runs SET status='completed',result=%s,completed_at=now() WHERE owner_id=%s AND job_id=%s AND id=%s",
                (
                    Jsonb(receipt),
                    owner,
                    row["job_id"],
                    row["node_run_id"],
                ),
            )
            db.execute(
                "UPDATE jobs SET active_claim_id=NULL,revision=revision+1 WHERE owner_id=%s AND id=%s",
                (owner, row["job_id"]),
            )
            return public(self._review(db, owner, identity))
