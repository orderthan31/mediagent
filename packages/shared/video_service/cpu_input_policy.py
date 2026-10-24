"""Versioned CPU video processing admission; not an upload/storage limit."""

from contextlib import contextmanager

from .content_store import MAX_CONTENT

LARGE_AGENTS = frozenset({"encode", "validate_video"})
LARGE_INPUT_BYTES = 4 * 1024 * 1024 * 1024
LARGE_DURATION_SECONDS = 6 * 60 * 60
LARGE_PROCESS_SECONDS = 2 * 60 * 60
LARGE_COMMAND_SECONDS = LARGE_PROCESS_SECONDS + 1800
LARGE_LEASE_SECONDS = LARGE_COMMAND_SECONDS + 600
LARGE_CACHE_BYTES = 10 * 1024 * 1024 * 1024
LARGE_PROFILE = {
    "id": "cpu_video_v2",
    "agent_revision": "2",
    "max_source_bytes": LARGE_INPUT_BYTES,
    "max_duration_seconds": LARGE_DURATION_SECONDS,
    "max_pixels": 3840 * 2160,
    "max_process_seconds": LARGE_PROCESS_SECONDS,
    "max_command_seconds": LARGE_COMMAND_SECONDS,
    "lease_seconds": LARGE_LEASE_SECONDS,
    "cache_budget_bytes": LARGE_CACHE_BYTES,
    "max_result_bytes": MAX_CONTENT,
}


def input_limit(agent, port, kind):
    if not isinstance(agent, dict) or set(agent) != {"id", "revision"}:
        raise ValueError("Invalid CPU input contract")
    if (
        agent["id"] in {"generate_subtitle", "preprocess_audio"}
        and agent["revision"] == "3"
    ):
        return MAX_CONTENT
    if agent["revision"] == "1":
        return MAX_CONTENT
    if agent["revision"] != "2" or agent["id"] not in LARGE_AGENTS:
        raise ValueError("Unsupported CPU input revision")
    return LARGE_INPUT_BYTES if port == "video" and kind == "video" else MAX_CONTENT


def source_policy(asset, definition):
    """Return a frozen large-source contract or retain the legacy small path."""
    size = asset["bytes"]
    if type(size) is not int or not 0 < size <= LARGE_INPUT_BYTES:
        raise ValueError("CPU video source exceeds explicit 4 GiB input limit")
    if size <= MAX_CONTENT:
        return None
    nodes = definition.get("nodes", [])
    if not nodes or any(
        n.get("type") not in LARGE_AGENTS
        or n.get("model_ref")
        or n.get("fallback_refs")
        for n in nodes
    ):
        raise ValueError(
            "Large input supports CPU encode/validate_video only; other roles remain 256 MiB"
        )
    metadata = asset.get("metadata", {})
    media = metadata.get("media") or {}
    if metadata.get("registration_state") != "verified":
        raise ValueError("Verified original media required")
    validate_media(media)
    return dict(LARGE_PROFILE)


def command_timeout(command):
    agent = command["agent"]
    input_limit(agent, "video", "video")
    return LARGE_COMMAND_SECONDS if agent["revision"] == "2" else 90


def model_runtime_seconds(max_calls):
    if type(max_calls) is not int or not 1 <= max_calls <= 4096:
        raise ValueError("Invalid bounded model call count")
    return min(2 * 60 * 60, max_calls * 45 + 120)


def lease_seconds(command):
    agent = command["agent"]
    kind = {"transcribe": "transcription", "translate": "translation"}.get(
        agent.get("id")
    )
    if kind and command.get(kind, {}).get("batch_policy"):
        config = command[kind]
        expected_policy = (
            "bounded_60s_v1" if kind == "transcription" else "bounded_100x16k_v1"
        )
        expected = model_runtime_seconds(config.get("max_model_calls"))
        if (
            config.get("batch_policy") != expected_policy
            or config.get("max_runtime_seconds") != expected
        ):
            raise ValueError("Invalid frozen bounded model deadline")
        return expected
    input_limit(agent, "video", "video")
    return LARGE_LEASE_SECONDS if agent["revision"] == "2" else 120


@contextmanager
def workspace(root, command):
    """V2 one-command disk scope; an interrupted scope is held, not swept."""
    import shutil
    import tempfile
    from pathlib import Path

    root = Path(root)
    input_limit(command["agent"], "video", "video")
    if command["agent"]["revision"] != "2":
        yield root
        return
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("Explicit private CPU cache required")
    if any(root.glob("large-v2-*")):
        raise ValueError("Interrupted large cache requires operator review")
    if shutil.disk_usage(root).free < LARGE_CACHE_BYTES:
        raise ValueError("Insufficient bounded CPU cache space")
    with tempfile.TemporaryDirectory(prefix="large-v2-", dir=root) as scoped:
        yield Path(scoped)


def validate_media(media):
    import math

    duration, width, height = (media.get(k) for k in ("duration", "width", "height"))
    if (
        type(duration) not in (int, float)
        or not math.isfinite(duration)
        or not 0 < duration <= LARGE_DURATION_SECONDS
        or type(width) is not int
        or type(height) is not int
        or not 0 < width <= 4096
        or not 0 < height <= 4096
        or width * height > LARGE_PROFILE["max_pixels"]
    ):
        raise ValueError("Large CPU video requires <=6h and <=3840x2160 pixel budget")
