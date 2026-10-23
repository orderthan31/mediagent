"""Narrow real PG/API position save regression; no work/media/model execution."""

from uuid import uuid4

from app.renewal import create_app
from fastapi.testclient import TestClient
from test_foundation import admin as _admin
from test_foundation import db as _db
from test_foundation import login
from video_service.content_store import ContentStore
from video_service.postgres.registry import Registry

admin, db = _admin, _db


def test_position_save_reread_preserves_model_fallback_options_and_edges(
    db, admin, tmp_path
):
    owner = admin[0]["id"]
    registry = Registry(db)
    connection = registry.save_connection(
        owner,
        uuid4().hex,
        revision=0,
        name="Isolated graph only",
        provider="openai_compatible",
        protocol="openai_compatible",
        endpoint="http://127.0.0.1:9/v1",
    )
    refs = []
    for index in range(2):
        model_id = uuid4().hex
        registry.save_model(
            owner,
            model_id,
            revision=0,
            name=f"Graph-only pin {index}",
            model="never-called",
            connection_id=connection["id"],
            connection_revision=1,
            model_types=["text"],
            input_modalities=["text"],
            output_modalities=["text"],
            capabilities=["text_generation"],
        )
        refs.append({"model_id": model_id, "revision": 1})
    payload = {
        "revision": 0,
        "catalog_version": 1,
        "name": "Isolated touch position save",
        "inputs": {"transcript": "transcript"},
        "nodes": [
            {
                "id": "translated",
                "type": "translate",
                "position": {"x": 100, "y": 200},
                "options": {},
                "model_ref": refs[0],
                "fallback_refs": refs[1:],
            }
        ],
        "edges": [
            {
                "id": uuid4().hex,
                "source": {"node": "$input", "port": "transcript"},
                "target": {"node": "translated", "port": "transcript"},
            }
        ],
    }
    content = tmp_path / "content"
    content.mkdir(mode=0o700)
    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        content_store=ContentStore(content),
        local_execution=False,
    )
    with TestClient(app) as client:
        login(client, admin)
        path = "/api/settings/workflow-definitions/" + uuid4().hex
        saved = client.put(path, json=payload)
        assert saved.status_code == 200
        changed = {key: saved.json()[key] for key in payload}
        changed["nodes"][0]["position"] = {"x": 150, "y": 250}
        result = client.put(path, json=changed)
        assert result.status_code == 200
        reread = client.get(path).json()
        assert reread["nodes"][0]["position"] == changed["nodes"][0]["position"]
        for key in ["type", "options", "model_ref", "fallback_refs"]:
            assert reread["nodes"][0][key] == payload["nodes"][0][key]
        assert (
            reread["edges"] == payload["edges"]
            and reread["inputs"] == payload["inputs"]
        )
        assert client.put(path, json=changed).status_code == 409
        with db.connection() as sql:
            assert sql.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 0
