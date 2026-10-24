"""Independent, bounded CPU agent entrypoint: JSON stdin -> JSON stdout.

No DB, workflow traversal, broker, provider credentials or GPU imports. Individual
agents are selected by --agent; only one immutable command is accepted per process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .agent_protocol import CPU_AGENTS
from .content_store import MAX_CONTENT
from .cpu_input_policy import (
    LARGE_INPUT_BYTES,
    LARGE_PROCESS_SECONDS,
    input_limit,
    validate_media,
)
from .node_contracts import validate_node
from .subtitles import segment_subtitles, segments_to_srt
from .transcript_input import parse_segments as _segments


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def reference_path(root, reference, *, max_bytes=MAX_CONTENT):
    if type(max_bytes) is not int or not 0 < max_bytes <= LARGE_INPUT_BYTES:
        raise ValueError("Invalid explicit CPU input bound")
    if isinstance(reference, dict) and "source_owner_id" in reference:
        from .content_store import reference_origin

        actor_root = Path(root)
        source, reference = reference_origin(actor_root.name, reference)
        if actor_root.is_symlink() or actor_root.parent.is_symlink():
            raise ValueError("Symlink input namespace denied")
        root = actor_root.parent / source
        if root.is_symlink():
            raise ValueError("Symlink source namespace denied")
    if not isinstance(reference, dict) or set(reference) != {
        "storage_key",
        "sha256",
        "bytes",
        "type",
    }:
        raise ValueError("Invalid artifact reference")
    key = reference["storage_key"]
    if (
        not isinstance(key, str)
        or not re.fullmatch(r"blobs/[a-f0-9]{64}", key)
        or key != "blobs/" + reference["sha256"]
    ):
        raise ValueError("Invalid artifact key")
    if type(reference["bytes"]) is not int or not 0 < reference["bytes"] <= max_bytes:
        raise ValueError("Invalid artifact size")
    root = Path(root).resolve(strict=True)
    path = root / key
    if (root / "blobs").is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError("Unavailable artifact")
    size = 0
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > max_bytes:
                raise ValueError("Artifact size exceeded")
            sha.update(block)
    if size != reference["bytes"] or sha.hexdigest() != reference["sha256"]:
        raise ValueError("Artifact integrity mismatch")
    return path


def process(arguments, *, cwd=None, timeout=60, diagnostics=False):
    # No shell, stdin, implicit hardware, URL protocols or environment proxy.
    result = subprocess.run(
        arguments,
        check=False,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        env={
            k: v
            for k, v in os.environ.items()
            if k in ("PATH", "LANG", "HOME", "TMPDIR", "FONTCONFIG_PATH")
        },
    )
    raw = result.stderr if diagnostics else result.stdout
    if result.returncode or len(raw) > 1024 * 1024:
        raise ValueError("CPU media processing failed")
    return raw


def process_bounded(
    arguments, *, output, cwd, timeout, max_bytes=MAX_CONTENT, resource_budget=None
):
    """Own child only: bounded work-file, silent diagnostics, finite wall time."""
    import time

    maximum = MAX_CONTENT
    if resource_budget is not None:
        from .long_audio_budget import CPU_ROLES, role_budget

        role = resource_budget.get("role")
        if (
            role not in CPU_ROLES
            or resource_budget != role_budget(role)
            or timeout > resource_budget["process_seconds"]
        ):
            raise ValueError("invalid_explicit_long_process_budget")
        maximum = resource_budget["outputs"].get("audio", MAX_CONTENT)
    if type(max_bytes) is not int or not 0 < max_bytes <= maximum:
        raise ValueError("Invalid output budget")
    child = subprocess.Popen(
        arguments,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={
            k: v
            for k, v in os.environ.items()
            if k in ("PATH", "LANG", "HOME", "TMPDIR", "FONTCONFIG_PATH")
        },
    )
    deadline = time.monotonic() + timeout
    try:
        while child.poll() is None:
            if time.monotonic() >= deadline or (
                output.exists() and output.stat().st_size > max_bytes
            ):
                raise ValueError("CPU output/time budget exceeded")
            time.sleep(0.1)
        if (
            child.returncode
            or not output.is_file()
            or not 0 < output.stat().st_size <= max_bytes
        ):
            raise ValueError("CPU output/process budget failed")
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)


def probe(path):
    raw = process(
        [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            "mov,matroska,webm,wav,mp3,ogg",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        timeout=10,
    )
    info = json.loads(raw)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    duration = float(info.get("format", {}).get("duration", 0))
    if (
        not video
        or not 0 < duration <= 31536000
        or not 0 < video["width"] <= 16384
        or not 0 < video["height"] <= 16384
    ):
        raise ValueError("Valid bounded video required")
    return {
        "duration": duration,
        "width": video["width"],
        "height": video["height"],
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "frame_rate": video.get("r_frame_rate", ""),
    }


def ffmpeg():
    return [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-max_alloc",
        "67108864",
        "-hwaccel",
        "none",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-filter_complex_threads",
        "1",
        "-protocol_whitelist",
        "file,pipe",
        "-format_whitelist",
        "mov,matroska,webm,wav,mp3,ogg",
    ]


def run(command, input_root, output_root, *, agent=None):
    fields = {
        "protocol_version",
        "run_id",
        "attempt_id",
        "generation",
        "agent",
        "inputs",
        "options",
    }
    if (
        isinstance(command, dict)
        and isinstance(command.get("agent"), dict)
        and command["agent"].get("revision") == "5"
    ):
        fields.add("resource_budget")
    if (
        not isinstance(command, dict)
        or set(command) != fields
        or command["protocol_version"] != 1
    ):
        raise ValueError("Invalid CPU command")
    kind = command["agent"].get("id") if isinstance(command["agent"], dict) else None
    if (
        kind not in CPU_AGENTS
        or set(command["agent"]) != {"id", "revision"}
        or agent not in (None, kind)
    ):
        raise ValueError("Unsupported CPU agent")
    if type(command["generation"]) is not int or command["generation"] < 1:
        raise ValueError("Invalid generation")
    for key in ("run_id", "attempt_id"):
        if not isinstance(command[key], str) or not re.fullmatch(
            r"[a-f0-9]{32}", command[key]
        ):
            raise ValueError("Invalid attempt identity")
    from .long_audio_budget import validate_command

    long_budget = validate_command(command)
    validate_node(
        {
            "node": kind,
            "inputs": {k: r["type"] for k, r in command["inputs"].items()},
            "options": command["options"],
        }
    )
    out_root = Path(output_root).resolve(strict=True)
    if long_budget and shutil.disk_usage(out_root).free < long_budget["cache_bytes"]:
        raise ValueError("insufficient_long_audio_private_cache")
    work = out_root / (command["run_id"] + "-" + command["attempt_id"])
    work.mkdir(mode=0o700, exist_ok=False)
    result = {
        "protocol_version": 1,
        "run_id": command["run_id"],
        "attempt_id": command["attempt_id"],
        "generation": command["generation"],
        "agent": command["agent"],
        "request_sha256": digest(command),
        "status": "failed",
        "outputs": {},
    }
    try:
        paths = {}
        for name, reference in command["inputs"].items():
            path = reference_path(
                input_root,
                reference,
                max_bytes=input_limit(command["agent"], name, reference["type"]),
            )
            # A byte copy, not a hardlink, freezes the actual input seen by ffmpeg.
            suffix = (
                ".srt"
                if reference["type"] == "subtitle"
                else ".json"
                if reference["type"] == "transcript"
                else ".media"
            )
            target = work / ("input-" + name + suffix)
            with path.open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            with target.open("rb") as frozen:
                frozen_sha = hashlib.file_digest(frozen, "sha256").hexdigest()
            if frozen_sha != reference["sha256"]:
                raise ValueError("Input changed during copy")
            paths[name] = target
        outputs = {}
        if kind in ("analyze", "validate_video"):
            data = probe(paths["video"])
            if command["agent"]["revision"] == "2":
                validate_media(data)
            port, output_type = (
                ("metadata", "media_metadata")
                if kind == "analyze"
                else ("report", "validation_report")
            )
            file = work / "report.json"
            file.write_bytes(
                canonical(
                    data
                    if kind == "analyze"
                    else {"valid": True, "media": data, "device": "cpu"}
                )
            )
            outputs[port] = (file, output_type)
        elif kind == "generate_subtitle":
            options = command["options"]
            raw = paths["transcript"].read_bytes()
            maximum = (
                16 * 1024 * 1024
                if command["agent"]["revision"] in {"3", "5"}
                else 1024 * 1024
            )
            if len(raw) > maximum:
                raise ValueError("Transcript size exceeded")
            file = work / "subtitles.srt"
            srt_text = segments_to_srt(segment_subtitles(_segments(raw)))
            if long_budget:
                serialized = srt_text.encode("utf-8")
                if len(serialized) > long_budget["outputs"]["subtitles"]:
                    raise ValueError("long_srt_serialized_byte_budget_exceeded")
                file.write_bytes(serialized)
            else:
                file.write_text(srt_text, encoding="utf-8")
            outputs["subtitles"] = (file, "subtitle")
            if options.get("format") == "srt_smi":
                if command["agent"]["revision"] not in {"3", "5"}:
                    raise ValueError("SAMI export requires subtitle revision 3")
                from .sami import segments_to_sami

                sami = work / "subtitles.smi"
                cues = segment_subtitles(_segments(raw))
                sami_text = segments_to_sami(
                    cues, language=options.get("language", "und")
                )
                if long_budget:
                    serialized = sami_text.encode("utf-8")
                    if len(serialized) > long_budget["outputs"]["sami"]:
                        raise ValueError("long_sami_serialized_byte_budget_exceeded")
                    sami.write_bytes(serialized)
                else:
                    sami.write_text(sami_text, encoding="utf-8")
                outputs["sami"] = (sami, "subtitle")
        elif kind == "extract_audio":
            file = work / "audio.wav"
            extract_arguments = [
                *ffmpeg(),
                "-i",
                str(paths["video"]),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-threads",
                "1",
                "-map_metadata",
                "-1",
                str(file),
            ]
            if long_budget:
                import wave

                from .long_audio_budget import FRAMES

                process_bounded(
                    extract_arguments,
                    output=file,
                    cwd=work,
                    timeout=long_budget["process_seconds"],
                    max_bytes=long_budget["outputs"]["audio"],
                    resource_budget=long_budget,
                )
                with wave.open(str(file), "rb") as extracted:
                    if not 0 < extracted.getnframes() <= FRAMES:
                        raise ValueError("long_extraction_frame_budget_exceeded")
            else:
                process(extract_arguments)
            outputs["audio"] = (file, "audio")
        elif kind == "preprocess_audio":
            options = command["options"]
            region_profile = options.get(
                "processing_profile"
            ) == "regions_pack_v4" or bool(
                long_budget and "regions" in command["inputs"]
            )
            packed_profile = options.get("processing_profile") in {
                "silence_pack_v3",
                "regions_pack_v4",
                "regions_long_v5",
            }
            expected_revision = (
                "5"
                if long_budget
                else "4"
                if region_profile
                else "3"
                if packed_profile
                else "1"
            )
            if command["agent"]["revision"] != expected_revision:
                raise ValueError("preprocess_profile_revision_mismatch")
            if options.get("vad_mode", "off") != "off":
                raise ValueError("cpu_preprocess_nvidia_requires_engine")
            if not packed_profile and options.get("audio_filter", "off") != "off":
                raise ValueError("cpu_preprocess_supports_off_only")
            import wave

            file = work / "normalized.wav"
            normalize_arguments = [
                *ffmpeg(),
                "-i",
                str(paths["audio"]),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                *(["-t", "21601" if long_budget else "301"] if packed_profile else []),
                str(file),
            ]
            if long_budget:
                process_bounded(
                    normalize_arguments,
                    output=file,
                    cwd=work,
                    timeout=long_budget["process_seconds"],
                    max_bytes=long_budget["outputs"]["audio"],
                    resource_budget=long_budget,
                )
            else:
                process(normalize_arguments, timeout=30 if packed_profile else 60)
            with wave.open(str(file), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
            if not 0 < duration <= 31536000:
                raise ValueError("invalid_audio_duration")
            timeline = work / "timeline.json"
            timeline.write_bytes(
                canonical(
                    [
                        {
                            "source_start": 0,
                            "source_end": duration,
                            "packed_start": 0,
                            "packed_end": duration,
                        }
                    ]
                )
            )
            if packed_profile:
                from .audio_preprocessing import pack_silence

                packed = work / "packed.wav"
                mapping = pack_silence(
                    file,
                    packed,
                    options.get("audio_filter", "off"),
                    max_seconds=21600 if long_budget else 300,
                    detect=lambda minimum: process(
                        [
                            *ffmpeg(),
                            "-loglevel",
                            "info",
                            "-i",
                            str(file),
                            "-af",
                            f"silencedetect=noise=-45dB:d={minimum}",
                            "-f",
                            "null",
                            "-",
                        ],
                        timeout=long_budget["process_seconds"] if long_budget else 30,
                        diagnostics=True,
                    ),
                )
                if region_profile:
                    from .audio_preprocessing import copy_regions
                    from .audio_regions import region_intervals

                    document = json.loads(paths["regions"].read_bytes())
                    with wave.open(str(file), "rb") as normalized:
                        frame_count = normalized.getnframes()
                    intervals = region_intervals(
                        [(s["source_start"], s["source_end"]) for s in mapping],
                        document,
                        source_sha256=command["inputs"]["audio"]["sha256"],
                        source_frames=frame_count,
                        audio_filter=options.get("audio_filter", "off"),
                        vad=[(0, frame_count / 16000)],
                    )
                    packed = work / "regions.wav"
                    mapping = copy_regions(
                        file,
                        packed,
                        intervals,
                        max_seconds=21600 if long_budget else 300,
                    )
                if long_budget:
                    from .long_audio_budget import make_clock

                    with wave.open(str(file), "rb") as source_audio:
                        source_frames = source_audio.getnframes()
                    with wave.open(str(packed), "rb") as packed_audio:
                        packed_frames = packed_audio.getnframes()
                    with packed.open("rb") as stream:
                        packed_sha = hashlib.file_digest(stream, "sha256").hexdigest()
                    mapping = make_clock(
                        mapping,
                        source_sha256=command["inputs"]["audio"]["sha256"],
                        audio_sha256=packed_sha,
                        source_frames=source_frames,
                        packed_frames=packed_frames,
                    )
                timeline.write_bytes(canonical(mapping))
                file = packed
            outputs["audio"] = (file, "audio")
            outputs["timeline"] = (timeline, "timeline_map")
        elif kind == "encode":
            source_media = probe(paths["video"])
            if command["agent"]["revision"] == "2":
                validate_media(source_media)
            options = command["options"]
            mode = options.get("subtitle_mode", "burn")
            file = work / "output.mp4"
            args = [*ffmpeg(), "-i", str(paths["video"])]
            filters = []
            resolution = options.get("resolution", "original")
            if resolution != "original":
                filters.append(
                    "scale=-2:" + ("720" if resolution == "720p" else "1080")
                )
            if mode == "burn":
                filters.append("subtitles=input-subtitles.srt")
            elif mode == "soft":
                args += ["-i", str(paths["subtitles"]), "-c:s", "mov_text"]
            if filters:
                args += ["-vf", ",".join(filters)]
            codec = options.get("video_codec", "h264")
            args += [
                "-c:v",
                "libx264" if codec == "h264" else "libx265",
                "-threads",
                "1",
                "-preset",
                "fast",
                "-crf",
                {"balanced": "23", "high": "18", "compact": "28"}[
                    options.get("quality_profile", "balanced")
                ],
                "-c:a",
                "aac",
                "-map_metadata",
                "-1",
                "-movflags",
                "+faststart",
                str(file),
            ]
            if codec == "hevc":
                args[-1:-1] = ["-x265-params", "pools=none:frame-threads=1"]
            if command["agent"]["revision"] == "2":
                # Bound disk output without ever accepting a truncated success.
                args[-1:-1] = ["-fs", str(MAX_CONTENT + 1024 * 1024)]
                process_bounded(
                    args, output=file, cwd=work, timeout=LARGE_PROCESS_SECONDS
                )
                output_media = probe(file)
                if abs(output_media["duration"] - source_media["duration"]) > 1:
                    raise ValueError(
                        "Encoded duration differs or output budget truncated"
                    )
            else:
                process(args, cwd=work)
                probe(file)
            outputs["video"] = (file, "video")
        for name, (file, output_type) in outputs.items():
            size = file.stat().st_size
            maximum = long_budget["outputs"][name] if long_budget else MAX_CONTENT
            if not 0 < size <= maximum:
                raise ValueError("Invalid output size")
            with file.open("rb") as stream:
                output_sha = hashlib.file_digest(stream, "sha256").hexdigest()
            result["outputs"][name] = {
                "storage_key": file.relative_to(out_root).as_posix(),
                "type": output_type,
                "bytes": size,
                "sha256": output_sha,
            }
        for port, reference in command["inputs"].items():
            reference_path(
                input_root,
                reference,
                max_bytes=input_limit(command["agent"], port, reference["type"]),
            )
        result["status"] = "completed"
    except Exception:  # noqa: BLE001 -- protocol boundary must suppress paths/credentials in errors
        # Keep per-attempt files for investigation; never leak raw ffmpeg/path errors.
        result.update(
            status="failed",
            outputs={},
            error={"code": "cpu_agent_failed", "retryable": False},
        )
    (work / "receipt.json").write_bytes(canonical(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", choices=sorted(CPU_AGENTS), required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("Command size exceeded")
        result = run(
            json.loads(raw), args.input_root, args.output_root, agent=args.agent
        )
        sys.stdout.buffer.write(canonical(result))
        return 0 if result["status"] == "completed" else 1
    except Exception:  # noqa: BLE001 -- protocol boundary must suppress paths/credentials in errors
        sys.stdout.write(
            '{"status":"failed","error":{"code":"invalid_command","retryable":false}}'
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
