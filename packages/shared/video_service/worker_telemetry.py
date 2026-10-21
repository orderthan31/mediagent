"""Status-only protocol. No credentials, workflow/input data or control commands."""

import json
import re
import time
from uuid import uuid4

from .cpu_agents import CPU_AGENTS

FAMILIES = {"cpu": frozenset(CPU_AGENTS), "model": frozenset({"transcribe", "translate"}),
            "gpu": frozenset({"preprocess_audio", "faceswap"})}
STATES = frozenset({"connected", "ready", "busy", "stopping", "stopped"})
ID = re.compile(r"[a-f0-9]{32}\Z")
MAX_REPORT = 2048
PREFIX = "mideagent.telemetry"


def exchange(family, role):
    if family not in FAMILIES or role not in FAMILIES[family]:
        raise ValueError("invalid_telemetry_role")
    return f"{PREFIX}.{family}.{role}.v1"


def validate_report(value, source_exchange):
    try:
        if not isinstance(value, dict) or set(value) != {
            "version", "worker_id", "boot_id", "family", "role", "state", "sequence", "ticket_id", "attempt_id"
        }:
            raise ValueError
        if (type(value["version"]) is not int or value["version"] != 1
            or not isinstance(value["worker_id"], str) or not ID.fullmatch(value["worker_id"])
            or not isinstance(value["boot_id"], str) or not ID.fullmatch(value["boot_id"])
            or type(value["sequence"]) is not int or not 0 <= value["sequence"] < 2**63
            or value["state"] not in STATES or exchange(value["family"], value["role"]) != source_exchange):
            raise ValueError
        busy = value["state"] in {"busy", "stopping"} and value["ticket_id"] is not None
        for key in ("ticket_id", "attempt_id"):
            if busy:
                if not isinstance(value[key], str) or not ID.fullmatch(value[key]):
                    raise ValueError
            elif value[key] is not None:
                raise ValueError
        if value["state"] == "busy" and not busy:
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError("invalid_worker_status_report") from None
    return value


class WorkerReporter:
    def __init__(self, worker_id, family, role, send, *, clock=time.monotonic):
        self.worker_id, self.family, self.role = worker_id, family, role
        # Ordered startup generation fences delayed reports from an older boot.
        self.boot_id, self.sequence = f"{time.time_ns():016x}{uuid4().hex[:16]}", 0
        self.send, self.clock, self.last_attempt = send, clock, -100.0
        self.announced = False
        self.state, self.ticket, self.attempt = "connected", None, None
        validate_report(self._report("connected", None, None), exchange(family, role))

    def _report(self, state, ticket, attempt):
        return {"version": 1, "worker_id": self.worker_id, "boot_id": self.boot_id,
                "family": self.family, "role": self.role, "state": state,
                "sequence": self.sequence, "ticket_id": ticket, "attempt_id": attempt}

    def _send(self, state, ticket, attempt):
        value = self._report(state, ticket, attempt)
        validate_report(value, exchange(self.family, self.role))
        self.sequence += 1
        self.last_attempt = self.clock()
        try:
            if not self.send(value):
                return False
        except Exception:  # status transport is never the job outcome
            return False
        return True

    def emit(self, state, ticket=None, attempt=None):
        self.state, self.ticket, self.attempt = state, ticket, attempt
        if not self.announced:
            if not self._send("connected", None, None):
                return False
            self.announced = True
            if state == "connected":
                return True
        return self._send(state, ticket, attempt)

    def tick(self):
        if self.clock() - self.last_attempt >= 3:
            return self.emit(self.state, self.ticket, self.attempt)
        return True

    def begin(self, delivery):
        try:
            command = json.loads(delivery.body)["command"]
            ticket, attempt = command["run_id"], command["attempt_id"]
            if not ID.fullmatch(ticket) or not ID.fullmatch(attempt):
                return False
        except (TypeError, ValueError, KeyError):
            return False
        return self.emit("busy", ticket, attempt)

    def close(self):
        from contextlib import suppress

        with suppress(Exception):
            if hasattr(self.send, "close"):
                self.send.close()


def reporter_from_file(path, family, role):
    if path is None:
        return None
    from .telemetry_transport import StatusSender

    sender = StatusSender(path)
    if sender.config["family"] != family or sender.config["role"] != role:
        raise ValueError("telemetry_role_config_mismatch")
    return WorkerReporter(sender.config["worker_id"], family, role, sender)
