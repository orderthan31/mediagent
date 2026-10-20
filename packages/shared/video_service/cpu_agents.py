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


def reference_path(root, reference):
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
    if type(reference["bytes"]) is not int or not 0 < reference["bytes"] <= MAX_CONTENT:
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
            if size > MAX_CONTENT:
                raise ValueError("Artifact size exceeded")
            sha.update(block)
    if size != reference["bytes"] or sha.hexdigest() != reference["sha256"]:
        raise ValueError("Artifact integrity mismatch")
    return path


def process(arguments, *, cwd=None, timeout=60):
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
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise ValueError("CPU media processing failed")
    return result.stdout


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
        not isinstance(command, dict)
        or set(command) != fields
        or command["protocol_version"] != 1
    ):
        raise ValueError("Invalid CPU command")
    kind = command["agent"].get("id") if isinstance(command["agent"], dict) else None
    if (
        kind not in CPU_AGENTS
        or command["agent"] != {"id": kind, "revision": "1"}
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
    validate_node(
        {
            "node": kind,
            "inputs": {k: r["type"] for k, r in command["inputs"].items()},
            "options": command["options"],
        }
    )
    out_root = Path(output_root).resolve(strict=True)
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
            path = reference_path(input_root, reference)
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
            if hashlib.sha256(target.read_bytes()).hexdigest() != reference["sha256"]:
                raise ValueError("Input changed during copy")
            paths[name] = target
        outputs = {}
        if kind in ("analyze", "validate_video"):
            data = probe(paths["video"])
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
            raw = paths["transcript"].read_bytes()
            if len(raw) > 1024 * 1024:
                raise ValueError("Transcript size exceeded")
            file = work / "subtitles.srt"
            file.write_text(
                segments_to_srt(segment_subtitles(_segments(raw))), encoding="utf-8"
            )
            outputs["subtitles"] = (file, "subtitle")
        elif kind == "extract_audio":
            file = work / "audio.wav"
            process(
                [
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
            )
            outputs["audio"] = (file, "audio")
        elif kind == "preprocess_audio":
            # CPU-only normalization contract. NVIDIA VAD and packed silence
            # filtering are not silently substituted with a successful no-op.
            options = command["options"]
            if (
                options.get("vad_mode", "off") != "off"
                or options.get("audio_filter", "off") != "off"
            ):
                raise ValueError("cpu_preprocess_supports_off_only")
            import wave

            file = work / "normalized.wav"
            process(
                [
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
                    str(file),
                ]
            )
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
            outputs["audio"] = (file, "audio")
            outputs["timeline"] = (timeline, "timeline_map")
        elif kind == "encode":
            probe(paths["video"])
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
            process(args, cwd=work)
            probe(file)
            outputs["video"] = (file, "video")
        for name, (file, output_type) in outputs.items():
            size = file.stat().st_size
            if not 0 < size <= MAX_CONTENT:
                raise ValueError("Invalid output size")
            result["outputs"][name] = {
                "storage_key": file.relative_to(out_root).as_posix(),
                "type": output_type,
                "bytes": size,
                "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            }
        for reference in command["inputs"].values():
            reference_path(input_root, reference)
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
