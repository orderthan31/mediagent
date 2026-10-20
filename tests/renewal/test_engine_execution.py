"""Real eight-role TLS/S3/PG workflow in an explicitly disposable PG schema.

Not a production account/job: product login acceptance remains a separate gate.
"""

import hashlib, json, os, subprocess, tempfile, threading, unittest
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


def speech_graph():
    kinds = [
        ("analyze", "analyze", {}),
        ("audio", "extract_audio", {}),
        ("prepare", "preprocess_audio", {"audio_filter": "off", "vad_mode": "off"}),
        ("asr", "transcribe", {}),
        ("translation", "translate", {}),
        ("subtitles", "generate_subtitle", {}),
        ("encode", "encode", {"subtitle_mode": "burn"}),
        ("validate", "validate_video", {}),
    ]
    links = [
        ("$input", "video", "analyze", "video"),
        ("$input", "video", "audio", "video"),
        ("audio", "audio", "prepare", "audio"),
        ("prepare", "audio", "asr", "audio"),
        ("prepare", "timeline", "asr", "timeline"),
        ("asr", "transcript", "translation", "transcript"),
        ("translation", "transcript", "subtitles", "transcript"),
        ("$input", "video", "encode", "video"),
        ("subtitles", "subtitles", "encode", "subtitles"),
        ("encode", "video", "validate", "video"),
    ]
    return {
        "catalog_version": 1,
        "revision": 0,
        "name": "실제 음성·로컬 전사·독일어 번역 검증",
        "inputs": {"video": "video"},
        "nodes": [
            {
                "id": identity,
                "type": kind,
                "options": options,
                "position": {"x": 200 * index, "y": 50},
            }
            for index, (identity, kind, options) in enumerate(kinds)
        ],
        "edges": [
            {
                "id": "e" + str(index),
                "source": {"node": source, "port": port},
                "target": {"node": target, "port": incoming},
            }
            for index, (source, port, target, incoming) in enumerate(links)
        ],
    }


@unittest.skipUnless(
    os.environ.get("MIDEAGENT_TEST_LOCAL_MODELS") == "1",
    "explicit actual model workflow",
)
class EngineWorkflowTests(unittest.TestCase):
    def test_audio_video_through_real_model_mq_into_pg_and_final_video(self):
        from video_service.postgres import Database
        from video_service.postgres.accounts import Accounts
        from video_service.postgres.engine_runtimes import EngineRuntimes
        from video_service.postgres.execution import Execution
        from video_service.cpu_agents import CPU_AGENTS
        from video_service.transport_files import (
            object_config,
            object_executor,
            document,
            broker_factory,
            engine_broker_factory,
        )
        from video_service.object_store import from_config
        from video_service.local_model_engines import model_identity
        from video_service.engine_object_agent import EngineObjectExecutor
        from video_service.engine_service import EngineHandler
        from video_service.rabbitmq_controller import BrokerController
        from mideagent_cpu.broker import CpuHandler

        fixture = Path("/fixture")
        dsn = Path("/run/bootstrap/database-dsn").read_text().strip()
        schema = "workflow_test_" + uuid4().hex
        with psycopg.connect(dsn) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
            )
        database = Database(make_conninfo(dsn, options="-c search_path=" + schema))
        try:
            database.migrate()
            with tempfile.TemporaryDirectory() as temporary:
                config, secrets = object_config("/run/bootstrap/objects.json")
                config["cache_root"] = temporary
                store = from_config(config, environ=secrets)
                runtime = Execution(database, store, engine_runtime_enabled=True)
                import secrets as random_secrets

                account = Accounts(database).create(
                    "isolated-workflow-fixture",
                    random_secrets.token_urlsafe(32),
                    first=True,
                )
                owner = account["id"]
                registry = EngineRuntimes(database)
                descriptors = {}
                for role, name in [
                    ("transcribe", "whisper-tiny-en"),
                    ("translate", "opus-en-de-int8"),
                ]:
                    descriptor = {
                        "role": role,
                        "family": "model",
                        "engine": name,
                        "model_sha256": model_identity(fixture / "models" / name),
                        "source_language": "en",
                        "target_language": "de" if role == "translate" else None,
                    }
                    registry.register(descriptor, revision=0, enabled=True)
                    descriptors[role] = descriptor
                source = runtime.ingest(
                    owner,
                    "spoken-fixture.mp4",
                    (fixture / "spoken-fixture.mp4").read_bytes(),
                )
                identity = uuid4().hex
                saved = runtime.save_definition(owner, identity, speech_graph())
                job = runtime.create(
                    owner,
                    source["asset_id"],
                    identity,
                    saved["revision"],
                    request_id=uuid4().hex,
                    options={"source_language": "en", "target_language": "de"},
                )
                plan = runtime.plan(owner, job["id"])
                self.assertTrue(plan["ready"], plan["reasons"])
                consent = runtime.confirm(owner, job["id"], plan["token"], uuid4().hex)
                runtime.admit(owner, job["id"], consent["id"], uuid4().hex)
                namespace = "mideagent.acceptance_" + uuid4().hex[:12]
                broker = document(
                    document("/run/bootstrap/api.json")["broker_config_file"]
                )
                factories = []
                for suffix, builder in [
                    ("cpu", broker_factory),
                    ("engine", engine_broker_factory),
                ]:
                    private = Path(temporary) / (suffix + "-broker.json")
                    private.write_text(
                        json.dumps({**broker, "namespace": namespace + "." + suffix})
                    )
                    factory = builder(private)
                    factories.append(factory)
                    with factory() as client:
                        client.declare()
                cpu_factory, engine_factory = factories
                cpu_factory.engine_factory = engine_factory
                controller = BrokerController(runtime, cpu_factory)
                stop = threading.Event()
                done = threading.Event()
                errors = []
                threads = []

                def consume(factory, role, handler):
                    try:
                        with factory() as client:
                            client.serve(role, handler, stop)
                    except Exception as error:
                        from video_service.rabbitmq_transport import BrokerError

                        errors.append(
                            {
                                "role": role,
                                "type": type(error).__name__,
                                "code": str(error)
                                if isinstance(error, BrokerError)
                                else "details_redacted",
                            }
                        )
                        done.set()

                for role in sorted(CPU_AGENTS):
                    threads.append(
                        threading.Thread(
                            target=consume,
                            args=(
                                cpu_factory,
                                role,
                                CpuHandler(
                                    role, object_executor("/run/bootstrap/objects.json")
                                ),
                            ),
                        )
                    )
                for role, descriptor in descriptors.items():
                    executor = EngineObjectExecutor(
                        store,
                        {
                            "descriptor": descriptor,
                            "model_dir": str(fixture / "models" / descriptor["engine"]),
                        },
                    )
                    threads.append(
                        threading.Thread(
                            target=consume,
                            args=(engine_factory, role, EngineHandler(role, executor)),
                        )
                    )

                def collect(delivery):
                    controller.receive(delivery)
                    state = runtime.get(owner, job["id"])
                    if state["status"] in {"completed", "failed", "cancelled"}:
                        done.set()

                for factory in factories:
                    threads.append(
                        threading.Thread(
                            target=consume, args=(factory, "result", collect)
                        )
                    )
                for thread in threads:
                    thread.start()
                try:
                    controller.dispatch(owner, job["id"])
                    self.assertTrue(done.wait(90), "real audio workflow timed out")
                finally:
                    stop.set()
                    for thread in threads:
                        thread.join(10)
                self.assertFalse(errors, errors)
                self.assertFalse(any(thread.is_alive() for thread in threads))
                finished = runtime.get(owner, job["id"])
                self.assertEqual(
                    finished["status"],
                    "completed",
                    [(r["node_id"], r["status"]) for r in finished["runs"]],
                )
                self.assertEqual(len(finished["runs"]), 8)
                for run in finished["runs"]:
                    self.assertEqual(run["status"], "completed")
                    if run["node_type"] in descriptors:
                        self.assertEqual(
                            run["agent_revision"], run["request"]["agent"]["revision"]
                        )
                        self.assertEqual(run["result"]["transport"], "s3_engine")
                encoded = next(
                    r for r in finished["runs"] if r["node_type"] == "encode"
                )["result"]["outputs"]["video"]
                final = store.read(owner, encoded, limit=268435456)
                self.assertEqual(hashlib.sha256(final).hexdigest(), encoded["sha256"])
                target = fixture / "PG-engine-workflow-final.mp4"
                target.write_bytes(final)
                probe = json.loads(
                    subprocess.check_output(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-show_format",
                            "-show_streams",
                            "-of",
                            "json",
                            str(target),
                        ],
                        text=True,
                    )
                )
                self.assertGreater(float(probe["format"]["duration"]), 5)
                self.assertTrue(
                    any(s["codec_type"] == "audio" for s in probe["streams"])
                )
                queues = {}
                for family, factory, roles in [
                    ("cpu", cpu_factory, list(CPU_AGENTS)),
                    ("engine", engine_factory, list(descriptors)),
                ]:
                    with factory() as client:
                        queues[family] = {
                            role: client.channel.queue_declare(
                                queue=client.config.queue(role), passive=True
                            ).method.message_count
                            for role in roles + ["result"]
                        }
                self.assertTrue(
                    all(
                        value == 0
                        for family in queues.values()
                        for value in family.values()
                    ),
                    queues,
                )
                evidence = {
                    "scope": "DISPOSABLE_SCHEMA_NOT_PRODUCT_ACCOUNT",
                    "schema": schema,
                    "job_id": job["id"],
                    "workflow_id": identity,
                    "namespace": namespace,
                    "job": finished,
                    "final_video": encoded,
                    "ffprobe": probe,
                    "queue_ready_after_ack": queues,
                }
                (fixture / "PG-engine-workflow-evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
                )
        finally:
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )


if __name__ == "__main__":
    unittest.main()
