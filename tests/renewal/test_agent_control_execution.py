"""Real isolated PostgreSQL/CAS/FFmpeg round trips for public business/control flows."""
import json
from uuid import uuid4

import pytest

from test_execution import (admin as _admin, db as _db, movie as _movie,
                            runtime as _runtime, admit)
from test_agent_control_workflow import node, edge, graph
from video_service.postgres.execution import Execution

admin, db, movie, runtime = _admin, _db, _movie, _runtime


def branching(selection="both", review=False):
    nodes = [node("choose", "select", data_type="video", selection=selection),
             node("left", "video_conversion_agent"), node("right", "video_conversion_agent"),
             node("joined", "join", left_type="video", right_type="video")]
    edges = [edge("$input", "video", "choose", "value"),
             edge("choose", "a", "left", "video"), edge("choose", "b", "right", "video"),
             edge("left", "video", "joined", "left"), edge("right", "video", "joined", "right")]
    if review:
        nodes.insert(0, node("approval", "review", data_type="video"))
        edges[0] = edge("approval", "value", "choose", "value")
        edges.append(edge("$input", "video", "approval", "value"))
    return graph(nodes, edges, video="video")


def create(runtime, owner, movie, public):
    source = runtime.ingest(owner, "controlled-cpu.mp4", movie)
    saved = runtime.save_definition(owner, uuid4().hex, public)
    assert runtime.inspect(owner, saved["id"], saved["revision"])["supported"]
    job = runtime.create(owner, source["asset_id"], saved["id"], saved["revision"], request_id=uuid4().hex)
    plan = runtime.plan(owner, job["id"])
    assert plan["ready"], plan["reasons"]
    admit(runtime, owner, job["id"])
    return source, job


@pytest.mark.parametrize("selection,count", [("a", 1), ("b", 1), ("both", 2)])
def test_selected_branches_produce_real_valid_videos_and_durable_join(runtime, admin, movie, selection, count):
    owner = admin[0]["id"]
    source, job = create(runtime, owner, movie, branching(selection))
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "completed"
    runs = {r["node_id"]: r for r in done["runs"]}
    kinds = {n["id"]: n["type"] for n in done["snapshot"]["definition"]["nodes"]}
    assert runs["choose"]["result"]["transport"] == "application_control"
    joined = runs["joined"]["result"]["outputs"]["manifest"]
    manifest = json.loads(runtime.store.read(owner, joined))
    assert len(manifest["items"]) == count
    assert len([r for r in done["runs"] if kinds[r["node_id"]] == "validate_video" and r["status"] == "completed"]) == count
    assert all(r["result"]["transport"] == "subprocess" for r in done["runs"] if kinds[r["node_id"]] in {"encode", "validate_video"} and r["status"] == "completed")
    if selection != "both":
        omitted = "right" if selection == "a" else "left"
        assert runs[omitted + "__encode"]["status"] == "skipped"
        assert omitted + "__validate_video" not in runs
        view = next(n for n in done["agent_workflow"]["nodes"] if n["id"] == omitted)
        assert view["state"] == "skipped"
    reopened = Execution(runtime.database, runtime.store).get(owner, job["id"])
    assert reopened["status"] == "completed" and reopened["snapshot_sha256"] == job["snapshot_sha256"]
    assert reopened["runs"] == done["runs"]
    assert runtime.run_local(owner, job["id"])["runs"] == done["runs"]
    assert runtime.store.read(owner, done["snapshot"]["inputs"]["video"]) == movie


def test_public_review_preserves_approval_and_requires_new_admission_after_confirmation(runtime, admin, movie):
    owner = admin[0]["id"]
    _source, job = create(runtime, owner, movie, branching("a", review=True))
    paused = runtime.run_local(owner, job["id"])
    assert paused["status"] == "review_required"
    kinds = {n["id"]: n["type"] for n in paused["snapshot"]["definition"]["nodes"]}
    assert not any(kinds[r["node_id"]] == "encode" for r in paused["runs"])
    task = paused["reviews"][0]
    saved = runtime.review_save(owner, task["id"], task["revision"], {"approved": True})
    runtime.review_confirm(owner, task["id"], saved["revision"])
    assert runtime.run_local(owner, job["id"])["status"] == "review_required"
    admit(runtime, owner, job["id"])
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "completed"
    assert done["reviews"][0]["status"] == "confirmed"
    assert len([r for r in done["runs"] if r["node_id"] == "approval"]) == 1


def test_failed_selected_branch_blocks_join_but_retains_the_completed_independent_video(runtime, admin, movie, monkeypatch, tmp_path):
    owner = admin[0]["id"]
    _source, job = create(runtime, owner, movie, branching("both"))
    command = runtime.claim_next(owner, job["id"])
    assert command["agent"]["id"] == "encode"
    failed_node = next(r["node_id"] for r in runtime.get(owner, job["id"])["runs"] if r["id"] == command["attempt_id"])
    # A real isolated worker with a missing executable, not a fabricated provider receipt.
    empty_path = tmp_path / "no-media-executables"
    empty_path.mkdir()
    with monkeypatch.context() as env:
        env.setenv("PATH", str(empty_path))
        result = runtime.execute_command(owner, command)
    assert result["status"] == "failed"
    assert result["transport"] == "subprocess"
    runtime.accept(owner, command, result)
    assert runtime.execute_command(owner, command) == result
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "failed"
    runs = {r["node_id"]: r for r in done["runs"]}
    assert runs["joined"]["status"] == "blocked"
    assert not (runs["joined"].get("result") or {}).get("outputs")
    healthy = "right" if failed_node == "left__encode" else "left"
    assert runs[healthy + "__validate_video"]["status"] == "completed"
    goal = next(n for n in done["agent_workflow"]["nodes"] if n["id"] == healthy)
    assert goal["state"] == "completed" and goal["outputs"]
    assert sum(r["node_id"] == failed_node for r in done["runs"]) == 1


def test_reviewed_srt_is_burned_into_real_video_after_explicit_new_admission(runtime, admin, movie):
    import subprocess
    owner = admin[0]["id"]
    public = graph([node("files", "subtitle_file_agent"), node("approval", "review", data_type="subtitle"), node("render", "subtitle_video_agent", subtitle_source="selected_subtitles")],
        [edge("$input", "transcript", "files", "transcript"), edge("files", "subtitles", "approval", "value"), edge("approval", "value", "render", "subtitles")], transcript="transcript")
    source = runtime.ingest(owner, "review-source.mp4", movie)
    saved = runtime.save_definition(owner, uuid4().hex, public)
    job = runtime.create(owner, source["asset_id"], saved["id"], saved["revision"], request_id=uuid4().hex,
        options={"subtitle_srt": "1\n00:00:00,000 --> 00:00:00,500\nOWNED REVIEW\n\n", "input_language": "en"})
    admit(runtime, owner, job["id"])
    paused = runtime.run_local(owner, job["id"])
    assert paused["status"] == "review_required"
    assert not any(r["node_id"] == "render__encode" for r in paused["runs"])
    task = paused["reviews"][0]
    draft = runtime.review_save(owner, task["id"], task["revision"], {"approved": True})
    runtime.review_confirm(owner, task["id"], draft["revision"])
    admit(runtime, owner, job["id"])
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "completed"
    runs = {r["node_id"]: r for r in done["runs"]}
    assert "render__generate_subtitle" not in runs
    raw = runs["files__generate_subtitle"]["result"]["outputs"]["subtitles"]
    assert runs["render__encode"]["inputs"]["subtitles"] == raw
    video = runs["render__encode"]["result"]["outputs"]["video"]
    path = runtime.store.path(owner, video)
    frame = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], timeout=20)
    import os
    from pathlib import Path
    evidence = os.environ.get("MIDEAGENT_EVIDENCE_DIR")
    if evidence:
        destination = Path(evidence)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "reviewed-cpu.mp4").write_bytes(path.read_bytes())
        (destination / "source-cpu.mp4").write_bytes(movie)
        (destination / "reviewed-source.srt").write_bytes(runtime.store.read(owner, raw))
        (destination / "reviewed-cpu.json").write_text(json.dumps({"job_id": job["id"],
            "snapshot_sha256": done["snapshot_sha256"], "video": video,
            "encode_request": runs["render__encode"]["request"],
            "max_channel": [max(frame[i::3]) for i in range(3)],
            "white_pixels": sum(all(v > 180 for v in frame[i:i + 3]) for i in range(0, len(frame), 3))}, indent=2))
    original_path = runtime.store.path(owner, done["snapshot"]["inputs"]["video"])
    source_frame = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(original_path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], timeout=20)
    neutral = lambda pixels: sum(pixels[i] > 40 and pixels[i + 1] > 40 for i in range(0, len(pixels), 3))
    assert neutral(source_frame) == 0 and neutral(frame) > 20
    assert runtime.store.read(owner, done["snapshot"]["inputs"]["video"]) == movie




def test_if_condition_controls_whole_business_goals_not_just_a_later_internal_tool(runtime, admin, movie):
    owner = admin[0]["id"]
    public = graph([node("audio", "audio_extraction_agent"), node("condition", "control_if", data_type="media_metadata", field="duration", operator="greater_than", compare_value="0"),
        node("yes", "video_conversion_agent"), node("no", "video_conversion_agent"), node("joined", "join", left_type="video", right_type="video")],
        [edge("$input", "video", "audio", "video"), edge("audio", "metadata", "condition", "value"), edge("condition", "true", "yes", "gate"), edge("condition", "false", "no", "gate"),
         edge("yes", "video", "joined", "left"), edge("no", "video", "joined", "right")], video="video")
    _source, job = create(runtime, owner, movie, public)
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "completed"
    runs = {r["node_id"]: r for r in done["runs"]}
    assert runs["no__encode"]["status"] == "skipped"
    assert "no__validate_video" not in runs
    assert runs["yes__validate_video"]["status"] == "completed"
    assert set(runs["condition"]["result"]["outputs"]) == {"true"}
    manifest = json.loads(runtime.store.read(owner, runs["joined"]["result"]["outputs"]["manifest"]))
    assert len(manifest["items"]) == 1


def test_a_business_output_cannot_start_the_next_goal_before_its_validation(runtime, admin, movie, monkeypatch, tmp_path):
    owner = admin[0]["id"]
    public = graph([node("first", "video_conversion_agent"), node("next", "video_conversion_agent")], [edge("first", "video", "next", "video")])
    _source, job = create(runtime, owner, movie, public)
    encode = runtime.claim_next(owner, job["id"])
    result = runtime.execute_command(owner, encode)
    assert result["status"] == "completed"
    runtime.accept(owner, encode, result)
    validation = runtime.claim_next(owner, job["id"])
    assert validation["agent"]["id"] == "validate_video"
    assert runtime.claim_next(owner, job["id"]) is None
    empty_path = tmp_path / "missing-validator"
    empty_path.mkdir()
    with monkeypatch.context() as env:
        env.setenv("PATH", str(empty_path))
        failure = runtime.execute_command(owner, validation)
    assert failure["status"] == "failed"
    runtime.accept(owner, validation, failure)
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "failed"
    runs = {r["node_id"]: r for r in done["runs"]}
    assert runs["next__encode"]["status"] == "blocked"
    from video_service.postgres import Conflict
    blocked = runs["next__encode"]
    with pytest.raises(Conflict):
        runtime.execute_command(owner, blocked["request"])
    with runtime.database.connection() as db:
        assert db.execute("SELECT count(*) AS n FROM agent_deliveries WHERE node_run_id=%s", (blocked["id"],)).fetchone()["n"] == 0
    assert "next__validate_video" not in runs
    assert runtime.store.path(owner, runs["first__encode"]["result"]["outputs"]["video"]).is_file()


@pytest.mark.parametrize("parallel", [False, True])
def test_audio_original_keeps_exact_normalization_pairs_with_downstream_or_parallel_goals(runtime, admin, parallel):
    import io
    import wave
    from copy import deepcopy
    from video_service.audio_original import frozen_origin
    owner = admin[0]["id"]
    raw = io.BytesIO()
    with wave.open(raw, "wb") as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
        stream.writeframes(b"\x00\x00" * 3200)
    source = runtime.ingest(owner, "original.wav", raw.getvalue())
    goals = [node("speech", "transcription_agent", audio_source="audio_file_v1"), node("files", "subtitle_file_agent")]
    edges = [edge("speech", "transcript", "files", "transcript")]
    if parallel:
        goals += [node("speech2", "transcription_agent", audio_source="audio_file_v1"), node("files2", "subtitle_file_agent")]
        edges += [edge("speech2", "transcript", "files2", "transcript")]
    public = graph(goals, edges, audio="audio")
    public["input_profile"] = "audio_file_v1"
    saved = runtime.save_definition(owner, uuid4().hex, public)
    job = runtime.create(owner, source["asset_id"], saved["id"], saved["revision"], request_id=uuid4().hex)
    assert frozen_origin(job["snapshot"])["asset_id"] == source["asset_id"]
    assert job["snapshot"]["definition"]["inputs"] == {"audio": "audio"}
    assert "video" not in job["snapshot"]["inputs"]
    assert job["status"] == "draft" and not job["runs"]
    # Model selection remains required: this test does not invent ASR/model output.
    assert not runtime.plan(owner, job["id"])["ready"]
    bad = deepcopy(job["snapshot"])
    target = next(e for e in bad["definition"]["edges"] if e["target"] == {"node": "speech__transcribe", "port": "timeline"})
    target["source"]["node"] = "speech2__preprocess_audio" if parallel else "unrelated"
    with pytest.raises(ValueError):
        frozen_origin(bad)
