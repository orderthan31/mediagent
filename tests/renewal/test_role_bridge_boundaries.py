"""R7/R8: actual PG/product cancellation and LangGraph, local controlled tool only."""

import base64
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from mideagent_models.broker import RoleReceiver
from mideagent_models.transcription import TranscriptionAgent
from test_execution import admin as _admin
from test_execution import db as _db
from test_execution import movie as _movie
from test_model_role_orchestration import formal
from video_service.audio_batches import split_normalized_audio
from video_service.model_role_tool import RoleToolBridge
from video_service.postgres.model_roles import ModelRoles

db, admin, movie = _db, _admin, _movie


def bridge_case(db, admin, movie, tmp_path, published=True):
    runtime, owner, command = formal(db, admin, movie, tmp_path)
    roles = ModelRoles(runtime)
    envelope = roles.enroll(owner, command)
    if published:
        assert roles.publish_exact(
            owner, command["run_id"], command["attempt_id"], lambda _: True
        )
    batch = list(
        split_normalized_audio(runtime.store.read(owner, command["inputs"]["audio"]))
    )[0]
    packet = {
        "task_id": command["attempt_id"],
        "chunk_index": 0,
        "model": envelope["task"]["model"],
        "source_language": "en",
        "audio_base64": base64.b64encode(batch.audio).decode(),
    }
    return runtime, roles, owner, command, envelope, packet


def test_r7_product_cancel_cannot_commit_between_final_validation_and_adapter_start(
    db, admin, movie, tmp_path, monkeypatch
):
    runtime, roles, owner, command, _, packet = bridge_case(db, admin, movie, tmp_path)
    bridge = RoleToolBridge(roles, chunk_concurrency=2)
    checked = threading.Event()
    cancel_attempted = threading.Event()
    cancel_committed = threading.Event()
    calls = []
    hooked = False
    original_connection = runtime.database.connection
    revision = runtime.get(owner, command["run_id"])["revision"]

    # Adapter creation is after the durable intent, immediately before the final check.
    class Adapter:
        def transcribe(self, *_):
            assert cancel_attempted.wait(5)
            # A final-check winner must retain its fence through actual adapter entry.
            with original_connection() as c:
                job = c.execute(
                    "SELECT cancel_requested,generation FROM jobs WHERE owner_id=%s AND id=%s",
                    (owner, command["run_id"]),
                ).fetchone()
            calls.append(job)
            assert not cancel_committed.is_set() and not job["cancel_requested"]
            assert job["generation"] == command["generation"]
            return []

        def close(self):
            pass

    def make(*_):
        nonlocal hooked
        hooked = True
        return Adapter()

    monkeypatch.setattr(runtime.transcription_runtime, "make_adapter", make)

    @contextmanager
    def connection():
        with original_connection() as c:
            if threading.current_thread().name == "cancel-r7":
                c.execute(
                    "SELECT set_config('application_name',%s,true)",
                    ("r7-cancel-" + command["attempt_id"],),
                )
            yield c
        # This is the old gap: final _current transaction already released its locks.
        if (
            hooked
            and threading.current_thread().name == "bridge"
            and not checked.is_set()
        ):
            checked.set()
            assert cancel_attempted.wait(5)
            # Wait until cancellation either committed (the original bug) or is
            # actually waiting for our advisory fence. No timing-based winner.
            from time import monotonic

            deadline = monotonic() + 5
            while not cancel_committed.is_set():
                with original_connection() as observer:
                    waiting = observer.execute(
                        "SELECT count(*) n FROM pg_stat_activity WHERE application_name=%s AND wait_event_type='Lock'AND wait_event='advisory'",
                        ("r7-cancel-" + command["attempt_id"],),
                    ).fetchone()["n"]
                if waiting:
                    break
                assert monotonic() < deadline, (
                    "cancel did not commit or reach the actual fence"
                )
                cancel_committed.wait(0.01)

    monkeypatch.setattr(runtime.database, "connection", connection)

    def cancel():
        threading.current_thread().name = "cancel-r7"
        assert checked.wait(5)
        cancel_attempted.set()
        runtime.cancel(owner, command["run_id"], revision)
        cancel_committed.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(cancel)
        oldname = threading.current_thread().name
        threading.current_thread().name = "bridge"
        try:
            assert bridge.invoke(packet) == []
        finally:
            threading.current_thread().name = oldname
        future.result(timeout=8)
    assert cancel_committed.is_set() and len(calls) == 1


def test_r8_fast_consumer_runs_during_publisher_confirm_without_permanent_hold(
    db, admin, movie, tmp_path
):
    runtime, roles, owner, command, envelope, packet = bridge_case(
        db, admin, movie, tmp_path, published=False
    )
    bridge = RoleToolBridge(roles, chunk_concurrency=2)
    calls = []

    class Adapter:
        def transcribe(self, *_):
            calls.append(True)
            return []

        def close(self):
            pass

    runtime.transcription_runtime.make_adapter = lambda *_: Adapter()

    class Tool:
        def for_chunk(self, task, chunk):
            return lambda *_: bridge.invoke(packet)

    role = TranscriptionAgent(tmp_path / "role", Tool())
    receiver = RoleReceiver(role, runtime.store, runtime.store)
    responses = []

    def send(packet):
        responses.append(receiver.deliver(packet))
        return True

    assert roles.publish_exact(owner, command["run_id"], command["attempt_id"], send)
    assert responses[0]["status"] == "completed" and calls == [True]
    with db.connection() as c:
        assert (
            c.execute("SELECT phase FROM model_role_tasks").fetchone()["phase"]
            == "sent"
        )
        assert (
            c.execute("SELECT status FROM model_role_tool_calls").fetchone()["status"]
            == "completed"
        )
    assert not roles.publish_exact(
        owner,
        command["run_id"],
        command["attempt_id"],
        lambda _: pytest.fail("no republish"),
    )


def test_r7_cancel_committed_first_blocks_adapter_and_records_known_noncall(
    db, admin, movie, tmp_path
):
    from video_service.postgres import Conflict

    runtime, roles, owner, command, _, packet = bridge_case(db, admin, movie, tmp_path)
    calls = []

    class Adapter:
        def transcribe(self, *_):
            calls.append(True)
            return []

        def close(self):
            pass

    def create(*_):
        runtime.cancel(
            owner, command["run_id"], runtime.get(owner, command["run_id"])["revision"]
        )
        with db.connection() as c:
            job = c.execute(
                "SELECT cancel_requested,generation FROM jobs WHERE owner_id=%s AND id=%s",
                (owner, command["run_id"]),
            ).fetchone()
            assert job["cancel_requested"] and job["generation"] > command["generation"]
        return Adapter()

    runtime.transcription_runtime.make_adapter = create
    with pytest.raises(Conflict, match="model_role_attempt_not_active"):
        RoleToolBridge(roles, chunk_concurrency=2).invoke(packet)
    assert calls == []
    with db.connection() as c:
        assert (
            c.execute("SELECT status FROM model_role_tool_calls").fetchone()["status"]
            == "failed"
        )


def test_r7_shared_fence_keeps_parallel_admissions_before_product_cancel(
    db, admin, movie, tmp_path
):
    from video_service.postgres.model_call_fence import model_call_fence

    runtime, roles, owner, command, _, _ = bridge_case(db, admin, movie, tmp_path)
    entered = threading.Barrier(3)
    release = threading.Event()
    committed = threading.Event()

    def admission():
        with model_call_fence(db, owner, command["run_id"]):
            entered.wait(timeout=5)
            assert release.wait(5)

    revision = runtime.get(owner, command["run_id"])["revision"]

    def cancel():
        runtime.cancel(owner, command["run_id"], revision)
        committed.set()

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(admission)
        second = pool.submit(admission)
        try:
            entered.wait(timeout=5)
            future = pool.submit(cancel)
            assert not committed.is_set()
        finally:
            release.set()
        first.result(timeout=6)
        second.result(timeout=6)
        future.result(timeout=6)
    assert committed.is_set()


def test_r8_early_completed_result_is_not_downgraded_by_later_confirm(
    db, admin, movie, tmp_path
):
    runtime, roles, owner, command, _, packet = bridge_case(
        db, admin, movie, tmp_path, published=False
    )
    bridge = RoleToolBridge(roles, chunk_concurrency=2)
    calls = []

    class Adapter:
        def transcribe(self, *_):
            calls.append(True)
            return []

        def close(self):
            pass

    runtime.transcription_runtime.make_adapter = lambda *_: Adapter()

    class Tool:
        def for_chunk(self, *_):
            return lambda *_: bridge.invoke(packet)

    receiver = RoleReceiver(
        TranscriptionAgent(tmp_path / "role", Tool()), runtime.store, runtime.store
    )

    def send(envelope):
        ack = receiver.deliver(envelope)
        assert ack["status"] == "completed"
        roles.receive(ack)
        return True

    assert roles.publish_exact(owner, command["run_id"], command["attempt_id"], send)
    with db.connection() as c:
        assert (
            c.execute("SELECT phase FROM model_role_tasks").fetchone()["phase"]
            == "accepted"
        )
    assert calls == [True]


def test_r8_unconfirmed_early_delivery_does_not_republish_or_repeat_model(
    db, admin, movie, tmp_path
):
    from video_service.postgres import Conflict

    runtime, roles, owner, command, _, packet = bridge_case(
        db, admin, movie, tmp_path, published=False
    )
    bridge = RoleToolBridge(roles, chunk_concurrency=2)
    calls = []

    class Adapter:
        def transcribe(self, *_):
            calls.append(True)
            return []

        def close(self):
            pass

    runtime.transcription_runtime.make_adapter = lambda *_: Adapter()

    class Tool:
        def for_chunk(self, *_):
            return lambda *_: bridge.invoke(packet)

    receiver = RoleReceiver(
        TranscriptionAgent(tmp_path / "role", Tool()), runtime.store, runtime.store
    )

    def send(envelope):
        assert receiver.deliver(envelope)["status"] == "completed"
        return False

    with pytest.raises(Conflict, match="model_role_publish_unconfirmed"):
        roles.publish_exact(owner, command["run_id"], command["attempt_id"], send)
    with db.connection() as c:
        assert (
            c.execute("SELECT phase FROM model_role_tasks").fetchone()["phase"]
            == "unknown"
        )
        assert (
            c.execute(
                "SELECT published_at FROM message_outbox WHERE id=%s",
                (command["attempt_id"],),
            ).fetchone()["published_at"]
            is None
        )
    assert not roles.publish_exact(
        owner,
        command["run_id"],
        command["attempt_id"],
        lambda _: pytest.fail("unknown must not republish"),
    )
    assert calls == [True]
