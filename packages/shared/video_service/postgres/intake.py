"""Verified original ingestion and immutable workflow storage; never executes jobs."""

from __future__ import annotations

import hashlib
import re
import tempfile
from uuid import uuid4

from psycopg.types.json import Jsonb

from ..content_store import MAX_CONTENT
from ..cpu_agents import digest, ffmpeg, probe, process
from ..renewal_contracts import validate
from . import Conflict, Missing
from .registry import resource_id, text


def request_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise ValueError("요청 식별자 오류")
    return value


def public_upload(row):
    return {
        "upload_id": row["id"],
        "filename": row["filename"],
        "expected_size": row["expected_size"],
        "uploaded_bytes": row["uploaded_bytes"],
        "asset_id": row["asset_id"],
        "status": "COMPLETED" if row["asset_id"] else "UPLOADING",
        "resumable": not bool(row["asset_id"]),
        "created_at": row["created_at"].isoformat(),
    }


def public_asset(row):
    return {
        "asset_id": row["id"],
        "original_filename": row["filename"],
        "size_bytes": row["bytes"],
        "sha256": row["sha256"],
        "content_verified": row["metadata"].get("registration_state") == "verified",
        "media": row["metadata"].get("media"),
        "created_at": row["created_at"].isoformat(),
        "web_preview": row["metadata"].get("web_preview", {"status": "unavailable"}),
        "provenance": {
            "kind": "verified_upload"
            if row["metadata"].get("registration_state") == "verified"
            else "declaration"
        },
    }


class Intake:
    def __init__(self, database, store):
        self.database, self.store = database, store

    def _asset(self, db, owner, identity):
        row = db.execute(
            "SELECT * FROM assets WHERE owner_id=%s AND id=%s",
            (owner, resource_id(identity)),
        ).fetchone()
        if not row:
            raise Missing("원본을 찾을 수 없습니다.")
        return row

    @staticmethod
    def asset_reference(row):
        if (
            row["metadata"].get("registration_state") != "verified"
            or row["storage_key"] != "sha256:" + row["sha256"]
        ):
            raise ValueError("실제 콘텐츠 검증이 끝난 원본이 필요합니다.")
        return {
            "storage_key": "blobs/" + row["sha256"],
            "sha256": row["sha256"],
            "bytes": row["bytes"],
            "type": "video",
        }

    def asset(self, owner, identity):
        with self.database.connection() as db:
            return public_asset(self._asset(db, owner, identity))

    def assets(self, owner):
        with self.database.connection() as db:
            return [
                public_asset(r)
                for r in db.execute(
                    "SELECT * FROM assets WHERE owner_id=%s ORDER BY created_at DESC,id",
                    (owner,),
                )
            ]

    def asset_path(self, owner, identity):
        with self.database.connection() as db:
            reference = self.asset_reference(self._asset(db, owner, identity))
        return self.store.path(owner, reference)

    def thumbnail_path(self, owner, identity):
        with self.database.connection() as db:
            row = self._asset(db, owner, identity)
            reference = row["metadata"].get("thumbnail")
            if reference is None:
                raise Missing("썸네일이 없습니다.")
        return self.store.path(owner, reference)

    def web_preview_path(self, owner, identity):
        with self.database.connection() as db:
            row = self._asset(db, owner, identity)
            state = row["metadata"].get("web_preview", {})
        if (
            state.get("status") != "ready"
            or state.get("source_sha256") != row["sha256"]
        ):
            raise Missing(
                "웹 전용 WebM이 준비되지 않았습니다. 원본은 다운로드할 수 있습니다."
            )
        return self.store.path(owner, state["reference"])

    def upload_create(self, owner, filename, size, nonce):
        request_id(nonce)
        text(filename, 255)
        if (
            "/" in filename
            or "\\" in filename
            or filename in (".", "..")
            or type(size) is not int
            or not 0 < size <= MAX_CONTENT
        ):
            raise ValueError("원본 이름/크기 오류 (최대 256 MiB)")
        sha = digest({"filename": filename, "size": size})
        with self.database.connection() as db:
            db.execute(
                "INSERT INTO source_uploads(owner_id,id,request_id,request_sha256,filename,expected_size) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(owner_id,request_id) DO NOTHING",
                (owner, uuid4().hex, nonce, sha, filename, size),
            )
            row = db.execute(
                "SELECT * FROM source_uploads WHERE owner_id=%s AND request_id=%s",
                (owner, nonce),
            ).fetchone()
            if row["request_sha256"] != sha:
                raise Conflict("같은 요청 ID의 내용이 다릅니다.")
            return public_upload(row)

    def _upload(self, db, owner, identity, *, lock=False):
        row = db.execute(
            "SELECT * FROM source_uploads WHERE owner_id=%s AND id=%s"
            + (" FOR UPDATE" if lock else ""),
            (owner, resource_id(identity)),
        ).fetchone()
        if not row:
            raise Missing("업로드를 찾을 수 없습니다.")
        return row

    def upload_get(self, owner, identity):
        with self.database.connection() as db:
            return public_upload(self._upload(db, owner, identity))

    def uploads(self, owner):
        with self.database.connection() as db:
            return [
                public_upload(r)
                for r in db.execute(
                    "SELECT * FROM source_uploads WHERE owner_id=%s ORDER BY created_at DESC,id",
                    (owner,),
                )
            ]

    def upload_chunk(self, owner, identity, offset, data):
        if (
            type(offset) is not int
            or offset < 0
            or not isinstance(data, bytes)
            or not 0 < len(data) <= 4 * 1024 * 1024
        ):
            raise ValueError("청크 크기/위치 오류")
        with self.database.connection() as db:
            row = self._upload(db, owner, identity, lock=True)
            if row["asset_id"]:
                raise Conflict("이미 등록한 원본의 업로드는 변경할 수 없습니다.")
            previous = db.execute(
                "SELECT reference FROM source_upload_parts WHERE owner_id=%s AND upload_id=%s AND byte_offset=%s",
                (owner, identity, offset),
            ).fetchone()
            sha = hashlib.sha256(data).hexdigest()
            if previous:
                if previous["reference"]["sha256"] != sha or previous["reference"][
                    "bytes"
                ] != len(data):
                    raise Conflict("이미 업로드한 청크와 다릅니다.")
                return public_upload(row)
            if (
                offset != row["uploaded_bytes"]
                or offset + len(data) > row["expected_size"]
            ):
                raise Conflict("서버 업로드 위치와 다릅니다.")
            reference = self.store.put(owner, [data], "upload_part")
            db.execute(
                "INSERT INTO source_upload_parts VALUES (%s,%s,%s,%s)",
                (owner, identity, offset, Jsonb(reference)),
            )
            row = db.execute(
                "UPDATE source_uploads SET uploaded_bytes=uploaded_bytes+%s WHERE owner_id=%s AND id=%s RETURNING *",
                (len(data), owner, identity),
            ).fetchone()
            return public_upload(row)

    def _parts(self, db, owner, identity):
        return [
            r["reference"]
            for r in db.execute(
                "SELECT reference FROM source_upload_parts WHERE owner_id=%s AND upload_id=%s ORDER BY byte_offset",
                (owner, identity),
            )
        ]

    def _blocks(self, owner, references):
        for reference in references:
            with self.store.path(owner, reference).open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    yield block

    def upload_verify(
        self, owner, identity, offset, length, sha256, uploaded_bytes=None
    ):
        if (
            type(offset) is not int
            or type(length) is not int
            or offset < 0
            or not 0 < length <= 4 * 1024 * 1024
            or not isinstance(sha256, str)
            or not re.fullmatch("[a-f0-9]{64}", sha256)
        ):
            raise ValueError("검증 범위 오류")
        with self.database.connection() as db:
            row = self._upload(db, owner, identity)
            if offset + length > row["uploaded_bytes"] or uploaded_bytes not in (
                None,
                row["uploaded_bytes"],
            ):
                raise Conflict("업로드 상태가 변경됐습니다.")
            references = self._parts(db, owner, identity)
        position, remaining, sha = 0, length, hashlib.sha256()
        for block in self._blocks(owner, references):
            start = max(0, offset - position)
            selected = block[start : start + remaining]
            position += len(block)
            sha.update(selected)
            remaining -= len(selected)
            if not remaining:
                break
        if remaining or sha.hexdigest() != sha256:
            raise ValueError("원본 업로드 prefix가 다릅니다.")

    def upload_complete(self, owner, identity):
        with self.database.connection() as db:
            row = self._upload(db, owner, identity, lock=True)
            if row["asset_id"]:
                return public_upload(row)
            if row["uploaded_bytes"] != row["expected_size"]:
                raise Conflict("업로드가 끝나지 않았습니다.")
            reference = self.store.put(
                owner, self._blocks(owner, self._parts(db, owner, identity)), "video"
            )
            media = probe(self.store.path(owner, reference))
            thumbnail = None
            with tempfile.TemporaryDirectory(prefix="mideagent-thumb-") as work:
                from pathlib import Path

                target = Path(work) / "thumbnail.jpg"
                process(
                    [
                        *ffmpeg(),
                        "-i",
                        str(self.store.path(owner, reference)),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=480:-2",
                        "-threads",
                        "1",
                        str(target),
                    ],
                    timeout=10,
                )
                thumbnail = self.store.put(owner, [target.read_bytes()], "image")
            asset_id = uuid4().hex
            metadata = {
                "registration_state": "verified",
                "media": media,
                "media_type": "video/mp4",
                "duration_seconds": media["duration"],
                "thumbnail": thumbnail,
            }
            from ..web_preview import create_preview

            metadata["web_preview"] = create_preview(self.store, owner, reference)
            db.execute(
                "INSERT INTO assets(owner_id,id,filename,storage_key,bytes,sha256,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    owner,
                    asset_id,
                    row["filename"],
                    "sha256:" + reference["sha256"],
                    reference["bytes"],
                    reference["sha256"],
                    Jsonb(metadata),
                ),
            )
            row = db.execute(
                "UPDATE source_uploads SET asset_id=%s WHERE owner_id=%s AND id=%s RETURNING *",
                (asset_id, owner, identity),
            ).fetchone()
            return public_upload(row)

    def ingest(self, owner, filename, data):
        upload = self.upload_create(owner, filename, len(data), uuid4().hex)
        for offset in range(0, len(data), 4 * 1024 * 1024):
            self.upload_chunk(
                owner,
                upload["upload_id"],
                offset,
                data[offset : offset + 4 * 1024 * 1024],
            )
        complete = self.upload_complete(owner, upload["upload_id"])
        return self.asset(owner, complete["asset_id"])

    def _definition(self, db, owner, identity, revision=None):
        identity = resource_id(identity)
        row = db.execute(
            "SELECT wr.* FROM workflows w JOIN workflow_revisions wr ON wr.owner_id=w.owner_id AND wr.workflow_id=w.id AND wr.revision=COALESCE(%s,w.revision) WHERE w.owner_id=%s AND w.id=%s",
            (revision, owner, identity),
        ).fetchone()
        if not row:
            raise Missing("워크플로우 버전을 찾을 수 없습니다.")
        if digest(row["definition"]) != row["sha256"]:
            raise Conflict("워크플로우 무결성 오류")
        return row["definition"]

    def definition(self, owner, identity, revision=None):
        with self.database.connection() as db:
            return self._definition(db, owner, identity, revision)

    def definitions(self, owner):
        with self.database.connection() as db:
            rows = db.execute(
                "SELECT wr.* FROM workflows w JOIN workflow_revisions wr ON wr.owner_id=w.owner_id AND wr.workflow_id=w.id AND wr.revision=w.revision WHERE w.owner_id=%s ORDER BY wr.name,w.id",
                (owner,),
            ).fetchall()
            return [
                {
                    "id": r["workflow_id"],
                    "name": r["name"],
                    "revision": r["revision"],
                    "node_count": len(r["definition"]["nodes"]),
                }
                for r in rows
            ]

    def _bindings(self, db, owner, definition, *, active=True):
        bindings = {}
        for node in definition["nodes"]:
            ref = node.get("model_ref")
            if not ref:
                continue
            model_id = resource_id(ref["model_id"])
            row = db.execute(
                "SELECT mr.*,m.active AS model_active,c.active AS connection_active,cr.endpoint,cr.protocol,cr.credential_ref FROM model_revisions mr JOIN registered_models m ON m.owner_id=mr.owner_id AND m.id=mr.model_id JOIN serving_connections c ON c.owner_id=mr.owner_id AND c.id=mr.connection_id JOIN connection_revisions cr ON cr.owner_id=mr.owner_id AND cr.connection_id=mr.connection_id AND cr.revision=mr.connection_revision WHERE mr.owner_id=%s AND mr.model_id=%s AND mr.revision=%s FOR SHARE OF m,c",
                (owner, model_id, ref["revision"]),
            ).fetchone()
            if not row:
                raise Missing("노드의 등록 모델 버전을 찾을 수 없습니다.")
            if active and (not row["model_active"] or not row["connection_active"]):
                raise Conflict("사용 중지한 모델/연결입니다.")
            bindings[node["id"]] = {
                k: row[k]
                for k in (
                    "model_id",
                    "revision",
                    "remote_model",
                    "connection_id",
                    "connection_revision",
                    "sha256",
                    "endpoint",
                    "protocol",
                    "credential_ref",
                    "model_types",
                    "input_modalities",
                    "output_modalities",
                    "capabilities",
                )
            }
        return bindings

    def save_definition(self, owner, identity, payload, *, provenance=None):
        resource_id(identity)
        validation = validate(payload)
        if not validation["valid"]:
            raise ValueError("워크플로우 연결/필수 입력/옵션을 확인하세요.")
        with self.database.connection() as db:
            db.execute(
                "INSERT INTO workflows(owner_id,id,revision) VALUES (%s,%s,0) ON CONFLICT DO NOTHING",
                (owner, identity),
            )
            row = db.execute(
                "SELECT revision FROM workflows WHERE owner_id=%s AND id=%s FOR UPDATE",
                (owner, identity),
            ).fetchone()
            if row["revision"] != payload["revision"]:
                raise Conflict(
                    "워크플로우가 변경됐습니다. 편집을 보존하고 다시 확인하세요."
                )
            self._bindings(db, owner, payload, active=False)
            result = {
                **payload,
                "id": identity,
                "revision": row["revision"] + 1,
                "name": payload["name"].strip(),
                "executable": False,
            }
            db.execute(
                "INSERT INTO workflow_revisions(owner_id,workflow_id,revision,name,definition,sha256,provenance) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    owner,
                    identity,
                    result["revision"],
                    result["name"],
                    Jsonb(result),
                    digest(result),
                    Jsonb(provenance or {"kind": "editor_save"}),
                ),
            )
            db.execute(
                "UPDATE workflows SET revision=%s WHERE owner_id=%s AND id=%s",
                (result["revision"], owner, identity),
            )
            return result

    def versions(self, owner, identity):
        self.definition(owner, identity)
        with self.database.connection() as db:
            return [
                {
                    "revision": r["revision"],
                    "sha256": r["sha256"],
                    "source": r["provenance"],
                }
                for r in db.execute(
                    "SELECT revision,sha256,provenance FROM workflow_revisions WHERE owner_id=%s AND workflow_id=%s ORDER BY revision",
                    (owner, identity),
                )
            ]

    def restore_definition(self, owner, identity, revision, source_revision):
        if (
            type(revision) is not int
            or type(source_revision) is not int
            or source_revision < 1
        ):
            raise ValueError("복원 버전 오류")
        old = self.definition(owner, identity, source_revision)
        payload = {
            k: old[k]
            for k in ("catalog_version", "revision", "name", "inputs", "nodes", "edges")
        }
        payload["revision"] = revision
        return self.save_definition(
            owner,
            identity,
            payload,
            provenance={
                "kind": "definition_revision",
                "revision": source_revision,
                "sha256": digest(old),
            },
        )
