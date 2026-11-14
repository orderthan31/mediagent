"""Pure recovery: frozen receipts, no cache/client/store execution."""
import copy
import hashlib
import io
import json
import wave

import pytest

from video_service.canonical import canonical, digest
from video_service.role_receipts import speech_chunks
from video_service.transcript_batches import split_transcript
from video_service.unit_recovery import build_manifest, preview_decisions, assemble_resolutions


def fixture(role="transcription", width=1):
    task = dict(version=2, role_policy_version=2, task_id="a" * 32, role=role,
                models=[dict(model_id=str(i) * 32, revision=1, pin_sha256="b" * 64) for i in range(width)],
                source_language="en", max_calls=3 * width)
    if role == "transcription":
        stream = io.BytesIO()
        with wave.open(stream, "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "NONE"))
            wav.writeframes(b"\0\0" * 48000)
        source = stream.getvalue()
        task.update(audio=dict(bytes=len(source), sha256=hashlib.sha256(source).hexdigest()), chunk_frames=16000,
                    timeline=[dict(source_start=10, source_end=11, packed_start=0, packed_end=1),
                              dict(source_start=20, source_end=22, packed_start=1, packed_end=3)])
        units = speech_chunks(task, source)
    else:
        source = [dict(id=i, start=i * 2, end=i * 2 + 1, text="source", speaker="A") for i in range(201)]
        task.update(transcript=dict(bytes=len(canonical(source)), sha256=digest(source)),
                    target_language="ko", batch_policy="bounded_100x16k_v1")
        units = list(split_transcript(source, policy_version=2))
    return task, source, units


def call(task, units, index, status="completed", candidate=0):
    response = ([dict(start=0, end=0.5, text="heard")] if task["role"] == "transcription"
                else json.dumps(["translated"] * len(units[index].segments)))
    return dict(task_id=task["task_id"], chunk_index=index * len(task["models"]) + candidate,
                model=copy.deepcopy(task["models"][candidate]), input_sha256=units[index].sha256,
                status=status, error_code="invalid_response" if status == "failed" else None,
                response=response if status == "completed" else None)


@pytest.mark.parametrize("role", ["transcription", "translation"])
def test_reuse_retry_skip_and_purity(role):
    task, source, units = fixture(role)
    calls = [call(task, units, 0), call(task, units, 1, "failed")]
    before = copy.deepcopy((task, source, calls))
    manifest = build_manifest(task, source, calls)
    assert [u["status"] for u in manifest["units"]] == ["succeeded", "failed", "unattempted"]
    assert manifest["manifest_sha256"] == digest({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    decisions = [dict(unit_index=1, action="retry"), dict(unit_index=2, action="skip")]
    preview = preview_decisions(manifest, decisions)
    assert preview["ready"] and preview["additional_call_limit"] == 1
    assert [u["index"] for u in preview["execution_units"]] == [1]
    result = assemble_resolutions(manifest, decisions, {"1": call(task, units, 1)["response"]})
    assert result["resolution_manifest"]["counts"] == dict(reused=1, model_retry=1, manual=0, skipped=1)
    if role == "transcription":
        assert [r["start"] for r in result["segments"]] == [10, 20]
        assert [r["start"] for r in result["packed_segments"]] == [0, 1]
    else:
        assert [r["id"] for r in result["segments"]] == list(range(200))
    assert (task, source, calls) == before


@pytest.mark.parametrize("role", ["transcription", "translation"])
def test_manual_skip_and_unresolved(role):
    task, source, units = fixture(role)
    manifest = build_manifest(task, source, [])
    value = ([dict(start=0.1, end=0.9, text="manual")] if role == "transcription"
             else [{**r, "text": "manual"} for r in units[1].segments])
    decisions = [dict(unit_index=1, action="manual", value=value), dict(unit_index=0, action="skip")]
    assert not preview_decisions(manifest, decisions)["ready"]
    decisions.append(dict(unit_index=2, action="skip"))
    result = assemble_resolutions(manifest, decisions)
    assert result["resolution_manifest"]["counts"]["manual"] == 1
    assert all(r["text"] == "manual" for r in result["segments"])
    assert result["segments"][0]["start"] == (20.1 if role == "transcription" else 200)
    with pytest.raises(ValueError, match="empty"):
        assemble_resolutions(manifest, [dict(unit_index=i, action="skip") for i in range(3)])


@pytest.mark.parametrize("status,expected", [("started", "active"), ("unknown", "unknown")])
def test_ambiguous_evidence_blocks(status, expected):
    task, source, units = fixture()
    manifest = build_manifest(task, source, [call(task, units, 0, status)])
    assert manifest["units"][0]["status"] == expected
    assert manifest["units"][0]["allowed_actions"] == []
    assert not preview_decisions(manifest, [dict(unit_index=0, action="skip")])["ready"]


@pytest.mark.parametrize("role", ["transcription", "translation"])
@pytest.mark.parametrize("fault", ["sha", "pin", "predecessor", "invalid_output", "task_binding"])
def test_invalid_receipt_is_blocked(fault, role):
    task, source, units = fixture(role, width=2)
    receipt = call(task, units, 0, candidate=1 if fault == "predecessor" else 0)
    if fault == "sha": receipt["input_sha256"] = "0" * 64
    if fault == "pin": receipt["model"]["pin_sha256"] = "0" * 64
    if fault == "invalid_output": receipt["response"] = [{"text": "untimed"}]
    if fault == "task_binding": receipt["task_id"] = "c" * 32
    manifest = build_manifest(task, source, [receipt])
    assert manifest["units"][0]["status"] == "evidence_invalid"
    assert not preview_decisions(manifest, [])["ready"]


def test_fallback_and_success_not_overridable():
    task, source, units = fixture(width=2)
    manifest = build_manifest(task, source, [call(task, units, 0, "failed"), call(task, units, 0, candidate=1)])
    assert manifest["units"][0]["status"] == "succeeded"
    assert not preview_decisions(manifest, [dict(unit_index=0, action="retry")])["ready"]


@pytest.mark.parametrize("role", ["transcription", "translation"])
def test_source_budget_legacy_errors(role):
    task, source, units = fixture(role)
    changed = copy.deepcopy(task)
    changed["audio" if role == "transcription" else "transcript"]["sha256"] = "0" * 64
    with pytest.raises(ValueError): build_manifest(changed, source, [])
    task["max_calls"] = 0
    with pytest.raises(ValueError): build_manifest(task, source, [call(task, units, 0)])
    task["version"] = 1
    with pytest.raises(ValueError, match="legacy"): build_manifest(task, source, [])


@pytest.mark.parametrize("fault", ["id", "time", "speaker", "order", "empty"])
def test_mt_manual_exact_identity(fault):
    task, source, units = fixture("translation")
    manifest = build_manifest(task, source, [])
    value = copy.deepcopy(units[0].segments)
    if fault == "id": value[0]["id"] = "changed"
    if fault == "time": value[0]["start"] = 0.1
    if fault == "speaker": value[0]["speaker"] = "B"
    if fault == "order": value.reverse()
    if fault == "empty": value = []
    assert not preview_decisions(manifest, [dict(unit_index=0, action="manual", value=value)])["ready"]


def test_asr_manual_bounds_and_unknown_fields():
    task, source, _ = fixture()
    manifest = build_manifest(task, source, [])
    for value in [[dict(start=0, end=2, text="outside")], [dict(start=0, end=1, text="x", id="invented")]]:
        assert not preview_decisions(manifest, [dict(unit_index=0, action="manual", value=value)])["ready"]


def test_projection_split_ids_stable_across_other_unit_omission():
    task, source, units = fixture()
    task["timeline"] = [dict(source_start=10, source_end=10.5, packed_start=0, packed_end=0.5),
                        dict(source_start=20, source_end=22.5, packed_start=0.5, packed_end=3)]
    receipt = call(task, units, 0)
    receipt["response"] = [dict(start=0, end=1, text="crosses gap")]
    manifest = build_manifest(task, source, [receipt, call(task, units, 1, "failed")])
    skipped = assemble_resolutions(manifest, [dict(unit_index=1, action="skip"), dict(unit_index=2, action="skip")])
    manual = assemble_resolutions(manifest, [dict(unit_index=1, action="manual", value=[dict(start=0, end=1, text="new")]), dict(unit_index=2, action="skip")])
    assert [r["id"] for r in skipped["segments"]] == [r["id"] for r in manual["segments"][:2]]
    assert [(r["start"], r["end"]) for r in skipped["segments"]] == [(10, 10.5), (20, 20.5)]


@pytest.mark.parametrize("role", ["transcription", "translation"])
@pytest.mark.parametrize("status", ["started", "unknown", "completed"])
def test_fallback_cannot_follow_nonfailure(role, status):
    task, source, units = fixture(role, width=2)
    manifest = build_manifest(task, source, [call(task, units, 0, status), call(task, units, 0, candidate=1)])
    assert manifest["units"][0]["status"] == "evidence_invalid"


def test_retry_exact_candidate_and_result_scope():
    task, source, _ = fixture(width=2)
    manifest = build_manifest(task, source, [])
    decisions = [dict(unit_index=0, action="retry", candidate_index=1), dict(unit_index=1, action="skip"), dict(unit_index=2, action="skip")]
    preview = preview_decisions(manifest, decisions)
    assert preview["models"] == [task["models"][1]]
    assert preview["additional_call_limit"] == 1
    with pytest.raises(ValueError): assemble_resolutions(manifest, decisions, {})
    with pytest.raises(ValueError): assemble_resolutions(manifest, decisions, {"0": [], "1": []})
    manifest["units"][0]["status"] = "succeeded"
    with pytest.raises(ValueError, match="manifest"): preview_decisions(manifest, decisions)
