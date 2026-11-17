"""Offline privacy and behavior contract; no broker/database/provider required."""
import asyncio
import json
import logging
import math

import pytest

from video_service.handoff_timing import handoff_context, handoff_span, timing_sink, timed


def test_nested_closed_schema_and_default_observable(capsys):
    previous = logging.root.disabled
    logging.root.disabled = True
    try:
        with handoff_context(job_id="a" * 32):
            with handoff_span("dispatch", secret="SECRET", job_id="invalid"):
                with handoff_span("preflight", bytes=5):
                    pass
    finally:
        logging.root.disabled = previous
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert len(records) == 2
    child, parent = records
    assert child["parent_span_id"] == parent["span_id"]
    assert child["trace_id"] == parent["trace_id"]
    assert child["job_id"] == parent["job_id"] == "a" * 32
    assert "SECRET" not in json.dumps(records)
    for record in records:
        assert math.isfinite(record["duration_ms"]) and record["duration_ms"] >= 0
        assert record["started_at"].endswith("Z") and record["ended_at"].endswith("Z")
        assert len(json.dumps(record)) < 2048


def test_metadata_rejected_without_coercion_and_unknown_stage_dropped():
    class Hostile:
        def __str__(self):
            raise AssertionError("must not stringify")
    records = []
    with timing_sink(records.append):
        with handoff_span("dispatch", job_id="secret" * 10000, bytes=True,
                          generation=float("inf"), sha256=Hostile(), url="SECRET") as span:
            span.record(bytes=-1, hash_ms=float("nan"), attempt_id=Hostile())
        with handoff_span("SECRET", job_id="b" * 32):
            pass
    assert len(records) == 1
    assert not {"job_id", "bytes", "generation", "sha256", "url", "hash_ms", "attempt_id"} & records[0].keys()
    assert "SECRET" not in json.dumps(records)


@pytest.mark.parametrize("error", [ValueError("SECRET"), KeyboardInterrupt("SECRET"), asyncio.CancelledError("SECRET")])
def test_original_exception_identity_and_sink_failure(error):
    def broken(record):
        raise KeyboardInterrupt("sink failed")
    with timing_sink(broken):
        with pytest.raises(BaseException) as caught:
            with handoff_span("dispatch"):
                raise error
    assert caught.value is error
    with timing_sink(broken):
        @timed("dispatch")
        def original():
            return error
        assert original() is error


def test_async_context_isolation_and_reset():
    records = []
    async def task(identity):
        with handoff_context(job_id=identity, root=True):
            with handoff_span("dispatch"):
                await asyncio.sleep(0)
                with handoff_span("preflight"):
                    pass
    async def run():
        await asyncio.gather(task("a" * 32), task("b" * 32))
    with timing_sink(records.append):
        asyncio.run(run())
        with handoff_span("dispatch"):
            pass
    assert "job_id" not in records[-1]
    for identity in ("a" * 32, "b" * 32):
        group = [r for r in records if r.get("job_id") == identity]
        assert len(group) == 2
        assert len({r["trace_id"] for r in group}) == 1
    assert records[0]["trace_id"] != records[2]["trace_id"]


def test_switching_authorized_job_does_not_inherit_old_attempt():
    records = []
    with timing_sink(records.append), handoff_context(job_id="a" * 32, attempt_id="c" * 32, generation=2):
        with handoff_context(job_id="b" * 32), handoff_span("dispatch"):
            pass
        with handoff_span("dispatch"):
            pass
    assert records[0]["job_id"] == "b" * 32
    assert "attempt_id" not in records[0] and "generation" not in records[0]
    assert records[1]["job_id"] == "a" * 32 and records[1]["attempt_id"] == "c" * 32
    assert records[0]["trace_id"] == records[1]["trace_id"]


def test_threads_do_not_inherit_other_callback_context():
    from concurrent.futures import ThreadPoolExecutor
    def callback(identity):
        records = []
        with timing_sink(records.append), handoff_context(root=True, job_id=identity):
            with handoff_span("mq_callback"):
                with handoff_span("preflight"):
                    pass
        with timing_sink(records.append), handoff_span("dispatch"):
            pass
        return records
    with ThreadPoolExecutor(max_workers=2) as pool:
        groups = list(pool.map(callback, ["a" * 32, "b" * 32]))
    assert groups[0][0]["job_id"] == "a" * 32
    assert groups[1][0]["job_id"] == "b" * 32
    assert groups[0][0]["trace_id"] != groups[1][0]["trace_id"]
    assert all("job_id" not in group[-1] for group in groups)


def test_clock_failure_and_nonfinite_elapsed_are_nonthrowing(monkeypatch):
    import video_service.handoff_timing as timing
    records = []
    with timing_sink(records.append):
        with monkeypatch.context() as patch:
            values = iter([1.0, float("inf")])
            patch.setattr(timing.time, "monotonic", lambda: next(values))
            with handoff_span("dispatch"):
                pass
        with monkeypatch.context() as patch:
            def broken():
                raise RuntimeError("SECRET-CLOCK")
            patch.setattr(timing.time, "monotonic", broken)
            with handoff_span("dispatch"):
                pass
        with handoff_span("dispatch"):
            pass
    assert records[0]["duration_ms"] == 0
    assert len(records) == 2
    assert "SECRET-CLOCK" not in json.dumps(records)
