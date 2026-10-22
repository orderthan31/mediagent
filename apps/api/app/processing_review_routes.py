"""Administrator processing decisions; separate from native host controls."""

from fastapi import Depends
from fastapi.responses import FileResponse
from pydantic import Field, StrictBool
from video_service.postgres.job_processing_review import JobProcessingReview
from .renewal import Body


class ProcessingDecision(Body):
    plan_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    decision_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    choice: str = Field(pattern=r"^(hold|create_child)$")
    reason: str = Field(min_length=1, max_length=1000)
    acknowledge_duplicate_risk: StrictBool


def mount_processing_review(app, runtime, administrator):
    dependency = Depends(administrator)
    service = JobProcessingReview(runtime)

    @app.get("/api/admin/processing-reviews")
    def cases(value=dependency):
        return {"cases": service.list(value["user"]["id"])}

    @app.get("/api/admin/jobs/{job_id}/processing-review")
    def status(job_id: str, value=dependency):
        return service.status(value["user"]["id"], job_id)

    @app.post("/api/admin/jobs/{job_id}/processing-review/preview")
    def preview(job_id: str, body: Body, value=dependency):
        return service.preview(value["user"]["id"], job_id)

    @app.post("/api/admin/jobs/{job_id}/processing-review/decisions")
    def decide(job_id: str, body: ProcessingDecision, value=dependency):
        return service.decide(value["user"]["id"], job_id, **body.model_dump())

    @app.get(
        "/api/admin/jobs/{job_id}/processing-review/quarantine/{message_sha}/{port}"
    )
    def quarantined(job_id: str, message_sha: str, port: str, value=dependency):
        owner, ref = service.quarantine_reference(
            value["user"]["id"], job_id, message_sha, port
        )
        return FileResponse(
            runtime.store.path(owner, ref),
            media_type="application/octet-stream",
            filename="quarantined-" + message_sha + "-" + port,
        )
