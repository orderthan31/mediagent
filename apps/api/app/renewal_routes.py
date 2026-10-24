"""Opt-in renewal routes. Mount only with an explicit content store."""

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import Field, StrictBool, StrictInt
from video_service.cpu_agents import digest
from video_service.original_upload_policy import MAX_ORIGINAL_UPLOAD
from video_service.postgres import Conflict
from video_service.renewal_contracts import validate

from .renewal import Body


class Upload(Body):
    filename: str = Field(min_length=1, max_length=255)
    size: StrictInt = Field(gt=0, le=MAX_ORIGINAL_UPLOAD)
    request_id: str = Field(min_length=1, max_length=100)


class Prefix(Body):
    offset: StrictInt = Field(ge=0)
    length: StrictInt = Field(gt=0, le=4194304)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    uploaded_bytes: StrictInt | None = Field(default=None, ge=0)


class Definition(Body):
    catalog_version: StrictInt
    revision: StrictInt = Field(ge=0)
    name: str = Field(min_length=1, max_length=80)
    inputs: dict
    nodes: list = Field(max_length=100)
    edges: list = Field(max_length=300)


class SourceRevision(Body):
    kind: str
    revision: StrictInt = Field(ge=1)


class Restore(Body):
    revision: StrictInt = Field(ge=1)
    source: SourceRevision


class Selection(Body):
    asset_id: str = Field(pattern="^[a-f0-9]{32}$")
    definition_id: str = Field(pattern="^[a-f0-9]{32}$")
    definition_revision: StrictInt = Field(ge=1)
    recovery_enabled: StrictBool = False
    options: dict = Field(default_factory=dict)


class Create(Selection):
    request_id: str = Field(min_length=1, max_length=100)
    token: str = Field(pattern="^[a-f0-9]{64}$")
    paid_confirmed: StrictBool = False


class Inspect(Body):
    definition_id: str = Field(pattern="^[a-f0-9]{32}$")
    definition_revision: StrictInt = Field(ge=1)


class Confirm(Body):
    token: str = Field(pattern="^[a-f0-9]{64}$")
    request_id: str = Field(min_length=1, max_length=100)


class Admit(Body):
    consent_id: str = Field(pattern="^[a-f0-9]{32}$")
    request_id: str = Field(min_length=1, max_length=100)


class Revision(Body):
    revision: StrictInt = Field(ge=1)


class Review(Revision):
    draft: dict


class Recovery(Body):
    request_id: str = Field(min_length=1, max_length=100)
    acknowledge_duplicate_risk: StrictBool


def ledger(job):
    statuses = {
        "draft": "READY",
        "waiting": "QUEUED",
        "running": "ANALYZING",
        "review_required": "AWAITING_REVIEW",
        "completed": "COMPLETED",
        "failed": "FAILED",
        "cancelled": "CANCELLED",
        "cancelling": "CANCELLING",
    }
    snapshot = job["snapshot"]
    return {
        "job_id": job["id"],
        "ticket_number": str(job["ticket_number"]),
        "status": "PROCESSING_REVIEW"
        if job.get("processing_review")
        else statuses[job["status"]],
        "original_filename": snapshot["asset"]["original_filename"],
        "expected_size": snapshot["asset"]["size_bytes"],
        "uploaded_bytes": snapshot["asset"]["size_bytes"],
        "created_at": job["created_at"],
        "completed_at": None,
        "source_language": "auto",
        "target_language": "ko",
        "quality_profile": "balanced",
        "error": None,
        "metadata": {
            "processing_review": job.get("processing_review"),
            "raw_status": job["status"],
            "asset_id": job["asset_id"],
            "workflow": {
                "definition_id": job["workflow_id"],
                "revision": job["workflow_revision"],
                "name": snapshot["definition"]["name"],
                "template": "renewal",
                "stages": [n["type"] for n in snapshot["definition"]["nodes"]],
            },
        },
    }


def mount_runtime(
    app, runtime, session, administrator, *, local_execution, broker_factory=None
):
    session_dependency = Depends(session)

    def owner(value=session_dependency):
        return value["user"]["id"]

    owner_dependency = Depends(owner)
    from .projection_recovery_routes import mount_projection_recoveries

    mount_projection_recoveries(app, runtime, owner_dependency)

    from video_service.content_store import MAX_CONTENT

    from .original_finalizations import OriginalFinalizations

    finalizations = OriginalFinalizations(runtime)
    from contextlib import asynccontextmanager

    from starlette.concurrency import run_in_threadpool

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def original_lifespan(application):
        async with previous_lifespan(application) as state:
            try:
                yield state
            finally:
                await run_in_threadpool(finalizations.close)

    app.router.lifespan_context = original_lifespan

    if getattr(runtime, "full_previews_enabled", False):
        from .full_preview_routes import mount_full_previews

        mount_full_previews(app, runtime, owner_dependency)

    administrator_dependency = Depends(administrator)

    def admin_owner(value=administrator_dependency):
        return value["user"]["id"]

    admin_dependency = Depends(admin_owner)

    @app.get("/api/settings/node-catalog")
    def nodes(owned=admin_dependency):
        return runtime.catalog()

    @app.get("/api/video-uploads")
    def uploads(owned=owner_dependency):
        return {
            "uploads": [
                finalizations.snapshot(owned, r["upload_id"], r)
                for r in runtime.uploads(owned)
            ]
        }

    @app.post("/api/video-uploads", status_code=201)
    def new_upload(body: Upload, owned=owner_dependency):
        return runtime.upload_create(owned, body.filename, body.size, body.request_id)

    @app.get("/api/video-uploads/{identity}")
    def upload(identity: str, owned=owner_dependency):
        return finalizations.snapshot(owned, identity)

    @app.put("/api/video-uploads/{identity}/chunks")
    async def chunk(
        identity: str,
        request: Request,
        offset: int = Query(ge=0),
        owned=owner_dependency,
    ):
        # The outer ASGI middleware enforces the limit against streamed bytes.
        return runtime.upload_chunk(owned, identity, offset, await request.body())

    @app.post("/api/video-uploads/{identity}/verify", status_code=204)
    def verify(identity: str, body: Prefix, owned=owner_dependency):
        runtime.upload_verify(owned, identity, **body.model_dump())

    @app.post("/api/video-uploads/{identity}/complete")
    def complete(identity: str, owned=owner_dependency):
        current = runtime.upload_get(owned, identity)
        if not current["asset_id"] and current["expected_size"] > MAX_CONTENT:
            result = finalizations.start(owned, identity)
            return JSONResponse(result, status_code=200 if result["asset_id"] else 202)
        return runtime.upload_complete(owned, identity)

    @app.get("/api/videos")
    def videos(owned=owner_dependency):
        return {"videos": runtime.assets(owned)}

    @app.get("/api/videos/{identity}")
    def video(identity: str, owned=owner_dependency):
        # Original details intentionally contain no jobs/subtitle/faceswap controls.
        return {"video": runtime.asset(owned, identity), "jobs": []}

    @app.get("/api/videos/{identity}/subtitles")
    def source_no_subtitles(identity: str, owned=owner_dependency):
        runtime.asset(owned, identity)
        return {"subtitles": []}

    @app.get("/api/videos/{identity}/stream")
    def stream(identity: str, download: bool = False, owned=owner_dependency):
        return FileResponse(
            runtime.web_preview_path(owned, identity),
            media_type="video/webm",
            filename=identity + "-web.webm" if download else None,
        )

    @app.get("/api/videos/{identity}/download")
    def original(identity: str, owned=owner_dependency):
        asset = runtime.asset(owned, identity)
        return FileResponse(
            runtime.asset_path(owned, identity),
            media_type="application/octet-stream",
            filename=asset["original_filename"],
        )

    @app.get("/api/videos/{identity}/thumbnail")
    def thumbnail(identity: str, owned=owner_dependency):
        return FileResponse(
            runtime.thumbnail_path(owned, identity), media_type="image/jpeg"
        )

    @app.get("/api/settings/workflow-definitions")
    def definitions(owned=admin_dependency):
        return {"definitions": runtime.definitions(owned)}

    @app.post("/api/settings/workflow-definitions/validate")
    def validation(body: Definition, owned=admin_dependency):
        return validate(body.model_dump())

    @app.get("/api/settings/workflow-definitions/{identity}")
    def definition(identity: str, owned=admin_dependency):
        return runtime.definition(owned, identity)

    @app.put("/api/settings/workflow-definitions/{identity}")
    def save_definition(identity: str, body: Definition, owned=admin_dependency):
        return runtime.save_definition(owned, identity, body.model_dump())

    @app.get("/api/settings/workflow-definitions/{identity}/versions")
    def versions(identity: str, owned=admin_dependency):
        return {"versions": runtime.versions(owned, identity)}

    @app.post("/api/settings/workflow-definitions/{identity}/restore")
    def restore(identity: str, body: Restore, owned=admin_dependency):
        if body.source.kind != "definition_revision":
            raise ValueError("저장된 정의 이력만 복원할 수 있습니다.")
        return runtime.restore_definition(
            owned, identity, body.revision, body.source.revision
        )

    @app.get("/api/work-entry/workflows")
    def job_choices(owned=owner_dependency):
        return {"definitions": runtime.job_definitions(owned)}

    @app.get("/api/work-entry/catalog")
    def job_catalog(owned=owner_dependency):
        return runtime.catalog()

    @app.get("/api/work-entry/workflows/{identity}")
    def job_graph(identity: str, revision: int = Query(ge=1), owned=owner_dependency):
        return runtime.job_definition(owned, identity, revision)

    @app.post("/api/settings/work-entry/inspect", dependencies=[Depends(administrator)])
    @app.post("/api/work-entry/inspect")
    def inspect(body: Inspect, owned=owner_dependency):
        result = runtime.inspect(owned, body.definition_id, body.definition_revision)
        if not local_execution:
            result["supported"] = result["model_ready"] = False
            result["reasons"].append(
                {"node_id": None, "message": "명시적인 CPU 실행 허용이 없습니다."}
            )
        return result

    def selection_plan(owned, selection):
        if selection.recovery_enabled:
            raise ValueError("복구는 원 작업의 별도 복구 경로를 사용하세요.")
        source = runtime.asset(owned, selection.asset_id)
        definition = runtime.job_definition(
            owned, selection.definition_id, selection.definition_revision
        )
        from video_service.cpu_input_policy import source_policy

        cpu_policy = source_policy(
            {
                "bytes": source["size_bytes"],
                "metadata": {
                    "registration_state": "verified"
                    if source["content_verified"]
                    else "unverified",
                    "media": source.get("media"),
                },
            },
            definition,
        )
        if cpu_policy and broker_factory is None:
            raise Conflict(
                "Large CPU video requires the independent broker execution path"
            )
        runtime.asset_path(owned, selection.asset_id)
        inspection = runtime.inspect(
            owned, selection.definition_id, selection.definition_revision
        )
        if not local_execution or not inspection["supported"]:
            raise Conflict(
                "지원되는 CPU 작업/입력인지 확인하세요. 모델 호출은 비활성입니다."
            )
        return {
            "token": digest(
                {
                    "source": source,
                    "definition": definition,
                    "selection": selection.model_dump(),
                    **({"cpu_input_policy": cpu_policy} if cpu_policy else {}),
                }
            ),
            "paid_roles": [
                role
                for node_type, role in (
                    ("translate", "translation"),
                    ("transcribe", "transcription"),
                )
                if getattr(runtime, role + "_runtime")
                and getattr(runtime, role + "_runtime").mode == "external"
                and any(
                    n["type"] == node_type and n.get("model_ref")
                    for n in definition["nodes"]
                )
            ],
            **({"cpu_input_policy": cpu_policy} if cpu_policy else {}),
            "notice": "작업 생성은 저장만 합니다. 작업 상세에서 계획 확인과 별도 실행이 필요합니다."
            + (
                " 대용량 CPU 전용: 원본4GiB/길이6시간/처리2시간/캐시10GiB/결과256MiB 한도입니다."
                if cpu_policy
                else ""
            ),
        }

    @app.post("/api/settings/work-entry/preview", dependencies=[Depends(administrator)])
    @app.post("/api/work-entry/preview")
    def preview(body: Selection, owned=owner_dependency):
        return selection_plan(owned, body)

    @app.post(
        "/api/settings/work-entry/create",
        status_code=201,
        dependencies=[Depends(administrator)],
    )
    @app.post("/api/work-entry/create", status_code=201)
    def create(body: Create, owned=owner_dependency):
        selection = Selection(
            **body.model_dump(exclude={"request_id", "token", "paid_confirmed"})
        )
        plan = selection_plan(owned, selection)
        if plan["paid_roles"] and not body.paid_confirmed:
            raise HTTPException(
                403, "전사/번역 후보 전체의 외부 호출 비용 동의가 필요합니다."
            )
        if plan["token"] != body.token:
            raise Conflict("입력/정의가 변경됐습니다. 다시 확인하세요.")
        return runtime.create(
            owned,
            body.asset_id,
            body.definition_id,
            body.definition_revision,
            request_id=body.request_id,
            options=body.options,
            paid_confirmed=body.paid_confirmed,
        )

    @app.get("/api/jobs")
    def jobs(owned=owner_dependency):
        return {"jobs": [ledger(j) for j in runtime.shared_jobs(owned)]}

    @app.get("/api/jobs/{identity}")
    def job(identity: str, owned=owner_dependency):
        return ledger(runtime.shared_get(owned, identity))

    @app.get("/api/renewal/jobs/{identity}")
    def execution(identity: str, owned=owner_dependency):
        return runtime.shared_get(owned, identity)

    @app.get("/api/renewal/jobs/{identity}/plan")
    def plan(identity: str, owned=owner_dependency):
        return runtime.plan(owned, identity)

    @app.post("/api/renewal/jobs/{identity}/confirm")
    def confirm(identity: str, body: Confirm, owned=owner_dependency):
        if not local_execution:
            raise HTTPException(403, "CPU 실행이 비활성입니다.")
        return runtime.confirm(owned, identity, body.token, body.request_id)

    @app.post("/api/renewal/jobs/{identity}/admit")
    def admit(identity: str, body: Admit, owned=owner_dependency):
        if not local_execution:
            raise HTTPException(403, "CPU 실행이 비활성입니다.")
        return runtime.admit(owned, identity, body.consent_id, body.request_id)

    @app.post("/api/renewal/jobs/{identity}/run")
    def run(identity: str, owned=owner_dependency):
        if not local_execution:
            raise HTTPException(403, "CPU 실행이 비활성입니다.")
        if broker_factory is not None:
            from video_service.rabbitmq_controller import BrokerController
            from video_service.rabbitmq_transport import BrokerError

            try:
                return BrokerController(runtime, broker_factory).dispatch(
                    owned, identity
                )
            except BrokerError:
                raise HTTPException(
                    503,
                    "브로커 전달을 확인하지 못했습니다. 실행 상태를 다시 확인하세요.",
                ) from None
        return runtime.run_local(owned, identity)

    @app.post("/api/renewal/jobs/{identity}/cancel")
    def cancel(identity: str, body: Revision, owned=owner_dependency):
        return runtime.cancel(owned, identity, body.revision)

    @app.post("/api/renewal/jobs/{identity}/recover", status_code=201)
    def recover(identity: str, body: Recovery, owned=owner_dependency):
        return runtime.recover(
            owned,
            identity,
            body.request_id,
            acknowledge_duplicate_risk=body.acknowledge_duplicate_risk,
        )

    @app.get("/api/renewal/reviews/{identity}/source")
    def review_source(identity: str, owned=owner_dependency):
        return FileResponse(
            runtime.review_source(owned, identity),
            media_type="audio/wav",
            filename="review-audio.wav",
        )

    @app.post("/api/renewal/reviews/{identity}/save")
    def review_save(identity: str, body: Review, owned=owner_dependency):
        return runtime.review_save(owned, identity, body.revision, body.draft)

    @app.post("/api/renewal/reviews/{identity}/confirm")
    def review_confirm(identity: str, body: Revision, owned=owner_dependency):
        return runtime.review_confirm(owned, identity, body.revision)

    @app.get("/api/renewal/jobs/{identity}/manifest")
    def artifact_manifest(
        identity: str, download: bool = False, owned=owner_dependency
    ):
        raw = runtime.shared_manifest(owned, identity)
        return Response(
            raw,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{identity}-manifest.json"'
            }
            if download
            else {},
        )

    @app.get("/api/renewal/jobs/{identity}/artifacts/{run_id}/{port}")
    def artifact(
        identity: str,
        run_id: str,
        port: str,
        download: bool = False,
        owned=owner_dependency,
    ):
        path, kind = runtime.shared_file(owned, identity, run_id, port)
        mime = {
            "video": "video/mp4",
            "audio": "audio/wav",
            "subtitle": "text/plain; charset=utf-8",
        }
        extension = {"video": "mp4", "audio": "wav", "subtitle": "srt"}.get(
            kind, "json"
        )
        if kind == "subtitle":
            from video_service.sami import subtitle_extension

            extension = subtitle_extension(path)
        return FileResponse(
            path,
            media_type=mime.get(kind, "application/json"),
            filename=run_id + "-" + port + "." + extension if download else None,
        )

    @app.get("/api/renewal/jobs/{identity}/artifacts/{run_id}/{port}/preview")
    def artifact_preview(
        identity: str,
        run_id: str,
        port: str,
        download: bool = False,
        owned=owner_dependency,
    ):
        path, _ = runtime.shared_file(owned, identity, run_id, port, preview=True)
        return FileResponse(
            path,
            media_type="video/webm",
            filename=run_id + "-web.webm" if download else None,
        )

    @app.get("/api/renewal/jobs/{identity}/inputs/{run_id}/{port}")
    def run_input(identity: str, run_id: str, port: str, owned=owner_dependency):
        path, kind = runtime.shared_file(owned, identity, run_id, port, inputs=True)
        mime = {
            "video": "video/mp4",
            "audio": "audio/wav",
            "subtitle": "text/plain; charset=utf-8",
        }
        return FileResponse(
            path,
            media_type=mime.get(kind, "application/json"),
        )

    @app.get("/api/renewal/jobs/{identity}/inputs/{run_id}/{port}/preview")
    def input_preview(identity: str, run_id: str, port: str, owned=owner_dependency):
        path, _ = runtime.shared_file(
            owned, identity, run_id, port, inputs=True, preview=True
        )
        return FileResponse(path, media_type="video/webm")
