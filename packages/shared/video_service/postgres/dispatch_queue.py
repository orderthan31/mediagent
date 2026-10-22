"""Application-side durable waiting for explicitly managed broker agents.

Never rewrites/adopts historical attempts and never controls a native runtime.
A broker TTL is a delivery bound, not the lifetime of an admitted queued job.
"""
from datetime import datetime, timezone
from ..cpu_agents import digest, canonical
from . import Conflict


class DispatchQueue:
    def __init__(self, runtime):
        self.runtime = runtime
        self.database = runtime.database

    @staticmethod
    def managed_in(db, agent):
        return bool(db.execute('SELECT 1 FROM remote_control_groups WHERE agent_id=%s', (agent,)).fetchone())

    @staticmethod
    def enqueue_in(db, job, run):
        db.execute('INSERT INTO broker_dispatch_queue(owner_id,job_id,node_run_id,agent_id) VALUES(%s,%s,%s,%s)',
                   (job['owner_id'], job['id'], run['id'], run['node_type']))

    @staticmethod
    def decorate_in(db, runs):
        if not runs:
            return runs
        queued = {r['node_run_id']: r for r in db.execute(
            'SELECT * FROM broker_dispatch_queue WHERE node_run_id=ANY(%s)',
            ([r['id'] for r in runs],)).fetchall()}
        values = []
        for row in runs:
            value = dict(row)
            if row['id'] in queued:
                q = queued[row['id']]
                value['dispatch'] = {k: q[k] for k in ('phase', 'worker_id', 'boot_id', 'published_at', 'received_at', 'error_code')}
            values.append(value)
        return values

    @staticmethod
    def _cleanup_in(db, agent):
        db.execute("UPDATE broker_dispatch_queue q SET phase='completed',updated_at=now() FROM node_runs r "
                   "WHERE q.node_run_id=r.id AND q.agent_id=%s AND q.phase IN ('sent','received') "
                   "AND (r.status IN ('completed','failed','quarantined') OR EXISTS "
                   "(SELECT 1 FROM result_quarantine x WHERE x.node_run_id=r.id))", (agent,))
        db.execute("UPDATE broker_dispatch_queue q SET phase='cancelled',updated_at=now() FROM jobs j "
                   "WHERE q.owner_id=j.owner_id AND q.job_id=j.id AND q.agent_id=%s "
                   "AND q.phase='pending' AND (j.cancel_requested OR j.active_claim_id IS NULL OR j.status NOT IN ('waiting','running'))", (agent,))
        db.execute("UPDATE node_runs r SET status='cancelled',completed_at=now() FROM broker_dispatch_queue q "
                   "WHERE q.node_run_id=r.id AND q.agent_id=%s AND q.phase='cancelled' AND r.status='waiting'", (agent,))

    def publish_in(self, db, job, outbox, send_confirm):
        """Return None for a historical/unmanaged attempt, otherwise a bool.

        The job and control-group locks serialize cancellation and stop admission
        against this one publish. Ambiguous sends are blocked, never auto-retried.
        """
        q = db.execute('SELECT * FROM broker_dispatch_queue WHERE node_run_id=%s FOR UPDATE', (outbox['id'],)).fetchone()
        if q is None:
            return None
        if q['phase'] != 'pending':
            return False
        run = db.execute('SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s FOR UPDATE',
                         (q['owner_id'], q['job_id'], q['node_run_id'])).fetchone()
        if (job['status'] not in ('waiting', 'running') or job['cancel_requested'] or job['generation'] != run['generation']
                or job['active_claim_id'] != run['claim_id'] or run['status'] != 'waiting'):
            db.execute("UPDATE broker_dispatch_queue SET phase='cancelled',updated_at=now() WHERE node_run_id=%s", (run['id'],))
            return False
        if outbox['message_type'] != 'agent.command.v1' or run['request_sha256'] != digest(outbox['payload']):
            raise Conflict('queued_dispatch_request_mismatch')
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended('dispatch-agent:'||%s,0))", (q['agent_id'],))
        self._cleanup_in(db, q['agent_id'])
        group = db.execute('SELECT *,observed_at>now()-interval \'15 seconds\' AS fresh FROM remote_control_groups WHERE agent_id=%s FOR SHARE', (q['agent_id'],)).fetchone()
        if (not group or not group['fresh'] or not group['enabled'] or group['replicas'] != 1
                or group['capacity'] != 1 or group['pending_request'] or group['quarantined']):
            return False
        workers = group['observed'] or []
        if len(workers) != 1:
            return False
        worker = workers[0]
        if (not worker.get('running') or worker.get('state') != 'ready' or not worker.get('boot_id')
                or worker.get('id') != group['slot_ids'][0]):
            return False
        active = db.execute("SELECT 1 FROM broker_dispatch_queue WHERE agent_id=%s AND phase IN ('sending','sent','received','unknown')", (q['agent_id'],)).fetchone()
        if active:
            return False
        db.execute("UPDATE broker_dispatch_queue SET phase='sending',worker_id=%s,boot_id=%s,updated_at=now() WHERE node_run_id=%s", (worker['id'], worker['boot_id'], run['id']))
        db.execute("UPDATE node_runs SET lease_owner='broker-dispatch',lease_expires_at=now()+interval '120 seconds' WHERE id=%s", (run['id'],))
        try:
            confirmed = send_confirm(outbox['id'], outbox['message_type'], canonical(outbox['payload'])) is True
        except Exception:
            confirmed = False
        if not confirmed:
            db.execute("UPDATE broker_dispatch_queue SET phase='unknown',error_code='dispatch_outcome_unknown',updated_at=now() WHERE node_run_id=%s", (run['id'],))
            return False
        db.execute('UPDATE message_outbox SET published_at=now() WHERE id=%s', (outbox['id'],))
        db.execute("UPDATE broker_dispatch_queue SET phase='sent',published_at=now(),updated_at=now() WHERE node_run_id=%s", (run['id'],))
        return True

    @staticmethod
    def received_in(db, job, run, *, from_result=False):
        q = db.execute('SELECT * FROM broker_dispatch_queue WHERE node_run_id=%s FOR UPDATE', (run['id'],)).fetchone()
        if not q or q['phase'] != 'sent' or run['status'] != 'waiting':
            return run
        if (job['status'] not in ('waiting', 'running') or job['cancel_requested'] or job['generation'] != run['generation']
                or job['active_claim_id'] != run['claim_id']):
            return run
        event = db.execute("SELECT received_at FROM worker_observation_events WHERE worker_id=%s AND boot_id=%s AND ticket_id=%s AND attempt_id=%s AND state IN ('busy','stopping') AND received_at>=%s ORDER BY received_at LIMIT 1",
                           (q['worker_id'], q['boot_id'], q['job_id'], q['node_run_id'], q['published_at'])).fetchone()
        if not event and not from_result:
            return run
        received = event['received_at'] if event else datetime.now(timezone.utc)
        db.execute("UPDATE broker_dispatch_queue SET phase='received',received_at=%s,updated_at=now() WHERE node_run_id=%s", (received, run['id']))
        value = db.execute("UPDATE node_runs SET status='running',started_at=%s WHERE id=%s RETURNING *", (received, run['id'])).fetchone()
        db.execute("UPDATE jobs SET status='running',revision=revision+1,updated_at=now() WHERE owner_id=%s AND id=%s", (job['owner_id'], job['id']))
        return value

    def tick(self, controller, *, agent):
        """Only newly enrolled, explicitly admitted attempts for this one agent."""
        with self.database.connection() as db:
            self._cleanup_in(db, agent)
            pending = [dict(r) for r in db.execute("SELECT owner_id,job_id,node_run_id FROM broker_dispatch_queue WHERE agent_id=%s AND phase IN ('pending','sent') ORDER BY created_at,node_run_id LIMIT 32", (agent,)).fetchall()]
        for q in pending:
            with self.database.connection() as db:
                job = self.runtime._job(db, q['owner_id'], q['job_id'], lock=True)
                run = db.execute('SELECT * FROM node_runs WHERE id=%s', (q['node_run_id'],)).fetchone()
                self.received_in(db, job, run)
            controller.publish_exact(q['owner_id'], q['job_id'], q['node_run_id'])
