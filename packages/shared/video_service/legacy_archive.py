"""Explicit read-only legacy inventory. Never assigns owners or runs old jobs."""

from contextlib import closing
import hashlib
import json
import re
import sqlite3
from pathlib import Path

SECRET = re.compile(
    r"(?:^|_)(?:api_?keys?|credentials?|passwords?|secrets?|tokens?|authorization|cookies?|csrf)(?:_|$)",
    re.I,
)


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def sanitized(value):
    if isinstance(value, dict):
        return {
            key: "[preserved privately; disabled]"
            if SECRET.search(key)
            else sanitized(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitized(item) for item in value]
    return value


def build_manifest(root, index_root, *, namespace):
    root, index_root = Path(root).resolve(), Path(index_root).resolve()
    if not re.fullmatch(r"legacy/[A-Za-z0-9_.:/-]{1,160}", namespace):
        raise ValueError("explicit_legacy_namespace_required")
    records, index_counts = [], {}

    def record(kind, identity, raw, *, scope=namespace, references=()):
        data = json.loads(raw)
        payload = sanitized(data)
        if kind == "settings":
            payload = {"state": "disabled_unresolved", "settings": payload}
        metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
        records.append(
            {
                "namespace": scope,
                "kind": kind,
                "record_id": identity,
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "classification": "legacy/unassigned",
                "internal": bool(metadata.get("internal")),
                "legacy_state": data.get("status") if isinstance(data, dict) else None,
                "payload": payload,
                "references": list(references),
            }
        )

    for path in sorted(root.glob("*/job.json")):
        if not re.fullmatch(r"[a-f0-9]{32}", path.parent.name):
            continue
        references = []
        for artifact in sorted(path.parent.rglob("*")):
            if not artifact.is_file() or artifact.name.endswith(".lock"):
                continue
            resolved = artifact.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError("legacy_reference_outside_source")
            references.append(
                {
                    "path": str(artifact.relative_to(root)).replace("\\", "/"),
                    "bytes": artifact.stat().st_size,
                }
            )
        record("job", path.parent.name, path.read_bytes(), references=references)
    for name, kind in [
        (".workflow-definitions", "workflow"),
        (".llm-settings", "settings"),
        (".assets", "asset"),
    ]:
        for path in sorted((root / name).rglob("*.json")):
            # Preserve named metadata, not huge derived arbitrary diagnostic JSON.
            if kind == "asset" and path.name != "asset.json":
                continue
            identity = str(path.relative_to(root / name)).replace("\\", "/")
            record(kind, identity, path.read_bytes())
    for path in sorted(index_root.rglob("*.sqlite3")):
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("legacy_sqlite_integrity_failed")
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
            ).fetchone():
                continue
            rows = db.execute("SELECT id,data FROM jobs ORDER BY id").fetchall()
            index_counts[path.name] = len(rows)
            for identity, data in rows:
                record(
                    "index",
                    identity,
                    data.encode() if isinstance(data, str) else data,
                    scope=namespace + "/index/" + path.stem,
                )
    records.sort(key=lambda row: (row["namespace"], row["kind"], row["record_id"]))
    result = {
        "version": 1,
        "namespace": namespace,
        "index_counts": index_counts,
        "records": records,
    }
    result["snapshot_id"] = hashlib.sha256(canonical(result)).hexdigest()
    return result
