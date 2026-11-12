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
# Storage/read boundary is separate from the unchanged upload/processing bound.
MAX_STORED_CONTENT = 8 * 1024 * 1024 * 1024


def valid_content_key(key, sha):
    if not isinstance(key, str) or not isinstance(sha, str) or not HEX.fullmatch(sha):
        return False
    if key == "blobs/" + sha:
        return True
    return bool(
        re.fullmatch(
            r"tickets/[a-f0-9]{32}/(?:manifests/" + sha + r"\.json|"
            r"nodes/[a-f0-9]{64}/attempts/[a-f0-9]{32}/(?:outputs|previews)/[a-z_][a-z0-9_]{0,49}/"
            + sha
            + r")",
            key,
        )
    )


def reference_origin(owner, reference):
    """Resolve a server-pinned input namespace without changing its blob key/hash."""
    if not isinstance(owner, str) or not ID.fullmatch(owner):
        raise ValueError("Invalid owner")
    base = {"storage_key", "sha256", "bytes", "type"}
    if not isinstance(reference, dict) or set(reference) not in (
        base,
        base | {"source_owner_id"},
    ):
        raise ValueError("Invalid content reference")
    source = reference.get("source_owner_id", owner)
    if not isinstance(source, str) or not ID.fullmatch(source):
        raise ValueError("Invalid source owner")
    return source, {k: reference[k] for k in base}


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
        owner, reference = reference_origin(owner, reference)
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
            or not valid_content_key(reference["storage_key"], sha)
        ):
            raise ValueError("Invalid opaque content key")
        if (
            type(reference["bytes"]) is not int
            or not 0 < reference["bytes"] <= MAX_STORED_CONTENT
        ):
            raise ValueError("Invalid content size")
        root = self.owner_root(owner)
        path = root
        for part in reference["storage_key"].split("/"):
            path = path / part
            if path.is_symlink():
                raise ValueError("Symlink storage denied")
        if not path.is_file():
            raise ValueError("Content unavailable")
        with path.open("rb") as stream:
            digest = hashlib.sha256()
            size = 0
            while block := stream.read(1024 * 1024):
                size += len(block)
                if size > MAX_STORED_CONTENT:
                    raise ValueError("Content size exceeded")
                digest.update(block)
        if size != reference["bytes"] or digest.hexdigest() != sha:
            raise ValueError("Content integrity mismatch")
        return path

    def bind_ticket(self, owner, key, reference):
        """Publish an immutable ticket path without duplicating local CAS bytes."""
        if (
            not isinstance(reference, dict)
            or not valid_content_key(key, reference.get("sha256"))
            or not key.startswith("tickets/")
        ):
            raise ValueError("Invalid ticket content key")
        source = self.path(owner, reference)
        parent = self.owner_root(owner)
        for part in key.split("/")[:-1]:
            parent = parent / part
            if parent.is_symlink():
                raise ValueError("Symlink storage denied")
            parent.mkdir(mode=0o700, exist_ok=True)
        target = parent / key.split("/")[-1]
        if target.is_symlink():
            raise ValueError("Symlink storage denied")
        try:
            os.link(source, target)
        except FileExistsError:
            pass
        value = {k: reference[k] for k in ("sha256", "bytes", "type")}
        value["storage_key"] = key
        self.path(owner, value)
        return value

    def put(self, owner, blocks, kind, *, max_bytes=MAX_CONTENT):
        if type(max_bytes) is not int or not 0 < max_bytes <= MAX_STORED_CONTENT:
            raise ValueError("Invalid explicit storage bound")
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
                    if size > max_bytes:
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

    def _subtitle_copy_directory(self):
        directory = self.root / 'subtitle-copies'
        if directory.is_symlink():
            raise ValueError('Symlink storage denied')
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory

    def _start_queue_directory(self):
        directory = self.root / 'start-queues'
        if directory.is_symlink():
            raise ValueError('Symlink storage denied')
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory

    def read_start_queue(self, owner):
        from .start_queue_policy import identity, MAX_POLICY_BYTES, decode_policy, QueueUnavailable
        path = self._start_queue_directory() / (identity(owner) + '.json')
        if path.is_symlink():
            raise ValueError('Symlink storage denied')
        try:
            with path.open('rb') as stream:
                raw = stream.read(MAX_POLICY_BYTES + 1)
        except FileNotFoundError:
            return None, None
        try:
            decode_policy(raw, owner)
        except ValueError:
            raise QueueUnavailable('대기열 저장 기록을 확인하지 못했습니다.') from None
        return raw, hashlib.sha256(raw).hexdigest()

    def list_start_queue_owners(self, after=None):
        import heapq
        from .start_queue_policy import identity
        if after is not None:
            identity(after)
        with os.scandir(self._start_queue_directory()) as entries:
            ids = heapq.nsmallest(21, (
                entry.name[:-5] for entry in entries
                if re.fullmatch(r'[a-f0-9]{32}\.json', entry.name)
                and entry.name[:-5] > (after or '')
            ))
        return ids[:20], len(ids) > 20

    def write_start_queue(self, owner, raw, token):
        from .start_queue_policy import identity, decode_policy, QueueConflict
        decode_policy(raw, identity(owner))
        directory = self._start_queue_directory()
        lock_path = directory / (owner + '.lock')
        if lock_path.is_symlink():
            raise ValueError('Symlink storage denied')
        # Local-mode policy CAS is also serialized across local API processes.
        # S3 overrides both hooks and never falls back to this local authority.
        with lock_path.open('a+b') as guard:
            if os.name == 'nt':
                import msvcrt
                guard.seek(0)
                if not guard.read(1):
                    guard.write(b'0')
                    guard.flush()
                guard.seek(0)
                msvcrt.locking(guard.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
            try:
                if self.read_start_queue(owner)[1] != token:
                    raise QueueConflict('대기열이 바뀌었습니다. 다시 확인하세요.')
                fd, name = tempfile.mkstemp(prefix='.incoming-', dir=directory)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(name, directory / (owner + '.json'))
                finally:
                    if os.path.exists(name):
                        os.unlink(name)
            finally:
                if os.name == 'nt':
                    guard.seek(0)
                    msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(guard.fileno(), fcntl.LOCK_UN)
        stored, next_token = self.read_start_queue(owner)
        if stored != raw:
            raise QueueConflict('대기열 저장 결과가 바뀌었습니다. 다시 확인하세요.')
        return next_token

    def read_subtitle_copy(self, id):
        from .subtitle_copies import identity, MAX_RECEIPT
        path = self._subtitle_copy_directory() / (identity(id) + '.json')
        if path.is_symlink():
            raise ValueError('Symlink storage denied')
        with path.open('rb') as stream:
            raw = stream.read(MAX_RECEIPT + 1)
        if not 0 < len(raw) <= MAX_RECEIPT:
            raise ValueError('Subtitle copy receipt size exceeded')
        return raw

    def create_subtitle_copy(self, id, raw):
        from .subtitle_copies import identity, decode_receipt
        decode_receipt(raw, identity(id))
        directory = self._subtitle_copy_directory()
        fd, name = tempfile.mkstemp(prefix='.incoming-', dir=directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(name, directory / (id + '.json'))
            except FileExistsError:
                pass
        finally:
            os.unlink(name)
        return self.read_subtitle_copy(id)

    def list_subtitle_copies(self, after=None):
        import heapq
        from .subtitle_copies import PAGE_SIZE, identity
        if after is not None:
            identity(after)
        with os.scandir(self._subtitle_copy_directory()) as entries:
            ids = heapq.nsmallest(PAGE_SIZE + 1, (
                entry.name[:-5] for entry in entries
                if re.fullmatch(r'[a-f0-9]{32}\.json', entry.name)
                and entry.name[:-5] > (after or '')
            ))
        return ids[:PAGE_SIZE], len(ids) > PAGE_SIZE
