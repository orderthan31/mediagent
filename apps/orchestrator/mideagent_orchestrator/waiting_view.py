"""Bounded shared read of actual broker deliveries; never a scheduler/control.

No _view/capture, cleanup, storage read, command payload, or native connection.
The single SELECT groups all states for each selected job before bounding output.
"""
import re

LIMIT = 100
PHASES = ("pending", "sending", "sent", "received", "unknown")

QUERY = """WITH deliveries AS (
    SELECT q.owner_id, q.job_id, q.phase, q.created_at, r.status AS run_status
    FROM broker_dispatch_queue q
    JOIN node_runs r ON r.owner_id=q.owner_id AND r.job_id=q.job_id AND r.id=q.node_run_id
    JOIN jobs j ON j.owner_id=q.owner_id AND j.id=q.job_id
    LEFT JOIN message_outbox o ON o.owner_id=q.owner_id AND o.aggregate_id=q.job_id AND o.id=q.node_run_id
    WHERE j.library_removed_at IS NULL
      AND q.phase IN ('pending','sending','sent','received','unknown')
      AND (q.phase='unknown' OR (
        r.status NOT IN ('completed','cancelled','quarantined')
        AND NOT (q.phase IN ('sent','received') AND r.status='failed')
        AND (q.phase<>'pending' OR (
          j.status IN ('waiting','running') AND j.cancel_requested=false
          AND j.active_claim_id IS NOT NULL AND r.claim_id=j.active_claim_id
          AND r.generation=j.generation AND r.status='waiting'
          AND o.id IS NOT NULL AND o.published_at IS NULL
        ))
      ))
), selected AS (
    SELECT owner_id, job_id, MIN(created_at) AS queued_at
    FROM deliveries GROUP BY owner_id, job_id
    ORDER BY queued_at, job_id, owner_id LIMIT 101
)
SELECT j.owner_id, j.id AS job_id, j.ticket_number, j.status,
    j.snapshot->'asset'->>'original_filename' AS original_filename,
    j.snapshot->'definition'->>'name' AS workflow_name,
    s.queued_at, d.phase, d.run_status, COUNT(*) AS delivery_count,
    (SELECT COUNT(*) FROM jobs identities WHERE identities.id=j.id) AS identity_count
FROM selected s
JOIN jobs j ON j.owner_id=s.owner_id AND j.id=s.job_id
JOIN deliveries d ON d.owner_id=s.owner_id AND d.job_id=s.job_id
GROUP BY j.owner_id,j.id,j.ticket_number,j.status,
    j.snapshot->'asset'->>'original_filename',j.snapshot->'definition'->>'name',
    s.queued_at,d.phase,d.run_status
ORDER BY s.queued_at,j.id,j.owner_id,d.phase,d.run_status
"""


def project(rows, actor):
    jobs = {}
    for row in rows:
        if row['identity_count'] != 1:
            raise ValueError("작업 식별자를 확인할 수 없습니다. 목록을 다시 확인하세요.")
        identity = row['job_id']
        if identity not in jobs:
            queued_at = row['queued_at']
            jobs[identity] = {
                'job_id': identity, 'ticket_number': str(row['ticket_number']),
                'status': row['status'], 'original_filename': row['original_filename'],
                'workflow_name': row['workflow_name'],
                'queued_at': queued_at.isoformat() if hasattr(queued_at, 'isoformat') else queued_at,
                'deliveries': [], 'access': {'can_manage': row['owner_id'] == actor},
            }
        jobs[identity]['deliveries'].append({
            'phase': row['phase'], 'run_status': row['run_status'], 'count': row['delivery_count'],
        })
    items = list(jobs.values())
    for job in items:
        job['deliveries'].sort(key=lambda item: (PHASES.index(item['phase']), item['run_status']))
    return {'jobs': items[:LIMIT], 'has_more': len(items) > LIMIT, 'limit': LIMIT}


class WaitingView:
    def __init__(self, database):
        self.database = database

    def read(self, actor):
        if not isinstance(actor, str) or not re.fullmatch(r'[a-f0-9]{32}', actor):
            raise ValueError('로그인 계정을 확인하세요.')
        with self.database.connection() as db:
            db.execute('SET TRANSACTION READ ONLY')
            rows = db.execute(QUERY).fetchall()
        return project(rows, actor)
