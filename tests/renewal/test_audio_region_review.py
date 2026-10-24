"""Saved review producer -> immutable CAS -> explicit CPU consumer, no GPU/provider."""

import json
import wave
from uuid import uuid4

from test_execution import admin as _admin_fixture
from test_execution import admit
from test_execution import db as _db_fixture
from test_execution import movie as _movie_fixture
from test_execution import runtime as _runtime_fixture

admin, db, movie, runtime = (
    _admin_fixture,
    _db_fixture,
    _movie_fixture,
    _runtime_fixture,
)


def region_graph():
    nodes = [
        {
            "id": "extract",
            "type": "extract_audio",
            "options": {},
            "position": {"x": 0, "y": 0},
        },
        {
            "id": "regions",
            "type": "review",
            "options": {"data_type": "audio", "review_kind": "audio_regions_v1"},
            "position": {"x": 300, "y": 0},
        },
        {
            "id": "prepare",
            "type": "preprocess_audio",
            "options": {
                "processing_profile": "regions_pack_v4",
                "audio_filter": "strong",
                "vad_mode": "off",
            },
            "position": {"x": 600, "y": 0},
        },
    ]
    links = [
        ("$input", "video", "extract", "video"),
        ("extract", "audio", "regions", "value"),
        ("regions", "value", "prepare", "audio"),
        ("regions", "regions", "prepare", "regions"),
    ]
    return {
        "catalog_version": 1,
        "revision": 0,
        "name": "음성 구간 검수",
        "inputs": {"video": "video"},
        "nodes": nodes,
        "edges": [
            {
                "id": "e" + str(i),
                "source": {"node": a, "port": b},
                "target": {"node": c, "port": d},
            }
            for i, (a, b, c, d) in enumerate(links)
        ],
    }


def test_review_producer_cas_is_consumed_by_new_cpu_ticket(runtime, admin, movie):
    owner = admin[0]["id"]
    from video_service.renewal_contracts import validate

    checked = validate(region_graph())
    assert checked["valid"], checked
    original = runtime.ingest(owner, "review-source.mp4", movie)
    definition = runtime.save_definition(owner, uuid4().hex, region_graph())
    job = runtime.create(
        owner,
        original["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
    )
    admit(runtime, owner, job["id"])
    waiting = runtime.run_local(owner, job["id"])
    assert waiting["status"] == "review_required"
    review = waiting["reviews"][0]
    assert review["contract"]["kind"] == "audio_regions_v1"
    info = review["contract"]["audio"]
    duration = info["source_frames"] / 16000
    draft = {
        "approved": True,
        "protected": [],
        "removals": [{"start": duration / 4, "end": duration / 2, "kind": "breath"}],
    }
    saved = runtime.review_save(owner, review["id"], review["revision"], draft)
    runtime.review_confirm(owner, saved["id"], saved["revision"])
    confirmed = runtime.get(owner, job["id"])
    produced = next(r for r in confirmed["runs"] if r["node_id"] == "regions")[
        "result"
    ]["outputs"]
    assert produced["value"] == review["contract"]["source"]
    decision = json.loads(runtime.store.read(owner, produced["regions"]))
    assert decision["source_sha256"] == produced["value"]["sha256"]
    assert decision["source_frames"] == info["source_frames"]
    assert decision["removals"] == draft["removals"]
    assert not any(r["node_id"] == "prepare" for r in confirmed["runs"])
    # Confirm is NOT execution: a new plan/consent/admission is still required.
    admit(runtime, owner, job["id"])
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "completed", done
    prepare = next(r for r in done["runs"] if r["node_id"] == "prepare")
    assert prepare["request"]["agent"] == {"id": "preprocess_audio", "revision": "4"}
    assert prepare["inputs"]["regions"] == produced["regions"]
    with wave.open(
        str(runtime.store.path(owner, prepare["result"]["outputs"]["audio"])), "rb"
    ) as audio:
        assert audio.getnframes() == info["source_frames"] * 3 // 4


def test_new_region_document_budget_does_not_widen_cpu_media_limit():
    from video_service.cpu_input_policy import input_limit

    assert (
        input_limit(
            {"id": "preprocess_audio", "revision": "4"}, "regions", "audio_regions"
        )
        == 131072
    )
    assert (
        input_limit({"id": "preprocess_audio", "revision": "4"}, "audio", "audio")
        == 268435456
    )


def waiting_review(runtime, admin, movie, graph=None):
    owner = admin[0]["id"]
    original = runtime.ingest(owner, "review-guard.mp4", movie)
    definition = runtime.save_definition(owner, uuid4().hex, graph or region_graph())
    job = runtime.create(
        owner,
        original["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
    )
    admit(runtime, owner, job["id"])
    waiting = runtime.run_local(owner, job["id"])
    assert waiting["status"] == "review_required"
    return owner, waiting, waiting["reviews"][0]


def test_region_review_stale_edits_and_repeat_confirmation_keep_exact_cas(
    runtime, admin, movie
):
    import pytest
    from video_service.postgres import Conflict

    owner, job, review = waiting_review(runtime, admin, movie)
    draft = {
        "approved": True,
        "protected": [{"start": 0.1, "end": 0.2}],
        "removals": [],
    }
    saved = runtime.review_save(owner, review["id"], review["revision"], draft)
    with pytest.raises(Conflict):
        runtime.review_save(owner, review["id"], review["revision"], draft)
    with pytest.raises(Conflict):
        runtime.review_confirm(owner, review["id"], review["revision"])
    with pytest.raises(ValueError):
        runtime.review_save(
            owner, saved["id"], saved["revision"], {**draft, "source_sha256": "0" * 64}
        )
    first = runtime.review_confirm(owner, saved["id"], saved["revision"])
    before = runtime.get(owner, job["id"])
    again = runtime.review_confirm(owner, saved["id"], saved["revision"])
    after = runtime.get(owner, job["id"])
    assert first["confirmed_sha256"] == again["confirmed_sha256"]
    assert before["revision"] == after["revision"]
    assert before["runs"] == after["runs"]


def test_cancelled_region_review_cannot_confirm_or_start_next_node(
    runtime, admin, movie
):
    import pytest
    from video_service.postgres import Conflict

    owner, job, review = waiting_review(runtime, admin, movie)
    current = runtime.get(owner, job["id"])
    runtime.cancel(owner, job["id"], current["revision"])
    with pytest.raises(Conflict):
        runtime.review_save(
            owner,
            review["id"],
            review["revision"],
            {"approved": True, "protected": [], "removals": []},
        )
    with pytest.raises(Conflict):
        runtime.review_confirm(owner, review["id"], review["revision"])
    state = runtime.get(owner, job["id"])
    assert not any(row["node_id"] == "prepare" for row in state["runs"])


def test_review_source_uses_real_auth_and_real_source_bytes(runtime, db, admin, movie):
    from app.renewal import create_app
    from fastapi.testclient import TestClient

    owner, _, review = waiting_review(runtime, admin, movie)
    app = create_app(
        db,
        allowed_origins=["https://testserver"],
        secure_cookies=False,
        content_store=runtime.store,
    )
    with TestClient(app, base_url="https://testserver") as client:
        route = "/api/renewal/reviews/" + review["id"] + "/source"
        assert client.get(route).status_code == 401
        response = client.post(
            "/api/auth/login",
            json={"username": admin[0]["username"], "password": admin[1]},
            headers={"Origin": "https://testserver"},
        )
        assert response.status_code == 200
        source = client.get(route)
        assert source.status_code == 200
        assert source.content == runtime.store.read(owner, review["contract"]["source"])
        assert source.headers["content-type"].startswith("audio/wav")
        denied = client.post(
            "/api/renewal/reviews/" + review["id"] + "/save",
            json={
                "revision": review["revision"],
                "draft": {"approved": True, "protected": [], "removals": []},
            },
            headers={"Origin": "https://testserver"},
        )
        assert denied.status_code == 403
    import secrets

    from video_service.postgres.accounts import Accounts

    member_password = secrets.token_urlsafe(24)
    member = Accounts(db).create("review-reader", member_password, actor_id=owner)
    with TestClient(app, base_url="https://testserver") as reader:
        signed = reader.post(
            "/api/auth/login",
            json={"username": member["username"], "password": member_password},
            headers={"Origin": "https://testserver"},
        )
        assert signed.status_code == 200
        shared = reader.get(route)
        assert shared.status_code == 200 and shared.content == source.content
        denied_edit = reader.post(
            "/api/renewal/reviews/" + review["id"] + "/save",
            json={
                "revision": review["revision"],
                "draft": {"approved": True, "protected": [], "removals": []},
            },
            headers={
                "Origin": "https://testserver",
                "X-CSRF-Token": signed.json()["csrf_token"],
            },
        )
        assert denied_edit.status_code == 404


def test_confirmed_region_producer_binds_explicit_gpu_command_without_dispatch(
    db, admin, movie, tmp_path
):
    from video_service.content_store import ContentStore
    from video_service.postgres.engine_runtimes import EngineRuntimes
    from video_service.postgres.execution import Execution

    runtime = Execution(db, ContentStore(tmp_path), engine_runtime_enabled=True)
    descriptor = {
        "role": "preprocess_audio",
        "family": "gpu",
        "engine": "nvidia-marblenet",
        "model_sha256": "b" * 64,
        "source_language": None,
        "target_language": None,
    }
    EngineRuntimes(db).register(descriptor, revision=0, enabled=True)
    graph = region_graph()
    graph["nodes"][2]["options"].update(
        processing_profile="nvidia_regions_v4", vad_mode="nvidia"
    )
    owner, job, review = waiting_review(runtime, admin, movie, graph)
    saved = runtime.review_save(
        owner,
        review["id"],
        review["revision"],
        {"approved": True, "protected": [{"start": 0.1, "end": 0.2}], "removals": []},
    )
    runtime.review_confirm(owner, saved["id"], saved["revision"])
    state = runtime.get(owner, job["id"])
    outputs = next(r for r in state["runs"] if r["node_id"] == "regions")["result"][
        "outputs"
    ]
    admit(runtime, owner, job["id"])
    command = runtime.claim_next(owner, job["id"])
    assert command["protocol_version"] == 2 and command["agent"]["family"] == "gpu"
    assert command["runtime"] == descriptor
    assert command["inputs"] == {
        "audio": outputs["value"],
        "regions": outputs["regions"],
    }
    assert json.loads(runtime.store.read(owner, command["inputs"]["regions"]))[
        "protected"
    ] == [{"start": 0.1, "end": 0.2}]
    # No execute_command / GPU process / broker dispatch is performed.


def test_region_review_rejects_missing_removal_classification(runtime, admin, movie):
    import pytest

    owner, _, review = waiting_review(runtime, admin, movie)
    with pytest.raises(ValueError):
        runtime.review_save(
            owner,
            review["id"],
            review["revision"],
            {
                "approved": True,
                "protected": [],
                "removals": [{"start": 0.1, "end": 0.2}],
            },
        )
