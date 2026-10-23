"""Bounded original assembly only. No preview/model/agent worker activation.

Bytes/parts live in SQL+CAS, not this executor. After process loss a user explicitly
retries completion of the same upload; the guarded service fences the final commit.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from video_service.postgres import Conflict


class OriginalFinalizations:
    def __init__(self, runtime):
        self.runtime = runtime
        self._pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="original-assembly"
        )
        self._lock = Lock()
        self._states = {}
        self._closed = False

    def close(self):
        with self._lock:
            self._closed = True
        self._pool.shutdown(wait=True, cancel_futures=True)

    def snapshot(self, owner, identity, row=None):
        row = row or self.runtime.upload_get(owner, identity)
        if row["asset_id"]:
            return {**row, "finalization_state": "complete"}
        key = (owner, identity)
        with self._lock:
            state = self._states.get(key, "pending")
        # Another API process may own the same session guard. Read only its key.
        if (
            state not in ("queued", "running")
            and row["uploaded_bytes"] == row["expected_size"]
        ):
            with self.runtime.database.connection() as db:
                active = db.execute(
                    """WITH k AS (
                    SELECT hashtextextended(current_schema()||%s,0) AS key
                ) SELECT EXISTS(SELECT 1 FROM pg_locks l,k WHERE l.locktype='advisory'
                    AND l.granted AND l.mode='ExclusiveLock' AND l.objsubid=1
                    AND l.classid::bigint=((k.key >> 32)&4294967295)
                    AND l.objid::bigint=(k.key&4294967295)
                    AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database())) AS yes""",
                    ("original-upload-complete:" + owner + ":" + identity,),
                ).fetchone()["yes"]
            if active:
                state = "running"
        return {
            **row,
            "status": "FINALIZING"
            if state in ("queued", "running")
            else "READY"
            if row["uploaded_bytes"] == row["expected_size"]
            else row["status"],
            "finalization_state": state,
            **(
                {
                    "finalization_error": "원본 등록이 끝나지 않았습니다. 청크는 보존됐으니 등록을 명시적으로 재시도하세요."
                }
                if state == "failed"
                else {}
            ),
        }

    def start(self, owner, identity):
        row = self.runtime.upload_get(owner, identity)
        if row["asset_id"]:
            return self.snapshot(owner, identity, row)
        if row["uploaded_bytes"] != row["expected_size"]:
            raise Conflict("업로드가 끝나지 않았습니다.")
        key = (owner, identity)
        with self._lock:
            if self._closed:
                raise Conflict("서버 종료 중입니다. 청크는 보존됩니다.")
            if self._states.get(key) not in ("queued", "running"):
                if sum(s in ("queued", "running") for s in self._states.values()) >= 2:
                    raise Conflict(
                        "다른 원본을 등록 중입니다. 잠시 후 같은 업로드 등록을 재시도하세요."
                    )
                self._states[key] = "queued"
                self._pool.submit(self._finish, owner, identity)
        return self.snapshot(owner, identity, row)

    def _finish(self, owner, identity):
        key = (owner, identity)
        with self._lock:
            self._states[key] = "running"
        try:
            result = self.runtime.upload_complete(owner, identity)
            state = "complete" if result["asset_id"] else "failed"
        except Exception:  # noqa: BLE001 -- keep SDK/DSN details out of background HTTP state
            # Never emit SDK/DSN/file-path diagnostics or lose durable uploaded bytes.
            state = "failed"
        with self._lock:
            self._states[key] = state
            for previous in list(self._states):
                if len(self._states) <= 64:
                    break
                if self._states[previous] not in ("queued", "running"):
                    del self._states[previous]
