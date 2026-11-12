"""Explicit selected-cue behavior and existing finite subtitle generation budgets.

Absent cue_policy retains historical wrapping/retiming. This mode is frozen only
for newly selected timed-input graphs and never inferred by a worker.
"""
from .canonical import canonical
from .content_store import MAX_CONTENT
from .transcript_input import parse_segments
from .subtitles import format_srt_timestamp

MAX_TRANSCRIPT_BYTES = 16 * 1024 * 1024
MAX_INPUT_OPTIONS_BYTES = 2 * MAX_TRANSCRIPT_BYTES + 20000
INPUT_REQUEST_BYTES = MAX_INPUT_OPTIONS_BYTES + 65536


def generation_limits(options):
    """Match generate_subtitle revisions 1, 3 and explicit long-budget 5."""
    if options.get("media_budget") == "audio_long_v5":
        from .long_audio_budget import role_budget
        budget = role_budget("generate_subtitle")
        return budget["inputs"]["transcript"], budget["outputs"]["subtitles"]
    return (MAX_TRANSCRIPT_BYTES if options.get("format") == "srt_smi" else 1024 * 1024), MAX_CONTENT


def timed_segments(rows, *, maximum=MAX_TRANSCRIPT_BYTES):
    """Validate bounded cues; MT/SAMI consumers own ordering and nonoverlap."""
    raw = canonical(rows)
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000 or len(raw) > maximum:
        raise ValueError(f"선택 자막은 1~10000구간, 현재 워크플로우에서 {maximum // 1024}KiB 이내여야 합니다.")
    cues = parse_segments(raw)
    identifiers = set()
    for cue in cues:
        identity = (type(cue.id).__name__, cue.id)
        if cue.id is not None and identity in identifiers:
            raise ValueError("자막 ID 중복을 수정한 뒤 다시 선택하세요.")
        identifiers.add(identity)
        if format_srt_timestamp(cue.start) == format_srt_timestamp(cue.end):
            raise ValueError("자막 구간은 밀리초 단위로 구분되어야 합니다.")
    return cues


def preserved_files(rows, options):
    maximum, output_maximum = generation_limits(options)
    cues = timed_segments(rows, maximum=maximum)
    blocks = [f"{cue.id if cue.id is not None else i}\n{format_srt_timestamp(cue.start)} --> {format_srt_timestamp(cue.end)}\n{cue.text}"
              for i, cue in enumerate(cues, 1)]
    files = {"subtitles": ("\n\n".join(blocks) + "\n").encode("utf-8")}
    if options.get("format") == "srt_smi":
        from .sami import segments_to_sami
        files["sami"] = segments_to_sami(cues, language=options.get("language", "und"), preserve_text=True).encode("utf-8")
    if any(not 0 < len(raw) <= output_maximum for raw in files.values()):
        raise ValueError("선택 자막의 출력 파일이 현재 워크플로우 용량을 초과합니다. 자막을 나누거나 출력 설정을 변경하세요.")
    return files
