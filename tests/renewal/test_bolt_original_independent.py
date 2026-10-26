import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from test_execution import admit
from test_packed_projection_execution import projection_wire as _wire
from test_vocalization_execution import admin as _admin
from test_vocalization_execution import db as _db
from test_vocalization_execution import movie as _movie
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime

admin, db, movie, projection_wire = _admin, _db, _movie, _wire


def test_actual_user_api_graph_two_review_gates_and_cpu_downloads(
    db, admin, tmp_path, projection_wire
):
    owner = admin[0]["id"]
    origin, calls = projection_wire
    credentials = CredentialStore(db, os.urandom(32))
    refs = []
    for speech in [True, False]:
        cid, mid = uuid4().hex, uuid4().hex
        connection = Registry(db).save_connection(
            owner,
            cid,
            revision=0,
            name="isolated subtitle tracks",
            provider="openai_compatible",
            protocol="gemini",
            endpoint=origin + "/v1",
        )
        connection = credentials.save(
            owner, cid, revision=connection["revision"], secret=uuid4().hex
        )
        Registry(db).save_model(
            owner,
            mid,
            revision=0,
            name="controlled subtitle tracks",
            model="gemini-2.5-flash",
            connection_id=cid,
            connection_revision=connection["current_revision"],
            model_types=["speech_recognition" if speech else "text"],
            input_modalities=["audio" if speech else "text"],
            output_modalities=["text"],
            capabilities=["speech_recognition" if speech else "text_generation"],
        )
        refs.append({"model_id": mid, "revision": 1})
    kwargs = {
        "transport_factory": lambda: httpx.HTTPTransport(retries=0),
        "approved_origins": {origin},
        "mode": "controlled_http",
    }
    import boto3
    from video_service.object_agent import ObjectAgentExecutor
    from video_service.object_store import S3ContentStore

    client = boto3.client(
        "s3",
        endpoint_url="https://upload-objects:9000",
        region_name="us-east-1",
        aws_access_key_id=os.environ["BOLT_FIXTURE_S3_ACCESS"],
        aws_secret_access_key=os.environ["BOLT_FIXTURE_S3_SECRET"],
        verify="/certs/ca.pem",
    )
    bucket = "bolt-source-" + uuid4().hex[:16]
    client.create_bucket(Bucket=bucket)
    app_cache = tmp_path / "application-cache"
    app_cache.mkdir()
    peer_cache = tmp_path / "independent-peer-cache"
    peer_cache.mkdir()
    store = S3ContentStore(client, bucket, app_cache, prefix="proof")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["BOLT_OBJECT_CONFIG"] = json.dumps(
        {
            "endpoint": "https://upload-objects:9000",
            "bucket": bucket,
            "prefix": "proof",
            "region": "us-east-1",
            "cache_root": str(peer_cache),
            "access_key_env": "BOLT_FIXTURE_S3_ACCESS",
            "secret_key_env": "BOLT_FIXTURE_S3_SECRET",
            "ca_file": "/certs/ca.pem",
        }
    )
    peer = ObjectAgentExecutor("BOLT_OBJECT_CONFIG", environ=env)
    runtime = Execution(
        db,
        store,
        agent_executor=peer,
        translation_runtime=TranslationRuntime(credentials, **kwargs),
        transcription_runtime=TranscriptionRuntime(credentials, **kwargs),
    )
    from psycopg.types.json import Jsonb
    from video_service.cpu_agents import probe

    source = Path("/media/original.mov")
    size = source.stat().st_size
    with source.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    assert size > 268435456
    store.import_original_file(owner, source, sha256=sha, byte_count=size)
    asset_id = uuid4().hex
    with db.connection() as c:
        c.execute(
            "INSERT INTO assets(owner_id,id,filename,storage_key,bytes,sha256,metadata)VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                owner,
                asset_id,
                "synthetic-original.mov",
                "sha256:" + sha,
                size,
                sha,
                Jsonb({"registration_state": "verified", "media": probe(source)}),
            ),
        )
    graph = json.loads(
        Path(__file__).with_name("bolt02-definition-r3.json").read_text()
    )
    graph["revision"] = 0
    graph["name"] = "independent large-original narrow smoke"
    graph.pop("id")
    graph.pop("executable", None)
    for n in graph["nodes"]:
        if n["type"] in {"transcribe", "translate"}:
            n["model_ref"] = refs[0 if n["type"] == "transcribe" else 1]
    definition = runtime.save_definition(owner, uuid4().hex, graph)
    job = runtime.create(
        owner,
        asset_id,
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
        options={"source_language": "auto", "target_language": "ko"},
    )
    assert job["snapshot"]["cpu_input_policy"]["id"] == "original_video_v6"
    assert job["snapshot"]["source_definition_sha256"]
    assert job["snapshot"]["definition"]["nodes"][2]["options"]["audio_filter"] == "off"

    def advance():
        for _ in range(60):
            command = runtime.claim_next(owner, job["id"])
            if command is not None:
                result = runtime.execute_command(owner, command)
                assert result["status"] == "completed", {
                    "agent": command["agent"],
                    "result": result,
                }
                runtime.accept(owner, command, result)
            value = runtime.get(owner, job["id"])
            if value["status"] in {"completed", "failed", "review_required"}:
                return value
        raise AssertionError("bounded scheduler did not settle")

    for kind in ["transcript", "subtitle_tracks"]:
        admit(runtime, owner, job["id"])
        gate = advance()
        assert gate["status"] == "review_required", gate
        review = next(r for r in gate["reviews"] if r["status"] == "draft")
        assert review["contract"]["type"] == kind
        saved = runtime.review_save(
            owner,
            review["id"],
            review["revision"],
            {**review["draft"], "approved": True},
        )
        runtime.review_confirm(owner, review["id"], saved["revision"])
    before = list(calls)
    admit(runtime, owner, job["id"])
    done = advance()
    assert done["status"] == "completed", done
    assert calls == before
    encodes = [r for r in done["runs"] if r["node_type"] == "encode"]
    assert len(encodes) == 2
    assert all(
        r["agent_revision"] == "6"
        for r in done["runs"]
        if r["node_type"] in {"analyze", "extract_audio", "encode", "validate_video"}
    )
    assert all(
        r["result"]["transport"] == "s3_subprocess"
        for r in done["runs"]
        if r["node_type"]
        in {"analyze", "extract_audio", "preprocess_audio", "encode", "validate_video"}
    )
    proof = {
        "job": job["id"],
        "status": done["status"],
        "input_bytes": size,
        "input_sha256": sha,
        "provider_mode": "controlled_loopback",
        "independent_cpu_cli_and_real_tls_s3": True,
        "real_mq_delivery": False,
        "outputs": [r["result"]["outputs"] for r in encodes],
    }
    Path("/evidence/narrow-independent-result.json").write_text(
        json.dumps(proof, indent=2)
    )
