import hashlib
import json
import threading

import pytest
from test_role_delivery_recovery import fixture_case
from video_service.cpu_agents import canonical


@pytest.mark.parametrize("wrong_first", [False, True])
def test_same_consumer_wrong_cancel_does_not_block_correct_scope(
    tmp_path, monkeypatch, wrong_first
):
    import video_service.object_store as stores
    from mideagent_models.broker import consume

    config, ch, calls, envelope, _ = fixture_case(tmp_path, monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    queued = []
    inputs = stores.from_config(config["input_store"])
    original_path = inputs.path

    def gated_path(*args):
        entered.set()
        assert release.wait(8), "test cancellation barrier did not settle"
        return original_path(*args)

    monkeypatch.setattr(inputs, "path", gated_path)
    control = {
        "version": 1,
        "role": "transcription",
        "task_id": envelope["task"]["task_id"],
        "request_sha256": hashlib.sha256(canonical(envelope)).hexdigest(),
    }
    original_pump = ch.connection.process_data_events

    def pump(time_limit):
        if entered.is_set() and not queued:
            queued.append(True)
            if wrong_first:
                ch.messages.append(
                    ("cancel", 1, canonical({**control, "request_sha256": "0" * 64}))
                )
            ch.messages.append(("cancel", 2, canonical(control)))
        original_pump(time_limit)

    monkeypatch.setattr(ch.connection, "process_data_events", pump)
    original_ack, original_nack = ch.basic_ack, ch.basic_nack

    def ack(delivery_tag):
        original_ack(delivery_tag)
        if delivery_tag == 2:
            release.set()

    def nack(delivery_tag, requeue):
        original_nack(delivery_tag, requeue)
        if delivery_tag == 2:
            release.set()

    monkeypatch.setattr(ch, "basic_ack", ack)
    monkeypatch.setattr(ch, "basic_nack", nack)
    try:
        consume(config)
    finally:
        release.set()
    assert 2 in ch.acks and 100 in ch.acks
    assert ch.nacks == ([(1, False)] if wrong_first else [])
    assert calls == []
    assert all(
        json.loads(message["body"])["status"] == "cancelled" for message in ch.results
    )


def test_legacy_rejected_wrong_scope_survives_receiver_recreation_without_poisoning(
    tmp_path, monkeypatch
):
    import video_service.object_store as stores
    from mideagent_models.broker import RoleReceiver
    from mideagent_models.transcription import TranscriptionAgent

    config, ch, calls, envelope, _ = fixture_case(tmp_path, monkeypatch)
    agent = TranscriptionAgent(
        tmp_path / "state", lambda *_: pytest.fail("model must not start")
    )
    receiver = RoleReceiver(
        agent,
        stores.from_config(config["input_store"]),
        stores.from_config(config["output_store"]),
    )
    task = envelope["task"]["task_id"]
    scope = hashlib.sha256(canonical(envelope)).hexdigest()
    correct = {
        "version": 1,
        "role": "transcription",
        "task_id": task,
        "request_sha256": scope,
    }
    bad = {**correct, "request_sha256": "0" * 64}
    bad_digest = hashlib.sha256(canonical(bad)).hexdigest()
    with agent.state.connect() as c:
        c.execute(
            "INSERT INTO role_envelopes(task,envelope_sha)VALUES(?,?)", (task, scope)
        )
        c.execute(
            "INSERT INTO role_artifact_deliveries(task,kind,envelope_sha,attempts,state,error_code)VALUES(?,'cancel_ack',?,1,'rejected','invalid_role_input')",
            (task, bad_digest),
        )
        before = tuple(
            c.execute(
                "SELECT * FROM role_artifact_deliveries WHERE kind='cancel_ack'"
            ).fetchone()
        )
    reopened = TranscriptionAgent(
        tmp_path / "state", lambda *_: pytest.fail("model must not start")
    )
    receiver = RoleReceiver(
        reopened,
        stores.from_config(config["input_store"]),
        stores.from_config(config["output_store"]),
    )
    ack = receiver.deliver(correct, kind="cancel_ack")
    assert ack["status"] == "cancelled"
    with reopened.state.connect() as c:
        assert (
            tuple(
                c.execute(
                    "SELECT * FROM role_artifact_deliveries WHERE kind='cancel_ack'"
                ).fetchone()
            )
            == before
        )
        assert (
            c.execute(
                "SELECT envelope_sha FROM role_cancellations WHERE task=?", (task,)
            ).fetchone()[0]
            == scope
        )


def _bound_receiver(tmp_path, monkeypatch):
    import video_service.object_store as stores
    from mideagent_models.broker import RoleReceiver
    from mideagent_models.transcription import TranscriptionAgent

    config, ch, calls, envelope, _ = fixture_case(tmp_path, monkeypatch)
    agent = TranscriptionAgent(
        tmp_path / "state", lambda *_: pytest.fail("model must not start")
    )
    receiver = RoleReceiver(
        agent,
        stores.from_config(config["input_store"]),
        stores.from_config(config["output_store"]),
    )
    task = envelope["task"]["task_id"]
    scope = hashlib.sha256(canonical(envelope)).hexdigest()
    with agent.state.connect() as c:
        c.execute(
            "INSERT INTO role_envelopes(task,envelope_sha)VALUES(?,?)", (task, scope)
        )
    packet = {
        "version": 1,
        "role": "transcription",
        "task_id": task,
        "request_sha256": scope,
    }
    return receiver, packet


def test_accepted_cancel_identity_and_budget_stay_immutable_after_rejection(
    tmp_path, monkeypatch
):
    from mideagent_models.protocol import InvalidRoleDelivery

    receiver, packet = _bound_receiver(tmp_path, monkeypatch)
    first = receiver.deliver(packet, kind="cancel_ack")
    with receiver.agent.state.connect() as c:
        before = tuple(c.execute("SELECT * FROM role_cancel_ack_deliveries").fetchone())
    with pytest.raises(InvalidRoleDelivery):
        receiver.deliver({**packet, "request_sha256": "0" * 64}, kind="cancel_ack")
    again = receiver.deliver(packet, kind="cancel_ack")
    assert again == first and first["status"] == "cancelled"
    with receiver.agent.state.connect() as c:
        assert (
            tuple(c.execute("SELECT * FROM role_cancel_ack_deliveries").fetchone())
            == before
        )
        assert c.execute(
            "SELECT attempts,state FROM role_cancel_ack_deliveries"
        ).fetchone()[:] == (1, "artifact_ready")


def test_legacy_matching_held_budget_is_not_reset_by_new_cancel_admission(
    tmp_path, monkeypatch
):
    from mideagent_models.broker import DeliveryHeld

    receiver, packet = _bound_receiver(tmp_path, monkeypatch)
    task = packet["task_id"]
    digest = hashlib.sha256(canonical(packet)).hexdigest()
    with receiver.agent.state.connect() as c:
        c.execute(
            "INSERT INTO role_artifact_deliveries(task,kind,envelope_sha,attempts,state,error_code)VALUES(?,'cancel_ack',?,3,'held','prior_uncertainty')",
            (task, digest),
        )
        before = tuple(
            c.execute(
                "SELECT * FROM role_artifact_deliveries WHERE kind='cancel_ack'"
            ).fetchone()
        )
    with pytest.raises(DeliveryHeld):
        receiver.deliver(packet, kind="cancel_ack")
    with receiver.agent.state.connect() as c:
        assert (
            tuple(
                c.execute(
                    "SELECT * FROM role_artifact_deliveries WHERE kind='cancel_ack'"
                ).fetchone()
            )
            == before
        )
