"""Authenticated full-preview queue operations, separate from old excerpt GETs."""

from fastapi.responses import FileResponse
from video_service.postgres.video_previews import VideoPreviews


def mount_full_previews(app, runtime, owner_dependency):
    previews = VideoPreviews(runtime)

    @app.post("/api/videos/{identity}/preview/full", status_code=202)
    def request_full_original(identity: str, owned=owner_dependency):
        return previews.request_asset(owned, identity)

    @app.get("/api/videos/{identity}/preview/full")
    def full_original_status(identity: str, owned=owner_dependency):
        return previews.asset_status(owned, identity)

    @app.get("/api/video-previews/{identity}")
    def full_preview_status(identity: str, owned=owner_dependency):
        return previews.get(owned, identity)

    @app.post("/api/video-previews/{identity}/cancel")
    def cancel_full_preview(identity: str, owned=owner_dependency):
        return previews.cancel(owned, identity)

    @app.get("/api/video-previews/{identity}/file")
    def full_preview_file(
        identity: str, download: bool = False, owned=owner_dependency
    ):
        return FileResponse(
            previews.file(owned, identity),
            media_type="video/webm",
            filename=identity + "-full.webm" if download else None,
        )

    @app.post(
        "/api/renewal/jobs/{job_id}/artifacts/{run_id}/{port}/preview/full",
        status_code=202,
    )
    def request_full_output(
        job_id: str, run_id: str, port: str, owned=owner_dependency
    ):
        return previews.request_artifact(owned, job_id, run_id, port)

    @app.get("/api/renewal/jobs/{job_id}/artifacts/{run_id}/{port}/preview/full")
    def full_output_status(job_id: str, run_id: str, port: str, owned=owner_dependency):
        return previews.artifact_status(owned, job_id, run_id, port)
