"""Run the real FaceFusion preview and record its actual active ORT sessions."""

import argparse
import json
import runpy
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_bytes())
    if request["operation"] != "preview":
        raise ValueError("preview_probe_required")
    module = runpy.run_path(str(Path(__file__).with_name("facefusion.py")))
    module["main"](args.engine, args.request)
    from facefusion import inference_manager

    sessions = []
    visited = set()

    def collect(value, path):
        if id(value) in visited:
            return
        visited.add(id(value))
        if hasattr(value, "get_providers"):
            sessions.append({"context": path, "providers": value.get_providers()})
        elif isinstance(value, dict):
            for name, item in value.items():
                collect(item, path + "/" + str(name))
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                collect(item, path + "/" + str(index))

    collect(inference_manager.INFERENCE_POOL_SET, "inference")
    active = [
        value
        for value in sessions
        if value["providers"] and value["providers"][0] == "CUDAExecutionProvider"
    ]
    swapper = [value for value in active if "face_swapper" in value["context"]]
    if not swapper:
        raise ValueError("actual_cuda_swapper_session_required")
    preview = json.loads((Path(request["output"]) / "result.json").read_bytes())
    if preview["matched_faces"] < 1:
        raise ValueError("fixture_face_not_matched")
    proof = {
        "cuda_sessions": len(active),
        "cuda_swapper_sessions": len(swapper),
        "sessions": sessions,
        "fingerprint": request["fingerprint"],
        "matched_faces": preview["matched_faces"],
    }
    (Path(request["output"]).parent / "engine-proof.json").write_text(json.dumps(proof))


if __name__ == "__main__":
    main()
