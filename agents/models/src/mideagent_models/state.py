"""Role-local durable state. No workflow, outbox, credential or PostgreSQL access."""

import contextlib
import json
import sqlite3
from pathlib import Path


class RoleState:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "role-state.sqlite"
        with self.connect() as c:
            c.executescript("""PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,request_sha TEXT NOT NULL,request TEXT NOT NULL,status TEXT NOT NULL,cancelled INTEGER NOT NULL DEFAULT 0,calls INTEGER NOT NULL DEFAULT 0,result TEXT);
            CREATE TABLE IF NOT EXISTS chunks(task TEXT NOT NULL,idx INTEGER NOT NULL,status TEXT NOT NULL,reply TEXT,result TEXT,error TEXT,PRIMARY KEY(task,idx));
            """)

    def connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    @contextlib.contextmanager
    def lock(self, task, kind, shared=False):
        import fcntl

        with (self.root / (task + "." + kind + ".lock")).open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def ensure(self, task, sha, request):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT request_sha FROM tasks WHERE id=?", (task,)
            ).fetchone()
            if row and row["request_sha"] != sha:
                raise ValueError("task_input_or_model_changed")
            c.execute(
                "INSERT OR IGNORE INTO tasks(id,request_sha,request,status)VALUES(?,?,?,'prepared')",
                (task, sha, json.dumps(request)),
            )

    def task(self, task):
        with self.connect() as c:
            row = c.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
            if not row:
                raise ValueError("unknown_role_task")
            return dict(row)

    def cancelled(self, task):
        return bool(self.task(task)["cancelled"])

    def cancel(self, task):
        with self.connect() as c:
            c.execute(
                "UPDATE tasks SET cancelled=1,status='cancelled'WHERE id=?", (task,)
            )
        # Cancellation ACK follows the task-local call fence, not an in-flight kill.
        with self.lock(task, "call-fence"):
            pass

    def chunk(self, task, index):
        with self.connect() as c:
            row = c.execute(
                "SELECT * FROM chunks WHERE task=? AND idx=?", (task, index)
            ).fetchone()
            return dict(row) if row else None

    def reserve(self, task, index):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
            if row["cancelled"]:
                return "cancelled"
            chunk = c.execute(
                "SELECT status FROM chunks WHERE task=?AND idx=?", (task, index)
            ).fetchone()
            if chunk:
                return chunk["status"]
            request = json.loads(row["request"])
            if row["calls"] >= request["max_calls"]:
                return "budget_exhausted"
            c.execute(
                "INSERT INTO chunks(task,idx,status)VALUES(?,?,'started')",
                (task, index),
            )
            c.execute("UPDATE tasks SET calls=calls+1 WHERE id=?", (task,))
            return "reserved"

    def reply(self, task, index, reply):
        with self.connect() as c:
            c.execute(
                "UPDATE chunks SET reply=?,status='received'WHERE task=?AND idx=?AND status='started'",
                (json.dumps(reply), task, index),
            )

    def complete(self, task, index, result):
        with self.connect() as c:
            c.execute(
                "UPDATE chunks SET result=?,status='completed'WHERE task=?AND idx=?AND status='received'",
                (json.dumps(result), task, index),
            )

    def fail(self, task, index, error, unknown):
        with self.connect() as c:
            c.execute(
                "UPDATE chunks SET status=?,error=?WHERE task=?AND idx=?",
                ("unknown" if unknown else "failed", error, task, index),
            )

    def finish(self, task, result):
        with self.connect() as c:
            c.execute(
                "UPDATE tasks SET status=?,result=?WHERE id=?",
                (result["status"], json.dumps(result), task),
            )
