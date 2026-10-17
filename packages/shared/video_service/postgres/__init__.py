"""Explicit PostgreSQL access; importing this package never connects or migrates."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import os
import psycopg
from psycopg.rows import dict_row


class Conflict(ValueError):
    pass


class Missing(LookupError):
    pass


class Database:
    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def connection(self):
        with psycopg.connect(self.dsn, connect_timeout=5, row_factory=dict_row) as db:
            db.execute("SET LOCAL statement_timeout = '15s'")
            db.execute("SET LOCAL lock_timeout = '5s'")
            yield db

    def migrate(self):
        """Atomic, checksum-checked migrations; never called by API startup."""
        applied = []
        with self.connection() as db:
            db.execute("SELECT pg_advisory_xact_lock(764931002)")
            db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
            for path in sorted((Path(__file__).parent / 'migrations').glob('*.sql')):
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                previous = db.execute("SELECT sha256 FROM schema_migrations WHERE name=%s", (path.name,)).fetchone()
                if previous:
                    if previous['sha256'] != digest:
                        raise Conflict('Applied migration checksum changed')
                    continue
                db.execute(raw.decode('utf-8'))
                db.execute("INSERT INTO schema_migrations(name,sha256) VALUES (%s,%s)", (path.name, digest))
                applied.append(path.name)
        return applied


if __name__ == '__main__':
    raise SystemExit('Use python -m video_service.postgres.migrate with an explicit test/deployment DSN')
