"""Rebuildable SQLite list index. JSON remains the recovery source of truth.

Each listing reconciles file identities and only parses changed manifests. No
worker claim or authorization decision relies on a potentially stale index row.
"""
import json
import sqlite3
from .models import JobRecord
from .storage import read_json
from .databases import database_path


def indexed_jobs(root):
    db = sqlite3.connect(database_path(root, 'job-index'), timeout=3)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, stamp TEXT NOT NULL, data TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        cached = {row[0]: row[1:] for row in db.execute('SELECT id, stamp, data FROM jobs')}
        present = set()
        records = []
        for path in root.glob('*/job.json'):
            identity = path.parent.name
            present.add(identity)
            try:
                stat = path.stat()
                stamp = f'{stat.st_mtime_ns}:{stat.st_size}:{stat.st_ino}'
                previous = cached.get(identity)
                data = json.loads(previous[1]) if previous and previous[0] == stamp else read_json(path)
                record = JobRecord.from_dict(data)
                if record.job_id != identity:
                    raise ValueError('Job identity mismatch')
                records.append(record)
                if not previous or previous[0] != stamp:
                    db.execute('INSERT OR REPLACE INTO jobs VALUES (?, ?, ?)',
                               (identity, stamp, json.dumps(data)))
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                db.execute('DELETE FROM jobs WHERE id=?', (identity,))
        db.executemany('DELETE FROM jobs WHERE id=?', [(key,) for key in cached.keys() - present])
        db.commit()
        return sorted(records, key=lambda record: record.updated_at, reverse=True)
    finally:
        db.close()
