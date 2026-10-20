"""Private JSON-line CPU instance; no DB, queue, shell, model or network listener."""

import argparse
import json
import os
import sys

from video_service.content_store import ContentStore
from video_service.cpu_agents import CPU_AGENTS, canonical, run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", required=True, choices=sorted(CPU_AGENTS))
    parser.add_argument("--content-root", required=True)
    args = parser.parse_args()
    store = ContentStore(args.content_root)
    # Verify the binary requirements without loading an engine/provider.
    import shutil

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("CPU media binaries unavailable")
    sys.stdout.buffer.write(
        canonical({"event": "ready", "agent_id": args.agent, "pid": os.getpid()})
        + b"\n"
    )
    sys.stdout.buffer.flush()
    while raw := sys.stdin.buffer.readline(65537):
        try:
            if len(raw) > 65536 or not raw.endswith(b"\n"):
                raise ValueError("Invalid envelope size")
            envelope = json.loads(raw)
            if set(envelope) != {"owner", "command"}:
                raise ValueError("Invalid envelope")
            root = store.owner_root(envelope["owner"])
            attempts = root / "attempts"
            if attempts.is_symlink():
                raise ValueError("Invalid attempt directory")
            attempts.mkdir(mode=0o700, exist_ok=True)
            result = run(envelope["command"], root, attempts, agent=args.agent)
            result["transport"] = "subprocess"
            result["process_exit_code"] = 0 if result["status"] == "completed" else 1
        except Exception:  # noqa: BLE001 -- do not expose input, paths or environment
            result = {
                "status": "failed",
                "error": {"code": "cpu_instance_protocol_error", "retryable": False},
            }
        sys.stdout.buffer.write(canonical(result) + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
