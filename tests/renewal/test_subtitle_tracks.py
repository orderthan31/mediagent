"""Master-compatible pre-encode subtitle review limits and readable layout lineage."""

import importlib
import importlib.util

import pytest

tracks = (
    importlib.import_module("video_service.subtitle_tracks")
    if importlib.util.find_spec("video_service.subtitle_tracks")
    else None
)


def test_review_layout_uses_master_cjk_width_and_retains_literal_parent_lineage():
    assert callable(getattr(tracks, "normalize", None))
    rows, lineage = tracks.normalize(
        [{"id": 7, "start": 0, "end": 5, "text": "가" * 100}],
        language="ko",
        duration=10,
    )
    assert len(rows) > 1
    assert rows[0]["start"] == 0 and rows[-1]["end"] == 5
    assert len({row["id"] for row in rows}) == len(rows)
    assert all(
        len(row["text"].splitlines()) <= 2
        and all(len(line) <= 24 for line in row["text"].splitlines())
        for row in rows
    )
    assert lineage["rows"][0]["literal_parent_id"] == 7
    with pytest.raises(ValueError):
        tracks.normalize(
            [{"start": 0, "end": 11, "text": "x"}], language="ko", duration=10
        )
    with pytest.raises(ValueError):
        tracks.normalize(
            [{"start": 0, "end": 1, "text": "a\nb\nc"}], language="en", duration=10
        )


def test_explicit_language_branches_and_six_track_controller_contract_do_not_change_old_nodes():
    from video_service.node_contracts import node_spec, validate_node

    assert validate_node(
        {
            "node": "translate",
            "inputs": {"transcript": "transcript"},
            "options": {
                "translation_profile": "language_target_v1",
                "target_language": "pt-BR",
                "batch_policy": "bounded_100x16k_v1",
                "max_model_calls": "1",
            },
        }
    )["valid"]
    assert validate_node(
        {
            "node": "subtitle_tracks",
            "inputs": {
                "original": "transcript",
                "translated": "transcript",
                "additional_1": "transcript",
            },
            "options": {
                "original_language": "en",
                "translated_language": "ko",
                "additional_1_language": "pt-BR",
            },
        }
    )["valid"]
    assert node_spec(
        "review", {"review_kind": "subtitle_tracks_v1", "data_type": "subtitle_tracks"}
    )["outputs"] == {"value": "subtitle_tracks"}
    assert node_spec("generate_subtitle")["inputs"] == {"transcript": "transcript"}


def test_source_auto_and_extended_language_tags_keep_the_master_language_choices():
    assert tracks.language("auto", auto=True) == "auto"
    assert tracks.language("zh-Hant-TW") == "zh-Hant-TW"
    from video_service.postgres.translation import languages

    languages("auto", "zh-Hant-TW")
    with pytest.raises(ValueError):
        tracks.language("auto")
