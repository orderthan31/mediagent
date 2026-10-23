"""Explicit independent preview runner. No API background queue or native slot."""

from contextlib import contextmanager
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from .postgres import Conflict


class PreviewWorker:
    def __init__(self, previews, cache_root):
        self.previews, self.database = previews, previews.database
        self.cache_root = cache_root
        self.instance = uuid4().hex
        self.guard = None
        self.held = False
        self.guard_lost = False

    @contextmanager
    def exclusive(self):
        if self.guard_lost:
            raise Conflict("Lost preview owner cannot reconnect or re-enroll")
        with psycopg.connect(
            self.database.dsn, autocommit=True, row_factory=dict_row, connect_timeout=5
        ) as guard:
            locked = guard.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(current_database()||':'||current_schema()||':full-video-preview-v1',0)) AS yes"
            ).fetchone()["yes"]
            if not locked:
                raise Conflict("Another full preview process owns the single runner")
            self.guard = guard
            try:
                with self._owned() as db:
                    db.execute(
                        "UPDATE video_preview_jobs SET state='held',stage='held',error_code='previous_worker_session_lost',finished_at=now() WHERE state='running'"
                    )
                    self.held = db.execute(
                        "SELECT EXISTS(SELECT 1 FROM video_preview_jobs WHERE state='held') AS yes"
                    ).fetchone()["yes"]
                yield self
            finally:
                self.guard = None

    @contextmanager
    def _owned(self):
        # The guarded backend also executes AND commits every worker SQL action.
        # Session death aborts that same transaction, not a separate check/use peer.
        if self.guard is None or self.guard_lost:
            raise Conflict("A live preview ownership session is required")
        try:
            with self.guard.transaction():
                self.guard.execute("SET LOCAL statement_timeout = '15s'")
                self.guard.execute("SET LOCAL lock_timeout = '5s'")
                owned = self.guard.execute(
                    """WITH k AS (
                        SELECT hashtextextended(current_database()||':'||current_schema()||':full-video-preview-v1',0) AS key
                    ) SELECT EXISTS (
                        SELECT 1 FROM pg_locks l,k
                        WHERE l.locktype='advisory' AND l.pid=pg_backend_pid()
                        AND l.granted AND l.mode='ExclusiveLock' AND l.objsubid=1
                        AND l.classid::bigint=((k.key >> 32) & 4294967295)
                        AND l.objid::bigint=(k.key & 4294967295)
                        AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database())
                    ) AS yes"""
                ).fetchone()["yes"]
                if not owned:
                    raise Conflict("Preview ownership lock is no longer held")
                yield self.guard
        except (psycopg.Error, Conflict):
            self.guard_lost = True
            self.held = True
            raise Conflict(
                "Preview ownership lost; no reconnect, claim or adoption"
            ) from None

    def claim_next(self):
        if self.guard is None:
            raise Conflict("Preview worker exclusive session is required")
        # A lost worker may still have an unproven child. Do not overlap it.
        if self.held:
            return None
        with self._owned() as db:
            if db.execute(
                "SELECT EXISTS(SELECT 1 FROM video_preview_jobs WHERE state IN ('running','held')) AS yes"
            ).fetchone()["yes"]:
                return None
            row = db.execute(
                "SELECT * FROM video_preview_jobs WHERE state='queued' AND NOT cancel_requested ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED"
            ).fetchone()
            if row is None:
                return None
            return db.execute(
                "UPDATE video_preview_jobs SET state='running',stage='loading',claim_count=1,worker_instance=%s,started_at=now() WHERE id=%s RETURNING *",
                (self.instance, row["id"]),
            ).fetchone()

    def _current(self, row):
        with self._owned() as db:
            current = db.execute(
                "SELECT * FROM video_preview_jobs WHERE id=%s", (row["id"],)
            ).fetchone()
            if (
                not current
                or current["worker_instance"] != self.instance
                or current["state"] != "running"
            ):
                raise Conflict("Preview attempt fence changed")
            return current, self.previews.binding_matches(db, current)

    def _finish(self, row, state, reference=None, media=None, error=None):
        from psycopg.types.json import Jsonb

        with self._owned() as db:
            current = db.execute(
                "SELECT * FROM video_preview_jobs WHERE id=%s FOR UPDATE", (row["id"],)
            ).fetchone()
            if (
                not current
                or current["state"] != "running"
                or current["worker_instance"] != self.instance
            ):
                raise Conflict("Preview finalization fence changed")
            if current["cancel_requested"]:
                state, error = "cancelled", "preview_cancelled"
            elif not self.previews.binding_matches(db, current):
                state, error = "held", "preview_source_changed"
            db.execute(
                "UPDATE video_preview_jobs SET state=%s,stage=CASE WHEN %s='held' THEN 'held' ELSE 'finished' END,output_ref=%s,output_media=%s,verified_at=CASE WHEN %s THEN now() ELSE NULL END,finished_at=now(),error_code=%s WHERE id=%s",
                (
                    state,
                    state,
                    Jsonb(reference) if reference else None,
                    Jsonb(media) if media else None,
                    reference is not None,
                    error,
                    row["id"],
                ),
            )
        if state == "held":
            self.held = True

    def _stage(self, row, stage):
        with self._owned() as db:
            if (
                db.execute(
                    "UPDATE video_preview_jobs SET stage=%s WHERE id=%s AND worker_instance=%s AND state='running'",
                    (stage, row["id"], self.instance),
                ).rowcount
                != 1
            ):
                raise Conflict("Preview stage fence changed")

    def process(self, row):
        import hashlib
        import os
        import shutil
        import subprocess
        import time
        from pathlib import Path
        from .cpu_agents import ffmpeg, probe
        from .postgres.video_previews import FULL_PROFILE
        from .object_store import S3ContentStore, ObjectStoreError

        if (
            self.guard is None
            or self.guard_lost
            or row["worker_instance"] != self.instance
        ):
            raise Conflict("Owned preview worker session required")
        profile = row["profile"]
        if profile != FULL_PROFILE:
            self._finish(row, "held", error="unsupported_frozen_preview_profile")
            return
        cache = Path(self.cache_root)
        if not cache.is_absolute() or cache.is_symlink() or not cache.is_dir():
            raise ValueError("Private preview disk required")
        if (
            any(cache.glob("full-preview-*"))
            or shutil.disk_usage(cache).free < profile["cache_bytes"]
        ):
            self._finish(row, "held", error="preview_disk_requires_review")
            self.held = True
            return
        child = None
        deadline = time.monotonic() + profile["wall_seconds"]
        with (
            self._wall_budget(profile["wall_seconds"]),
            self._workspace(cache) as work,
        ):
            base = self.previews.store
            (work / "cache").mkdir(exist_ok=True)
            store = (
                S3ContentStore(
                    base.client, base.bucket, work / "cache", prefix=base.prefix
                )
                if getattr(base, "storage_kind", None) == "s3"
                else base
            )
            try:
                current, eligible = self._current(row)
                if current["cancel_requested"] or not eligible:
                    self._finish(
                        row,
                        "cancelled" if current["cancel_requested"] else "held",
                        error="preview_source_unavailable",
                    )
                    return
                source = store.path(row["storage_owner_id"], row["source_ref"])
                original = probe(source)
                if (
                    not 0 < original["duration"] <= profile["max_duration_seconds"]
                    or not 0 < original["width"] <= 4096
                    or not 0 < original["height"] <= 4096
                    or original["width"] * original["height"] > profile["max_pixels"]
                ):
                    raise ValueError("Native preview source budget exceeded")
                target = work / "full.webm"
                args = [
                    *ffmpeg(),
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-sn",
                    "-dn",
                    "-vf",
                    "scale=w=min(960\\,iw):h=min(720\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2,fps=15",
                    "-c:v",
                    "libvpx-vp9",
                    "-threads",
                    "1",
                    "-deadline",
                    "good",
                    "-cpu-used",
                    "4",
                    "-crf",
                    "36",
                    "-b:v",
                    "0",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "64k",
                    "-map_metadata",
                    "-1",
                    "-fs",
                    str(profile["max_output_bytes"] + 1024 * 1024),
                    "-f",
                    "webm",
                    str(target),
                ]
                with self._owned():
                    current, eligible = self._current(row)
                    if current["cancel_requested"] or not eligible:
                        self._finish(
                            row,
                            "cancelled" if current["cancel_requested"] else "held",
                            error="preview_source_unavailable_before_native",
                        )
                        return
                    child = subprocess.Popen(
                        args,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env={
                            **{
                                k: v
                                for k, v in os.environ.items()
                                if k in ("PATH", "LANG", "HOME", "FONTCONFIG_PATH")
                            },
                            "TMPDIR": str(work),
                        },
                    )
                    self._stage(row, "encoding")
                while child.poll() is None:
                    current, eligible = self._current(row)
                    if current["cancel_requested"] or not eligible:
                        self._stop_child(child)
                        self._finish(
                            row,
                            "cancelled" if current["cancel_requested"] else "held",
                            error="preview_cancelled_or_source_changed",
                        )
                        return
                    if time.monotonic() > deadline or (
                        target.exists()
                        and target.stat().st_size > profile["max_output_bytes"]
                    ):
                        raise ValueError("Preview wall/output budget exceeded")
                    time.sleep(0.15)
                if (
                    child.returncode
                    or not target.is_file()
                    or not 0 < target.stat().st_size <= profile["max_output_bytes"]
                ):
                    raise ValueError("Preview encoder failed or output exceeded")
                self._stage(row, "verifying")
                media = probe(target)
                if abs(media["duration"] - original["duration"]) > 0.25:
                    raise ValueError("Full preview duration mismatch/truncation")
                from .content_store import ContentStore

                with target.open("rb") as stream:
                    reference = ContentStore.put(
                        store,
                        row["storage_owner_id"],
                        iter(lambda: stream.read(1024 * 1024), b""),
                        "web_video",
                        max_bytes=profile["max_output_bytes"],
                    )
                if getattr(store, "storage_kind", None) == "s3":
                    with target.open("rb") as stream:
                        store._create(
                            store._key(
                                row["storage_owner_id"], reference["storage_key"]
                            ),
                            stream,
                            reference["sha256"],
                            reference["bytes"],
                        )
                verified = store.path(row["storage_owner_id"], reference)
                with verified.open("rb") as stream:
                    sha = hashlib.file_digest(stream, "sha256").hexdigest()
                if sha != reference["sha256"] or probe(verified) != media:
                    raise ValueError("Preview stored bytes/metadata mismatch")
                self._finish(row, "ready", reference, media)
            except Exception as error:
                if child is not None:
                    self._stop_child(child)
                if self.guard_lost:
                    raise
                if isinstance(error, ObjectStoreError):
                    self.held = True
                    self._finish(row, "held", error="preview_storage_outcome_unproven")
                else:
                    self._finish(row, "failed", error="full_preview_generation_failed")
            finally:
                if child is not None:
                    self._stop_child(child)

    @contextmanager
    def _workspace(self, cache):
        import shutil
        import tempfile
        from pathlib import Path

        work = Path(tempfile.mkdtemp(prefix="full-preview-", dir=cache))
        try:
            yield work
        except BaseException:
            self.held = True
            raise
        finally:
            if not self.held:
                shutil.rmtree(work)

    @staticmethod
    @contextmanager
    def _wall_budget(seconds):
        import signal
        from threading import current_thread, main_thread

        if not hasattr(signal, "SIGALRM") or current_thread() is not main_thread():
            raise ValueError(
                "Preview execution requires an independent POSIX main process"
            )

        def elapsed(*_):
            raise TimeoutError("Full preview wall budget exhausted")

        old = signal.signal(signal.SIGALRM, elapsed)
        previous = signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
            if previous[0]:
                signal.setitimer(signal.ITIMER_REAL, *previous)

    @staticmethod
    def _stop_child(child):
        import subprocess

        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)


def main():
    import argparse
    import json
    import signal
    from pathlib import Path
    import time
    from .object_store import from_config
    from .postgres import Database
    from .postgres.execution import Execution
    from .postgres.video_previews import VideoPreviews

    parser = argparse.ArgumentParser(
        description="Explicit single-process durable full WebM runner"
    )
    parser.add_argument("--dsn-file", required=True)
    parser.add_argument("--object-config", required=True)
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--enable-full-previews", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.enable_full_previews:
        parser.error("Full previews require explicit enablement")
    cache = Path(args.cache_root)
    if not cache.is_absolute() or not cache.is_dir() or cache.is_symlink():
        parser.error("Explicit existing private disk root required")
    mounts = Path("/proc/self/mountinfo").read_text().splitlines()
    matches = [
        line.split() for line in mounts if line.split()[4] == str(cache.resolve())
    ]
    if not matches or any(
        x[x.index("-") + 1] in ("tmpfs", "ramfs", "devtmpfs") for x in matches
    ):
        parser.error("Preview root must be a real disk mount, not tmpfs/overlay-only")
    config = json.loads(Path(args.object_config).read_text())
    if Path(config["cache_root"]).resolve() != cache.resolve():
        parser.error("Object/cache roots differ")
    stopped = False

    def request_stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    previews = VideoPreviews(
        Execution(
            Database(Path(args.dsn_file).read_text().strip()), from_config(config)
        )
    )
    with PreviewWorker(previews, cache).exclusive() as worker:
        print(
            json.dumps(
                {"worker": "ready", "instance": worker.instance, "held": worker.held}
            ),
            flush=True,
        )
        while not stopped:
            if worker.held:
                return 4
            row = worker.claim_next()
            if row:
                worker.process(row)
                state = previews.get(row["requested_by"], row["id"])["state"]
                print(json.dumps({"id": row["id"], "state": state}), flush=True)
                if args.once:
                    return 0 if state in ("ready", "cancelled") else 2
            elif args.once:
                return 0
            else:
                time.sleep(0.25)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
