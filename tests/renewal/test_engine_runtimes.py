"""Runtime revisions are platform metadata, not inferred provider configuration."""

import unittest
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from video_service.postgres import Database


class EngineRuntimeRegistryTests(unittest.TestCase):
    def test_explicit_database_revision_pin_and_disabled_state(self):
        from video_service.postgres.engine_runtimes import EngineRuntimes

        dsn = Path("/run/bootstrap/database-dsn").read_text().strip()
        schema = "runtime_test_" + uuid4().hex
        with psycopg.connect(dsn) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
            )
        database = Database(make_conninfo(dsn, options="-c search_path=" + schema))
        try:
            database.migrate()
            registry = EngineRuntimes(database)
            with self.assertRaises(ValueError):
                registry.resolve("transcribe")
            descriptor = {
                "role": "transcribe",
                "family": "model",
                "engine": "whisper-tiny-en",
                "model_sha256": "b" * 64,
                "source_language": "en",
                "target_language": None,
            }
            row = registry.register(descriptor, revision=0, enabled=True)
            self.assertEqual(row["revision"], 1)
            self.assertEqual(registry.resolve("transcribe")["descriptor"], descriptor)
            from video_service.postgres.execution import Execution

            node = next(
                value
                for value in Execution(
                    database, None, engine_runtime_enabled=True
                ).catalog()["nodes"]
                if value["id"] == "transcribe"
            )
            self.assertEqual(node["execution"], "engine_amqp")
            self.assertEqual(node["engine_runtime"]["sha256"], row["sha256"])
            self.assertEqual(
                node["runtime_scope"], "configuration_not_inference_readiness"
            )
            self.assertEqual(
                registry.register(descriptor, revision=1, enabled=True)["revision"], 1
            )
            changed = {**descriptor, "model_sha256": "c" * 64}
            with self.assertRaises(ValueError):
                registry.register(changed, revision=0, enabled=True)
            registry.register(changed, revision=1, enabled=True)
            with self.assertRaises(ValueError):
                registry.resolve("transcribe", sha256=row["sha256"])
            registry.register(changed, revision=2, enabled=False)
            with self.assertRaises(ValueError):
                registry.resolve("transcribe")
        finally:
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )


if __name__ == "__main__":
    unittest.main()
