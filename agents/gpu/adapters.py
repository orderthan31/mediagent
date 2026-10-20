"""GPU-only role adapters. No queue, DB, workflow scan, key or provider fallback."""

import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import wave
from pathlib import Path
from video_service.cpu_agents import canonical


def child(argv, work):
    names = {
        "PATH",
        "LD_LIBRARY_PATH",
        "CUDA_VISIBLE_DEVICES",
        "NVIDIA_VISIBLE_DEVICES",
        "NVIDIA_DRIVER_CAPABILITIES",
        "CUDA_CACHE_PATH",
        "HOME",
        "TMPDIR",
    }
    env = {key: value for key, value in os.environ.items() if key in names}
    env.update(PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", OMP_NUM_THREADS="2")
    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise ValueError("gpu_engine_timed_out") from None
    (work / "engine.log").write_bytes(stdout[-32768:] + stderr[-32768:])
    if process.returncode:
        raise ValueError("gpu_engine_command_failed")


def face_execute(store, owner, command, config, work):
    import math
    import shutil
    from video_service.cpu_agents import digest
    from video_service.engine_protocol import reference

    session = json.loads(store.read(owner, command["inputs"]["session"], limit=65536))
    preview = json.loads(store.read(owner, command["inputs"]["preview"], limit=65536))
    if (
        set(session)
        != {
            "version",
            "source",
            "source_position",
            "face_position",
            "reference_frame",
            "distance",
            "engine_fingerprint",
        }
        or type(session["version"]) is not int
        or session["version"] != 1
    ):
        raise ValueError("invalid_face_session")
    if (
        set(preview)
        != {
            "version",
            "session_sha256",
            "target_sha256",
            "engine_fingerprint",
            "settings_sha256",
            "approved",
            "image",
        }
        or type(preview["version"]) is not int
        or preview["version"] != 1
        or preview["approved"] is not True
    ):
        raise ValueError("explicit_face_preview_required")
    fingerprint = command["runtime"]["model_sha256"]
    if (
        session["engine_fingerprint"] != fingerprint
        or preview["engine_fingerprint"] != fingerprint
        or preview["session_sha256"] != command["inputs"]["session"]["sha256"]
        or preview["target_sha256"] != command["inputs"]["video"]["sha256"]
        or preview["settings_sha256"] != digest(command["options"])
    ):
        raise ValueError("face_preview_pin_changed")
    for name in ["source_position", "face_position", "reference_frame"]:
        if type(session[name]) is not int or not 0 <= session[name] <= 3600:
            raise ValueError("invalid_face_selector")
    if (
        session["reference_frame"] < 1
        or type(session["distance"]) not in (int, float)
        or not math.isfinite(session["distance"])
        or not 0 <= session["distance"] <= 1.5
    ):
        raise ValueError("invalid_face_selector")
    for image in [session["source"], preview["image"]]:
        reference(image)
        if image["type"] != "image" or image["bytes"] > 10 * 1024**2:
            raise ValueError("bounded_face_image_required")
        store.path(owner, image)
    executable = Path(config["python"])
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("explicit_face_interpreter_required")
    source = work / "source.png"
    target = work / "target.mp4"
    shutil.copyfile(store.path(owner, session["source"]), source)
    shutil.copyfile(store.path(owner, command["inputs"]["video"]), target)
    media = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,width,height",
                "-of",
                "json",
                str(target),
            ],
            timeout=10,
        )
    )
    if not 0 < float(media["format"]["duration"]) <= 30 or not any(
        row.get("codec_type") == "video"
        and row.get("width", 0) * row.get("height", 0) <= 1280 * 720
        for row in media["streams"]
    ):
        raise ValueError("face_role_accepts_bounded_video_only")
    settings = {
        **{
            key: session[key]
            for key in [
                "source_position",
                "face_position",
                "reference_frame",
                "distance",
            ]
        },
        "preset": command["options"].get("preset", "fast"),
        "video_codec": command["options"].get("video_codec", "h264"),
    }
    request = {
        "operation": "preview",
        "output": str(work / "runtime-preview"),
        "source": str(source),
        "target": str(target),
        "fingerprint": fingerprint,
        "session_id": command["attempt_id"],
        "settings": settings,
        "preview_frame": session["reference_frame"],
        "preview_resolution": 512,
    }
    path = work / "preview-request.json"
    path.write_bytes(canonical(request))
    child(
        [
            str(executable),
            str(Path(__file__).with_name("probe.py")),
            "--engine",
            config["model_dir"],
            "--request",
            str(path),
        ],
        work,
    )
    request.update(operation="render", output=str(work / "render"))
    path = work / "render-request.json"
    path.write_bytes(canonical(request))
    child(
        [
            str(executable),
            str(Path(__file__).with_name("facefusion.py")),
            "--engine",
            config["model_dir"],
            "--request",
            str(path),
        ],
        work,
    )
    output = work / "render/final.mp4"
    if not output.is_file() or not 0 < output.stat().st_size <= 268435456:
        raise ValueError("face_video_output_missing")
    return {"video": (output.read_bytes(), "video")}


def execute(store, owner, command, config):
    root = store.owner_root(owner) / "engine-attempts"
    if root.is_symlink():
        raise ValueError("unsafe_engine_workspace")
    root.mkdir(mode=0o700, exist_ok=True)
    work = root / command["attempt_id"]
    work.mkdir(mode=0o700, exist_ok=False)
    role = command["runtime"]["role"]
    if role == "faceswap":
        return face_execute(store, owner, command, config, work)
    if role != "preprocess_audio":
        raise ValueError("gpu_role_not_implemented")
    if command["options"].get("audio_filter", "off") != "off":
        raise ValueError("gpu_vad_supports_filter_off_only")
    model = Path(config["model_dir"]) / "vad_multilingual_marblenet.nemo"
    with model.open("rb") as stream:
        model_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    if model_sha != command["runtime"]["model_sha256"]:
        raise ValueError("gpu_model_pin_changed")
    audio = store.path(owner, command["inputs"]["audio"])
    with wave.open(str(audio), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (
            1,
            2,
            16000,
        ) or not 0 < stream.getnframes() <= 16000 * 300:
            raise ValueError("bounded_16khz_mono_audio_required")
        frames = stream.readframes(stream.getnframes())
    report_path = work / "vad.json"
    child(
        [
            sys.executable,
            "-m",
            "mideagent_gpu.vad",
            "--audio",
            str(audio),
            "--model",
            str(model),
            "--output",
            str(report_path),
            "--device",
            "cuda",
            "--batch-size",
            "64",
        ],
        work,
    )
    report = json.loads(report_path.read_bytes())
    if (
        report["device"] != "cuda"
        or report["cuda_peak_allocated_bytes"] <= 0
        or report["model_sha256"] != model_sha
        or not report["intervals"]
    ):
        raise ValueError("actual_cuda_vad_required")
    chunks = []
    spans = []
    last_source = packed = 0
    for start, end in report["intervals"]:
        left, right = round(start * 16000), round(end * 16000)
        if left < last_source or right <= left or right > len(frames) // 2:
            raise ValueError("invalid_vad_intervals")
        chunks.append(frames[2 * left : 2 * right])
        spans.append(
            {
                "source_start": left / 16000,
                "source_end": right / 16000,
                "packed_start": packed / 16000,
                "packed_end": (packed + right - left) / 16000,
            }
        )
        packed += right - left
        last_source = right
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"".join(chunks))
    raw = output.getvalue()
    clock = {
        "version": 2,
        "audio_sha256": hashlib.sha256(raw).hexdigest(),
        "source_sha256": command["inputs"]["audio"]["sha256"],
        "spans": spans,
        "engine": report,
    }
    return {"audio": (raw, "audio"), "timeline": (canonical(clock), "timeline_map")}
