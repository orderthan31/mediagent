"""Focused worker telemetry tests; no product credentials or provider calls."""
import importlib
from uuid import uuid4

import pytest


def report(state="connected", seq=0):
    return {"version": 1, "worker_id": uuid4().hex, "boot_id": uuid4().hex,
            "family": "cpu", "role": "analyze", "state": state, "sequence": seq,
            "ticket_id": None, "attempt_id": None}


def test_report_identity_is_bound_to_its_status_only_exchange():
    module = "video_service.worker_telemetry"
    assert importlib.util.find_spec(module) is not None, "worker telemetry protocol missing"
    telemetry = importlib.import_module(module)
    value = report()
    assert telemetry.validate_report(value, "mideagent.telemetry.cpu.analyze.v1") == value
    with pytest.raises(ValueError):
        telemetry.validate_report(value, "mideagent.telemetry.cpu.encode.v1")
    with pytest.raises(ValueError):
        telemetry.validate_report({**value, "credential": "never accepted"}, "mideagent.telemetry.cpu.analyze.v1")


def test_reporter_announces_boot_then_tracks_busy_ready_and_periodic_heartbeat():
    module = "video_service.worker_telemetry"
    assert importlib.util.find_spec(module) is not None, "worker telemetry protocol missing"
    telemetry = importlib.import_module(module)
    sent = []
    clock = [0.0]
    reporter = telemetry.WorkerReporter(uuid4().hex, "cpu", "analyze", lambda x: sent.append(x) or True, clock=lambda: clock[0])
    reporter.emit("ready")
    assert [r["state"] for r in sent] == ["connected", "ready"]
    ticket, attempt = uuid4().hex, uuid4().hex
    reporter.emit("busy", ticket, attempt)
    assert sent[-1]["ticket_id"] == ticket and sent[-1]["attempt_id"] == attempt
    clock[0] = 4
    reporter.tick()
    assert sent[-1]["state"] == "busy" and len(sent) == 4
    reporter.emit("ready")
    assert sent[-1]["ticket_id"] is None
    assert [r["sequence"] for r in sent] == list(range(len(sent)))


def test_telemetry_send_failure_does_not_raise_into_the_work_executor():
    module = "video_service.worker_telemetry"
    assert importlib.util.find_spec(module) is not None, "worker telemetry protocol missing"
    telemetry = importlib.import_module(module)
    reporter = telemetry.WorkerReporter(uuid4().hex, "cpu", "analyze", lambda _: False)
    assert reporter.emit("ready") is False


def test_unconfirmed_status_never_reuses_a_sequence_for_different_state():
    from video_service.worker_telemetry import WorkerReporter
    attempted = []
    def send(value):
        attempted.append(value)
        return len(attempted) > 1
    reporter = WorkerReporter(uuid4().hex, "cpu", "analyze", send)
    assert reporter.emit("ready") is False
    assert reporter.emit("ready") is True
    assert len({x["sequence"] for x in attempted}) == len(attempted)


def test_real_consumer_loop_reports_busy_identity_without_changing_ack_order():
    import threading
    from test_amqp import client_seam, synthetic_command
    from video_service.rabbitmq_transport import envelope
    from video_service.worker_telemetry import WorkerReporter

    command = synthetic_command()
    stop = threading.Event()
    client, channel, _ = client_seam(envelope("a" * 32, command), stop)
    sent = []
    reporter = WorkerReporter(uuid4().hex, "cpu", "analyze", lambda value: sent.append(value) or True)
    client.serve("analyze", lambda delivery: None, stop, telemetry=reporter)
    assert channel.acks == [{"delivery_tag": 1}]
    assert [x["state"] for x in sent] == ["connected", "ready", "busy", "stopping", "stopped"]
    busy = next(x for x in sent if x["state"] == "busy")
    assert busy["ticket_id"] == command["run_id"] and busy["attempt_id"] == command["attempt_id"]
