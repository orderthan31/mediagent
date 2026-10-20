"""Fixed-role console entrypoints backed by the shared versioned command contract."""

import sys

from video_service.cpu_agents import main


def _run(kind):
    if any(arg == "--agent" or arg.startswith("--agent=") for arg in sys.argv[1:]):
        raise SystemExit("The executable fixes the agent role; --agent is not accepted")
    return main(["--agent", kind, *sys.argv[1:]])


def analyze():
    return _run("analyze")


def extract_audio():
    return _run("extract_audio")


def generate_subtitle():
    return _run("generate_subtitle")


def encode():
    return _run("encode")


def validate_video():
    return _run("validate_video")
