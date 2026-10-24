"""Real PG chunk intents bound to a formal model node attempt; no provider calls."""

import hashlib
import json
import secrets
from uuid import uuid4

import httpx
import pytest
from test_execution import movie as _movie
from test_foundation import admin as _admin
from test_original_upload_policy import db as _db
from test_transcription_execution import audio_graph
from video_service.content_store import ContentStore
from video_service.cpu_agents import canonical, digest
from video_service.postgres import Conflict
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime

try:
    from video_service.postgres.model_batches import ModelBatchLedger
except ModuleNotFoundError as error:
    if error.name != "video_service.postgres.model_batches":
        raise
    ModelBatchLedger = None

admin, db, movie = _admin, _db, _movie


def formal_attempt(
    db, admin, movie, root, filename="ledger-synthetic.mp4", max_calls=3
):
    owner = admin[0]["id"]
    registry, credentials = Registry(db), CredentialStore(db, secrets.token_bytes(32))
    cid, mid = uuid4().hex, uuid4().hex
    conn = registry.save_connection(
        owner,
        cid,
        revision=0,
        name="controlled Gemini audio",
        provider="openai_compatible",
        protocol="gemini",
        endpoint="http://127.0.0.1:9111/v1",
    )
    conn = credentials.save(
        owner, cid, revision=conn["revision"], secret=secrets.token_urlsafe(32)
    )
    registry.save_model(
        owner,
        mid,
        revision=0,
        name="controlled timed audio",
        model="gemini-3.8-flash",
        connection_id=cid,
        connection_revision=conn["current_revision"],
        model_types=["speech_recognition"],
        input_modalities=["audio"],
        output_modalities=["text"],
        capabilities=["speech_recognition"],
    )
    transport = lambda: httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(
            AssertionError("No model request in ledger test")
        )
    )
    asr = TranscriptionRuntime(
        credentials,
        transport_factory=transport,
        approved_origins={"http://127.0.0.1:9111"},
        mode="controlled_http",
    )
    runtime = Execution(db, ContentStore(root), transcription_runtime=asr)
    graph = audio_graph(
        {"model_id": mid, "revision": 1}, {"model_id": mid, "revision": 1}
    )
    graph["nodes"] = graph["nodes"][:-1]
    graph["edges"] = [
        edge for edge in graph["edges"] if edge["target"]["node"] != "translate"
    ]
    for node in graph["nodes"]:
        if node["type"] == "transcribe":
            node["options"] = {
                "batch_policy": "bounded_60s_v1",
                "max_model_calls": str(max_calls),
            }
    definition = runtime.save_definition(owner, uuid4().hex, graph)
    original = runtime.ingest(owner, filename, movie)
    ticket = runtime.create(
        owner,
        original["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "ko"},
    )
    plan = runtime.plan(owner, ticket["id"])
    assert plan["ready"], plan["reasons"]
    consent = runtime.confirm(owner, ticket["id"], plan["token"], uuid4().hex)
    runtime.admit(owner, ticket["id"], consent["id"], uuid4().hex)
    for _ in range(2):
        command = runtime.claim_next(owner, ticket["id"])
        result = runtime.execute_command(owner, command)
        assert result["status"] == "completed"
        runtime.accept(owner, command, result)
    command = runtime.claim_next(owner, ticket["id"])
    assert command["agent"]["id"] == "transcribe" and "transcription" in command
    return runtime, owner, command


def test_chunk_intent_is_committed_before_outbound_and_completed_reference_is_reused(
    db, admin, movie, tmp_path
):
    assert callable(ModelBatchLedger)
    runtime, owner, command = formal_attempt(db, admin, movie, tmp_path)
    pin = command["transcription"]["candidates"][0]
    context = {
        "version": 1,
        "role": "transcription",
        "source_sha256": command["inputs"]["audio"]["sha256"],
        "input_sha256": command["inputs"]["audio"]["sha256"],
        "clock_sha256": command["inputs"]["timeline"]["sha256"],
        "span_unit": "pcm_frame",
        "span_start": 0,
        "span_end": 9600,
        "source_language": "en",
        "target_language": None,
        "candidates": command["transcription"]["candidates"],
    }
    ledger = ModelBatchLedger(runtime.database, owner, command, max_calls=3)
    output = runtime.store.put(
        owner,
        [canonical([{"start": 0.1, "end": 0.4, "text": "controlled ledger output"}])],
        "transcript",
    )
    with ledger.chunk(
        context, verify=lambda reference: runtime.store.read(owner, reference)
    ) as chunk:
        assert chunk.output is None
        call_id = chunk.start(0, pin)
        with db.connection() as reader:
            intent = reader.execute(
                "SELECT status,model_id,model_revision FROM model_chunk_attempts WHERE owner_id=%s AND call_id=%s",
                (owner, call_id),
            ).fetchone()
            budget = reader.execute(
                "SELECT issued_count FROM model_call_budgets WHERE owner_id=%s AND job_id=%s AND node_run_id=%s",
                (owner, command["run_id"], command["attempt_id"]),
            ).fetchone()
        assert intent == {
            "status": "started",
            "model_id": pin["model_id"],
            "model_revision": pin["revision"],
        }
        assert budget["issued_count"] == 1
        chunk.complete(output, pin)
    with ledger.chunk(
        context, verify=lambda reference: runtime.store.read(owner, reference)
    ) as cached:
        assert (
            cached.output == output and cached.selected["model_id"] == pin["model_id"]
        )
        assert json.loads(runtime.store.read(owner, cached.output))
    assert ledger.call_count() == 1
    assert hashlib.sha256(canonical(context)).hexdigest() == digest(context)


def test_orphaned_intent_is_durably_unknown_and_never_automatically_recalled(
    db, admin, movie, tmp_path
):
    runtime, owner, command = formal_attempt(db, admin, movie, tmp_path)
    pin = command["transcription"]["candidates"][0]
    context = {
        "version": 1,
        "role": "transcription",
        "source_sha256": command["inputs"]["audio"]["sha256"],
        "input_sha256": command["inputs"]["audio"]["sha256"],
        "clock_sha256": command["inputs"]["timeline"]["sha256"],
        "span_unit": "pcm_frame",
        "span_start": 0,
        "span_end": 9600,
        "source_language": "en",
        "target_language": None,
        "candidates": command["transcription"]["candidates"],
    }
    ledger = ModelBatchLedger(db, owner, command, max_calls=3)
    with ledger.chunk(
        context, verify=lambda ref: runtime.store.read(owner, ref)
    ) as chunk:
        call = chunk.start(0, pin)
        # Crash-equivalent gap after durable intent: no proof whether bytes left.
    with (
        pytest.raises(Conflict, match="불명"),
        ledger.chunk(context, verify=lambda ref: runtime.store.read(owner, ref)),
    ):
        pytest.fail("an unknown intent must not reach a new model invocation")
    with db.connection() as reader:
        status = reader.execute(
            "SELECT status FROM model_chunk_attempts WHERE owner_id=%s AND call_id=%s",
            (owner, call),
        ).fetchone()["status"]
        cache = reader.execute(
            "SELECT status FROM model_chunk_cache WHERE owner_id=%s", (owner,)
        ).fetchone()["status"]
    assert status == "unknown" and cache == "held"
    assert ledger.call_count() == 1


def test_live_guard_never_classifies_an_active_http_intent_as_orphaned(
    db, admin, movie, tmp_path
):
    runtime, owner, command = formal_attempt(db, admin, movie, tmp_path)
    context = {
        "role": "transcription",
        "candidates": command["transcription"]["candidates"],
        "source_sha256": command["inputs"]["audio"]["sha256"],
        "input_sha256": command["inputs"]["audio"]["sha256"],
        "clock_sha256": command["inputs"]["timeline"]["sha256"],
        "span_unit": "pcm_frame",
        "span_start": 0,
        "span_end": 9600,
    }
    ledger = ModelBatchLedger(db, owner, command, max_calls=3)
    with ledger.chunk(
        context, verify=lambda ref: runtime.store.read(owner, ref)
    ) as active:
        call = active.start(0, context["candidates"][0])
        with (
            pytest.raises(Conflict, match="진행 중"),
            ledger.chunk(context, verify=lambda ref: runtime.store.read(owner, ref)),
        ):
            pytest.fail("a second live guard must not enter")
        with db.connection() as reader:
            assert (
                reader.execute(
                    "SELECT status FROM model_chunk_attempts WHERE owner_id=%s AND call_id=%s",
                    (owner, call),
                ).fetchone()["status"]
                == "started"
            )


def test_result_commit_failure_preserves_original_intent_and_holds_without_recharge(
    db, admin, movie, tmp_path
):
    import psycopg

    runtime, owner, command = formal_attempt(db, admin, movie, tmp_path)
    context = {
        "role": "transcription",
        "candidates": command["transcription"]["candidates"],
        "source_sha256": command["inputs"]["audio"]["sha256"],
        "input_sha256": command["inputs"]["audio"]["sha256"],
        "clock_sha256": command["inputs"]["timeline"]["sha256"],
        "span_unit": "pcm_frame",
        "span_start": 0,
        "span_end": 9600,
    }
    ledger = ModelBatchLedger(db, owner, command, max_calls=3)
    with db.connection() as fixture:
        fixture.execute(
            "CREATE FUNCTION reject_fixture_model_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.status='completed' THEN RAISE EXCEPTION 'controlled deferred model commit failure'; END IF; RETURN NEW; END $$"
        )
        fixture.execute(
            "CREATE CONSTRAINT TRIGGER reject_fixture_model_commit AFTER UPDATE ON model_chunk_cache DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reject_fixture_model_commit()"
        )
    reference = runtime.store.put(
        owner,
        [
            canonical(
                [
                    {
                        "start": 0.1,
                        "end": 0.4,
                        "text": "controlled result before lost commit",
                    }
                ]
            )
        ],
        "transcript",
    )
    with (
        pytest.raises(psycopg.Error),
        ledger.chunk(
            context, verify=lambda ref: runtime.store.read(owner, ref)
        ) as chunk,
    ):
        chunk.start(0, context["candidates"][0])
        chunk.complete(reference, context["candidates"][0])
    with (
        pytest.raises(Conflict, match="불명"),
        ledger.chunk(context, verify=lambda ref: runtime.store.read(owner, ref)),
    ):
        pytest.fail("a lost result commit may not issue a second HTTP request")
    assert ledger.call_count() == 1
    assert runtime.store.read(owner, reference), (
        "unadopted content is preserved, not deleted or called normal completion"
    )
    with db.connection() as reader:
        assert (
            reader.execute(
                "SELECT status FROM model_chunk_cache WHERE owner_id=%s", (owner,)
            ).fetchone()["status"]
            == "held"
        )


def test_known_failure_is_settled_once_and_retained_for_ordered_fallback(
    db, admin, movie, tmp_path
):
    runtime, owner, command = formal_attempt(db, admin, movie, tmp_path)
    context = {
        "role": "transcription",
        "candidates": command["transcription"]["candidates"],
        "source_sha256": command["inputs"]["audio"]["sha256"],
        "input_sha256": command["inputs"]["audio"]["sha256"],
        "clock_sha256": command["inputs"]["timeline"]["sha256"],
        "span_unit": "pcm_frame",
        "span_start": 0,
        "span_end": 9600,
    }
    ledger = ModelBatchLedger(db, owner, command, max_calls=3)
    with ledger.chunk(
        context, verify=lambda ref: runtime.store.read(owner, ref)
    ) as chunk:
        chunk.start(0, context["candidates"][0])
        assert callable(getattr(chunk, "fail", None))
        chunk.fail("upstream_failure")
    with ledger.chunk(
        context, verify=lambda ref: runtime.store.read(owner, ref)
    ) as resumed:
        assert (
            resumed.attempts[0]["status"] == "failed"
            and resumed.attempts[0]["error_code"] == "upstream_failure"
        )
        with pytest.raises(Conflict, match="반복"):
            resumed.start(0, context["candidates"][0])
    assert ledger.call_count() == 1


def test_first_intent_commit_failure_enters_no_external_sender_and_reserves_no_spend(
    db, admin, movie, tmp_path
):
    import psycopg

    runtime, owner, command = formal_attempt(db, admin, movie, tmp_path)
    context = {
        "role": "transcription",
        "candidates": command["transcription"]["candidates"],
        "source_sha256": command["inputs"]["audio"]["sha256"],
        "input_sha256": command["inputs"]["audio"]["sha256"],
        "clock_sha256": command["inputs"]["timeline"]["sha256"],
        "span_unit": "pcm_frame",
        "span_start": 0,
        "span_end": 9600,
    }
    ledger = ModelBatchLedger(db, owner, command, max_calls=3)
    with db.connection() as fixture:
        fixture.execute(
            "CREATE FUNCTION reject_fixture_intent_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'controlled deferred intent commit failure'; END $$"
        )
        fixture.execute(
            "CREATE CONSTRAINT TRIGGER reject_fixture_intent_commit AFTER INSERT ON model_chunk_attempts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reject_fixture_intent_commit()"
        )
    entered = []
    with (
        pytest.raises(psycopg.Error),
        ledger.chunk(
            context, verify=lambda ref: runtime.store.read(owner, ref)
        ) as chunk,
    ):
        chunk.start(0, context["candidates"][0])
        entered.append("external_call")
    assert entered == [] and ledger.call_count() == 0
    with db.connection() as reader:
        assert (
            reader.execute(
                "SELECT count(*) AS count FROM model_chunk_attempts WHERE owner_id=%s",
                (owner,),
            ).fetchone()["count"]
            == 0
        )
        assert (
            reader.execute(
                "SELECT status FROM model_chunk_cache WHERE owner_id=%s", (owner,)
            ).fetchone()["status"]
            == "prepared"
        )


def test_budget_is_monotonic_and_cannot_be_silently_increased_for_the_same_formal_request(
    db, admin, movie, tmp_path
):
    from video_service.postgres.model_batches import ModelCallBudgetExceeded

    runtime, owner, command = formal_attempt(db, admin, movie, tmp_path, max_calls=1)
    context = {
        "role": "transcription",
        "candidates": command["transcription"]["candidates"],
        "source_sha256": command["inputs"]["audio"]["sha256"],
        "input_sha256": command["inputs"]["audio"]["sha256"],
        "clock_sha256": command["inputs"]["timeline"]["sha256"],
        "span_unit": "pcm_frame",
        "span_start": 0,
        "span_end": 4800,
    }
    ledger = ModelBatchLedger(db, owner, command, max_calls=1)
    reference = runtime.store.put(
        owner,
        [
            canonical(
                [{"start": 0, "end": 0.1, "text": "completed first budgeted chunk"}]
            )
        ],
        "transcript",
    )
    with ledger.chunk(
        context, verify=lambda ref: runtime.store.read(owner, ref)
    ) as first:
        first.start(0, context["candidates"][0])
        first.complete(reference, context["candidates"][0])
    later = {**context, "span_start": 4800, "span_end": 9600}
    with (
        pytest.raises(ModelCallBudgetExceeded),
        ledger.chunk(
            later, verify=lambda ref: runtime.store.read(owner, ref)
        ) as next_chunk,
    ):
        next_chunk.start(0, context["candidates"][0])
    assert ledger.call_count() == 1
    with pytest.raises(ValueError, match="frozen"):
        ModelBatchLedger(db, owner, command, max_calls=2)


def test_first_chunk_budget_must_match_the_formal_immutable_request_not_a_worker_argument(
    db, admin, movie, tmp_path
):
    _runtime, owner, command = formal_attempt(db, admin, movie, tmp_path)
    with pytest.raises(ValueError, match="frozen"):
        ModelBatchLedger(db, owner, command, max_calls=2)
    with db.connection() as reader:
        assert (
            reader.execute(
                "SELECT count(*) AS count FROM model_call_budgets WHERE owner_id=%s",
                (owner,),
            ).fetchone()["count"]
            == 0
        )


@pytest.mark.parametrize(
    "changed",
    [
        {"source_language": "ja"},
        {"source_sha256": "f" * 64},
        {"clock_sha256": "e" * 64},
        {"span_unit": "seconds"},
    ],
)
def test_chunk_cannot_change_frozen_language_source_or_pcm_clock(
    db, admin, movie, tmp_path, changed
):
    runtime, owner, command = formal_attempt(db, admin, movie, tmp_path)
    context = {
        "role": "transcription",
        "candidates": command["transcription"]["candidates"],
        "source_sha256": command["inputs"]["audio"]["sha256"],
        "input_sha256": command["inputs"]["audio"]["sha256"],
        "clock_sha256": command["inputs"]["timeline"]["sha256"],
        "span_unit": "pcm_frame",
        "span_start": 0,
        "span_end": 9600,
        "source_language": "en",
        "target_language": None,
    }
    ledger = ModelBatchLedger(db, owner, command, max_calls=3)
    with (
        pytest.raises(ValueError, match="frozen_chunk"),
        ledger.chunk(
            {**context, **changed}, verify=lambda ref: runtime.store.read(owner, ref)
        ),
    ):
        pass
    assert ledger.call_count() == 0


def test_lost_owned_guard_session_is_fenced_before_external_http(
    db, admin, movie, tmp_path
):
    import psycopg

    runtime, owner, command = formal_attempt(db, admin, movie, tmp_path)
    context = {
        "role": "transcription",
        "candidates": command["transcription"]["candidates"],
        "source_sha256": command["inputs"]["audio"]["sha256"],
        "input_sha256": command["inputs"]["audio"]["sha256"],
        "clock_sha256": command["inputs"]["timeline"]["sha256"],
        "span_unit": "pcm_frame",
        "span_start": 0,
        "span_end": 9600,
    }
    ledger = ModelBatchLedger(db, owner, command, max_calls=3)
    entered = []
    with (
        pytest.raises(psycopg.Error),
        ledger.chunk(
            context, verify=lambda ref: runtime.store.read(owner, ref)
        ) as chunk,
    ):
        assert callable(getattr(chunk, "before_http", None))
        chunk.start(0, context["candidates"][0])
        with db.connection() as operator:
            assert operator.execute(
                "SELECT pg_terminate_backend(%s) AS terminated",
                (chunk.db.info.backend_pid,),
            ).fetchone()["terminated"]
        chunk.before_http()
        entered.append("external_http")
    assert entered == [] and ledger.call_count() == 1
    with (
        pytest.raises(Conflict, match="불명"),
        ledger.chunk(context, verify=lambda ref: runtime.store.read(owner, ref)),
    ):
        pytest.fail("lost owner intent may not be retried")
