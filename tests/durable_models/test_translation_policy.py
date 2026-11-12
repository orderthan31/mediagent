import json

import pytest

from video_service.canonical import canonical
from video_service.transcript_batches import split_transcript, validate_source


def test_v2_empty_source_is_zero_batches_and_v1_still_rejects():
    assert validate_source([], policy_version=2) == []
    assert list(split_transcript([], policy_version=2)) == []
    with pytest.raises(ValueError):
        validate_source([])


def test_v2_expansion_uses_output_limits_and_keeps_input_wire_bounded():
    from video_service.translation_output import decode_output

    source = [{"id": 1, "start": 0, "end": 1, "speaker": "A", "text": "hi"}]
    text = "한국어字幕🌏" * 1800
    translated = decode_output(json.dumps([text], ensure_ascii=False), source)
    assert translated == [{**source[0], "text": text}]
    assert len(canonical(translated)) > 16000
    with pytest.raises(ValueError):
        list(split_transcript(translated, policy_version=2))


def test_output_finite_row_batch_document_and_packet_limits():
    from video_service.translation_output import (
        OutputCapacityError, decode_output, validate_output, validate_packet,
    )

    source = [{"start": 0, "end": 1, "text": "hi"}]
    with pytest.raises(OutputCapacityError, match="row"):
        decode_output(json.dumps(["한" * 22000], ensure_ascii=False), source)
    with pytest.raises(OutputCapacityError, match="response"):
        decode_output(" " * 262145, source)
    with pytest.raises(ValueError, match="identity"):
        validate_output([{**source[0], "start": 0.0}], source)
    with pytest.raises(ValueError):
        decode_output('["   "]', source)
    with pytest.raises(OutputCapacityError, match="packet"):
        validate_packet({"trace": "x" * (16 * 1024 * 1024)})


def test_batch_and_document_limits_include_row_metadata():
    from video_service.translation_output import OutputCapacityError, validate_output

    source = [{"id": str(i), "start": i, "end": i + 1, "speaker": "A", "text": "x"} for i in range(350)]
    rows = [{**r, "text": "x" * 50000} for r in source]
    with pytest.raises(OutputCapacityError, match="batch"):
        validate_output(rows[:6], source[:6], batch=True)
    with pytest.raises(OutputCapacityError, match="document"):
        validate_output(rows, source)


@pytest.mark.parametrize("change", [{"id": "1"}, {"start": 0.0}, {"end": 2}, {"speaker": "B"}])
def test_output_preserves_literal_ids_times_and_speaker(change):
    from video_service.translation_output import validate_output

    source = [{"id": 1, "start": 0, "end": 1, "speaker": "A", "text": "hi"}]
    with pytest.raises(ValueError, match="identity"):
        validate_output([{**source[0], **change, "text": "번역"}], source)
