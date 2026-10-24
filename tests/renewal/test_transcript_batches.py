"""Batched translation keeps literal IDs/order/timing; no outbound calls."""

from itertools import chain

try:
    from video_service.transcript_batches import split_transcript
except ModuleNotFoundError as error:
    if error.name != "video_service.transcript_batches":
        raise
    split_transcript = None

from video_service.cpu_agents import canonical


def test_translation_batches_preserve_all_ids_order_times_and_existing_wire_limits():
    assert callable(split_transcript)
    source = [
        {
            "id": "subtitle-" + str(index),
            "start": index * 2,
            "end": index * 2 + 1,
            "text": "긴 자막 " * 90,
        }
        for index in range(251)
    ]
    batches = list(split_transcript(source))
    assert batches[0].start == 0 and batches[-1].end == len(source)
    assert list(chain.from_iterable(batch.segments for batch in batches)) == source
    for batch in batches:
        assert len(batch.segments) <= 100
        assert len(canonical(batch.segments)) <= 16000
        assert batch.end - batch.start == len(batch.segments)
