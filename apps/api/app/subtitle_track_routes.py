"""Authenticated, CSRF-covered per-language review saves and shared file reads."""

from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from video_service.postgres.subtitle_tracks import SubtitleTracks


class SubtitleSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt = Field(ge=1)
    cues: list[dict] = Field(min_length=1, max_length=10000)


def mount_subtitle_tracks(app, runtime, owner_dependency):
    service = SubtitleTracks(runtime)
    owner = owner_dependency

    @app.get("/api/renewal/reviews/{identity}/subtitle-tracks/{name}")
    def track(identity: str, name: str, actor=owner):
        return service.track(identity, name)

    @app.post("/api/renewal/reviews/{identity}/subtitle-tracks/{name}/save")
    def save(identity: str, name: str, body: SubtitleSave, actor=owner):
        return service.save(actor, identity, body.revision, name, body.cues)

    @app.get("/api/renewal/jobs/{identity}/subtitle-outputs")
    def outputs(identity: str, actor=owner):
        return service.outputs(identity)

    @app.get(
        "/api/renewal/jobs/{identity}/subtitle-outputs/{run_id}/{name}/{extension}"
    )
    def artifact(identity: str, run_id: str, name: str, extension: str, actor=owner):
        path, filename = service.file(identity, run_id, name, extension)
        return FileResponse(
            path, media_type="text/plain; charset=utf-8", filename=filename
        )
