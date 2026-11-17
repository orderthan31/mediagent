"""Best-effort metadata-only handoff spans, independent of root/SDK logging.

No argument inspection, record merging, exception text or payload serialization.
Callers bind identities only AFTER their existing protocol validation. Durations
are monotonic; UTC boundaries are observations, never database commit evidence.
Synchronous spans include nested work (not exclusive times). No wire-latency claim.
Outcome 'ok' means normal return, not business acceptance. mq_callback measures
handler work only, not owner-thread scheduling/ACK latency. object_get measures
response setup; streamed reads, hash and writes live in object_download_hash_write.
"""
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import json
import math
import re
import sys
import time
from uuid import uuid4

_STAGES = frozenset({
    "dispatch", "claim", "preflight", "result_callback", "result_accept",
    "result_import", "model_result_callback", "model_adoption", "outbox_publish",
    "mq_connect", "mq_publish_confirm", "mq_callback", "object_get",
    "object_download_hash_write", "object_materialize", "object_path", "object_put",
})
_IDS = frozenset({"job_id", "claim_id", "attempt_id", "task_id", "boot_id"})
_HASHES = frozenset({"sha256", "request_sha256"})
_NUMBERS = frozenset({"bytes", "generation", "hash_ms", "write_ms"})
_context: ContextVar[dict | None] = ContextVar("handoff_context", default=None)
_parent: ContextVar[str | None] = ContextVar("handoff_parent", default=None)
_sink: ContextVar[Callable[[dict], None] | None] = ContextVar("handoff_sink", default=None)


def _safe(values):
    result = {}
    # Fixed schema iteration bounds work even for oversized/untrusted metadata.
    for key in _IDS | _HASHES | _NUMBERS:
        value = values.get(key)
        if key in _IDS | _HASHES:
            length = 32 if key in _IDS else 64
            if type(value) is str and len(value) == length and re.fullmatch("[a-f0-9]+", value):
                result[key] = value
        elif type(value) in (int, float) and 0 <= value <= 2**53 and math.isfinite(value):
            result[key] = value
    return result


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _stderr(record):
    # A new closed-schema object only: never a logging LogRecord or its extras.
    line = json.dumps(record, separators=(",", ":"), allow_nan=False)
    if len(line) <= 2048:
        sys.stderr.write(line + "\n")


@contextmanager
def timing_sink(sink):
    """Context-local injection for tests/collectors; no global mutable sink."""
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


@contextmanager
def handoff_context(*, root=False, **metadata):
    """Bind validated opaque correlation for exactly this synchronous callback."""
    token = parent_token = None
    try:
        values = {} if root else dict(_context.get() or {})
        safe = _safe(metadata)
        if "job_id" in safe and values.get("job_id") not in (None, safe["job_id"]):
            # advance_queue may dispatch another authorized job in this callback.
            # Keep causal trace linkage, never the previous job's attempt/claim.
            values = {key: value for key, value in values.items() if key == "trace_id"}
        values.update(safe)
        values.setdefault("trace_id", uuid4().hex)
        token = _context.set(values)
        if root:
            parent_token = _parent.set(None)
    except BaseException:
        pass
    try:
        yield
    finally:
        try:
            if parent_token is not None:
                _parent.reset(parent_token)
            if token is not None:
                _context.reset(token)
        except BaseException:
            pass


class handoff_span:
    """Nonthrowing telemetry; __exit__ never suppresses the business exception."""
    def __init__(self, stage, **metadata):
        self.stage = stage
        self.metadata = metadata
        self.token = self.context_token = None
        self.value = None

    def record(self, **metadata):
        try:
            if self.value is not None:
                self.value.update(_safe(metadata))
        except BaseException:
            pass

    @contextmanager
    def measure(self, field):
        """Accumulate hash/write work without emitting per-stream-block records."""
        started = None
        try:
            if type(field) is str and field in {"hash_ms", "write_ms"}:
                started = time.monotonic()
        except BaseException:
            pass
        try:
            yield
        finally:
            try:
                if started is not None and self.value is not None:
                    elapsed = (time.monotonic() - started) * 1000
                    if math.isfinite(elapsed) and elapsed >= 0:
                        self.record(**{field: self.value.get(field, 0) + elapsed})
            except BaseException:
                pass

    def __enter__(self):
        try:
            if type(self.stage) is not str or self.stage not in _STAGES:
                return self
            values = dict(_context.get() or {})
            if "trace_id" not in values:
                values["trace_id"] = uuid4().hex
                self.context_token = _context.set(values)
            self.value = {"event": "handoff_timing", "version": 1, **values,
                          **_safe(self.metadata), "stage": self.stage,
                          "span_id": uuid4().hex, "started_at": _utc()}
            parent = _parent.get()
            if parent is not None:
                self.value["parent_span_id"] = parent
            self.started = time.monotonic()
            self.token = _parent.set(self.value["span_id"])
        except BaseException:
            self.value = None
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            if self.value is not None:
                elapsed = (time.monotonic() - self.started) * 1000
                if not math.isfinite(elapsed) or elapsed < 0 or elapsed > 2**53:
                    elapsed = 0.0
                self.value.update(ended_at=_utc(), duration_ms=elapsed,
                                  outcome="ok" if exc_type is None else "error")
                (_sink.get() or _stderr)(dict(self.value))
        except BaseException:
            pass
        finally:
            try:
                if self.token is not None:
                    _parent.reset(self.token)
                if self.context_token is not None:
                    _context.reset(self.context_token)
            except BaseException:
                pass
        return False


def timed(stage):
    """Time a synchronous boundary without inspecting its arguments or result."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with handoff_span(stage):
                return function(*args, **kwargs)
        return wrapped
    return decorate
