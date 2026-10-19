"""Explicit private content root. No legacy paths, URL fetches or deletion API."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

HEX = re.compile(r"[a-f0-9]{64}\Z")
ID = re.compile(r"[a-f0-9]{32}\Z")
MAX_CONTENT = 256 * 1024 * 1024


class ContentStore:
    storage_kind = "local"

    def __init__(self, root):
        path = Path(root)
        if not path.is_absolute() or path.is_symlink() or not path.is_dir():
            raise ValueError("Explicit existing private content root required")
        self.root = path.resolve(strict=True)

    def owner_root(self, owner):
        if not isinstance(owner, str) or not ID.fullmatch(owner):
            raise ValueError("Invalid owner")
        path = self.root / owner
        if path.is_symlink():
            raise ValueError("Symlink storage denied")
        path.mkdir(mode=0o700, exist_ok=True)
        return path

    def path(self, owner, reference):
        if not isinstance(reference, dict) or set(reference) != {
            "storage_key",
            "sha256",
            "bytes",
            "type",
        }:
            raise ValueError("Invalid content reference")
        sha = reference["sha256"]
        if (
            not isinstance(sha, str)
            or not HEX.fullmatch(sha)
            or reference["storage_key"] != "blobs/" + sha
        ):
            raise ValueError("Invalid opaque content key")
        if (
            type(reference["bytes"]) is not int
            or not 0 < reference["bytes"] <= MAX_CONTENT
        ):
            raise ValueError("Invalid content size")
        root = self.owner_root(owner)
        directory = root / "blobs"
        path = directory / sha
        if directory.is_symlink() or path.is_symlink() or not path.is_file():
            raise ValueError("Content unavailable")
        with path.open("rb") as stream:
            digest = hashlib.sha256()
            size = 0
            while block := stream.read(1024 * 1024):
                size += len(block)
                if size > MAX_CONTENT:
                    raise ValueError("Content size exceeded")
                digest.update(block)
        if size != reference["bytes"] or digest.hexdigest() != sha:
            raise ValueError("Content integrity mismatch")
        return path

    def put(self, owner, blocks, kind):
        root = self.owner_root(owner)
        directory = root / "blobs"
        if directory.is_symlink():
            raise ValueError("Symlink storage denied")
        directory.mkdir(mode=0o700, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        fd, name = tempfile.mkstemp(prefix=".incoming-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                for block in blocks:
                    if not isinstance(block, bytes):
                        raise ValueError("Binary content required")  # noqa: TRY004 -- public validation contract uses ValueError
                    size += len(block)
                    if size > MAX_CONTENT:
                        raise ValueError("Content size exceeded")
                    digest.update(block)
                    stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
            if size == 0:
                raise ValueError("Empty content denied")
            sha = digest.hexdigest()
            target = directory / sha
            # Never overwrite an existing blob. Trusted root is not user-writable.
            try:
                os.link(name, target)
                target.chmod(0o400)
            except FileExistsError:
                pass
            reference = {
                "storage_key": "blobs/" + sha,
                "sha256": sha,
                "bytes": size,
                "type": kind,
            }
            ContentStore.path(self, owner, reference)
            return reference
        finally:
            # Only the temporary file created by this invocation is removed.
            os.unlink(name)

    def read(self, owner, reference, *, limit=1024 * 1024):
        if reference["bytes"] > limit:
            raise ValueError("Structured content size exceeded")
        with self.path(owner, reference).open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit or hashlib.sha256(data).hexdigest() != reference["sha256"]:
            raise ValueError("Structured content integrity mismatch")
        return data
