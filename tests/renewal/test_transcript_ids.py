"""Literal subtitle IDs survive timing/text transformations, without cap changes."""

from video_service.cpu_agents import canonical
from video_service.transcript_input import parse_segments


def test_literal_subtitle_ids_survive_parse_text_and_clock_changes():
    rows = [
        {"id": "cue-001", "start": 0, "end": 1, "text": "first"},
        {"id": 2, "start": 2, "end": 3, "text": "second", "speaker": "A"},
    ]
    parsed = parse_segments(canonical(rows))
    assert [row.to_dict() for row in parsed] == rows
    assert parsed[0].with_times(start=3, end=4).to_dict()["id"] == "cue-001"
    assert parsed[1].with_text("translated").to_dict()["id"] == 2
    assert (
        "id"
        not in parse_segments(canonical([{"start": 0, "end": 1, "text": "old"}]))[
            0
        ].to_dict()
    )
