"""Independent subtitle files execute through real upload, database and CPU output paths."""
import json
from uuid import uuid4

import pytest

from test_execution import admin as _admin, db as _db, runtime as _runtime, admit
from test_agent_control_workflow import node, graph
from video_service.subtitle_import import parse_sami
from video_service.subtitle_original import policy

admin, db, runtime = _admin, _db, _runtime

SRT = "1\r\n00:10:00,000 --> 00:10:02,500\r\nHello & goodbye.\r\nSecond line.\r\n\r\n"
SAMI = "<SAMI><BODY><SYNC Start=600000><P Class=ENCC>Hello &amp; goodbye.<br>Second line.<SYNC Start=602500><P>&nbsp;</BODY></SAMI>"


def text_definition():
    value = graph([node("files", "subtitle_file_agent", format="srt_smi")], [], transcript="transcript")
    value["input_profile"] = "subtitle_file_v1"
    return value


@pytest.mark.parametrize("filename,text", [("standalone.srt", SRT), ("standalone.smi", SAMI)])
def test_subtitle_original_without_any_video_registers_and_creates_real_srt_sami(runtime, admin, filename, text):
    owner = admin[0]["id"]
    source = runtime.ingest(owner, filename, text.encode("utf-8"))
    assert source["media_kind"] == "subtitle"
    assert source["subtitle_original_policy"] == policy()
    assert "web_preview" not in source
    saved = runtime.save_definition(owner, uuid4().hex, text_definition())
    job = runtime.create(owner, source["asset_id"], saved["id"], saved["revision"],
                         options={"input_language": "en"}, request_id=uuid4().hex)
    assert job["snapshot"]["definition"]["inputs"] == {"transcript": "transcript"}
    assert "video" not in job["snapshot"]["inputs"]
    assert not job["snapshot"]["model_bindings"]
    plan = runtime.plan(owner, job["id"])
    assert plan["ready"], plan["reasons"]
    admit(runtime, owner, job["id"])
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "completed"
    assert len(done["runs"]) == 1
    run = done["runs"][0]
    assert run["result"]["transport"] == "subprocess"
    outputs = run["result"]["outputs"]
    rendered = runtime.store.read(owner, outputs["subtitles"]).decode("utf-8")
    assert "00:10:00,000 --> 00:10:02,500" in rendered
    assert "Hello & goodbye.\nSecond line." in rendered
    sami = runtime.store.read(owner, outputs["sami"]).decode("utf-8")
    assert parse_sami(sami) == json.loads(runtime.store.read(owner, done["snapshot"]["inputs"]["transcript"]))
    assert runtime.store.read(owner, done["snapshot"]["inputs"]["subtitle"]) == text.encode("utf-8")
    assert runtime.get(owner, job["id"])["runs"] == done["runs"]


@pytest.mark.parametrize("body", [
    "<SAMI><BODY><SYNC Start=0><P Class=ENCC>One<SYNC Start=1000><P Class=KRCC>둘<SYNC Start=2000><P>&nbsp;",
    "<SAMI><BODY><SYNC Start=0><P>Missing end",
    "<SAMI><BODY><SYNC Start=1000><P>One<SYNC Start=500><P>&nbsp;",
    "<SAMI><BODY><SYNC Start=0><P>One<script>bad()</script><SYNC Start=1000><P>&nbsp;",
])
def test_ambiguous_or_unbounded_sami_is_rejected_without_inventing_text_or_duration(body):
    with pytest.raises(ValueError):
        parse_sami(body)
