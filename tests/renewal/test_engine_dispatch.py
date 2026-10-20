"""A stale DB engine pin must be rejected before the publisher can run."""

import tempfile, unittest, secrets
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


class EngineDispatchTests(unittest.TestCase):
    def test_changed_physical_engine_pin_cannot_publish_a_reserved_command(self):
        from video_service.postgres import Database, Conflict
        from video_service.postgres.accounts import Accounts
        from video_service.postgres.execution import Execution
        from video_service.postgres.engine_runtimes import EngineRuntimes
        from video_service.transport_files import object_config, object_executor
        from video_service.object_store import from_config
        from video_service.durable_transport import DurableTransport
        from test_engine_execution import speech_graph

        dsn = Path("/run/bootstrap/database-dsn").read_text().strip()
        schema = "dispatch_test_" + uuid4().hex
        with psycopg.connect(dsn) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
            )
        db = Database(make_conninfo(dsn, options="-c search_path=" + schema))
        try:
            db.migrate()
            owner = Accounts(db).create(
                "isolated-dispatch-fixture", secrets.token_urlsafe(32), first=True
            )["id"]
            with tempfile.TemporaryDirectory() as temporary:
                config, credentials = object_config("/run/bootstrap/objects.json")
                config["cache_root"] = temporary
                store = from_config(config, environ=credentials)
                runtime = Execution(
                    db,
                    store,
                    engine_runtime_enabled=True,
                    agent_executor=object_executor("/run/bootstrap/objects.json"),
                )
                registry = EngineRuntimes(db)
                descriptors = {}
                for role, name in [
                    ("transcribe", "whisper-tiny-en"),
                    ("translate", "opus-en-de-int8"),
                ]:
                    descriptor = {
                        "role": role,
                        "family": "model",
                        "engine": name,
                        "model_sha256": "a" * 64,
                        "source_language": "en",
                        "target_language": "de" if role == "translate" else None,
                    }
                    registry.register(descriptor, revision=0, enabled=True)
                    descriptors[role] = descriptor
                asset = runtime.ingest(
                    owner,
                    "spoken-fixture.mp4",
                    Path("/fixture/spoken-fixture.mp4").read_bytes(),
                )
                identity = uuid4().hex
                saved = runtime.save_definition(owner, identity, speech_graph())
                job = runtime.create(
                    owner,
                    asset["asset_id"],
                    identity,
                    saved["revision"],
                    request_id=uuid4().hex,
                    options={"source_language": "en", "target_language": "de"},
                )
                plan = runtime.plan(owner, job["id"])
                consent = runtime.confirm(owner, job["id"], plan["token"], uuid4().hex)
                runtime.admit(owner, job["id"], consent["id"], uuid4().hex)
                for _ in range(8):
                    command = runtime.claim_next(owner, job["id"])
                    self.assertIsNotNone(command)
                    if command["protocol_version"] == 2:
                        break
                    runtime.accept(
                        owner, command, runtime.execute_command(owner, command)
                    )
                self.assertEqual(command["agent"]["id"], "transcribe")
                registry.register(
                    {**descriptors["transcribe"], "model_sha256": "b" * 64},
                    revision=1,
                    enabled=True,
                )

                def forbidden_send(*_):
                    self.fail("publisher called for stale engine pin")

                with self.assertRaises(Conflict):
                    DurableTransport(runtime).publish_exact(
                        owner, job["id"], command["attempt_id"], forbidden_send
                    )
        finally:
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )


if __name__ == "__main__":
    unittest.main()
