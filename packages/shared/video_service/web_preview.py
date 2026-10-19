"""Derived browser-only WebM. The uploaded/processed original is never replaced."""

from __future__ import annotations

import tempfile
from pathlib import Path

from .cpu_agents import ffmpeg, probe, process

PROFILE = "webm-vp9-opus-v1"


def create_preview(store, owner, reference):
    state = {"profile": PROFILE, "source_sha256": reference["sha256"]}
    try:
        source = store.path(owner, reference)
        with tempfile.TemporaryDirectory(prefix="mideagent-webm-") as work:
            target = Path(work) / "preview.webm"
            process(
                [
                    *ffmpeg(),
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-sn",
                    "-dn",
                    "-vf",
                    "scale=w=min(1280\\,iw):h=min(720\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2",
                    "-c:v",
                    "libvpx-vp9",
                    "-threads",
                    "1",
                    "-deadline",
                    "good",
                    "-cpu-used",
                    "4",
                    "-crf",
                    "36",
                    "-b:v",
                    "0",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "64k",
                    "-map_metadata",
                    "-1",
                    "-f",
                    "webm",
                    str(target),
                ],
                timeout=60,
            )
            metadata = probe(target)
            with target.open("rb") as stream:
                preview = store.put(
                    owner, iter(lambda: stream.read(1024 * 1024), b""), "web_video"
                )
        return {**state, "status": "ready", "reference": preview, "media": metadata}
    except (ValueError, OSError, __import__("subprocess").TimeoutExpired):
        # Original artifact remains valid/downloadable; never fallback to playing
        # a potentially unsupported original or pretend preview creation succeeded.
        return {**state, "status": "failed", "error_code": "web_preview_failed"}
