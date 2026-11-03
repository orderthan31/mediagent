"""Build-time tokenizer resources. Never download while serving a model request."""
import hashlib
import os
from pathlib import Path

RESOURCES = {
    "cl100k_base": "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
    "o200k_base": "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
}


def resource(name):
    url = "https://openaipublic.blob.core.windows.net/encodings/" + name + ".tiktoken"
    return url, hashlib.sha1(url.encode()).hexdigest()


def verify(directory=None):
    root = Path(directory or os.environ.get("CUSTOM_TIKTOKEN_CACHE_DIR", ""))
    for name, digest in RESOURCES.items():
        _, key = resource(name)
        path = root / key
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("SDK offline tokenizer cache missing or invalid")
    return root


def build(directory):
    """Explicit package/image build command only; no runtime caller."""
    import urllib.request
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    for name, digest in RESOURCES.items():
        url, key = resource(name)
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(8 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Tokenizer build resource checksum mismatch")
        (root / key).write_bytes(data)
    verify(root)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m mideagent_model_tools.sdk_cache BUILD_DIRECTORY")
    build(sys.argv[1])
