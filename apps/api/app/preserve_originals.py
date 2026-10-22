"""Explicit preservation operator. No account creation, overwrite, delete or replay."""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from psycopg.types.json import Jsonb
from video_service.postgres import Database
from video_service.postgres.registry import resource_id

from app.operator import runtime_components
from app.server import load_bootstrap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-file", required=True)
    parser.add_argument("--manifest-file", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--approval-message", required=True)
    parser.add_argument("--import-preserved-originals", action="store_true")
    args = parser.parse_args()
    if not args.import_preserved_originals:
        parser.error("Explicit preservation import approval is required")
    resource_id(args.actor_id)
    root = Path(args.source_root).resolve(strict=True)
    evidence = Path(args.evidence_root)
    assert evidence.is_absolute() and evidence.is_dir()
    manifest = json.loads(Path(args.manifest_file).read_text())
    assert isinstance(manifest, list) and len(manifest) == 17
    assert len({row["id"] for row in manifest}) == 17
    config, dsn = load_bootstrap(args.bootstrap_file)
    database = Database(dsn)
    store, _, _ = runtime_components(database, config)
    assert store.storage_kind == "s3"
    with database.connection() as db:
        actor = db.execute(
            "SELECT id,role,active FROM accounts WHERE id=%s", (args.actor_id,)
        ).fetchone()
        assert actor and actor["active"] and actor["role"] == "admin"
    for item in manifest:
        identity = resource_id(item["id"])
        source = root / identity / item["source_filename"]
        descriptor = root / identity / "asset.json"
        assert source.resolve().is_relative_to(root) and not source.is_symlink()
        metadata = json.loads(descriptor.read_text())
        assert (
            metadata["asset_id"] == identity
            and metadata["owner_id"] == item["owner_id"]
        )
        source_before = source.stat()
        assert source_before.st_size == item["bytes"] == metadata["size_bytes"]
        assert (
            hashlib.sha256(descriptor.read_bytes()).hexdigest()
            == item["asset_json_sha256"]
        )
        with source.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        origin = {
            "namespace": "legacy/windows-original",
            "record_id": identity + "/asset.json",
            "original_owner_id": item["owner_id"],
            "imported_by": args.actor_id,
            "approval_message": args.approval_message,
            "source_asset_json_sha256": item["asset_json_sha256"],
        }
        # SQL owner_id is the existing operator's storage custody namespace, NOT a
        # fabricated original uploader. public_asset returns the original owner.
        with database.connection() as db:
            archived = db.execute(
                "SELECT payload FROM legacy_archive_records WHERE namespace=%s AND kind='asset' AND record_id=%s",
                (origin["namespace"], origin["record_id"]),
            ).fetchone()
            assert archived and archived["payload"]["asset_id"] == identity
            assert archived["payload"]["owner_id"] == item["owner_id"]
            previous = db.execute(
                "SELECT * FROM assets WHERE id=%s", (identity,)
            ).fetchall()
            if previous:
                assert len(previous) == 1 and previous[0]["owner_id"] == args.actor_id
                assert (
                    previous[0]["sha256"] == sha
                    and previous[0]["bytes"] == item["bytes"]
                )
                assert previous[0]["metadata"]["legacy_origin"] == origin
                print(
                    json.dumps({"asset_id": identity, "phase": "already_registered"}),
                    flush=True,
                )
                continue
        intent = {
            "asset_id": identity,
            "phase": "uploading",
            "source_sha256": sha,
            "bytes": item["bytes"],
            "original_owner_id": item["owner_id"],
            "custodian": args.actor_id,
        }
        journal = evidence / (identity + ".json")
        journal.write_text(json.dumps(intent, indent=2))
        ref = store.import_original_file(
            args.actor_id, source, sha256=sha, byte_count=item["bytes"]
        )
        result = {
            "registration_state": "verified",
            "media": metadata["media"],
            "legacy_origin": origin,
            "media_type": "video/mp4",
            "web_preview": {"status": "unavailable"},
        }
        thumbnail = source.parent / "thumbnail-v1.jpg"
        if thumbnail.is_file():
            with thumbnail.open("rb") as stream:
                result["thumbnail"] = store.put(
                    args.actor_id, iter(lambda: stream.read(1024 * 1024), b""), "image"
                )
        with tempfile.TemporaryDirectory(dir=evidence) as temp:
            preview = Path(temp) / "preserved-preview.webm"
            cmd = [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(source),
                "-t",
                "30",
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                "scale=w=min(960\\,iw):h=-2,fps=15",
                "-c:v",
                "libvpx-vp9",
                "-b:v",
                "650k",
                "-deadline",
                "realtime",
                "-cpu-used",
                "8",
                "-row-mt",
                "1",
                "-threads",
                "2",
                "-c:a",
                "libopus",
                "-b:a",
                "64k",
                "-y",
                str(preview),
            ]
            generated = subprocess.run(
                cmd, capture_output=True, timeout=180, check=False
            )
            if (
                generated.returncode == 0
                and preview.is_file()
                and preview.stat().st_size
            ):
                with preview.open("rb") as stream:
                    derivative = store.put(
                        args.actor_id,
                        iter(lambda: stream.read(1024 * 1024), b""),
                        "video",
                    )
                result["web_preview"] = {
                    "status": "ready",
                    "profile": "preserved-excerpt-vp9-opus-v1",
                    "source_sha256": sha,
                    "reference": derivative,
                    "excerpt_seconds": 30,
                }
            else:
                result["web_preview"] = {
                    "status": "failed",
                    "error_code": "preserved_excerpt_unavailable",
                    "source_sha256": sha,
                }
        with database.connection() as db:
            db.execute(
                "INSERT INTO assets(owner_id,id,filename,storage_key,bytes,sha256,metadata,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    args.actor_id,
                    identity,
                    item["filename"],
                    "sha256:" + sha,
                    item["bytes"],
                    sha,
                    Jsonb(result),
                    item["created_at"],
                ),
            )
        intent.update(
            phase="registered",
            remote_bytes_verified=True,
            storage_key=ref["storage_key"],
            preview_status=result["web_preview"]["status"],
            source_stat_preserved=source.stat().st_mtime_ns == source_before.st_mtime_ns,
        )
        assert intent["source_stat_preserved"]
        journal.write_text(json.dumps(intent, indent=2))
        print(json.dumps(intent), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 -- operator boundary must never print private DSNs/SDK values
        # Database/SDK exceptions can contain credentials; emit only fixed/type codes.
        print(json.dumps({"status": "blocked", "code": "preservation_import_stopped",
                          "error_type": type(error).__name__,
                          "sqlstate": getattr(error, "sqlstate", None)}), flush=True)
        raise SystemExit(2) from None
