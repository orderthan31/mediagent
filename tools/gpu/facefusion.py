"""Executed only by FaceFusion's Python. Private engine imports stay in this file."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def engine_frame_number(number, version):
    # Project/API cursors stay one-based across engine upgrades.
    return number - 1 if version == "3.9.0" else number


def main(engine_arg=None, request_arg=None):
    tick = time.perf_counter()
    timings = {}

    def mark(stage):
        nonlocal tick
        now = time.perf_counter()
        timings[stage] = round((now - tick) * 1000, 1)
        tick = now

    if sys.platform == "linux" and os.getenv("FACEFUSION_PARENT_PID"):
        import ctypes
        import signal

        # Kill the entire engine group if the worker disappears, including CLI/FFmpeg children.
        signal.signal(
            signal.SIGTERM, lambda *_: os.killpg(os.getpgrp(), signal.SIGKILL)
        )
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Cannot register parent-death signal")
        if os.getppid() != int(os.environ["FACEFUSION_PARENT_PID"]):
            os.killpg(os.getpgrp(), signal.SIGKILL)
    engine = Path(engine_arg).resolve()
    os.chdir(engine)
    sys.path.insert(0, str(engine))
    import cv2
    import numpy as np
    import onnxruntime as ort

    if os.name != "nt":
        ort.preload_dlls(directory="")
    from facefusion import content_analyser, metadata, state_manager

    version = metadata.get("version")
    if version not in {"3.5.4", "3.9.0"}:
        raise ValueError("지원하는 FaceFusion 버전은 3.5.4 또는 3.9.0입니다.")
    from facefusion.args import apply_args
    from facefusion.program import create_program

    if version == "3.9.0":
        from facefusion.face_creator import get_static_faces as get_many_faces
        from facefusion.face_store import FACE_STORE
        from facefusion.face_store import clear_faces as clear_static_faces
    else:
        from facefusion.face_analyser import get_many_faces
        from facefusion.face_store import FACE_STORE, clear_static_faces
    from facefusion.face_selector import select_faces, sort_and_filter_faces
    from facefusion.processors.modules.face_swapper import core as swapper
    from facefusion.vision import (
        count_video_frame_total,
        detect_video_fps,
        read_static_video_frame,
    )

    request = json.loads(Path(request_arg).read_text(encoding="utf-8"))
    output = Path(request["output"])
    output.mkdir(parents=True, exist_ok=True)
    models = [
        "2dfan4",
        "arcface_w600k_r50",
        "bisenet_resnet_34",
        "fairface",
        "fan_68_5",
        "hyperswap_1a_256",
        "nsfw_1",
        "nsfw_2",
        "nsfw_3",
        "xseg_1",
        "yoloface_8n",
    ]
    for model in models:
        if not (engine / ".assets/models" / (model + ".onnx")).is_file():
            raise ValueError("필수 모델이 설치되지 않았습니다: " + model)
    fingerprint = hashlib.sha256(ort.__version__.encode())
    fingerprint.update(Path(__file__).read_bytes())
    for path in sorted((engine / "facefusion").rglob("*.py")):
        fingerprint.update(path.relative_to(engine).as_posix().encode())
        fingerprint.update(path.read_bytes())
    for model in models:
        path = engine / ".assets/models" / (model + ".onnx")
        fingerprint.update(
            f"{model}:{path.stat().st_size}:{path.stat().st_mtime_ns}".encode()
        )
    fingerprint = fingerprint.hexdigest()
    if request["operation"] == "capabilities":
        from facefusion.hash_helper import validate_hash

        for model in models:
            if not validate_hash(str(engine / ".assets/models" / (model + ".onnx"))):
                raise ValueError("모델 해시 검증 실패: " + model)
        session = ort.InferenceSession(
            str(engine / ".assets/models/yoloface_8n.onnx"),
            providers=["CUDAExecutionProvider"],
        )
        if session.get_providers()[0] != "CUDAExecutionProvider":
            raise ValueError("CUDA 추론을 초기화하지 못했습니다.")
        session.run(
            None, {session.get_inputs()[0].name: np.zeros((1, 3, 640, 640), np.float32)}
        )
        result = {
            "ready": True,
            "version": metadata.get("version"),
            "fingerprint": fingerprint,
            "presets": ["fast", "balanced", "quality"],
            "provider": "cuda",
            "max_source_bytes": 10 * 1024**2,
        }
    else:
        if fingerprint != request["fingerprint"]:
            raise ValueError("엔진 또는 모델이 변경되었습니다. 설정을 다시 확인하세요.")
        settings = request["settings"]
        boost = {"fast": "256x256", "balanced": "512x512", "quality": "768x768"}[
            settings["preset"]
        ]
        config_path = output.parent / "facefusion.ini"
        config_path.write_text("", encoding="utf-8")
        cli = [
            "headless-run",
            "--config-path",
            str(config_path),
            "--execution-providers",
            "cuda",
            "--execution-thread-count",
            "1",
            "--processors",
            "face_swapper",
            "--face-swapper-model",
            "hyperswap_1a_256",
            "--face-swapper-pixel-boost",
            boost,
            "--face-selector-mode",
            "reference",
            "--face-selector-order",
            "left-right",
            "--reference-face-position",
            str(settings["face_position"]),
            "--reference-frame-number",
            str(engine_frame_number(settings["reference_frame"], version)),
            "--reference-face-distance",
            str(settings["distance"]),
            "--face-mask-types",
            *settings.get("mask_types", ["box"]),
            "--face-mask-blur",
            str(settings.get("mask_blur", 0.3)),
            "--face-mask-padding",
            *map(str, settings.get("mask_padding", [0, 0, 0, 0])),
            "--face-mask-areas",
            *settings.get("mask_areas", ["upper-face", "lower-face", "mouth"]),
            "--face-mask-regions",
            *settings.get(
                "mask_regions",
                [
                    "skin",
                    "left-eyebrow",
                    "right-eyebrow",
                    "left-eye",
                    "right-eye",
                    "glasses",
                    "nose",
                    "mouth",
                    "upper-lip",
                    "lower-lip",
                ],
            ),
            "--face-detector-angles",
            *map(str, settings.get("detector_angles", [0])),
            "--output-audio-encoder",
            "aac",
            "--output-audio-volume",
            "100",
            "--temp-frame-format",
            "png",
            "--log-level",
            "info",
        ]
        if version == "3.9.0":
            # Match the existing single-frame identity selector in preview and CLI.
            cli += [
                "--face-tracker-score",
                "0",
                "--face-swapper-weight",
                "0.5",
                "--target-frame-amount",
                "0",
                "--workflow-strategy",
                "disk",
            ]
        # The engine reads config-path from argv while constructing its parser.
        sys.argv = [sys.argv[0], *cli]
        # Parser construction launches FFmpeg encoder discovery several times.
        # Its choices are static during this resident engine's lifetime.
        if not hasattr(main, "program"):
            main.program = create_program()
        program = main.program
        apply_args(vars(program.parse_args(cli)), state_manager.init_item)
        # FaceFusion caches faces by image bytes, not detector options. Invalidate
        # on detector changes and cap retained frames while keeping GPU sessions.
        if getattr(main, "session_id", None) != request.get("session_id"):
            clear_static_faces()
            read_static_video_frame.cache_clear()
            if version == "3.9.0":
                from facefusion.video_manager import clear_video_pool

                clear_video_pool()
        main.session_id = request.get("session_id")
        angles = tuple(settings.get("detector_angles", [0]))
        cached_faces = FACE_STORE if version == "3.9.0" else FACE_STORE["static_faces"]
        if getattr(main, "angles", None) != angles or len(cached_faces) > 32:
            clear_static_faces()
        main.angles = angles
        if read_static_video_frame.cache_info().currsize > 16:
            read_static_video_frame.cache_clear()
        mark("initialize")

        def checked(frame):
            if frame is None:
                raise ValueError("프레임을 읽을 수 없습니다.")
            if content_analyser.analyse_frame(frame):
                raise ValueError("FaceFusion 콘텐츠 검사에서 처리가 제한되었습니다.")
            return frame

        def faces(frame):
            detected = get_many_faces([frame])
            return (
                sort_and_filter_faces([], detected)
                if version == "3.9.0"
                else sort_and_filter_faces(detected)
            )

        def export_faces(frame, detected, original_size=None):
            cv2.imwrite(str(output / "original.png"), frame)
            values = []
            for i, face in enumerate(detected):
                x1, y1, x2, y2 = face.bounding_box.tolist()
                h, w = frame.shape[:2]
                if original_size:
                    x1, x2 = x1 * w / original_size[0], x2 * w / original_size[0]
                    y1, y2 = y1 * h / original_size[1], y2 * h / original_size[1]
                pad = max(x2 - x1, y2 - y1) * 0.15
                crop = frame[
                    max(0, int(y1 - pad)) : min(h, int(y2 + pad)),
                    max(0, int(x1 - pad)) : min(w, int(x2 + pad)),
                ]
                if crop.size:
                    cv2.imwrite(str(output / f"face_{i}.png"), crop)
                    values.append(
                        {
                            "position": i,
                            "bbox": [
                                max(0, x1 / w),
                                max(0, y1 / h),
                                min(1, x2 / w),
                                min(1, y2 / h),
                            ],
                            "file": f"face_{i}.png",
                        }
                    )
            return {"faces": values, "width": frame.shape[1], "height": frame.shape[0]}

        def video_frame(number):
            if not 1 <= number <= count_video_frame_total(request["target"]):
                raise ValueError("영상 범위 안의 프레임 번호를 선택하세요.")
            return checked(
                read_static_video_frame(
                    request["target"], engine_frame_number(number, version)
                )
            )

        operation = request["operation"]
        if operation == "inspect_video":
            result = {
                "frame_count": count_video_frame_total(request["target"]),
                "fps": detect_video_fps(request["target"]),
            }
        elif operation == "analyze_source":
            frame = checked(cv2.imread(request["source"]))
            result = export_faces(frame, faces(frame))
        elif operation == "analyze_reference":
            analysis_frame = (
                request.get("analysis_frame") or settings["reference_frame"]
            )
            frame = video_frame(analysis_frame)
            result = export_faces(frame, faces(frame))
            result["frame_number"] = analysis_frame
            result["frame_count"] = count_video_frame_total(request["target"])
            result["fps"] = detect_video_fps(request["target"])
        else:
            source = checked(cv2.imread(request["source"]))
            source_faces = faces(source)
            if not 0 <= settings["source_position"] < len(source_faces):
                raise ValueError("Source 얼굴을 다시 선택하세요.")
            # A single aligned crop is used by both preview and CLI, avoiding largest-face drift.
            from facefusion.face_helper import warp_face_by_face_landmark_5

            chosen = source_faces[settings["source_position"]]
            cropped, _ = warp_face_by_face_landmark_5(
                source, chosen.landmark_set["5/68"], "arcface_112_v2", (512, 512)
            )
            if len(get_many_faces([cropped])) != 1:
                raise ValueError(
                    "선택한 Source 얼굴을 분리하지 못했습니다. 단독 인물 사진을 사용하세요."
                )
            cropped_path = output.parent / "selected-source.png"
            cv2.imwrite(str(cropped_path), cropped)
            mark("source")
            reference = video_frame(settings["reference_frame"])
            if not 0 <= settings["face_position"] < len(faces(reference)):
                raise ValueError("기준 인물을 다시 선택하세요.")
            mark("reference")
            if operation == "preview":
                target = video_frame(request["preview_frame"])
                matched = (
                    select_faces(reference, [cropped], [target])
                    if version == "3.9.0"
                    else select_faces(reference, target)
                )
                mark("target")
                from facefusion.vision import restrict_frame

                size = request.get("preview_resolution", 1024)
                display = restrict_frame(target, (size, size))
                processed, _ = swapper.process_frame(
                    {
                        "reference_vision_frame": reference,
                        "source_vision_frames": [cropped],
                        "target_vision_frame": target,
                        "target_vision_frames": [target],
                        "temp_vision_frame": display.copy(),
                        "temp_vision_mask": np.ones(display.shape[:2], np.float32),
                    }
                )
                mark("swap")
                cv2.imwrite(str(output / "preview.png"), processed)
                result = {
                    **export_faces(
                        display, faces(target), (target.shape[1], target.shape[0])
                    ),
                    "matched_faces": len(matched),
                    "frame_number": request["preview_frame"],
                    "frame_count": count_video_frame_total(request["target"]),
                    "fps": detect_video_fps(request["target"]),
                }
                mark("images")
                result["timings_ms"] = timings
            elif operation == "render":
                # Free preview/model sessions before launching the full CLI in this process tree.
                from facefusion import inference_manager

                inference_manager.INFERENCE_POOL_SET = {"cli": {}, "ui": {}}
                # A fresh CLI process needs its own CUDA preload on Linux.
                bootstrap = (
                    'import os,runpy,sys; os.environ["OMP_NUM_THREADS"]="1"; '
                    "import onnxruntime as ort; "
                    'ort.preload_dlls(directory="") if os.name != "nt" else None; '
                    'entry=sys.argv.pop(1); runpy.run_path(entry,run_name="__main__")'
                )
                command = [
                    sys.executable,
                    "-c",
                    bootstrap,
                    str(engine / "facefusion.py"),
                    *cli,
                    "-s",
                    str(cropped_path),
                    "-t",
                    request["target"],
                    "-o",
                    str(output / "final.mp4"),
                    "--jobs-path",
                    str(output.parent / "engine-jobs"),
                    "--temp-path",
                    str(output.parent / "temp"),
                    "--output-video-encoder",
                    "h264_nvenc" if settings["video_codec"] == "h264" else "hevc_nvenc",
                ]
                if "chunk" in request:
                    # Keep the original target/reference identity; only extract this interval.
                    command += [
                        "--trim-frame-start",
                        str(request["chunk"]["start"]),
                        "--trim-frame-end",
                        str(request["chunk"]["end"]),
                        "--output-video-fps",
                        str(request["chunk"]["fps"]),
                        "--output-video-quality",
                        "100",
                        "--output-audio-volume",
                        "0",
                    ]
                subprocess.run(command, check=True)
                result = {"file": "final.mp4"}
            else:
                raise ValueError("Unknown operation")
    (output / "result.json").write_text(json.dumps(result), encoding="utf-8")


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--request")
    group.add_argument("--serve")
    args = parser.parse_args()
    if args.request:
        main(args.engine, args.request)
    else:
        inbox = Path(args.serve) / "inbox.json"
        while True:
            if not inbox.exists():
                time.sleep(0.025)
                continue
            message = json.loads(inbox.read_text(encoding="utf-8"))
            inbox.unlink()
            try:
                main(args.engine, message["request"])
                status = {"ok": True}
            except Exception:  # noqa: BLE001 -- isolated engine protocol boundary
                status = {
                    "ok": False,
                    "error": {"code": "gpu_engine_failed", "retryable": False},
                }
            destination = Path(message["response"])
            temporary = destination.with_suffix(".tmp")
            temporary.write_text(json.dumps(status), encoding="utf-8")
            temporary.replace(destination)


if __name__ == "__main__":
    cli()
