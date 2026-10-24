"""Explicit packed projection must split, not bridge removed source intervals."""

import importlib
import importlib.util

module = (
    importlib.import_module("video_service.packed_projection")
    if importlib.util.find_spec("video_service.packed_projection")
    else None
)


def test_crossing_cue_repeats_full_text_and_traces_original_literal_id():
    assert callable(getattr(module, "project", None))
    spans = [
        {"source_start": 1, "source_end": 2, "packed_start": 0, "packed_end": 1},
        {"source_start": 4, "source_end": 5, "packed_start": 1, "packed_end": 2},
    ]
    original = [
        {"id": 7, "start": 0.5, "end": 1.5, "text": "whole sentence", "speaker": "A"}
    ]
    projected, trace = module.project(original, spans)
    assert [(r["start"], r["end"]) for r in projected] == [(1.5, 2), (4, 4.5)]
    assert [r["text"] for r in projected] == ["whole sentence", "whole sentence"]
    assert all(r["speaker"] == "A" for r in projected)
    assert len({r["id"] for r in projected}) == 2
    assert trace["rows"][0]["packed_segment"] == original[0]
    assert trace["rows"][0]["text_policy"] == "repeat-full-sentence-on-each-piece"
    assert [p["output_id"] for p in trace["rows"][0]["pieces"]] == [
        r["id"] for r in projected
    ]
    assert module.project(original, spans) == (projected, trace)


def test_new_projection_clock_rejects_a_one_frame_overlap_old_validator_tolerated():
    import pytest

    spans = [
        {"source_start": 0, "source_end": 1, "packed_start": 0, "packed_end": 1},
        {
            "source_start": 2,
            "source_end": 3,
            "packed_start": 1 - 1 / 16000,
            "packed_end": 2 - 1 / 16000,
        },
    ]
    with pytest.raises(ValueError):
        module.project([{"start": 0.5, "end": 1.5, "text": "gap"}], spans)


def test_duplicate_literal_parent_ids_cannot_be_hidden_by_split_child_ids():
    import pytest

    spans = [
        {
            "source_start": i * 3,
            "source_end": i * 3 + 1,
            "packed_start": i,
            "packed_end": i + 1,
        }
        for i in range(4)
    ]
    with pytest.raises(ValueError, match="duplicate"):
        module.project(
            [
                {"id": 7, "start": 0.5, "end": 1.5, "text": "a"},
                {"id": 7, "start": 2.5, "end": 3.5, "text": "b"},
            ],
            spans,
        )


def test_contiguous_source_spans_merge_and_keep_the_literal_id():
    spans = [
        {"source_start": 1, "source_end": 2, "packed_start": 0, "packed_end": 1},
        {"source_start": 2, "source_end": 3, "packed_start": 1, "packed_end": 2},
    ]
    rows, trace = module.project(
        [{"id": "007", "start": 0.5, "end": 1.5, "text": "literal"}], spans
    )
    assert rows == [{"id": "007", "start": 1.5, "end": 2.5, "text": "literal"}]
    assert trace["rows"][0]["pieces"][0]["span_indices"] == [0, 1]


def test_submillisecond_piece_is_explicitly_traced_not_silently_bridged():
    spans = [
        {"source_start": 0, "source_end": 1, "packed_start": 0, "packed_end": 1},
        {"source_start": 2, "source_end": 3, "packed_start": 1, "packed_end": 2},
    ]
    rows, trace = module.project(
        [{"start": 0.9999, "end": 1.001, "text": "tiny boundary"}], spans
    )
    assert len(rows) == 1 and rows[0]["start"] == 2
    assert [p["status"] for p in trace["rows"][0]["pieces"]] == [
        "dropped_submillisecond",
        "emitted",
    ]
