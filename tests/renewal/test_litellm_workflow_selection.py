"""Actual save/read/create/freeze/SDK functions with memory-only SQL/HTTP I/O.

No product DB, persistent job, original, provider request or model result is
created. Fixture speech is a wire-contract assertion, never recognition proof.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import wave

import httpx

from test_litellm_model_tools import ROOT, no_provider_sockets, reply
from mideagent_orchestrator.execution import Execution
from mideagent_orchestrator.workflow import default_definition
from video_service.canonical import digest
from video_service.postgres.intake import Intake
from video_service.postgres.translation import TranslationRuntime
from video_service.postgres.transcription import TranscriptionRuntime


class MemorySQL:
    def __init__(self, models):
        self.models, self.head, self.documents, self.jobs, self.rows = models, 0, {}, [], []

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql, params=None):
        self.rows = []
        if sql.startswith("INSERT INTO workflows"):
            pass
        elif sql.startswith("SELECT revision,library_removed_at"):
            self.rows = [{"revision": self.head, "library_removed_at": None}]
        elif sql.startswith("SELECT mr.*"):
            self.rows = [deepcopy(self.models[params[1], params[2]])]
        elif sql.startswith("INSERT INTO workflow_revisions"):
            self.documents[params[2]] = {"owner_id": params[0], "workflow_id": params[1], "revision": params[2], "name": params[3], "definition": deepcopy(params[4].obj), "sha256": params[5]}
        elif sql.startswith("UPDATE workflows SET revision"):
            self.head = params[0]
        elif sql.startswith("SELECT wr.*"):
            self.rows = [deepcopy(self.documents[params[0] or self.head])]
        elif sql.startswith("SELECT * FROM jobs"):
            self.rows = [j for j in self.jobs if j["owner_id"] == params[0] and j["creation_request_id"] == params[1]]
        elif sql.startswith("SELECT pg_advisory_xact_lock"):
            pass
        elif sql.startswith("INSERT INTO jobs"):
            row = {"owner_id": params[0], "id": params[1], "asset_id": params[2], "workflow_id": params[3], "workflow_revision": params[4], "snapshot": deepcopy(params[5].obj), "snapshot_sha256": params[6], "status": "draft", "creation_request_id": params[8], "creation_sha256": params[9]}
            self.jobs.append(row)
            self.rows = [deepcopy(row)]
        else:
            raise AssertionError("Unexpected memory-only SQL: " + sql.split(" FROM ")[0])
        return self

    def fetchone(self):
        return deepcopy(self.rows[0]) if self.rows else None

    def fetchall(self):
        return deepcopy(self.rows)


class CreationBoundary(Execution):
    """External source/artifact reads and public rendering are replaced, not creation logic."""
    def __init__(self, database, asset):
        self.database, self.asset = database, asset
        self.store = type("ReadOnlyFixtureStore", (), {"path": lambda *args: None})()

    def _shared_asset(self, db, identity):
        assert identity == self.asset["id"]
        return deepcopy(self.asset)

    def _engine_bindings(self, db, definition):
        return {}

    def _view(self, db, row):
        return deepcopy(row)


def test_selected_workflow_models_save_reopen_create_and_reach_real_sdk():
    owner, workflow, asset_id = "f" * 32, "e" * 32, "d" * 32
    profiles = {"model_types": ["multimodal"], "input_modalities": ["audio", "text"], "output_modalities": ["text"], "capabilities": ["speech_recognition", "structured_output", "text_generation"]}
    models = {}
    for index, (protocol, model, revision) in enumerate([("gemini", "gemini-3.8-flash", 7), ("openai", "workflow-text-choice", 8)]):
        identity = str(index + 1) * 32
        models[identity, revision] = {**deepcopy(profiles), "model_id": identity, "revision": revision, "remote_model": model,
            "connection_id": "c" * 32, "connection_revision": 2, "sha256": str(index + 3) * 64,
            "protocol": protocol, "provider": protocol, "endpoint": "https://unit.invalid/" + ("v1beta" if protocol == "gemini" else "v1"),
            "credential_ref": "db:" + "a" * 32, "model_active": True, "connection_active": True}
    database = MemorySQL(models)
    intake = object.__new__(Intake); intake.database = database
    definition = default_definition()
    for index, node in enumerate(definition["nodes"][:2]):
        node["model_ref"] = {"model_id": str(index + 1) * 32, "revision": 7 + index}
        node["options"]["llm_options"] = json.dumps({"timeout": 70 + index, "max_tokens": 1024 + index})
    saved = intake.save_definition(owner, workflow, definition)
    reopened = intake.definition(owner, workflow, saved["revision"])
    assert reopened == saved
    # A later registry revision must not retarget the saved explicit revision.
    models["1" * 32, 99] = {**models["1" * 32, 7], "revision": 99, "remote_model": "not-selected-later-head"}
    asset = {"id": asset_id, "owner_id": owner, "filename": "memory-only-descriptor.mp4", "bytes": 100,
             "sha256": "b" * 64, "storage_key": "sha256:" + "b" * 64, "created_at": datetime.now(timezone.utc),
             "metadata": {"registration_state": "verified", "duration_seconds": .1, "media": {"duration": .1, "width": 640, "height": 360, "has_audio": True, "frame_rate": "25/1"}}}
    runtime = CreationBoundary(database, asset)
    recorded = runtime.create(owner, asset_id, workflow, saved["revision"], request_id="memory-only-creation", options={"source_language": "auto", "target_language": "ko"}, paid_confirmed=True)
    snapshot = recorded["snapshot"]
    assert digest(snapshot) == recorded["snapshot_sha256"]
    assert snapshot["agent_definition"] == reopened
    pins = snapshot["model_bindings"]
    assert len(database.jobs) == 1  # Only this memory object's recording; product DB is never connected.
    seen = []
    def wire(request):
        seen.append(request)
        protocol = "gemini" if "/models/" in request.url.path else "openai"
        text = '{"segments":[{"start":0,"end":0.08,"text":"fixture"}]}' if protocol == "gemini" else '{"translations":["통제 번역"]}'
        return httpx.Response(200, json=reply(protocol, "fixture", text))
    audio = io.BytesIO()
    with wave.open(audio, "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(b"\x00\x00" * 1600)
    for index, (node_id, runtime_type) in enumerate([("transcription__transcribe", TranscriptionRuntime), ("translation__translate", TranslationRuntime)]):
        pin = pins[node_id]
        engine = runtime_type(object(), transport_factory=lambda: httpx.MockTransport(wire), approved_origins={"https://unit.invalid"}, mode="external")
        adapter = engine.make_adapter(pin, "memory-only-credential")
        try:
            assert adapter._client.timeout.read == 70 + index
            if index == 0:
                adapter.transcribe(pin["remote_model"], audio.getvalue(), "auto")
            else:
                adapter.chat(pin["remote_model"], [{"role": "system", "content": "Translate"}, {"role": "user", "content": '["fixture"]'}])
        finally:
            adapter.close()
    assert "gemini-3.8-flash" in seen[0].url.path
    assert json.loads(seen[1].content)["model"] == "workflow-text-choice"
    assert pins["transcription__transcribe"]["revision"] == 7
    assert pins["translation__translate"]["revision"] == 8
    assert json.loads(seen[0].content)["generationConfig"]["max_output_tokens"] == 1024
    assert json.loads(seen[1].content)["max_tokens"] == 1025
