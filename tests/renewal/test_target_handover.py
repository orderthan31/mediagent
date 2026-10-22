"""One-slot target replacement: real PG, controlled native inspect/signal boundary."""

import importlib.util
import json
import secrets
from uuid import uuid4

from test_control_journal import actor as actor  # noqa: PLC0414 - pytest fixture export
from video_service.agent_control import Target
from video_service.control_ack_receipts import AckReceipts
from video_service.durable_control import BrokerReports, DurableHost, SignalControl
from video_service.postgres.remote_control import RemoteControl
from video_service.postgres.worker_telemetry import WorkerTelemetry
from video_service.worker_telemetry import WorkerReporter, exchange


def setup_case(actor, tmp_path):
    db, admin = actor
    group = "replace_" + uuid4().hex[:10]
    wid = uuid4().hex
    labels = (
        ("com.docker.compose.project", "handover-fixture"),
        ("com.docker.compose.service", group),
        ("mideagent.worker_id", wid),
    )
    old = Target("a" * 64, "sha256:" + "c" * 64, labels)
    new = Target("b" * 64, "sha256:" + "d" * 64, labels)
    running = {old.container_id: True, new.container_id: False}
    signals = []
    sink = WorkerTelemetry(db)
    sink.beat()
    reporter = WorkerReporter(
        wid,
        "cpu",
        "encode",
        lambda report: sink.accept(
            report, exchange("cpu", "encode"), expected_worker_id=wid
        ),
    )
    reporter.emit("ready")

    def cli(args):
        if args[:2] == ["container", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": t.container_id,
                        "Image": t.image_id,
                        "Config": {"Labels": dict(t.labels)},
                        "HostConfig": {"RestartPolicy": {"Name": "no"}},
                        "State": {
                            "Running": running[t.container_id],
                            "Status": "running"
                            if running[t.container_id]
                            else "exited",
                            "Paused": False,
                            "Dead": False,
                            "ExitCode": 0,
                            "StartedAt": "2026-01-01T00:00:00Z",
                        },
                    }
                    for t in (old, new)
                    if t.container_id in args[2:]
                ]
            )
        signals.append(args)
        if args[1] == "kill":
            running[args[-1]] = False
            reporter.emit("stopped")
        return ""

    store = RemoteControl(db)
    old_adapter = SignalControl({group: (old,)}, runner=cli)
    new_adapter = SignalControl({group: (new,)}, runner=cli)
    receipts = AckReceipts(tmp_path, secrets.token_bytes(32))
    host = DurableHost(
        store,
        old_adapter,
        {group: [wid]},
        BrokerReports(db, {group: ("cpu", "encode")}),
        receipts=receipts,
        recovery=__import__(
            "video_service.postgres.control_recovery", fromlist=["ControlRecovery"]
        ).ControlRecovery(store),
    )
    host.step()
    request = store.configure(
        admin, group, revision=0, enabled=False, replicas=0, request_id=uuid4().hex
    )
    host.step()
    host.close()
    assert store.get(group)["control"]["phase"] is None
    return (
        db,
        admin,
        store,
        group,
        wid,
        old_adapter,
        new_adapter,
        receipts,
        signals,
        running,
        request,
    )


def test_audited_handover_preserves_originals_and_never_starts(actor, tmp_path):
    assert importlib.util.find_spec("video_service.target_handover"), (
        "audited target handover missing"
    )
    from video_service.postgres.target_handover import TargetHandover
    from video_service.target_handover import HandoverHost

    db, admin, store, group, wid, old, new, receipts, calls, running, request = (
        setup_case(actor, tmp_path)
    )
    ledger = TargetHandover(store)
    executor = HandoverHost(ledger, old, new, {group: [wid]}, receipts)
    candidate = executor.prepare(group)
    plan = ledger.preview(admin, group, candidate["id"])
    decision = ledger.submit(
        admin,
        group,
        plan_id=plan["id"],
        decision_id=uuid4().hex,
        reason="합성 슬롯의 정상 중지와 새 정확한 대상을 확인함",
        acknowledge=True,
    )
    applied = executor.apply(decision["id"])
    assert applied["phase"] == "applied"
    assert len(calls) == 1 and not any(r for r in running.values())
    with db.connection() as c:
        g = c.execute(
            "SELECT * FROM remote_control_groups WHERE agent_id=%s", (group,)
        ).fetchone()
        original = c.execute(
            "SELECT * FROM remote_control_requests WHERE request_id=%s",
            (request["request_id"],),
        ).fetchone()
        contracts = c.execute(
            "SELECT * FROM control_target_contracts WHERE agent_id=%s ORDER BY epoch",
            (group,),
        ).fetchall()
    assert g["target_epoch"] == 1 and not g["enabled"] and g["replicas"] == 0
    assert g["observed"] is None and g["pending_handover"] is None
    assert original["phase"] == "succeeded" and len(contracts) == 2
    assert (
        contracts[0]["descriptor"]["container_id"]
        == old._targets(group)[0].container_id
    )
    assert (
        contracts[1]["descriptor"]["container_id"]
        == new._targets(group)[0].container_id
    )
    assert executor.apply(decision["id"]) == applied
    assert len(calls) == 1


def admitted(actor, tmp_path):
    from video_service.postgres.target_handover import TargetHandover
    from video_service.target_handover import HandoverHost

    state = setup_case(actor, tmp_path)
    _db, admin, store, group, wid, old, new, receipts, _calls, _running, _request = (
        state
    )
    ledger = TargetHandover(store)
    host = HandoverHost(ledger, old, new, {group: [wid]}, receipts)
    candidate = host.prepare(group)
    plan = ledger.preview(admin, group, candidate["id"])
    decision = ledger.submit(
        admin,
        group,
        plan_id=plan["id"],
        decision_id=uuid4().hex,
        reason="기존 정지와 새로운 고정 대상의 근거를 확인함",
        acknowledge=True,
    )
    return state, ledger, host, candidate, plan, decision


def test_source_cas_and_concurrent_decisions(actor, tmp_path):

    import pytest
    from video_service.postgres import Conflict

    state, ledger, host, candidate, plan, first = admitted(actor, tmp_path)
    _db, admin, _store, group, *_ = state
    with pytest.raises(Conflict, match="handover_in_progress"):
        ledger.submit(
            admin,
            group,
            plan_id=plan["id"],
            decision_id=uuid4().hex,
            reason="동시 요청은 앞선 교체를 덮어쓸 수 없어야 함",
            acknowledge=True,
        )
    assert host.apply(first["id"])["phase"] == "applied"
    with pytest.raises(Conflict):
        ledger.preview(admin, group, candidate["id"])


def test_native_evidence_change_is_held_without_start(actor, tmp_path):
    state, _ledger, host, _candidate, _plan, decision = admitted(actor, tmp_path)
    db, _admin, _store, group, _wid, _old, new, _receipts, calls, running, _request = (
        state
    )
    running[new._targets(group)[0].container_id] = True
    assert host.apply(decision["id"])["phase"] == "held"
    running[new._targets(group)[0].container_id] = False
    assert host.apply(decision["id"])["phase"] == "held"
    assert len(calls) == 1
    with db.connection() as c:
        g = c.execute(
            "SELECT * FROM remote_control_groups WHERE agent_id=%s", (group,)
        ).fetchone()
        assert g["target_epoch"] == 0 and g["pending_handover"] == decision["id"]


def test_interrupted_applying_is_held_never_auto_resumed(actor, tmp_path, monkeypatch):
    import pytest

    state, _ledger, host, _candidate, _plan, decision = admitted(actor, tmp_path)
    original = host._finish

    def crash(_):
        raise SystemExit("fixture interrupted after applying commit")

    monkeypatch.setattr(host, "_finish", crash)
    with pytest.raises(SystemExit):
        host.apply(decision["id"])
    monkeypatch.setattr(host, "_finish", original)
    assert host.apply(decision["id"])["phase"] == "held"
    assert host.apply(decision["id"])["phase"] == "held"
    assert len(state[8]) == 1


def test_committed_response_loss_returns_same_applied_receipt(
    actor, tmp_path, monkeypatch
):
    import pytest

    state, _ledger, host, _candidate, _plan, decision = admitted(actor, tmp_path)
    original = host._finish

    def crash(identity):
        original(identity)
        raise SystemExit("fixture committed response lost")

    monkeypatch.setattr(host, "_finish", crash)
    with pytest.raises(SystemExit):
        host.apply(decision["id"])
    monkeypatch.setattr(host, "_finish", original)
    assert host.apply(decision["id"])["phase"] == "applied"
    assert len(state[8]) == 1


def test_old_live_host_ownership_blocks_handover(actor, tmp_path):
    import pytest
    from video_service.postgres import Conflict

    state, _ledger, host, _candidate, _plan, decision = admitted(actor, tmp_path)
    db, _admin, store, group, wid, old, _new, _receipts, calls, _running, _request = (
        state
    )
    previous = DurableHost(
        store, old, {group: [wid]}, BrokerReports(db, {group: ("cpu", "encode")})
    )
    try:
        with pytest.raises(Conflict, match="old_host_still_owned"):
            host.apply(decision["id"])
    finally:
        previous.close()
    assert len(calls) == 1


def test_stale_host_cannot_signal_after_owner_closed(actor, tmp_path):
    import pytest

    db, _admin, store, group, wid, old, _new, _receipts, calls, _running, _request = (
        setup_case(actor, tmp_path)
    )
    previous = DurableHost(
        store, old, {group: [wid]}, BrokerReports(db, {group: ("cpu", "encode")})
    )
    previous.close()
    import psycopg

    with pytest.raises(psycopg.OperationalError, match="closed"):
        old.signal(group, 0, "start")
    assert len(calls) == 1


def test_new_host_requires_explicit_exact_binding_and_old_is_fenced(actor, tmp_path):
    import pytest
    from video_service.agent_control import ControlError
    from video_service.postgres import Conflict
    from video_service.target_handover import descriptor, resolve_active

    state, ledger, executor, candidate, _plan, decision = admitted(actor, tmp_path)
    db, _admin, store, group, wid, old, new, _receipts, calls, running, _request = state
    executor.apply(decision["id"])
    original = descriptor(old._targets(group)[0], wid)
    approved = descriptor(new._targets(group)[0], wid)
    with pytest.raises(ControlError):
        resolve_active(ledger, group, original, None)
    assert resolve_active(ledger, group, original, approved) == approved
    with pytest.raises(Conflict):
        store.claim(group, candidate["from_contract"])
    with pytest.raises(Conflict):
        store.publish(group, candidate["from_contract"], [])
    with pytest.raises(Conflict):
        DurableHost(
            store, old, {group: [wid]}, BrokerReports(db, {group: ("cpu", "encode")})
        )
    fresh = DurableHost(
        store, new, {group: [wid]}, BrokerReports(db, {group: ("cpu", "encode")})
    )
    try:
        fresh.step()
        assert len(calls) == 1 and not running[new._targets(group)[0].container_id]
    finally:
        fresh.close()


def test_startup_entrypoint_accepts_separate_handover_bindings():
    import inspect

    from video_service.control_runtime import run

    assert "handover_bindings" in inspect.signature(run).parameters, (
        "active target bindings missing from actual host entrypoint"
    )


def test_true_concurrent_submit_accepts_only_one(actor, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from video_service.postgres import Conflict
    from video_service.postgres.target_handover import TargetHandover
    from video_service.target_handover import HandoverHost

    state = setup_case(actor, tmp_path)
    _db, admin, store, group, wid, old, new, receipts, calls, *_ = state
    ledger = TargetHandover(store)
    host = HandoverHost(ledger, old, new, {group: [wid]}, receipts)
    candidate = host.prepare(group)
    plans = [ledger.preview(admin, group, candidate["id"]) for _ in range(2)]
    barrier = Barrier(2)

    def submit(plan):
        barrier.wait()
        try:
            return ledger.submit(
                admin,
                group,
                plan_id=plan["id"],
                decision_id=uuid4().hex,
                reason="같은 개정에 대한 동시 교체 결정을 검증함",
                acknowledge=True,
            )["phase"]
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, plans))
    assert sorted(results) == ["conflict", "planned"]
    assert len(calls) == 1


def test_semantic_aba_is_stale_even_after_observation_restored(actor, tmp_path):
    import pytest
    from video_service.postgres import Conflict
    from video_service.postgres.target_handover import TargetHandover
    from video_service.target_handover import HandoverHost

    state = setup_case(actor, tmp_path)
    db, admin, store, group, wid, old, new, receipts, *_ = state
    ledger = TargetHandover(store)
    host = HandoverHost(ledger, old, new, {group: [wid]}, receipts)
    candidate = host.prepare(group)
    plan = ledger.preview(admin, group, candidate["id"])
    with db.connection() as c:
        g = c.execute(
            "SELECT * FROM remote_control_groups WHERE agent_id=%s", (group,)
        ).fetchone()
    changed = [{**g["observed"][0], "boot_id": uuid4().hex}]
    store.publish(group, g["contract_sha256"], changed)
    store.publish(group, g["contract_sha256"], g["observed"])
    with pytest.raises(Conflict, match="evidence_changed"):
        ledger.submit(
            admin,
            group,
            plan_id=plan["id"],
            decision_id=uuid4().hex,
            reason="원래 값으로 돌아와도 관측 세대 변경을 거부함",
            acknowledge=True,
        )


def test_unresolved_control_blocks_prepare(actor, tmp_path):
    import pytest
    from video_service.postgres import Conflict
    from video_service.postgres.target_handover import TargetHandover
    from video_service.target_handover import HandoverHost

    state = setup_case(actor, tmp_path)
    db, _admin, store, group, wid, old, new, receipts, *_ = state
    for phase in ["queued", "applying", "unknown"]:
        with db.connection() as c:
            c.execute(
                "UPDATE remote_control_requests SET phase=%s WHERE request_id=%s",
                (phase, state[-1]["request_id"]),
            )
        executor = HandoverHost(
            TargetHandover(store), old, new, {group: [wid]}, receipts
        )
        with pytest.raises(Conflict, match="unresolved_control"):
            executor.prepare(group)
    with db.connection() as c:
        assert not c.execute(
            "SELECT 1 FROM control_target_candidates WHERE agent_id=%s", (group,)
        ).fetchone()


def test_corrupt_signed_stop_is_held_and_not_repaired(actor, tmp_path):
    import json

    state, _ledger, host, candidate, _plan, decision = admitted(actor, tmp_path)
    path = state[7]._path(candidate["context"]["stop_action"]["id"])
    data = json.loads(path.read_bytes())
    data["signature"] = "0" * 64
    path.write_text(json.dumps(data))
    assert host.apply(decision["id"])["phase"] == "held"
    assert json.loads(path.read_bytes())["signature"] == "0" * 64
    assert len(state[8]) == 1


def test_revoked_admin_is_held_and_reenable_does_not_resume(actor, tmp_path):
    state, _ledger, host, _candidate, _plan, decision = admitted(actor, tmp_path)
    db, admin = state[:2]
    with db.connection() as c:
        c.execute("UPDATE accounts SET active=false WHERE id=%s", (admin,))
    try:
        assert host.apply(decision["id"])["phase"] == "held"
    finally:
        with db.connection() as c:
            c.execute("UPDATE accounts SET active=true WHERE id=%s", (admin,))
    assert host.apply(decision["id"])["phase"] == "held"
    assert len(state[8]) == 1


def test_direct_pin_overwrite_and_history_rewrite_are_denied(actor, tmp_path):
    import psycopg
    import pytest

    state, _ledger, host, candidate, plan, decision = admitted(actor, tmp_path)
    db, _admin, _store, group, *_ = state
    for query, args in [
        (
            "UPDATE remote_control_groups SET contract_sha256=%s WHERE agent_id=%s",
            ("f" * 64, group),
        ),
        (
            "UPDATE control_target_candidates SET new_contract=%s WHERE id=%s",
            ("f" * 64, candidate["id"]),
        ),
        ("DELETE FROM control_target_plans WHERE id=%s", (plan["id"],)),
        (
            "UPDATE control_target_transitions SET phase='applied' WHERE id=%s",
            (decision["id"],),
        ),
    ]:
        with pytest.raises(psycopg.errors.CheckViolation), db.connection() as c:
            c.execute(query, args)
    assert host.apply(decision["id"])["phase"] == "applied"
    with pytest.raises(psycopg.errors.CheckViolation), db.connection() as c:
        c.execute(
            "DELETE FROM control_target_events WHERE transition_id=%s",
            (decision["id"],),
        )


def test_pending_handover_blocks_legacy_api_start_without_pin_privilege(
    actor, tmp_path
):
    import psycopg
    import pytest
    from video_service.postgres import Conflict

    state, _ledger, _host, _candidate, _plan, _decision = admitted(actor, tmp_path)
    db, admin, store, group, *_ = state
    with pytest.raises(Conflict, match="control_observation_unavailable"):
        store.configure(
            admin,
            group,
            revision=store.get(group)["revision"],
            enabled=True,
            replicas=1,
            request_id=uuid4().hex,
        )
    # The pre-feature API does not have the new projection gate. Its actual
    # request INSERT is independently refused by the migration's DB fence.
    with pytest.raises(psycopg.errors.CheckViolation), db.connection() as c:
        c.execute(
            "INSERT INTO remote_control_requests(request_id,agent_id,actor_id,payload_sha256,revision,replicas,phase) VALUES(%s,%s,%s,%s,%s,1,'queued')",
            (uuid4().hex, group, admin, "a" * 64, store.get(group)["revision"] + 1),
        )
    assert len(state[8]) == 1


def test_real_restricted_db_roles_cannot_overwrite_pins_or_history(actor, tmp_path):
    import psycopg
    import pytest
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    state, _ledger, host, _candidate, _plan, decision = admitted(actor, tmp_path)
    db, _admin, _store, group, *_ = state
    api_role = "handover_api_" + uuid4().hex[:10]
    host_role = "handover_host_" + uuid4().hex[:10]
    password = secrets.token_urlsafe(32)
    with db.connection() as c:
        for role in (api_role, host_role):
            c.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
            c.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    sql.Identifier(role)
                )
            )
            c.execute(
                sql.SQL(
                    "GRANT SELECT ON remote_control_groups,control_target_candidates,control_target_plans,control_target_transitions,control_target_contracts,control_target_events TO {}"
                ).format(sql.Identifier(role))
            )
        c.execute(
            sql.SQL(
                "GRANT INSERT ON control_target_plans,control_target_transitions TO {}"
            ).format(sql.Identifier(api_role))
        )
        c.execute(
            sql.SQL(
                "GRANT UPDATE(revision,pending_handover) ON remote_control_groups TO {}"
            ).format(sql.Identifier(api_role))
        )
        c.execute(
            sql.SQL("GRANT SELECT(id,role,active) ON accounts TO {}").format(
                sql.Identifier(host_role)
            )
        )
    for query, args in [
        (
            "UPDATE remote_control_groups SET contract_sha256=%s WHERE agent_id=%s",
            ("f" * 64, group),
        ),
        ("DELETE FROM control_target_contracts WHERE agent_id=%s", (group,)),
        (
            "UPDATE control_target_transitions SET phase='applied' WHERE id=%s",
            (decision["id"],),
        ),
        ("DELETE FROM control_target_events WHERE transition_id=%s", (decision["id"],)),
    ]:
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            psycopg.connect(
                make_conninfo(db.dsn, user=api_role, password=password)
            ) as c,
        ):
            c.execute(query, args)
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        psycopg.connect(make_conninfo(db.dsn, user=host_role, password=password)) as c,
    ):
        c.execute("SELECT password_hash FROM accounts")
    assert host.apply(decision["id"])["phase"] == "applied"


def test_real_controller_process_exit_is_held_without_resignal(actor, tmp_path):
    import multiprocessing
    import os

    state, _ledger, host, _candidate, _plan, decision = admitted(actor, tmp_path)

    def interrupted():
        host._finish = lambda _identity: os._exit(23)
        host.apply(decision["id"])

    child = multiprocessing.get_context("fork").Process(target=interrupted)
    child.start()
    child.join(8)
    assert child.exitcode == 23
    assert host.apply(decision["id"])["phase"] == "held"
    assert host.apply(decision["id"])["phase"] == "held"
    assert len(state[8]) == 1


def test_pending_replacement_is_not_manageable(actor, tmp_path):
    state, _ledger, _host, _candidate, _plan, _decision = admitted(actor, tmp_path)
    view = state[2].get(state[3])
    assert view["manageable"] is False
    assert view["unavailable_reason"] == "target_handover_pending"
