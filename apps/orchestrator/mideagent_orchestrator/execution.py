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

from video_service.canonical import canonical, digest
from video_service.agent_protocol import CPU_AGENTS
from video_service.renewal_contracts import spec
from video_service.postgres import Conflict, Missing
from video_service.postgres.intake import Intake, public_asset, request_id
from video_service.postgres.registry import resource_id

CONTROL = frozenset(
    {
        "select",
        "join",
        "review",
        "control_if",
        "control_switch",
        "subtitle_tracks",
        "subtitle_outputs",
        "subtitle_track",
    }
)
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
        vocalization_runtime=None,
    ):
        super().__init__(database, store)
        self.agent_executor = agent_executor
        self.fleet = fleet
        self.engine_runtime_enabled = bool(engine_runtime_enabled)
        self.translation_runtime = translation_runtime
        self.transcription_runtime = transcription_runtime
        self.vocalization_runtime = vocalization_runtime
        from video_service.postgres.ticket_artifacts import TicketArtifacts

        self.ticket_artifacts = TicketArtifacts(store)

    def catalog(self):
        from mideagent_agents.catalog import catalog
        return {**catalog(), "local_engine_transport_enabled":self.engine_runtime_enabled}

    @staticmethod
    def _engine_role(node):
        if node["type"] in {"translate", "transcribe", "vocalize"} and (
            node.get("model_ref")
            or node.get("options", {}).get("model_source") == "registered_api"
        ):
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
        from video_service.postgres.engine_runtimes import EngineRuntimes

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

    def _execution_reasons(
        self, db, definition, bindings, options, done_nodes=(), model_bindings=None
    ):
        from video_service.postgres.engine_runtimes import EngineRuntimes

        reasons = []
        for node in definition["nodes"]:
            if node["id"] in done_nodes:
                continue
            role = self._engine_role(node)
            if (
                node["type"] in {"transcribe", "translate", "vocalize"}
                and not node.get("model_ref")
                and (
                    node["type"] == "vocalize"
                    or node.get("options", {}).get("model_source") == "registered_api"
                )
            ):
                reasons.append("등록 API 모델 선택이 필요: " + node["id"])
                continue
            if node.get("model_ref"):
                pin = (model_bindings or {}).get(node["id"])
                kind = {
                    "translate": "translation",
                    "transcribe": "transcription",
                    "vocalize": "vocalization",
                }.get(node["type"])
                executor = getattr(self, (kind or "unsupported") + "_runtime", None)
                if (
                    executor is None
                    or not pin
                    or not any(
                        executor.available(p) for p in [pin, *pin.get("fallbacks", [])]
                    )
                ):
                    reasons.append(
                        "등록 모델의 실행 transport/사용 가능한 후보 없음: "
                        + node["id"]
                    )
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
                and node.get("options", {}).get("processing_profile")
                not in {"silence_pack_v3", "regions_pack_v4", "regions_long_v5"}
            ):
                reasons.append(
                    "CPU 전처리는 필터 off 또는 명시 silence_pack_v3가 필요: "
                    + node["id"]
                )
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
            for kind in ("translation", "transcription", "vocalization"):
                if kind in delivery:
                    row[kind] = delivery[kind]
        return rows

    def _output_mode(self,job):
        from urllib.parse import urlsplit
        controlled=set()
        for runtime in (self.transcription_runtime,self.translation_runtime,self.vocalization_runtime):
            controlled.update(getattr(runtime,'nonpaid_origins',()))
        for pin in job['snapshot'].get('model_bindings',{}).values():
            endpoint=urlsplit(pin['endpoint'])
            if f'{endpoint.scheme}://{endpoint.netloc}'in controlled:
                return 'controlled'
        return None

    def _view(self, db, job):
        owner, identity = job["owner_id"], job["id"]
        from mideagent_orchestrator.dispatch_queue import DispatchQueue
        from video_service.postgres.job_processing_review import JobProcessingReview
        from mideagent_orchestrator.agent_pool import AgentPool

        processing_review = JobProcessingReview(self).capture_in(db, job)
        runs = DispatchQueue.decorate_in(db, self._runs(db, owner, identity))
        from video_service.postgres.task_logs import decorate_status_in
        runs,display_status=decorate_status_in(db,job,runs)
        from .agent_view import read_agent_view
        agent_workflow=read_agent_view(db,job,runs)
        if agent_workflow and any(n["state"]=="failed"for n in agent_workflow["nodes"]) and job["status"]not in {"cancelled","completed"}:
            display_status="failed"
        return {
            "agent_workflow":agent_workflow,
            "display_status":display_status,
            **public(job),
            "processing_review": processing_review,
            "output_mode": self._output_mode(job),
            "execution_state": 'preparing'if AgentPool.preparing_in(db,job)and not any(r['status']=='running'for r in runs)else None,
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
        rows = db.execute(
            "SELECT * FROM jobs WHERE id=%s LIMIT 2 FOR UPDATE",
            (resource_id(identity),),
        ).fetchall()
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
        keys = {
            "id",
            "ticket_number",
            "owner_id",
            "asset_id",
            "asset_owner_id",
            "workflow_id",
            "workflow_revision",
            "status",
            "execution_state",
            "display_status",
            "revision",
            "generation",
            "snapshot_sha256",
            "parent_id",
            "created_at",
            "updated_at",
            "output_mode",
            "processing_review",
            "artifact_manifest",
            "agent_workflow",
        }
        value = {k: state[k] for k in keys if k in state}
        value["snapshot"] = {
            k: v
            for k, v in state["snapshot"].items()
            if k
            in {
                "version",
                "asset",
                "inputs",
                "definition",
                "options",
                "recovery",
                "artifact_layout",
                "cpu_input_policy",
                "audio_pipeline_policy",
                "source_definition_sha256",
            }
        }
        public_source = value["snapshot"].get("asset", {})
        if "original_uploaded_by" in public_source:
            value["snapshot"]["asset"] = {
                **public_source,
                "uploaded_by": public_source["original_uploaded_by"],
            }
        value["snapshot_redacted"] = True
        value["executed_by"] = state["owner_id"]
        value["access"] = {"can_manage": actor == state["owner_id"]}
        run_keys = {
            "id",
            "node_id",
            "node_type",
            "status",
            "display_status",
            "display_reason",
            "options",
            "inputs",
            "error_code",
            "input_sha256",
            "settings_sha256",
            "attempt",
            "iteration",
            "generation",
            "started_at",
            "completed_at",
            "result",
            "dispatch",
            "translation",
            "transcription",
            "vocalization",
        }
        value["runs"] = []
        for run in state.get("runs", []):
            public_run = {k: run[k] for k in run_keys if k in run}
            if run.get("result"):
                public_run["result"] = {
                    k: v
                    for k, v in run["result"].items()
                    if k
                    in {
                        "status",
                        "outputs",
                        "previews",
                        "reused_from",
                        "translation",
                        "transcription",
                        "vocalization",
                        "ticket_artifacts",
                    }
                }
            value["runs"].append(public_run)
        review_keys = {"id", "node_run_id", "revision", "status", "draft", "contract"}
        value["reviews"] = [
            {k: v for k, v in r.items() if k in review_keys}
            for r in state.get("reviews", [])
        ]
        return value

    def shared_get(self, actor, identity):
        with self.database.connection() as db:
            return self._shared_view(
                self._view(db, self._shared_job(db, identity)), actor
            )

    def shared_jobs(self, actor):
        with self.database.connection() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE library_removed_at IS NULL ORDER BY created_at DESC,id,owner_id"
            ).fetchall()
            if len({r["id"] for r in rows}) != len(rows):
                raise Conflict("작업 식별자가 중복되어 공용 조회할 수 없습니다.")
            return [
                self._shared_view(
                    self._view(db, self._job(db, r["owner_id"], r["id"], lock=True)),
                    actor,
                )
                for r in rows
            ]

    def shared_file(
        self, actor, identity, run_id, port, *, inputs=False, preview=False
    ):
        with self.database.connection() as db:
            job = self._shared_job(db, identity)
            state = self._view(db, job)
        run = next((r for r in state["runs"] if r["id"] == run_id), None)
        if not run or (not inputs and run["status"] != "completed"):
            raise Missing("완료된 산출물/고정 입력을 찾을 수 없습니다.")
        reference = (
            run["inputs"].get(port)
            if inputs
            else (run["result"] or {}).get("outputs", {}).get(port)
        )
        if not reference or (preview and reference["type"] != "video"):
            raise Missing("산출물/고정 입력을 찾을 수 없습니다.")
        if not inputs and self.ticket_artifacts.enabled(job):
            try:
                return self.ticket_artifacts.output(
                    job, state["runs"], run_id, port, preview=preview
                )
            except Missing:
                if not preview:
                    raise
                # A verified pass-through output may reuse its preserved source WebM.
                # Manifest/hash failures are not caught and raw MP4 is never substituted.
                return self._video_preview_state(state, reference), reference["type"]
        path = (
            self._video_preview_state(state, reference)
            if preview
            else self.store.path(job["owner_id"], reference)
        )
        return path, reference["type"]

    def shared_manifest(self, actor, identity):
        with self.database.connection() as db:
            job = self._shared_job(db, identity)
            runs = self._runs(db, job["owner_id"], job["id"])
            return self.ticket_artifacts.read(job, runs)

    def jobs(self, owner):
        with self.database.connection() as db:
            ids = [
                r["id"]
                for r in db.execute(
                    "SELECT id FROM jobs WHERE owner_id=%s AND library_removed_at IS NULL ORDER BY created_at DESC,id",
                    (owner,),
                )
            ]
        # Release each row lock separately; never hold child then parent list locks.
        return [self.get(owner, identity) for identity in ids]

    def inspect(self, owner, identity, revision):
        public_definition = self.job_definition(owner, identity, revision)
        from mideagent_orchestrator.workflow import compile_definition
        agent_plan = compile_definition(public_definition) if public_definition.get("catalog_version")==2 else None
        definition = agent_plan["definition"] if agent_plan else public_definition
        reasons = []
        with self.database.connection() as db:
            bindings = self._engine_bindings(db, definition)
            workflow_owner, _ = self._job_definition(db, owner, identity, revision)
            models = self._bindings(db, workflow_owner, definition, active=False)
            model_names = {
                key: db.execute(
                    "SELECT name FROM model_revisions WHERE owner_id=%s AND model_id=%s AND revision=%s",
                    (pin["owner_id"], pin["model_id"], pin["revision"]),
                ).fetchone()["name"]
                for key, pin in models.items()
            }
            reasons += [
                {"node_id": None, "message": message}
                for message in self._execution_reasons(
                    db, definition, bindings, None, model_bindings=models
                )
            ]
        if definition["inputs"] not in (
            {"video": "video"},
            {"transcript": "transcript"},
        ):
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
        value = {
            "supported": not reasons,
            "definition_revision": revision,
            "model_ready": not reasons,
            "summary": [
                {
                    **{k: n[k] for k in ("id", "type", "options")},
                    **(
                        {
                            "model_required": True,
                            "model_ref": n.get("model_ref"),
                            "model": {
                                **{
                                    k: models[n["id"]][k]
                                    for k in (
                                        "model_id",
                                        "revision",
                                        "name",
                                        "provider",
                                        "protocol",
                                        "connection_id",
                                        "connection_revision",
                                        "model_types",
                                        "input_modalities",
                                        "output_modalities",
                                        "capabilities",
                                    )
                                    if k in models[n["id"]]
                                },
                                "model": models[n["id"]].get("remote_model"),
                                "name": model_names[n["id"]],
                            }
                            if n["id"] in models
                            else None,
                        }
                        if n["type"] in {"transcribe", "translate", "vocalize"}
                        else {}
                    ),
                }
                for n in definition["nodes"]
            ],
            "reasons": reasons,
            "notice": "포트 계약과 등록된 로컬 runtime 조회입니다. 실제 입력·소유권·언어·엔진 실행 검증은 별도입니다.",
        }

        if agent_plan:
            from mideagent_agents.catalog import CLASSES
            indexed={n["id"]:n for n in value["summary"]}
            value["summary"]=[{**indexed[CLASSES[n["type"]](n).publication()],
                "id":n["id"],"type":n["type"],"options":n["options"]}for n in public_definition["nodes"]]
        return value

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
            workflow_owner, definition = self._job_definition(
                db, owner, definition_id, definition_revision
            )
            from video_service.cpu_input_policy import source_policy
            from video_service.long_audio_budget import definition_policy
            from video_service.original_video_budget import resolve_definition

            original_definition_sha = digest(definition)
            from mideagent_orchestrator.workflow import compile_definition
            agent_plan = compile_definition(definition) if definition.get("catalog_version") == 2 else None
            if agent_plan:
                definition = agent_plan["definition"]
            definition = resolve_definition(asset, definition)

            for track_node in definition["nodes"]:
                if track_node["type"] == "subtitle_tracks" and (
                    track_node["options"]["original_language"]
                    != options.get("source_language")
                    or track_node["options"]["translated_language"]
                    != options.get("target_language", "ko")
                ):
                    raise ValueError(
                        "작업 원문·주 번역 언어는 명시 자막 묶기 설정과 같아야 합니다."
                    )
            audio_policy = definition_policy(definition)
            from video_service.long_audio_budget import bounded_vocalization_policy

            vocal_policy = bounded_vocalization_policy(asset, definition)
            cpu_policy = source_policy(asset, definition)
            if cpu_policy and getattr(self.store, "storage_kind", None) != "s3":
                raise ValueError("Large CPU input requires independent S3 transport")
            reference = self.asset_reference(asset)
            if asset["owner_id"] != owner:
                reference = {**reference, "source_owner_id": asset["owner_id"]}
            if cpu_policy and cpu_policy.get("id") == "original_video_v6":
                self.store.verify_descriptor(owner, reference)
            else:
                self.store.path(owner, reference)
            bindings = self._bindings(db, workflow_owner, definition, active=False)
            engine_bindings = self._engine_bindings(db, definition)
            input_refs = {"video": reference}
            if definition["inputs"] == {"transcript": "transcript"}:
                from video_service.postgres.translation import segments

                text = segments(options.get("transcript"))
                input_refs = {
                    "transcript": self.store.put(owner, [canonical(text)], "transcript")
                }
            if any(
                n["type"] in {"translate", "transcribe", "vocalize"}
                and n.get("model_ref")
                for n in definition["nodes"]
            ):
                from video_service.postgres.translation import languages

                languages(
                    options.get("source_language"), options.get("target_language", "ko")
                )
            parent = self._job(db, owner, parent_id) if parent_id else None
            from video_service.postgres.job_processing_review import JobProcessingReview

            if parent and JobProcessingReview.blocked_in(db, owner, parent_id):
                raise Conflict("관리자 판단에 연결된 새 작업 절차를 사용하세요.")
            if parent and parent["status"] not in ("failed", "cancelled"):
                raise Conflict(
                    "종료된 실패/취소 작업만 새 복구 작업으로 분리할 수 있습니다."
                )
            snapshot_asset = public_asset(asset)
            if asset["metadata"].get("legacy_origin"):
                # Keep the applied012 FK compatibility field as storage custody,
                # while preserving/displaying the real (possibly unknown) uploader.
                snapshot_asset["original_uploaded_by"] = snapshot_asset["uploaded_by"]
                snapshot_asset["storage_custodian_id"] = asset["owner_id"]
                snapshot_asset["uploaded_by"] = asset["owner_id"]
            snapshot = {
                **({"cpu_input_policy": cpu_policy} if cpu_policy else {}),
                **({"audio_pipeline_policy": audio_policy} if audio_policy else {}),
                **(
                    {
                        (
                            "long_vocalization_policy"
                            if vocal_policy["id"] == "streamed_vocalization_v2"
                            else "bounded_vocalization_policy"
                        ): vocal_policy
                    }
                    if vocal_policy
                    else {}
                ),
                **(
                    {"source_definition_sha256": original_definition_sha}
                    if digest(definition) != original_definition_sha
                    else {}
                ),
                "version": 1,
                "artifact_layout": 1,
                "asset": snapshot_asset,
                "inputs": input_refs,
                "definition": definition,
                **({"agent_plan_version":1,"agent_definition":agent_plan["agent_definition"],
                    "agent_tool_owners":agent_plan["owners"],
                    "agent_output_bindings":agent_plan["outputs"]} if agent_plan else {}),
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
            from video_service.postgres.subtitle_tracks import selected

            if selected(snapshot):
                from copy import deepcopy

                from video_service.subtitle_tracks import POLICY

                snapshot["subtitle_tracks_policy"] = deepcopy(POLICY)
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

    def _preflight_cpu_inputs(self, owner, identity, command=None):
        # Immutable input verification must not hold the mutable job row lock.
        with self.database.connection() as db:
            job = self._job(db, owner, identity)
            if not (
                job["snapshot"].get("cpu_input_policy")
                or job["snapshot"].get("audio_pipeline_policy")
            ):
                return None
            references = list(job["snapshot"]["inputs"].values())
            if command is not None:
                run = db.execute(
                    "SELECT request_sha256,inputs FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                    (owner, identity, command["attempt_id"]),
                ).fetchone()
                if not run or run["request_sha256"] != digest(command):
                    raise Conflict("Unknown frozen CPU input request")
                references = list(run["inputs"].values())
            else:
                for run in self._runs(db, owner, identity):
                    if run["status"] == "completed":
                        references.extend(
                            (run["result"] or {}).get("outputs", {}).values()
                        )
            snapshot_sha = job["snapshot_sha256"]
        audio_contracts = {}
        for ref in references:
            self.store.path(owner, ref)
            if job["snapshot"].get("audio_pipeline_policy") and ref["type"] == "audio":
                from video_service.postgres.audio_region_reviews import contract_for

                audio_contracts[digest(ref)] = contract_for(
                    self.store, owner, ref, kind="audio_regions_long_v5"
                )
        return {
            "audio_review_contracts": audio_contracts,
            "snapshot_sha256": snapshot_sha,
            "references": {digest(ref) for ref in references},
        }

    def _checked_input(self, owner, job, reference, verified):
        if job["snapshot"].get("cpu_input_policy") or job["snapshot"].get(
            "audio_pipeline_policy"
        ):
            if (
                not verified
                or verified["snapshot_sha256"] != job["snapshot_sha256"]
                or digest(reference) not in verified["references"]
            ):
                raise Conflict("CPU input context changed; reread required")
            return
        self.store.path(owner, reference)

    def _plan(self, db, job, verified=None):
        from video_service.postgres.job_processing_review import JobProcessingReview

        if JobProcessingReview(self).capture_in(db, job):
            return {
                "token": digest({"job": job["id"], "processing_review": True}),
                "ready": False,
                "reasons": ["관리자 처리 확인이 필요합니다."],
                "notice": "원 실행을 다시 시작하지 않습니다.",
            }
        for ref in job["snapshot"]["inputs"].values():
            self._checked_input(job["owner_id"], job, ref, verified)
        runs = self._runs(db, job["owner_id"], job["id"])
        for run in runs:
            if run["status"] == "completed":
                for ref in (run["result"] or {}).get("outputs", {}).values():
                    self._checked_input(job["owner_id"], job, ref, verified)
        reviews = db.execute(
            "SELECT id,revision,status,confirmed_sha256 FROM review_tasks WHERE owner_id=%s AND job_id=%s ORDER BY id",
            (job["owner_id"], job["id"]),
        ).fetchall()
        definition = job["snapshot"]["definition"]
        reasons = []
        if any(
            n["type"] == "vocalize"
            and n["options"].get("batch_policy") == "streamed_vocalization_v2"
            for n in definition["nodes"]
        ):
            from mideagent_orchestrator.model_roles import ModelRoleCoordinator

            if not ModelRoleCoordinator.enrolled(
                self, job["owner_id"], job["id"], role="vocalization"
            ):
                reasons.append("장문 보컬은 독립 보컬 실행을 먼저 선택해야 합니다.")
        if not job["recovery_ready"]:
            reasons.append("복구 receipt 검증이 끝나지 않았습니다.")
        if definition["inputs"] not in (
            {"video": "video"},
            {"transcript": "transcript"},
        ):
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
        pending = [
            n
            for n in definition["nodes"]
            if n["type"] == "translate"
            and n.get("model_ref")
            and not any(
                r["node_id"] == n["id"] and r["status"] == "completed" for r in runs
            )
        ]
        pending_asr = [
            n
            for n in definition["nodes"]
            if n["type"] == "transcribe"
            and n.get("model_ref")
            and not any(
                r["node_id"] == n["id"] and r["status"] == "completed" for r in runs
            )
        ]
        external_roles = []
        for role, nodes, executor in [
            ("translation", pending, self.translation_runtime),
            ("transcription", pending_asr, self.transcription_runtime),
        ]:
            if executor and any(
                executor.requires_paid([pin, *pin.get("fallbacks", [])])
                for node in nodes
                for pin in [job["snapshot"]["model_bindings"][node["id"]]]
            ):
                external_roles.append(role)
        pending_vocal = [
            n
            for n in definition["nodes"]
            if n["type"] == "vocalize"
            and n.get("model_ref")
            and not any(
                r["node_id"] == n["id"] and r["status"] == "completed" for r in runs
            )
        ]
        if (
            pending_vocal
            and self.vocalization_runtime
            and any(
                self.vocalization_runtime.requires_paid(
                    [pin, *pin.get("fallbacks", [])]
                )
                for node in pending_vocal
                for pin in [job["snapshot"]["model_bindings"][node["id"]]]
            )
        ):
            external_roles.append("vocalization")
        external = bool(external_roles)
        if external and not job["snapshot"].get("translation_paid_authorized"):
            reasons.append("전사/번역 후보 전체의 외부 호출 비용 동의가 필요합니다.")
        plan = {
            **(
                {
                    "vocalization_mode": self.vocalization_runtime.mode
                    if pending_vocal and self.vocalization_runtime
                    else None,
                    "vocalization_usage": [
                        self.vocalization_runtime.available(p)
                        for n in pending_vocal
                        for pin in [job["snapshot"]["model_bindings"][n["id"]]]
                        for p in [pin, *pin.get("fallbacks", [])]
                    ]
                    if self.vocalization_runtime
                    else [],
                }
                if pending_vocal
                else {}
            ),
            **(
                {"audio_pipeline_policy": job["snapshot"]["audio_pipeline_policy"]}
                if job["snapshot"].get("audio_pipeline_policy")
                else {}
            ),
            **(
                {
                    "transcription_mode": self.transcription_runtime.mode
                    if self.transcription_runtime
                    else None,
                    "transcription_usage": [
                        self.transcription_runtime.available(p)
                        for n in pending_asr
                        for pin in [job["snapshot"]["model_bindings"][n["id"]]]
                        for p in [pin, *pin.get("fallbacks", [])]
                    ]
                    if self.transcription_runtime
                    else [],
                }
                if pending_asr
                else {}
            ),
            "translation_mode": self.translation_runtime.mode
            if pending and self.translation_runtime
            else None,
            "translation_usage": [
                self.translation_runtime.available(p)
                for n in pending
                for pin in [job["snapshot"]["model_bindings"][n["id"]]]
                for p in [pin, *pin.get("fallbacks", [])]
            ]
            if self.translation_runtime
            else [],
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
            "cost": {
                "classification": "external_unpriced"
                if external
                else "verified_no_external_calls",
                "amount": None,
            },
            "reasons": sorted(set(reasons)),
        }
        return {
            "token": digest(plan),
            "ready": not reasons,
            "reasons": plan["reasons"],
            "paid_roles": external_roles,
            "cost": plan["cost"],
            "notice": "등록 모델 후보의 외부 호출은 비용이 발생할 수 있습니다. 금액은 미산정입니다."
            if external
            else "외부 유료 호출 없는 로컬/통제 HTTP 실행입니다. 동의 저장과 실행 요청은 별개입니다.",
            "snapshot_sha256": job["snapshot_sha256"],
            "generation": job["generation"],
        }

    def plan(self, owner, identity):
        verified = self._preflight_cpu_inputs(owner, identity)
        with self.database.connection() as db:
            return self._plan(db, self._job(db, owner, identity, lock=True), verified)

    def confirm(self, owner, identity, token, nonce):
        verified = self._preflight_cpu_inputs(owner, identity)
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
            plan = self._plan(db, job, verified)
            if not plan["ready"] or plan["token"] != token:
                raise Conflict("현재 입력/검수/계획을 다시 확인하세요.")
            row = db.execute(
                "INSERT INTO execution_consents(owner_id,job_id,id,request_id,plan_sha256,expires_at,request_sha256) VALUES (%s,%s,%s,%s,%s,now()+interval '15 minutes',%s) RETURNING *",
                (owner, identity, uuid4().hex, nonce, token, payload_sha),
            ).fetchone()
            return public(row)

    def admit(self, owner, identity, consent_id, nonce):
        verified = self._preflight_cpu_inputs(owner, identity)
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
            plan = self._plan(db, job, verified)
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
        from mideagent_orchestrator.dispatch_queue import DispatchQueue
        from mideagent_orchestrator.agent_pool import AgentPool

        deferred = (
            status == "running"
            and node["type"] in getattr(self, "defer_broker_agents", ())
            and DispatchQueue.managed_in(db, node["type"])
            and not AgentPool.enrolled_in(db,job)
        )
        if deferred:
            status = "waiting"
        identity = uuid4().hex
        from video_service.cpu_input_policy import LARGE_AGENTS, LARGE_PROFILE, lease_seconds

        cpu_policy = job["snapshot"].get("cpu_input_policy")
        from video_service.original_video_budget import CPU_ROLES as VIDEO_ROLES
        from video_service.original_video_budget import ID as ORIGINAL_ID
        from video_service.original_video_budget import policy as original_policy
        from video_service.original_video_budget import role_budget as original_role_budget

        original_video = bool(cpu_policy and cpu_policy.get("id") == ORIGINAL_ID)
        if cpu_policy and (
            (original_video and cpu_policy != original_policy())
            or (
                not original_video
                and (cpu_policy != LARGE_PROFILE or node["type"] not in LARGE_AGENTS)
            )
        ):
            raise Conflict("Frozen CPU input policy is unsupported")
        audio_policy = job["snapshot"].get("audio_pipeline_policy")
        if audio_policy:
            from video_service.long_audio_budget import policy

            if audio_policy != policy():
                raise Conflict("frozen_long_audio_policy_changed")
        command = {
            "protocol_version": 1,
            "run_id": job["id"],
            "attempt_id": identity,
            "generation": job["generation"],
            "agent": {
                "id": node["type"],
                "revision": "2" if cpu_policy and not original_video else "1",
            },
            "inputs": inputs,
            "options": node["options"],
        }
        if original_video and node["type"] in VIDEO_ROLES:
            command["agent"]["revision"] = "6"
            command["resource_budget"] = original_role_budget(node["type"])
        if (
            node["type"] == "preprocess_audio"
            and node["options"].get("processing_profile") == "silence_pack_v3"
        ):
            command["agent"]["revision"] = "3"
        if (
            node["type"] == "preprocess_audio"
            and node["options"].get("processing_profile") == "regions_pack_v4"
        ):
            command["agent"]["revision"] = "4"
        if (
            node["type"] == "generate_subtitle"
            and node["options"].get("format") == "srt_smi"
        ):
            command["agent"]["revision"] = "3"
            if "language" not in command["options"]:
                producers = [
                    edge["source"]["node"]
                    for edge in job["snapshot"]["definition"]["edges"]
                    if edge["target"] == {"node": node["id"], "port": "transcript"}
                ]
                translated_input = any(
                    item["id"] in producers and item["type"] == "translate"
                    for item in job["snapshot"]["definition"]["nodes"]
                )
                language = job["snapshot"]["options"].get(
                    "target_language" if translated_input else "source_language", "und"
                )
                command["options"]["language"] = (
                    "und" if language == "auto" else language
                )
        if node["options"].get("media_budget") == "audio_long_v5":
            from video_service.long_audio_budget import CPU_ROLES, command_budget

            if not audio_policy:
                raise Conflict("long_audio_snapshot_budget_missing")
            command["resource_budget"] = command_budget(node["type"], node["options"])
            if node["type"] in CPU_ROLES:
                command["agent"]["revision"] = "5"
        if (
            node["type"] in {"translate", "transcribe", "vocalize"}
            and node.get("model_ref")
            and status == "running"
        ):
            pin = job["snapshot"]["model_bindings"][node["id"]]
            kind = {
                "translate": "translation",
                "transcribe": "transcription",
                "vocalize": "vocalization",
            }[node["type"]]
            command[kind] = {
                "candidates": [pin, *pin.get("fallbacks", [])],
                "source_language": node["options"].get(
                    "source_language", job["snapshot"]["options"]["source_language"]
                ),
                **(
                    {
                        "target_language": node["options"]["target_language"]
                        if node["options"].get("translation_profile")
                        == "language_target_v1"
                        else job["snapshot"]["options"]["target_language"]
                    }
                    if kind == "translation"
                    else {}
                ),
                "paid_authorized": job["snapshot"].get(
                    "translation_paid_authorized", False
                ),
            }
            if kind == "vocalization":
                command[kind].update(
                    purpose="vocalization_regions_v1",
                    strength=node["options"]["strength"],
                )
            if kind == "transcription" and node["options"].get("clock_policy") in {
                "packed_projection_v2",
                "packed_projection_v5",
            }:
                command[kind]["clock_policy"] = node["options"]["clock_policy"]
            if node["options"].get("media_budget") == "audio_long_v5":
                command[kind]["media_budget"] = "audio_long_v5"
            batch_policy = node["options"].get("batch_policy", "single")
            if batch_policy != "single":
                expected = {
                    "transcription": "bounded_60s_v1",
                    "translation": "bounded_100x16k_v1",
                    "vocalization": batch_policy
                    if batch_policy
                    in {"bounded_vocalization_v1", "streamed_vocalization_v2"}
                    else "bounded_vocalization_v1",
                }[kind]
                if batch_policy != expected:
                    raise Conflict("지원하지 않는 분할 실행 정책입니다.")
                command[kind]["batch_policy"] = batch_policy
                command[kind]["max_model_calls"] = int(
                    node["options"].get("max_model_calls", "128")
                )
                from video_service.cpu_input_policy import model_runtime_seconds

                command[kind]["max_runtime_seconds"] = model_runtime_seconds(
                    command[kind]["max_model_calls"]
                )
        elif self._engine_role(node) and status == "running":
            from video_service.engine_protocol import make_command

            if not self.engine_runtime_enabled:
                raise Conflict("engine transport가 비활성 상태입니다.")
            pin = job["snapshot"]["engine_bindings"][node["id"]]
            from video_service.postgres.engine_runtimes import EngineRuntimes

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
            "INSERT INTO node_runs(owner_id,job_id,id,node_id,agent_revision,attempt,generation,status,input_sha256,settings_sha256,inputs,options,node_type,request,request_sha256,claim_id,lease_owner,lease_expires_at,started_at) VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()+(%s*interval '1 second'),now()) RETURNING *",
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
                lease_seconds(command) if command["protocol_version"] == 1 else 120,
            ),
        ).fetchone()
        if deferred:
            row = db.execute(
                "UPDATE node_runs SET started_at=NULL,lease_owner=NULL,lease_expires_at=NULL WHERE id=%s RETURNING *",
                (identity,),
            ).fetchone()
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

    @staticmethod
    def _ready_agent_tools(snapshot, indexed):
        from mideagent_orchestrator.workflow import ready_tool_ids
        return ready_tool_ids(snapshot, indexed)

    def claim_next(self, owner, identity):
        verified = self._preflight_cpu_inputs(owner, identity)
        from video_service.postgres.subtitle_tracks import SubtitleTracks

        subtitle_staged = SubtitleTracks(self).preflight(owner, identity)
        if verified and subtitle_staged:
            for material in subtitle_staged.values():
                if material["snapshot_sha256"] != verified["snapshot_sha256"]:
                    raise Conflict("staged_subtitle_snapshot_changed")
                for reference in material.get("outputs", {}).values():
                    # Actual bytes are checked before taking the scheduling lock;
                    # staged input/snapshot digests are checked again at adoption.
                    self.store.path(owner, reference)
                    verified["references"].add(digest(reference))
        with self.database.connection() as db:
            job = self._job(db, owner, identity, lock=True)
            from video_service.postgres.job_processing_review import JobProcessingReview

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
            eligible_tools = self._ready_agent_tools(job["snapshot"], indexed)
            for node in definition["nodes"]:
                if eligible_tools is not None and node["id"] not in eligible_tools:
                    continue
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
                if (
                    node["type"]
                    in {"subtitle_tracks", "subtitle_outputs", "subtitle_track"}
                    or node.get("options", {}).get("review_kind")
                    == "subtitle_tracks_v1"
                ) and node["id"] not in (subtitle_staged or {}):
                    # Stage a newly completed control parent outside the lock next claim.
                    continue
                for ref in inputs.values():
                    self._checked_input(owner, job, ref, verified)
                from mideagent_orchestrator.agent_pool import AgentPool
                if not AgentPool.ready_in(db,job,node):
                    continue
                instance = None
                if (
                    self.fleet is not None
                    and node["type"] in CPU_AGENTS
                    and not self._engine_role(node)
                ):
                    instance = self.fleet.reserve(db, node["type"])
                    if instance is None:
                        continue
                from .workflow import scope_snapshot
                scope = scope_snapshot(job["snapshot"])
                def invoke_tool(identity):
                    if identity != node["id"]:
                        raise Conflict("agent_tool_selection_changed")
                    return self._insert_run(db, job, node, inputs,
                        "review_required" if node["type"] == "review" else "running")
                if scope:
                    from mideagent_agents.catalog import CLASSES
                    agent_node=next(n for n in scope["definition"]["nodes"] if n["id"]==scope["owners"][node["id"]])
                    agent=CLASSES[agent_node["type"]](agent_node,tool_bindings=scope["bindings"][agent_node["id"]])
                    claimed=agent.advance(indexed,definition,invoke_tool)
                    if claimed is None:
                        continue
                    row,command=claimed
                else:
                    row,command=invoke_tool(node["id"])
                AgentPool.assigned_in(db,job,node,row)
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
                    draft = {"approved": False}
                    if node["options"].get("review_kind") == "subtitle_tracks_v1":
                        staged = (subtitle_staged or {}).get(node["id"])
                        if (
                            not staged
                            or staged["inputs_sha256"] != digest(inputs)
                            or staged["snapshot_sha256"] != job["snapshot_sha256"]
                        ):
                            raise Conflict("자막 자료가 바뀌었습니다. 재검증하세요.")
                        contract = staged["contract"]
                        draft = {
                            "approved": False,
                            "tracks": {
                                name: {
                                    "transcript": track["transcript"],
                                    "lineage": track["lineage"],
                                }
                                for name, track in contract["tracks"].items()
                            },
                        }
                    elif node["options"].get("review_kind") == "audio_regions_long_v5":
                        contract = (
                            (verified or {})
                            .get("audio_review_contracts", {})
                            .get(digest(inputs["value"]))
                        )
                        if not contract:
                            raise Conflict(
                                "long_audio_review_source_not_preflight_verified"
                            )
                        draft = {"approved": False, "protected": [], "removals": []}
                    elif node["options"].get("review_kind") == "audio_regions_v1":
                        from video_service.postgres.audio_region_reviews import contract_for

                        contract = contract_for(self.store, owner, inputs["value"])
                        draft = {"approved": False, "protected": [], "removals": []}
                    db.execute(
                        "INSERT INTO review_tasks(owner_id,job_id,node_run_id,id,revision,contract,draft,status) VALUES (%s,%s,%s,%s,1,%s,%s,'draft')",
                        (
                            owner,
                            identity,
                            row["id"],
                            review_id,
                            Jsonb(contract),
                            Jsonb(draft),
                        ),
                    )
                    db.execute(
                        "INSERT INTO review_revisions VALUES (%s,%s,1,%s,%s,now())",
                        (
                            owner,
                            review_id,
                            Jsonb(draft),
                            digest(draft),
                        ),
                    )
                    indexed[node["id"]] = row
                    continue
                if node["type"] in CONTROL:
                    try:
                        if node["type"] in {
                            "subtitle_tracks",
                            "subtitle_outputs",
                            "subtitle_track",
                        }:
                            staged = (subtitle_staged or {}).get(node["id"])
                            if (
                                not staged
                                or staged["inputs_sha256"] != digest(inputs)
                                or staged["snapshot_sha256"] != job["snapshot_sha256"]
                            ):
                                raise Conflict(
                                    "자막 자료가 바뀌었습니다. 재검증하세요."
                                )
                            outputs = staged["outputs"]
                        else:
                            outputs = self._control_outputs(
                                owner, node["type"], inputs, node["options"]
                            )
                        receipt = self.ticket_artifacts.capture(
                            db,
                            job,
                            row,
                            {
                                "outputs": outputs,
                                "transport": "application_control",
                            },
                        )
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
                if not (
                    command.get("translation")
                    or command.get("transcription")
                    or command.get("vocalization")
                ) and (
                    node["type"] not in CPU_AGENTS
                    and not self._engine_role(node)
                    or node.get("model_ref")
                ):
                    raise Conflict("비활성 실행 경로")
                message_type = (
                    "agent.engine.command.v2"
                    if command["protocol_version"] == 2
                    else "agent.command.v1"
                )
                if (
                    command.get("translation")
                    or command.get("transcription")
                    or command.get("vocalization")
                ):
                    from video_service.registered_broker import COMMAND as REGISTERED_COMMAND

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
        from video_service.long_audio_budget import validate_command

        validate_command(command)
        # Reserve the exact delivery before starting a process. A duplicate whose
        # outcome is unknown never automatically launches a second process.
        with self.database.connection() as db:
            job = self._job(db, owner, command["run_id"], lock=True)
            from video_service.postgres.job_processing_review import JobProcessingReview

            if JobProcessingReview(self).capture_in(db, job):
                raise Conflict("관리자 확인 중인 원 실행은 다시 시작하지 않습니다.")
            run = db.execute(
                "SELECT *,lease_expires_at>now() AS lease_valid FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, command["run_id"], command["attempt_id"]),
            ).fetchone()
            if not run or run["request_sha256"] != digest(command):
                raise Conflict("실행 요청 무결성 오류")
            if (
                command.get("transcription")
                and db.execute(
                    "SELECT to_regclass('model_role_tasks') AS relation"
                ).fetchone()["relation"]
            ):
                independent = db.execute(
                    "SELECT 1 FROM model_role_tasks WHERE owner_id=%s AND job_id=%s AND attempt_id=%s",
                    (owner, command["run_id"], command["attempt_id"]),
                ).fetchone()
                if independent:
                    raise Conflict("independent_role_owns_attempt")
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
        if (
            command.get("translation")
            or command.get("transcription")
            or command.get("vocalization")
        ):
            from video_service.postgres.translation import execute_translation

            if command.get("vocalization"):
                from video_service.postgres.vocalization import execute_vocalization

                result = execute_vocalization(self, owner, command)
            else:
                result = execute_translation(self, owner, command)
            with self.database.connection() as db:
                db.execute(
                    "UPDATE agent_deliveries SET status='completed',result=%s WHERE owner_id=%s AND job_id=%s AND node_run_id=%s AND status='started'",
                    (Jsonb(result), owner, command["run_id"], command["attempt_id"]),
                )
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
        from video_service.cpu_input_policy import command_timeout

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
                timeout=command_timeout(command),
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
            from video_service.engine_protocol import envelope

            envelope(owner, command, result)
        elif result.get("transport") == "s3_engine":
            raise ValueError("Engine result cannot satisfy a CPU command")
        from video_service.long_audio_budget import validate_command

        audio_budget = validate_command(command)
        expected = spec(command["agent"]["id"], command["options"])["outputs"]
        values = result.get("outputs")
        if audio_budget and (
            not isinstance(values, dict)
            or any(
                not isinstance(ref, dict)
                or type(ref.get("bytes")) is not int
                or not 0 < ref["bytes"] <= audio_budget["outputs"].get(port, 0)
                for port, ref in values.items()
            )
        ):
            raise ValueError("long_audio_result_role_budget_exceeded")
        if not isinstance(values, dict) or set(values) != set(expected):
            raise ValueError("Agent output ports differ")
        if result.get("transport") in {
            "registered_http",
            "independent_model_role",
        } and (
            command.get("translation")
            or command.get("transcription")
            or command.get("vocalization")
        ):
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
                    owner,
                    iter(lambda: stream.read(1024 * 1024), b""),
                    ref["type"],
                    **(
                        {"max_bytes": audio_budget["outputs"][port]}
                        if audio_budget
                        else {}
                    ),
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
                candidates.extend(
                    (owner, p)
                    for p in (run["result"] or {}).get("previews", {}).values()
                )
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
        verified = self._preflight_cpu_inputs(owner, command["run_id"], command)
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
            from video_service.postgres.job_processing_review import JobProcessingReview

            processing = JobProcessingReview(self)
            processing.capture_in(db, job)
            if processing.late_in(db, job, run, command, result):
                return self._view(db, job)
            from mideagent_orchestrator.dispatch_queue import DispatchQueue

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
                        self._checked_input(owner, job, ref, verified)
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
                            "vocalization",
                            "vocalization",
                        )
                    }
                    receipt["outputs"] = outputs
                    receipt["previews"] = {}
                    receipt = self.ticket_artifacts.capture(db, job, run, receipt)
                    db.execute(
                        "UPDATE node_runs SET status='completed',result=%s,completed_at=now(),lease_owner=NULL,lease_expires_at=NULL WHERE owner_id=%s AND job_id=%s AND id=%s",
                        (Jsonb(receipt), owner, identity, run_id),
                    )
                    for port, ref in outputs.items():
                        if self.ticket_artifacts.enabled(job):
                            ref = next(
                                entry["storage"]
                                for entry in receipt["ticket_artifacts"]["entries"]
                                if entry["output_port"] == port
                            )
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
                    if getattr(self, "full_previews_enabled", False):
                        from video_service.postgres.video_previews import VideoPreviews

                        previews = VideoPreviews(self)
                        for port, ref in outputs.items():
                            if ref["type"] == "video":
                                previews.enqueue_in(
                                    db,
                                    owner,
                                    previews.artifact_source(
                                        db, identity, run_id, port
                                    ),
                                    automatic=True,
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
                                    **{
                                        kind: result[kind]
                                        for kind in (
                                            "translation",
                                            "transcription",
                                            "vocalization",
                                        )
                                        if command.get(kind) and kind in result
                                    },
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
        with self.database.connection() as db:
            if self._job(db, owner, identity)["snapshot"].get("cpu_input_policy"):
                raise Conflict("Large CPU input requires independent broker execution")
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
        from video_service.postgres.model_call_fence import lock_product_cancel

        with self.database.connection() as db:
            lock_product_cancel(db, owner, identity)
            job = self._job(db, owner, identity, lock=True)
            from video_service.postgres.job_processing_review import JobProcessingReview

            if JobProcessingReview(self).capture_in(db, job):
                raise Conflict(
                    "확인 중인 원 기록은 초기화하거나 취소로 덮어쓰지 않습니다."
                )
            if job["cancel_requested"]:
                return {**self._view(db, job), "cancel_outcome": "already_requested"}
            if job["status"] in ("completed", "failed", "cancelled"):
                return {**self._view(db, job), "cancel_outcome": "terminal_noop"}
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
            from mideagent_orchestrator.model_roles import ModelRoleCoordinator

            ModelRoleCoordinator.enqueue_cancel_in(db, job)
            return {**self._view(db, job), "cancel_outcome": "newly_requested"}

    def _review(self, db, owner, identity, lock=False):
        row = db.execute(
            "SELECT * FROM review_tasks WHERE owner_id=%s AND id=%s"
            + (" FOR UPDATE" if lock else ""),
            (owner, resource_id(identity)),
        ).fetchone()
        if not row:
            raise Missing("검수 자료를 찾을 수 없습니다.")
        return row

    def review_source(self, actor, identity):
        # All authenticated users may read shared media; edits retain owner gates.
        with self.database.connection() as db:
            rows = db.execute(
                "SELECT * FROM review_tasks WHERE id=%s LIMIT 2",
                (resource_id(identity),),
            ).fetchall()
            if len(rows) != 1 or rows[0]["contract"].get("kind") not in {
                "audio_regions_v1",
                "audio_regions_long_v5",
            }:
                raise Missing("음성 구간 검수 자료를 찾을 수 없습니다.")
            row = rows[0]
            self._shared_job(db, row["job_id"])
        return self.store.path(row["owner_id"], row["contract"]["source"])

    def review_save(self, owner, identity, revision, draft):
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
            if row["contract"].get("kind") == "subtitle_tracks_v1":
                if (
                    not isinstance(draft, dict)
                    or set(draft) != {"approved", "tracks"}
                    or type(draft["approved"]) is not bool
                    or draft["tracks"] != row["draft"]["tracks"]
                ):
                    raise ValueError("자막 내용은 언어별 저장 경로로 저장하세요.")
            elif row["contract"].get("kind") in {
                "audio_regions_v1",
                "audio_regions_long_v5",
            }:
                from video_service.postgres.audio_region_reviews import document_for

                document_for(row["contract"], draft)
            elif draft != {"approved": True} and draft != {"approved": False}:
                raise ValueError("검수 확인 필드 오류")
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
        with self.database.connection() as read_db:
            hint = self._review(read_db, owner, identity)
        if hint["contract"].get("kind") == "subtitle_tracks_v1":
            from video_service.postgres.subtitle_tracks import SubtitleTracks

            return SubtitleTracks(self).confirm(owner, identity, revision)
        with self.database.connection() as db:
            hint = self._review(db, owner, identity)
            job = self._job(db, owner, hint["job_id"], lock=True)
            row = self._review(db, owner, identity, lock=True)
            if (
                row["revision"] != revision
                or (
                    row["draft"].get("approved") is not True
                    if row["contract"].get("kind")
                    in {"audio_regions_v1", "audio_regions_long_v5"}
                    else row["draft"] != {"approved": True}
                )
                or job["status"] != "review_required"
            ):
                raise Conflict("저장된 최신 검수 자료를 확인하세요.")
            source = row["contract"]["source"]
            self.store.path(owner, source)
            outputs = {"value": source}
            if row["contract"].get("kind") in {
                "audio_regions_v1",
                "audio_regions_long_v5",
            }:
                if row["status"] == "confirmed":
                    return public(row)
                from video_service.postgres.audio_region_reviews import document_for

                document = document_for(row["contract"], row["draft"])
                outputs["regions"] = self.store.put(
                    owner, [canonical(document)], "audio_regions"
                )
            confirmed_sha = digest(
                {
                    "draft": row["draft"],
                    "source": source,
                    "revision": revision,
                    **({"regions": outputs["regions"]} if "regions" in outputs else {}),
                }
            )
            db.execute(
                "UPDATE review_tasks SET status='confirmed',confirmed_sha256=%s WHERE owner_id=%s AND id=%s",
                (confirmed_sha, owner, identity),
            )
            run = db.execute(
                "SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, row["job_id"], row["node_run_id"]),
            ).fetchone()
            receipt = self.ticket_artifacts.capture(
                db,
                job,
                run,
                {
                    "outputs": outputs,
                    "transport": "human_gate",
                    "review_id": identity,
                    "review_revision": revision,
                    "confirmed_sha256": confirmed_sha,
                },
            )
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
