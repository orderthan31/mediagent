"""Transactional per-owner queue controls, independent of running job state locks."""
from contextlib import contextmanager
import json
import sqlite3
from .databases import database_path
from .locking import JobBusyError

QUEUE_LOCK_ID = 'e' * 32


class QueueConflict(ValueError):
    pass


class QueueControl:
    def __init__(self, root):
        self.root = root
        self.path = database_path(root, 'queue-control')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute('CREATE TABLE IF NOT EXISTS controls (owner TEXT PRIMARY KEY, revision INTEGER NOT NULL, paused INTEGER NOT NULL, ordering TEXT NOT NULL)')
            yield connection
        except sqlite3.OperationalError as exc:
            if (getattr(exc, 'sqlite_errorcode', 0) & 255) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                raise JobBusyError('Queue metadata busy') from exc
            raise
        finally:
            connection.close()

    def read(self, owner=None):
        if not self.path.exists():
            return {'revision': 0, 'paused': False, 'order': []}
        with self.connect() as db:
            row = db.execute('SELECT revision, paused, ordering FROM controls WHERE owner=?',
                             (json.dumps(owner),)).fetchone()
        return {'revision': row[0], 'paused': bool(row[1]), 'order': json.loads(row[2])} if row else {
            'revision': 0, 'paused': False, 'order': []}

    def update(self, owner, revision, *, paused=None, order=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision, paused, ordering FROM controls WHERE owner=?',
                             (json.dumps(owner),)).fetchone()
            current = row[0] if row else 0
            if current != revision:
                raise QueueConflict('다른 창에서 큐가 변경됐습니다. 새로고침 후 다시 시도해 주세요.')
            result = {'revision': current + 1, 'paused': bool(row[1]) if row else False,
                      'order': json.loads(row[2]) if row else []}
            if paused is not None:
                result['paused'] = paused
            if order is not None:
                result['order'] = list(order)
            db.execute('INSERT OR REPLACE INTO controls VALUES (?, ?, ?, ?)',
                       (json.dumps(owner), result['revision'], int(result['paused']), json.dumps(result['order'])))
            db.commit()
        try:
            (self.root / '.faceswap-wakeup').touch()
        except OSError:
            pass
        return result

    def ordered(self, jobs):
        states = {}
        for job in jobs:
            owner = job.metadata.get('owner_id')
            if owner not in states:
                state = self.read(owner)
                state['positions'] = {job_id: i for i, job_id in enumerate(state['order'])}
                states[owner] = state
        def key(job):
            state = states[job.metadata.get('owner_id')]
            preview = job.metadata.get('faceswap_operation') in {'analyze_source', 'analyze_reference', 'preview'}
            return (0 if preview else 1, state['positions'].get(job.job_id, len(state['positions'])),
                    job.metadata.get('queued_at', job.created_at), job.job_id)
        return sorted((job for job in jobs if not states[job.metadata.get('owner_id')]['paused']), key=key)
