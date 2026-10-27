from video_service.audio_contract import timed_segments
from video_service.packed_projection import project


def test_silence_is_a_valid_transcription_result():
    assert timed_segments([], 1) == []


def test_overlapping_speakers_survive_projection():
    rows = [
        {"start": 0.0, "end": 1.0, "text": "A", "speaker": "one"},
        {"start": 0.5, "end": 1.5, "text": "B", "speaker": "two"},
    ]
    result, trace = project(
        rows,
        [{"packed_start": 0, "packed_end": 2, "source_start": 10, "source_end": 12}],
    )
    assert [(r["start"], r["end"], r.get("speaker")) for r in result] == [
        (10.0, 11.0, "one"),
        (10.5, 11.5, "two"),
    ]
