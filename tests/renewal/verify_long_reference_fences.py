"""Narrow latest-guard installed replay/forgery checks; never reprocess media."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from app.operator import runtime_components
from app.server import load_bootstrap
from video_service.cpu_agents import canonical
from video_service.postgres import Database
from video_service.postgres.execution import Execution
from video_service.rabbitmq_transport import Delivery
from video_service.registered_broker import COMMAND

assert (
    os.environ.get("MIDEAGENT_TEST_DISPOSABLE") == "1"
    and "PYTHONPATH" not in os.environ
)
root = Path("/run/bootstrap")
saved = json.loads(Path("/evidence/independent-long-workflow.json").read_text())
reference = saved["exact_registered_reference"]
for actor in ["worker", "seed"]:
    Path("/tmp/long-" + actor + "-content").mkdir(exist_ok=True)
    Path("/tmp/long-" + actor + "-cache").mkdir(exist_ok=True)
config, dsn = load_bootstrap(root / "seed.json")
database = Database(dsn)
store, credentials, factory = runtime_components(
    database,
    config,
    enable_broker=True,
    enable_registered=True,
    allow_controlled_models=True,
)
runtime = Execution(
    database,
    store,
    translation_runtime=factory.translation_runtime,
    transcription_runtime=factory.transcription_runtime,
)
owner, job = reference["owner"], reference["job_id"]


def facts():
    with database.connection() as db:
        return {
            "attempts": db.execute(
                "SELECT * FROM model_chunk_attempts WHERE owner_id=%s ORDER BY context_sha256,candidate_index",
                (owner,),
            ).fetchall(),
            "budgets": db.execute(
                "SELECT * FROM model_call_budgets WHERE owner_id=%s ORDER BY node_run_id",
                (owner,),
            ).fetchall(),
            "deliveries": db.execute(
                "SELECT * FROM agent_deliveries WHERE owner_id=%s ORDER BY node_run_id",
                (owner,),
            ).fetchall(),
        }


def until(read, expected, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = read()
        if expected(value):
            return value
        time.sleep(0.1)
    raise AssertionError("narrow installed reference check timed out")


before = facts()
manifest_before = hashlib.sha256(runtime.shared_manifest(owner, job)).hexdigest()
requests = []


class Observer(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        requests.append(True)
        self.send_error(500)


server = ThreadingHTTPServer(("127.0.0.1", 9419), Observer)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
with Path("/private-logs/latest-guard-model-receiver.log").open("wb") as log:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.operator",
            "consume-registered-models",
            "--bootstrap-file",
            str(root / "worker.json"),
            "--enable-broker",
            "--enable-registered-models",
            "--allow-controlled-models",
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        env=dict(os.environ),
    )
    try:
        with factory.registered_factory() as broker:
            delivery = Delivery(
                canonical(reference), COMMAND, reference["attempt_id"], job
            )
            assert broker.publish(delivery)

        def ready_count():
            with factory.registered_factory() as broker:
                return broker.channel.queue_declare(
                    queue=broker.config.queue("registered"), passive=True
                ).method.message_count

        until(ready_count, lambda value: value == 0)

        def dead_count():
            with factory.registered_factory() as broker:
                return broker.channel.queue_declare(
                    queue=broker.config.queue("registered") + ".dead", passive=True
                ).method.message_count

        dead_before = dead_count()
        for changed in [
            {**reference, "request_sha256": "f" * 64},
            {**reference, "attempt_id": uuid4().hex},
        ]:
            with factory.registered_factory() as broker:
                assert broker.publish(
                    Delivery(canonical(changed), COMMAND, changed["attempt_id"], job)
                )
        until(dead_count, lambda value: value == dead_before + 2)
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
        code = process.wait(timeout=30)
        log.close()
        server.shutdown()
        server.server_close()
        thread.join(5)
assert code == 0 and requests == [] and facts() == before
assert (
    hashlib.sha256(runtime.shared_manifest(owner, job)).hexdigest() == manifest_before
)
Path("/evidence/latest-guard-installed-reference-fences.json").write_text(
    json.dumps(
        {
            "completed_reference_fresh_process": True,
            "unexpected_model_http_requests": len(requests),
            "forged_references_deadlettered": 2,
            "model_budgets_attempts_and_execution_receipts_unchanged": True,
            "accepted_manifest_unchanged": True,
            "consumer_exit_code": code,
            "scope": "latest guarded installed application; no repeated media or operating queue access",
        },
        indent=2,
    )
)
print("latest_guard_installed_reference_fences_passed")
