"""Controller-owned controls are checked separately from media/MQ consumers."""

import json, secrets, tempfile, unittest
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


class ControllerRoleTests(unittest.TestCase):
    def test_select_join_review_are_real_controller_state_and_decision_is_closed(self):
        from video_service.postgres import Database
        from video_service.postgres.accounts import Accounts
        from video_service.postgres.execution import Execution
        from video_service.content_store import ContentStore

        dsn = Path("/run/bootstrap/database-dsn").read_text().strip()
        schema = "controls_test_" + uuid4().hex
        with psycopg.connect(dsn) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
            )
        db = Database(make_conninfo(dsn, options="-c search_path=" + schema))
        try:
            db.migrate()
            owner = Accounts(db).create(
                "isolated-controls-fixture", secrets.token_urlsafe(32), first=True
            )["id"]
            with tempfile.TemporaryDirectory() as directory:
                runtime = Execution(db, ContentStore(directory))
                source = runtime.ingest(
                    owner,
                    "spoken-fixture.mp4",
                    Path("/fixture/spoken-fixture.mp4").read_bytes(),
                )
                nodes = [
                    ("select", "select", {"selection": "a", "data_type": "video"}),
                    ("left", "encode", {"subtitle_mode": "none"}),
                    ("right", "encode", {"subtitle_mode": "none"}),
                    ("join", "join", {"left_type": "video", "right_type": "video"}),
                    ("review", "review", {"data_type": "artifact_manifest"}),
                ]
                edges = [
                    ("$input", "video", "select", "value"),
                    ("select", "a", "left", "video"),
                    ("select", "b", "right", "video"),
                    ("left", "video", "join", "left"),
                    ("right", "video", "join", "right"),
                    ("join", "manifest", "review", "value"),
                ]

                def graph(nodes, edges):
                    return {
                        "catalog_version": 1,
                        "revision": 0,
                        "name": "실제 제어 경로",
                        "inputs": {"video": "video"},
                        "nodes": [
                            {
                                "id": identity,
                                "type": kind,
                                "options": options,
                                "position": {"x": index * 100, "y": 0},
                            }
                            for index, (identity, kind, options) in enumerate(nodes)
                        ],
                        "edges": [
                            {
                                "id": "e" + str(i),
                                "source": {"node": a, "port": p},
                                "target": {"node": b, "port": q},
                            }
                            for i, (a, p, b, q) in enumerate(edges)
                        ],
                    }

                identity = uuid4().hex
                saved = runtime.save_definition(owner, identity, graph(nodes, edges))
                job = runtime.create(
                    owner,
                    source["asset_id"],
                    identity,
                    saved["revision"],
                    request_id=uuid4().hex,
                )
                plan = runtime.plan(owner, job["id"])
                self.assertTrue(plan["ready"], plan["reasons"])
                consent = runtime.confirm(owner, job["id"], plan["token"], uuid4().hex)
                runtime.admit(owner, job["id"], consent["id"], uuid4().hex)
                state = runtime.run_local(owner, job["id"])
                self.assertEqual(state["status"], "review_required")
                indexed = {row["node_id"]: row for row in state["runs"]}
                self.assertEqual(indexed["right"]["status"], "skipped")
                self.assertEqual(
                    indexed["select"]["result"]["transport"], "application_control"
                )
                self.assertEqual(
                    indexed["join"]["result"]["transport"], "application_control"
                )
                manifest = json.loads(
                    runtime.store.read(
                        owner, indexed["join"]["result"]["outputs"]["manifest"]
                    )
                )
                self.assertEqual(len(manifest["items"]), 1)
                self.assertEqual(state["reviews"][0]["status"], "draft")
                import subprocess

                metadata = json.loads(
                    subprocess.check_output(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-show_format",
                            "-of",
                            "json",
                            "/fixture/spoken-fixture.mp4",
                        ]
                    )
                )
                for kind, options, port in [
                    (
                        "control_if",
                        {
                            "data_type": "media_metadata",
                            "field": "duration",
                            "operator": "greater_than",
                            "compare_value": "0",
                        },
                        "true",
                    ),
                    (
                        "control_switch",
                        {
                            "data_type": "media_metadata",
                            "field": "duration",
                            "cases": str(float(metadata["format"]["duration"])),
                        },
                        "case_1",
                    ),
                ]:
                    definition = graph(
                        [
                            ("analysis", "analyze", {}),
                            ("condition", kind, options),
                            ("review", "review", {"data_type": "media_metadata"}),
                        ],
                        [
                            ("$input", "video", "analysis", "video"),
                            ("analysis", "metadata", "condition", "value"),
                            ("condition", port, "review", "value"),
                        ],
                    )
                    identity = uuid4().hex
                    saved = runtime.save_definition(owner, identity, definition)
                    child = runtime.create(
                        owner,
                        source["asset_id"],
                        identity,
                        saved["revision"],
                        request_id=uuid4().hex,
                    )
                    plan = runtime.plan(owner, child["id"])
                    self.assertTrue(plan["ready"], plan["reasons"])
                    consent = runtime.confirm(
                        owner, child["id"], plan["token"], uuid4().hex
                    )
                    runtime.admit(owner, child["id"], consent["id"], uuid4().hex)
                    checked = runtime.run_local(owner, child["id"])
                    self.assertEqual(checked["status"], "review_required")
                    condition = next(
                        row for row in checked["runs"] if row["node_id"] == "condition"
                    )
                    self.assertIn(port, condition["result"]["outputs"])
                    self.assertEqual(
                        condition["result"]["transport"], "application_control"
                    )
                for kind in ["decision", "control_loop", "control_fallback"]:
                    definition = graph(
                        [(kind, kind, {"data_type": "video"})],
                        [("$input", "video", kind, "value")],
                    )
                    identity = uuid4().hex
                    saved = runtime.save_definition(owner, identity, definition)
                    preview = runtime.inspect(owner, identity, saved["revision"])
                    self.assertFalse(preview["supported"])
        finally:
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )


if __name__ == "__main__":
    unittest.main()
