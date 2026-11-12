"""Bounded, read-only input resolution; only create materializes inline transcript CAS.

Clients choose committed job/run/port identities. Storage locators and custodian
origins are resolved on the server and are never accepted from a client selector.
"""
from copy import deepcopy
import hashlib
import json
import re
import wave

from video_service.canonical import canonical, digest
from video_service.object_store import validate_reference
from video_service.subtitle_tracks import language
from video_service.transcript_batches import validate_source
from video_service.renewal_contracts import spec
from video_service.timed_subtitles import (MAX_TRANSCRIPT_BYTES, MAX_INPUT_OPTIONS_BYTES,
                                         generation_limits, preserved_files, timed_segments as validate_timed)

MAX_TEXT = MAX_TRANSCRIPT_BYTES
ID = re.compile(r"[a-f0-9]{32}\Z")
STAMP = r"(\d{2,5}):([0-5]\d):([0-5]\d),(\d{3})"


def timed_segments(rows, *, maximum=MAX_TEXT):
    validate_timed(rows, maximum=maximum)
    return deepcopy(rows)


def parse_srt(text, *, maximum=MAX_TEXT):
    """Strict bounded SRT reader; shared native segment validators own the timeline."""
    if not isinstance(text, str) or not 1 <= len(text.encode("utf-8")) <= maximum:
        raise ValueError(f"SRT 파일은 UTF-8 {maximum // 1024}KiB 이내여야 합니다. 자막을 나누거나 출력 설정을 변경하세요.")
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    rows = []
    for block in re.split(r"\n[ \t]*\n", normalized.rstrip("\n")):
        lines = block.split("\n")
        if len(lines) < 3 or not re.fullmatch(r"\d{1,128}", lines[0]):
            raise ValueError("번호·시각·문구가 있는 SRT 파일을 선택하세요.")
        clock = re.fullmatch(STAMP + r" --> " + STAMP, lines[1])
        if not clock:
            raise ValueError("SRT 시각은 HH:MM:SS,mmm 형식이어야 합니다.")
        if any(re.fullmatch(STAMP + r" --> " + STAMP, line) for line in lines[2:]):
            raise ValueError("SRT 구간 사이에는 빈 줄이 필요합니다.")
        values = list(map(int, clock.groups()))
        seconds = lambda v: v[0] * 3600 + v[1] * 60 + v[2] + v[3] / 1000
        rows.append({"id": lines[0], "start": seconds(values[:4]), "end": seconds(values[4:]), "text": "\n".join(lines[2:])})
        if len(rows) > 10000:
            raise ValueError("선택 자막은 10000구간 이내로 나눈 뒤 다시 선택하세요.")
    return timed_segments(rows, maximum=maximum)


def verify_raw_wav(path):
    from video_service.audio_batches import RATE, MAX_BATCH_AUDIO_SECONDS, MAX_BATCH_AUDIO_BYTES
    if path.stat().st_size > MAX_BATCH_AUDIO_BYTES:
        raise ValueError("재사용 음성은 PCM WAV 1GiB/6시간 이내입니다.")
    try:
        with wave.open(str(path), "rb") as source:
            if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, RATE, "NONE"):
                raise ValueError("재사용 음성은 16kHz 모노 PCM16 WAV여야 합니다.")
            frames = source.getnframes()
            if not 0 < frames <= RATE * MAX_BATCH_AUDIO_SECONDS:
                raise ValueError("추출 음성 길이를 확인하세요.")
            total = 0
            while block := source.readframes(RATE * 30):
                total += len(block)
            if total != frames * 2:
                raise ValueError("추출 WAV 본문이 손상되었습니다.")
    except (wave.Error, EOFError):
        raise ValueError("검증 가능한 추출 WAV가 필요합니다.") from None


def transcript_consumers(native):
    """Follow only the selected transcript, including successive translations."""
    nodes = {n["id"]: n for n in native["nodes"]}
    sources, consumers = {("$input", "transcript")}, set()
    while True:
        prior = len(consumers)
        for edge in native["edges"]:
            source, target = edge["source"], edge["target"]
            if (source["node"], source["port"]) in sources and target["port"] == "transcript":
                consumers.add(target["node"])
                if nodes[target["node"]]["type"] == "translate":
                    sources.add((target["node"], "transcript"))
        if len(consumers) == prior:
            return [n for n in native["nodes"] if n["id"] in consumers]


class NormalInputs:
    def __init__(self, runtime):
        self.runtime = runtime

    def accepted(self, db, actor, asset, port, selector, *, maximum=MAX_TEXT):
        if (not isinstance(selector, dict) or set(selector) != {"job_id", "run_id", "port"}
                or any(not isinstance(selector.get(k), str) or not ID.fullmatch(selector[k]) for k in ("job_id", "run_id"))
                or selector["port"] != port):
            raise ValueError("완료 작업·실행·출력 포트를 선택하세요.")
        runtime = self.runtime
        job = runtime._shared_job(db, selector["job_id"])
        if job["status"] != "completed" or job.get("library_removed_at"):
            raise ValueError("완료되어 보관 중인 작업만 입력으로 사용할 수 있습니다.")
        runs = runtime._runs(db, job["owner_id"], job["id"])
        matches = [r for r in runs if r["id"] == selector["run_id"]]
        if len(matches) != 1:
            raise ValueError("완료된 입력 실행을 찾을 수 없습니다.")
        run = matches[0]
        if run["status"] != "completed" or run.get("display_status", "completed") != "completed":
            raise ValueError("확정 완료된 입력만 선택하세요.")
        receipt = run.get("result")
        if (not isinstance(receipt, dict) or not isinstance(receipt.get("outputs"), dict)
                or receipt.get("status") in {"failed", "unknown", "held"}
                or (run.get("dispatch") or {}).get("phase") in {"failed", "unknown", "held"}):
            raise ValueError("입력 실행의 확정 완료 receipt를 확인할 수 없습니다.")
        request = run.get("request")
        if request and digest(request) != run.get("request_sha256"):
            raise ValueError("입력 실행의 고정 요청 digest가 다릅니다.")
        node = next((n for n in job["snapshot"]["definition"]["nodes"] if n["id"] == run["node_id"]), None)
        contract = spec(node["type"], node["options"]) if node else None
        if not contract or contract["outputs"].get(port) != port:
            raise ValueError("입력의 원래 출력 계약이 맞지 않습니다.")
        if port == "audio":
            original = job["snapshot"]["inputs"].get("video", {})
            selected = runtime.asset_reference(asset)
            sources = [e["source"] for e in job["snapshot"]["definition"].get("edges", []) if e["target"] == {"node": node["id"], "port": "video"}]
            actual = run.get("inputs", {}).get("video", {})
            if (node["type"] != "extract_audio" or job["asset_id"] != asset.get("id", asset.get("asset_id"))
                    or sources != [{"node": "$input", "port": "video"}]
                    or any(original.get(k) != selected.get(k) or actual.get(k) != original.get(k) for k in ("sha256", "bytes", "type"))):
                raise ValueError("같은 영상에서 완료된 원본 음성 추출 결과만 재사용합니다.")
        elif node["type"] not in {"transcribe", "translate"}:
            raise ValueError("전사·번역 도구의 완료된 시간 자막을 선택하세요.")
        runtime.ticket_artifacts.read(job, runs)
        reference = receipt["outputs"].get(port)
        validate_reference(reference)
        if reference["type"] != port:
            raise ValueError("선택한 출력의 입력 유형이 다릅니다.")
        path = runtime.store.path(job["owner_id"], reference)
        rows, selected_language = None, None
        if port == "audio":
            verify_raw_wav(path)
        else:
            if reference["bytes"] > maximum:
                raise ValueError(f"선택 자막이 현재 워크플로우의 {maximum // 1024}KiB 입력 한도를 초과합니다. 출력 설정을 변경하세요.")
            rows = timed_segments(json.loads(runtime.store.read(job["owner_id"], reference, limit=maximum)), maximum=maximum)
            key = "target_language" if node["type"] == "translate" else "source_language"
            model_kind = "translation" if node["type"] == "translate" else "transcription"
            selected_language = (request or {}).get(model_kind, {}).get(key)
            if not selected_language:
                selected_language = job["snapshot"].get("options", {}).get(key, "auto")
                if node["type"] == "transcribe" or node["options"].get("translation_profile") == "language_target_v1":
                    selected_language = node["options"].get(key) or selected_language
            selected_language = language(selected_language, auto=True)
        bound = {**deepcopy(reference), **({"source_owner_id": job["owner_id"]} if job["owner_id"] != actor else {})}
        pin = {**selector, "kind": "accepted", "node_id": node["id"], "reference": deepcopy(reference),
               "custodian_id": job["owner_id"], "snapshot_sha256": job["snapshot_sha256"],
               "receipt_sha256": digest(receipt), **({"request_sha256": run["request_sha256"]} if request else {}),
               **({"language": selected_language} if selected_language else {})}
        if rows is not None:
            pin["segments"] = len(rows)
        return bound, pin, rows

    def resolve(self, db, actor, asset, definition, options):
        declared = definition.get("inputs", {})
        if len(canonical(options)) > (MAX_INPUT_OPTIONS_BYTES if "transcript" in declared else 20000):
            raise ValueError("작업 입력 크기를 초과했습니다. 자막을 나눈 뒤 다시 선택하세요.")
        from .workflow import compile_definition
        from video_service.original_video_budget import resolve_definition
        native = compile_definition(definition)["definition"]
        if "bytes" in asset:
            native = resolve_definition(asset, native)
        consumers = transcript_consumers(native)
        generators = [n for n in consumers if n["type"] == "generate_subtitle"]
        maximum = min([MAX_TEXT, *(generation_limits(n["options"])[0] for n in generators)])
        accepted = options.get("accepted_inputs", {})
        if not isinstance(accepted, dict) or set(accepted) - {k for k in declared if k in {"audio", "transcript"}}:
            raise ValueError("워크플로우가 요구하는 입력만 선택하세요.")
        if "transcript" not in declared and any(k in options for k in ("subtitle_srt", "transcript", "input_language")):
            raise ValueError("이 워크플로우에는 자막 입력을 추가하지 않습니다.")
        refs, bindings, rows, input_language = {}, {}, None, None
        for port in ("transcript", "audio"):
            if port not in declared:
                continue
            inline = [k for k in ("subtitle_srt", "transcript") if k in options] if port == "transcript" else []
            if (port in accepted) + len(inline) != 1:
                raise ValueError("필요한 자막 파일 또는 완료 입력 하나를 선택하세요.")
            if port in accepted:
                refs[port], bindings[port], selected_rows = self.accepted(db, actor, asset, port, accepted[port], maximum=maximum)
                if port == "transcript":
                    rows = selected_rows
                    input_language = bindings[port]["language"]
                    if "input_language" in options and options["input_language"] != input_language:
                        raise ValueError("완료 전사문의 원래 언어를 임의로 바꿀 수 없습니다.")
            else:
                kind = inline[0]
                rows = parse_srt(options[kind], maximum=maximum) if kind == "subtitle_srt" else timed_segments(options[kind], maximum=maximum)
                input_language = language(options.get("input_language", options.get("source_language", "auto")), auto=True)
                raw = canonical(rows)
                refs[port] = {"type": "transcript", "bytes": len(raw), "sha256": digest(rows), "storage_key": "blobs/" + digest(rows)}
                bindings[port] = {"kind": kind, "language": input_language, "content_sha256": digest(rows),
                                  "segments": len(rows),
                                  **({"source_sha256": hashlib.sha256(options[kind].encode("utf-8")).hexdigest()} if kind == "subtitle_srt" else {})}
        if rows is not None:
            if any(n["type"] == "translate" for n in consumers):
                validate_source(rows)
            # Serialize prospectively without CAS writes, checking actual selected
            # output budgets too. Translated output is checked again by its worker.
            native = compile_definition(definition, input_language=input_language)["definition"]
            if "bytes" in asset:
                native = resolve_definition(asset, native)
            for node in transcript_consumers(native):
                if node["type"] == "generate_subtitle":
                    preserved_files(rows, node["options"])
        return {"references": refs, "bindings": bindings, "segments": rows, "language": input_language}

    def materialize(self, actor, resolved):
        refs = deepcopy(resolved["references"])
        if resolved["bindings"].get("transcript", {}).get("kind") in {"subtitle_srt", "transcript"}:
            reference = self.runtime.store.put(actor, [canonical(resolved["segments"])], "transcript")
            if reference != refs["transcript"]:
                raise ValueError("고정 자막 입력의 저장 digest가 다릅니다.")
        return refs


def public_input_summary(bindings):
    return [{"input": port, **{k: pin[k] for k in ("kind", "language", "segments", "job_id", "run_id", "port") if k in pin}}
            for port, pin in bindings.items()]
