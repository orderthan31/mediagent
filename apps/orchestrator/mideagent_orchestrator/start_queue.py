"""Owner-scoped future Start queue. SQL claims authorize membership, never S3 alone."""
from video_service.start_queue_policy import (
    MAX_MEMBERS, QueueConflict, QueueMissing, claim_digest, decode_policy,
    encode_policy, identity, initial_policy, QueueUnavailable,
)


MEMBER_ROWS = """
SELECT j.id,j.owner_id,j.generation,j.active_claim_id,j.status,j.cancel_requested,
       j.ticket_number,j.created_at,
       j.snapshot->'asset'->>'original_filename' AS filename,
       j.snapshot->'definition'->>'name' AS workflow_name,
       EXISTS(SELECT 1 FROM node_runs r WHERE r.owner_id=j.owner_id AND r.job_id=j.id) AS started,
       EXISTS(SELECT 1 FROM node_runs r WHERE r.owner_id=j.owner_id AND r.job_id=j.id
              AND r.status IN ('running','waiting','review_required')) AS active,
       EXISTS(SELECT 1 FROM broker_dispatch_queue q
              JOIN node_runs r ON r.owner_id=q.owner_id AND r.job_id=q.job_id AND r.id=q.node_run_id
              JOIN message_outbox m ON m.owner_id=r.owner_id AND m.aggregate_id=r.job_id AND m.id=r.id
              WHERE q.owner_id=j.owner_id AND q.job_id=j.id AND q.phase='pending'
                AND r.status='waiting' AND r.generation=j.generation AND r.claim_id=j.active_claim_id
                AND m.published_at IS NULL) AS deliverable,
       EXISTS(SELECT 1 FROM broker_dispatch_queue q
              JOIN node_runs r ON r.owner_id=q.owner_id AND r.job_id=q.job_id AND r.id=q.node_run_id
              WHERE q.owner_id=j.owner_id AND q.job_id=j.id
                AND (q.phase='unknown' OR (q.phase IN ('sending','sent','received')
                                          AND r.status IN ('waiting','running')))) AS uncertain,
       c.id AS claim_id,c.generation AS claim_generation,c.consent_id,c.request_sha256
FROM jobs j JOIN execution_claims c
  ON c.owner_id=j.owner_id AND c.job_id=j.id AND c.id=j.active_claim_id
WHERE j.owner_id=%s AND j.id=ANY(%s)
"""


class StartQueue:
    def __init__(self, runtime):
        self.runtime, self.store = runtime, runtime.store

    @staticmethod
    def lock_in(db, owner):
        db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                   ('start-queue:' + identity(owner),))

    def load(self, owner):
        raw, token = self.store.read_start_queue(identity(owner))
        try:
            return (initial_policy(owner) if raw is None else decode_policy(raw, owner)), token
        except ValueError:
            raise QueueUnavailable('대기열 저장 기록을 확인하지 못했습니다.') from None

    @staticmethod
    def _new_claim(row):
        return row['request_sha256'] == claim_digest(row['id'], row['consent_id'])

    def _rows_in(self, db, policy, *, active_only=True):
        if not policy['members']:
            return {}
        members = {m['job_id']: m for m in policy['members']}
        rows = db.execute(MEMBER_ROWS, (policy['owner_id'], list(members))).fetchall()
        return {r['id']: r for r in rows if (
            r['claim_id'] == members[r['id']]['claim_id'] == r['active_claim_id']
            and r['claim_generation'] == r['generation'] == members[r['id']]['generation']
            and (not active_only or (r['status'] in {'waiting', 'running', 'review_required'}
                                     and not r['cancel_requested']))
            and self._new_claim(r)
        )}

    @staticmethod
    def _ordered(policy, rows):
        queued = {id: row for id, row in rows.items() if not row['started'] and row['status'] == 'waiting'}
        ids = list(dict.fromkeys([*policy['order'], *(m['job_id'] for m in policy['members'])]))
        return [queued[id] for id in ids if id in queued]

    def view_in(self, db, policy):
        rows = self._ordered(policy, self._rows_in(db, policy))
        ids = [row['id'] for row in rows]
        return dict(revision=policy['revision'], paused=policy['paused'],
                    order=[id for id in policy['order'] if id in ids], jobs=ids,
                    details=[dict(job_id=r['id'], ticket_number=str(r['ticket_number']),
                                  original_filename=r['filename'], workflow_name=r['workflow_name'],
                                  status='QUEUED', access={'can_manage': True}) for r in rows])

    def get(self, owner):
        # Read only: no preflight/capture, policy writes, model calls or dispatch.
        policy, _ = self.load(owner)
        with self.runtime.database.connection() as db:
            return self.view_in(db, policy)

    def patch(self, owner, revision, *, paused=None, order=None):
        if type(revision) is not int or revision < 0:
            raise ValueError('Invalid queue revision')
        if paused is not None and type(paused) is not bool:
            raise ValueError('Invalid queue pause state')
        if order is not None:
            if not isinstance(order, list) or len(order) > MAX_MEMBERS:
                raise ValueError('대기열은 1000개 이내여야 합니다.')
            for id in order:
                identity(id)
            if len(set(order)) != len(order):
                raise ValueError('대기열 순서가 중복되었습니다.')
        with self.runtime.database.connection() as db:
            self.lock_in(db, owner)
            policy, token = self.load(owner)
            if revision != policy['revision']:
                raise QueueConflict('대기열이 바뀌었습니다. 다시 확인하세요.')
            rows = self._rows_in(db, policy, active_only=False)
            for id in order or []:
                row = rows.get(id)
                if row is None:
                    raise QueueMissing('관리할 수 있는 새 시작 대기 작업을 찾을 수 없습니다.')
                if row['started'] or row['status'] != 'waiting' or row['cancel_requested']:
                    raise QueueConflict('시작했거나 더 이상 대기 중이 아닌 작업의 순서는 바꿀 수 없습니다.')
            next_policy = {**policy, 'revision': revision + 1}
            if paused is not None:
                next_policy['paused'] = paused
            if order is not None:
                next_policy['order'] = order
            self.store.write_start_queue(owner, encode_policy(next_policy), token)
            return self.view_in(db, next_policy)

    def enroll_in(self, db, job, claim):
        """Called only inside a newly validated admission, queue lock → job lock.

        Write BEFORE the PG claim commit. Failed/unknown cross-store admission can
        leave only an ignored orphan: exact committed claim+generation is required.
        """
        owner = job['owner_id']
        policy, token = self.load(owner)
        live = self._rows_in(db, policy)
        members = [m for m in policy['members'] if m['job_id'] in live and m['job_id'] != job['id']]
        if len(members) >= MAX_MEMBERS:
            raise QueueConflict('시작 대기열이 가득 찼습니다. 현재 작업을 확인하세요.')
        members.append(dict(job_id=job['id'], claim_id=identity(claim), generation=job['generation']))
        member_ids = {m['job_id'] for m in members}
        updated = {**policy, 'revision': policy['revision'] + 1, 'members': members,
                   'order': [id for id in policy['order'] if id in member_ids]}
        self.store.write_start_queue(owner, encode_policy(updated), token)

    def requires_in(self, db, job):
        claim = db.execute(
            'SELECT id AS claim_id,generation AS claim_generation,consent_id,request_sha256 '
            'FROM execution_claims WHERE owner_id=%s AND job_id=%s AND id=%s',
            (job['owner_id'], job['id'], job['active_claim_id']),
        ).fetchone()
        if not claim:
            return True  # Missing claim is never a legacy execution permission.
        return self._new_claim({**job, **claim})

    def allowed_in(self, db, job, *, new_claim=None):
        """First reservation only; caller holds owner queue lock then the job lock."""
        if new_claim is None:
            new_claim = self.requires_in(db, job)
        if not new_claim:
            return True  # Historical/absent queue policy retains its old execution contract.
        policy, _ = self.load(job['owner_id'])
        if policy['paused']:
            return False
        for row in self._ordered(policy, self._rows_in(db, policy)):
            if row['id'] == job['id']:
                # The native claim may record capacity demand while unready;
                # actual capacity/model/budget guards still own the reservation.
                return True
            if self.runtime._queue_start_ready_in(db, row):
                return False
        return False  # New-policy claims MUST have exact committed membership.

    def progression(self, owner):
        """Authorized members only. Never enumerate all waiting jobs or deliveries."""
        policy, _ = self.load(owner)
        with self.runtime.database.connection() as db:
            rows = self._rows_in(db, policy)
            # Started descendants are never stopped by a queue pause/reorder.
            started = [r['id'] for r in rows.values() if r['started'] and not r['uncertain']
                       and (not r['active'] or r['deliverable'])
                       and r['status'] in {'waiting', 'running'}]
            pending = [] if policy['paused'] else [r['id'] for r in self._ordered(policy, rows)]
            return list(dict.fromkeys([*started, *pending]))
