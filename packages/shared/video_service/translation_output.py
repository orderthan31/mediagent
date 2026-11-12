"""v2 output capacity, separate from the unchanged 100-row/16000-byte input wire.

Limits count canonical UTF-8 bytes, including row metadata. The provider response
remains bounded by the adapter's 262144-byte response cap. Capacity failures are
held for revalidation/reassembly; they are never a candidate transition.
"""

import json

from .canonical import canonical
from .transcript_input import parse_segments

MAX_RESPONSE_BYTES = 262144
MAX_OUTPUT_ROW_BYTES = 65536
MAX_OUTPUT_BATCH_BYTES = 262144
MAX_OUTPUT_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_RESULT_PACKET_BYTES = 16 * 1024 * 1024


class OutputCapacityError(ValueError):
    pass


def validate_output(rows, source, *, batch=False):
    if type(rows) is not list or type(source) is not list or len(rows) != len(source):
        raise ValueError("translation_output_row_count_changed")
    if len(rows) > (100 if batch else 10000):
        raise OutputCapacityError("translation_output_row_count_capacity")
    maximum = MAX_OUTPUT_BATCH_BYTES if batch else MAX_OUTPUT_DOCUMENT_BYTES
    if len(canonical(rows)) > maximum:
        code = "translation_output_batch_capacity" if batch else "translation_output_document_capacity"
        raise OutputCapacityError(code)
    for before, after in zip(source, rows):
        if type(after) is not dict:
            raise ValueError("translation_output_identity_changed")
        before_identity = {k: v for k, v in before.items() if k != "text"}
        after_identity = {k: v for k, v in after.items() if k != "text"}
        if canonical(before_identity) != canonical(after_identity):
            raise ValueError("translation_output_identity_changed")
        if len(canonical(after)) > MAX_OUTPUT_ROW_BYTES:
            raise OutputCapacityError("translation_output_row_capacity")
        text = after.get("text")
        if type(text) is not str or not text.strip():
            raise ValueError("translation_output_text_required")
    parse_segments(canonical(rows), max_text_chars=MAX_OUTPUT_ROW_BYTES)
    return rows


def decode_output(raw, source):
    if type(raw) is not str:
        raise ValueError("translation_output_json_required")
    if len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise OutputCapacityError("translation_output_response_capacity")
    values = json.loads(raw)
    if (
        type(values) is not list
        or len(values) != len(source)
        or any(type(text) is not str for text in values)
    ):
        raise ValueError("translation_output_strings_required")
    return validate_output(
        [{**row, "text": text} for row, text in zip(source, values)], source, batch=True
    )


def validate_packet(packet):
    if len(canonical(packet)) > MAX_RESULT_PACKET_BYTES:
        raise OutputCapacityError("role_result_packet_capacity")
    return packet
