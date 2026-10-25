"""CAS-backed multi-track human gates and controller-only text exports.

No provider credentials, model calls, worker activation or source/job replacement.
Large track I/O is staged outside the source scheduling lock.
"""

import hashlib
import json
from copy import deepcopy

from psycopg.types.json import Jsonb

from ..cpu_agents import canonical, digest
from ..sami import segments_to_sami
from ..subtitle_tracks import MANIFEST_BYTES, POLICY, TRACK_BYTES, names, normalize
from ..subtitles import segments_to_srt
from ..transcript import TranscriptSegment
from . import Conflict, Missing
from .execution import public
from .registry import resource_id


def selected(snapshot):
    return any(
        node["type"] in {"subtitle_tracks", "subtitle_outputs"}
        or node.get("options", {}).get("review_kind") == "subtitle_tracks_v1"
        for node in snapshot["definition"]["nodes"]
    )


class SubtitleTracks:
    def __init__(self, runtime):
        self.runtime = runtime
        self.store = runtime.store
        self.database = runtime.database

    def read(self, owner, reference, kind, maximum):
        if (
            reference.get("type") != kind
            or type(reference.get("bytes")) is not int
            or not 0 < reference["bytes"] <= maximum
        ):
            raise ValueError("subtitle_reference_budget_or_type")
        raw = self.store.read(owner, reference, limit=maximum)
        if (
            len(raw) != reference["bytes"]
            or hashlib.sha256(raw).hexdigest() != reference["sha256"]
        ):
            raise ValueError("subtitle_material_sha_mismatch")
        return json.loads(raw)

    def put(self, owner, value, kind, maximum):
        raw = canonical(value)
        if len(raw) > maximum:
            raise ValueError("subtitle_serialized_budget_exceeded")
        return self.store.put(owner, [raw], kind)

    def bundle(self, owner, reference, snapshot):
        doc = self.read(owner, reference, "subtitle_tracks", MANIFEST_BYTES)
        if (
            set(doc)
            - {
                "version",
                "policy",
                "source_video_sha256",
                "duration_seconds",
                "tracks",
                "review",
            }
            or doc.get("version") != 1
            or doc.get("policy") != POLICY
            or doc.get("source_video_sha256") != snapshot["asset"]["sha256"]
            or doc.get("duration_seconds") != snapshot["asset"]["media"]["duration"]
            or not isinstance(doc.get("tracks"), dict)
            or not {"original", "translated"} <= set(doc["tracks"])
            or not 2 <= len(doc["tracks"]) <= 6
        ):
            raise ValueError("subtitle_bundle_binding_mismatch")
        total = 0
        for track in doc["tracks"].values():
            rows = self.read(owner, track["transcript"], "transcript", TRACK_BYTES)
            normalize(
                rows, language=track["language"], duration=doc["duration_seconds"]
            )
            total += track["transcript"]["bytes"]
        if total > POLICY["aggregate_track_bytes"]:
            raise ValueError("subtitle_aggregate_budget_exceeded")
        return doc

    def compose(self, job, node, inputs, producers):
        owner = job["owner_id"]
        options = node.get("options", {})
        codes = names(options, inputs)
        tracks = {}
        for port, reference in inputs.items():
            key = (
                port
                if port in {"original", "translated"}
                else "translated." + options[port + "_language"]
            )
            code = codes[key]
            producer = producers[port]
            if port == "original":
                if (
                    producer.get("node_type") != "transcribe"
                    or job["snapshot"]["options"].get("source_language") != code
                ):
                    raise ValueError("original_track_language_or_producer_mismatch")
            elif (
                producer.get("node_type") != "translate"
                or producer["result"].get("translation", {}).get("target_language")
                != code
            ):
                raise ValueError("translated_track_language_or_producer_mismatch")
            rows = self.read(owner, reference, "transcript", TRACK_BYTES)
            normalized, lineage = normalize(
                rows,
                language=code,
                duration=job["snapshot"]["asset"]["media"]["duration"],
                initial=True,
            )
            tracks[key] = {
                "language": code,
                "transcript": self.put(owner, normalized, "transcript", TRACK_BYTES),
                "source_transcript": reference,
                "lineage": self.put(
                    owner, {"source": reference, **lineage}, "metadata", TRACK_BYTES
                ),
                "producer": {
                    "node_id": producer["node_id"],
                    "node_run_id": producer["id"],
                    "request_sha256": producer["request_sha256"],
                    "accepted_result_sha256": digest(producer["result"]),
                },
            }
        doc = {
            "version": 1,
            "policy": deepcopy(POLICY),
            "source_video_sha256": job["snapshot"]["asset"]["sha256"],
            "duration_seconds": job["snapshot"]["asset"]["media"]["duration"],
            "tracks": tracks,
        }
        ref = self.put(owner, doc, "subtitle_tracks", MANIFEST_BYTES)
        self.bundle(owner, ref, job["snapshot"])
        return {"tracks": ref}

    def contract(self, job, reference):
        doc = self.bundle(job["owner_id"], reference, job["snapshot"])
        return {
            "version": 3,
            "kind": "subtitle_tracks_v1",
            "type": "subtitle_tracks",
            "source": reference,
            "phase": "gate",
            "policy": deepcopy(POLICY),
            "duration_seconds": doc["duration_seconds"],
            "source_video_sha256": doc["source_video_sha256"],
            "tracks": doc["tracks"],
            "fields": {
                "type": "object",
                "properties": {
                    "approved": {"type": "boolean", "title": "언어별 자막을 검수했음"}
                },
                "required": ["approved"],
            },
        }

    def export(self, job, node, reference):
        owner = job["owner_id"]
        doc = self.bundle(owner, reference, job["snapshot"])
        files = {}
        outputs = {}
        if not doc.get("review"):
            raise ValueError("subtitle_export_requires_confirmed_review")
        for name, track in doc["tracks"].items():
            rows = self.read(owner, track["transcript"], "transcript", TRACK_BYTES)
            cues = [TranscriptSegment.from_dict(row) for row in rows]
            parts = {}
            texts = {"srt": segments_to_srt(cues)}
            if node.get("options", {}).get("format", "srt") == "srt_smi":
                texts["smi"] = segments_to_sami(
                    cues, "und" if track["language"] == "auto" else track["language"]
                )
            for extension, text in texts.items():
                raw = text.encode("utf-8")
                if len(raw) > TRACK_BYTES:
                    raise ValueError("subtitle_rendered_file_budget_exceeded")
                parts[extension] = {
                    "filename": name + "." + extension,
                    "reference": self.store.put(owner, [raw], "subtitle"),
                }
                if name == "translated":
                    outputs["subtitles" if extension == "srt" else "sami"] = parts[
                        extension
                    ]["reference"]
            files[name] = {
                "language": track["language"],
                "transcript": track["transcript"],
                "lineage": track["lineage"],
                "files": parts,
            }
        outputs["manifest"] = self.put(
            owner,
            {
                "version": 1,
                "kind": "subtitle_outputs_v1",
                "source_bundle": reference,
                "source_video_sha256": doc["source_video_sha256"],
                "review": doc["review"],
                "tracks": files,
            },
            "artifact_manifest",
            MANIFEST_BYTES,
        )
        return outputs

    def preflight(self, owner, identity):
        r = self.runtime
        with self.database.connection() as db:
            job = r._job(db, owner, identity, lock=True)
            if not selected(job["snapshot"]):
                return None
            if job["snapshot"].get("subtitle_tracks_policy") != POLICY:
                raise ValueError("subtitle_policy_not_frozen")
            runs = {row["node_id"]: row for row in r._runs(db, owner, identity)}
            ready = []
            for node in job["snapshot"]["definition"]["nodes"]:
                if node["id"] in runs or not (
                    node["type"] in {"subtitle_tracks", "subtitle_outputs"}
                    or node.get("options", {}).get("review_kind")
                    == "subtitle_tracks_v1"
                ):
                    continue
                edges = [
                    edge
                    for edge in job["snapshot"]["definition"]["edges"]
                    if edge["target"]["node"] == node["id"]
                ]
                states = [(edge, *r._result_for(job, runs, edge)) for edge in edges]
                if not states or any(
                    state != "completed" or not ref for _, state, ref in states
                ):
                    continue
                inputs = {edge["target"]["port"]: ref for edge, _, ref in states}
                producers = {
                    edge["target"]["port"]: runs[edge["source"]["node"]]
                    for edge in edges
                    if edge["source"]["node"] != "$input"
                }
                ready.append((node, inputs, producers))
        staged = {}
        for node, inputs, producers in ready:
            item = {
                "inputs_sha256": digest(inputs),
                "snapshot_sha256": job["snapshot_sha256"],
            }
            if node["type"] == "subtitle_tracks":
                item["outputs"] = self.compose(job, node, inputs, producers)
            elif node["type"] == "subtitle_outputs":
                item["outputs"] = self.export(job, node, inputs["tracks"])
            else:
                item["contract"] = self.contract(job, inputs["value"])
            staged[node["id"]] = item
        return staged

    def review(self, identity, *, owner=None):
        with self.database.connection() as db:
            rows = db.execute(
                "SELECT * FROM review_tasks WHERE id=%s LIMIT 2",
                (resource_id(identity),),
            ).fetchall()
            if len(rows) != 1:
                raise Missing("검수 자료를 찾을 수 없습니다.")
            row = rows[0]
            job = self.runtime._shared_job(db, row["job_id"])
            if owner is not None and row["owner_id"] != owner:
                raise Missing("검수 수정 권한이 없습니다.")
            if row["contract"].get("kind") != "subtitle_tracks_v1":
                raise ValueError("subtitle_review_contract_required")
        return row, job

    def track(self, identity, name):
        row, _ = self.review(identity)
        if name not in row["contract"]["tracks"]:
            raise Missing("자막 언어를 찾을 수 없습니다.")
        value = row["draft"]["tracks"][name]
        cues = self.read(
            row["owner_id"], value["transcript"], "transcript", TRACK_BYTES
        )
        return {
            "review_id": identity,
            "revision": row["revision"],
            "status": row["status"],
            "name": name,
            "language": row["contract"]["tracks"][name]["language"],
            "transcript": value["transcript"],
            "cues": cues,
        }

    def save(self, owner, identity, revision, name, cues):
        row, job = self.review(identity, owner=owner)
        if (
            row["revision"] != revision
            or row["status"] == "confirmed"
            or job["status"] != "review_required"
            or job["cancel_requested"]
        ):
            raise Conflict("검수 버전/상태가 바뀌었습니다. 편집 내용을 보존하세요.")
        if name not in row["contract"]["tracks"]:
            raise Missing("자막 언어를 찾을 수 없습니다.")
        normalized, lineage = normalize(
            cues,
            language=row["contract"]["tracks"][name]["language"],
            duration=row["contract"]["duration_seconds"],
        )
        source = row["draft"]["tracks"][name]["transcript"]
        changed = {
            "transcript": self.put(owner, normalized, "transcript", TRACK_BYTES),
            "lineage": self.put(
                owner, {"source": source, **lineage}, "metadata", TRACK_BYTES
            ),
        }
        with self.database.connection() as db:
            current_job = self.runtime._job(db, owner, row["job_id"], lock=True)
            current = self.runtime._review(db, owner, identity, lock=True)
            if (
                current["revision"] != revision
                or current["status"] == "confirmed"
                or current_job["status"] != "review_required"
                or current_job["cancel_requested"]
            ):
                raise Conflict("검수 상태가 바뀌었습니다. 편집 내용을 보존하세요.")
            draft = deepcopy(current["draft"])
            draft["approved"] = False
            draft["tracks"][name] = changed
            next_revision = revision + 1
            db.execute(
                "INSERT INTO review_revisions VALUES (%s,%s,%s,%s,%s,now())",
                (owner, identity, next_revision, Jsonb(draft), digest(draft)),
            )
            result = db.execute(
                "UPDATE review_tasks SET revision=%s,draft=%s,status='draft' WHERE owner_id=%s AND id=%s RETURNING *",
                (next_revision, Jsonb(draft), owner, identity),
            ).fetchone()
            db.execute(
                "UPDATE jobs SET revision=revision+1 WHERE owner_id=%s AND id=%s",
                (owner, row["job_id"]),
            )
        return public(result)

    def confirm(self, owner, identity, revision):
        row, job = self.review(identity, owner=owner)
        if row["revision"] != revision:
            raise Conflict("최신 저장 검수를 확인하세요.")
        if row["status"] == "confirmed":
            return public(row)
        if (
            job["status"] != "review_required"
            or job["cancel_requested"]
            or row["draft"].get("approved") is not True
        ):
            raise Conflict("저장된 모든 언어와 명시 확인을 먼저 확인하세요.")
        source = row["contract"]["source"]
        doc = self.bundle(owner, source, job["snapshot"])
        for name, value in row["draft"]["tracks"].items():
            cues = self.read(owner, value["transcript"], "transcript", TRACK_BYTES)
            normalize(
                cues,
                language=doc["tracks"][name]["language"],
                duration=doc["duration_seconds"],
            )
            self.read(owner, value["lineage"], "metadata", TRACK_BYTES)
            doc["tracks"][name].update(value)
        confirmed_sha = digest(
            {"draft": row["draft"], "source": source, "revision": revision}
        )
        doc["review"] = {
            "id": identity,
            "revision": revision,
            "confirmed_sha256": confirmed_sha,
        }
        outputs = {"value": self.put(owner, doc, "subtitle_tracks", MANIFEST_BYTES)}
        with self.database.connection() as db:
            current_job = self.runtime._job(db, owner, row["job_id"], lock=True)
            current = self.runtime._review(db, owner, identity, lock=True)
            if current["revision"] != revision:
                raise Conflict("검수 버전이 바뀌었습니다.")
            if current["status"] == "confirmed":
                return public(current)
            if (
                current_job["status"] != "review_required"
                or current_job["cancel_requested"]
                or current["draft"] != row["draft"]
            ):
                raise Conflict("검수 상태가 바뀌었습니다.")
            run = db.execute(
                "SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, row["job_id"], row["node_run_id"]),
            ).fetchone()
            receipt = self.runtime.ticket_artifacts.capture(
                db,
                current_job,
                run,
                {
                    "outputs": outputs,
                    "transport": "human_gate",
                    "review_id": identity,
                    "review_revision": revision,
                    "confirmed_sha256": confirmed_sha,
                },
            )
            db.execute(
                "UPDATE review_tasks SET status='confirmed',confirmed_sha256=%s WHERE owner_id=%s AND id=%s",
                (confirmed_sha, owner, identity),
            )
            db.execute(
                "UPDATE node_runs SET status='completed',result=%s,completed_at=now() WHERE owner_id=%s AND job_id=%s AND id=%s",
                (Jsonb(receipt), owner, row["job_id"], row["node_run_id"]),
            )
            db.execute(
                "UPDATE jobs SET active_claim_id=NULL,revision=revision+1 WHERE owner_id=%s AND id=%s",
                (owner, row["job_id"]),
            )
            return public(self.runtime._review(db, owner, identity))

    def output_manifest(self, identity, run_id):
        with self.database.connection() as db:
            job = self.runtime._shared_job(db, identity)
            runs = self.runtime._runs(db, job["owner_id"], identity)
            run = next(
                (
                    row
                    for row in runs
                    if row["id"] == run_id
                    and row["node_type"] == "subtitle_outputs"
                    and row["status"] == "completed"
                ),
                None,
            )
            if run is None:
                raise Missing("완료된 다국어 산출물을 찾을 수 없습니다.")
        reference = run["result"]["outputs"]["manifest"]
        document = self.read(
            job["owner_id"], reference, "artifact_manifest", MANIFEST_BYTES
        )
        if (
            document.get("kind") != "subtitle_outputs_v1"
            or document.get("source_bundle") != run["inputs"]["tracks"]
        ):
            raise ValueError("subtitle_outputs_binding_mismatch")
        return job, document

    def outputs(self, identity):
        with self.database.connection() as db:
            job = self.runtime._shared_job(db, identity)
            runs = self.runtime._runs(db, job["owner_id"], identity)
            selected_runs = [
                row["id"]
                for row in runs
                if row["node_type"] == "subtitle_outputs"
                and row["status"] == "completed"
            ]
        return {
            "outputs": [
                {"run_id": run_id, **self.output_manifest(identity, run_id)[1]}
                for run_id in selected_runs
            ]
        }

    def file(self, identity, run_id, name, extension):
        job, doc = self.output_manifest(identity, run_id)
        if name not in doc["tracks"] or extension not in doc["tracks"][name]["files"]:
            raise Missing("자막 파일을 찾을 수 없습니다.")
        entry = doc["tracks"][name]["files"][extension]
        reference = entry["reference"]
        if (
            reference.get("type") != "subtitle"
            or not 0 < reference["bytes"] <= TRACK_BYTES
        ):
            raise ValueError("subtitle_file_budget_or_type")
        raw = self.store.read(job["owner_id"], reference, limit=TRACK_BYTES)
        if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            raise ValueError("subtitle_file_sha_mismatch")
        return self.store.path(job["owner_id"], reference), entry["filename"]
