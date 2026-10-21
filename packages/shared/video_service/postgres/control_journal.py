"""At-most-once lifecycle signals, independently observed cooperative completion.

A confirmed CLI return is journaled as sent before waiting for work to drain.
Restart may observe/reconcile sent actions, never issue them again. A crash in
issuing (before durable send acknowledgement) stays unknown, even at target count.
"""
from datetime import datetime, timezone
from uuid import uuid4
from . import Conflict, Missing


def utc(value):
    if isinstance(value,datetime):return value
    if not isinstance(value,str):return None
    try:return datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:return None


class ControlJournal:
    def __init__(self, store):self.store,self.database=store,store.database

    def prepare(self, command, contract, observations):
        with self.database.connection() as db:
            group=db.execute('SELECT * FROM remote_control_groups WHERE agent_id=%s FOR UPDATE',(command['agent_id'],)).fetchone()
            if not group or group['contract_sha256']!=contract or group['pending_request']!=command['request_id']:
                raise Conflict('control_journal_contract_conflict')
            if db.execute('SELECT 1 FROM remote_control_batches WHERE request_id=%s',(command['request_id'],)).fetchone():return
            if [o['id'] for o in observations]!=group['slot_ids'] or any(type(o.get('running')) is not bool for o in observations):
                raise ValueError('invalid_journal_observation')
            if any(o.get('restart_policy')!='no' for o in observations):
                raise ValueError('cooperative_signal_requires_no_restart_policy')
            db.execute('INSERT INTO remote_control_batches(request_id,agent_id,contract_sha256) VALUES(%s,%s,%s)',(command['request_id'],command['agent_id'],contract))
            for index,row in enumerate(observations):
                desired=index<command['replicas']
                if desired==row['running']:continue
                db.execute('INSERT INTO remote_control_actions(id,request_id,worker_id,action,before_boot_id) VALUES(%s,%s,%s,%s,%s)',(uuid4().hex,command['request_id'],row['id'],'start' if desired else 'stop',row.get('boot_id')))

    def actions(self, request_id):
        with self.database.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM remote_control_actions WHERE request_id=%s ORDER BY worker_id',(request_id,)).fetchall()]

    def begin(self, identity, *, owner=None):
        # Actual executors pass their held advisory-lock connection. If it died,
        # this UPDATE cannot authorize a new native call on a replacement session.
        query="UPDATE remote_control_actions SET phase='issuing',issue_count=1,issued_at=now(),updated_at=now() WHERE id=%s AND phase='planned' AND issue_count=0 RETURNING id"
        if owner is not None:return bool(owner.execute(query,(identity,)).fetchone())
        with self.database.connection() as db:return bool(db.execute(query,(identity,)).fetchone())

    def sent(self, identity):
        with self.database.connection() as db:
            if not db.execute("UPDATE remote_control_actions SET phase='sent',updated_at=now() WHERE id=%s AND phase='issuing' RETURNING id",(identity,)).fetchone():
                raise Conflict('control_signal_not_issuing')

    def unknown(self, identity):
        with self.database.connection() as db:
            db.execute("UPDATE remote_control_actions SET phase='unknown',updated_at=now() WHERE id=%s AND phase='issuing'",(identity,))

    def pending(self, agent):
        with self.database.connection() as db:
            row=db.execute('SELECT r.* FROM remote_control_groups g JOIN remote_control_requests r ON r.request_id=g.pending_request WHERE g.agent_id=%s',(agent,)).fetchone()
            return dict(row) if row else None

    def reconcile(self, request_id, observations):
        with self.database.connection() as db:
            request=db.execute('SELECT * FROM remote_control_requests WHERE request_id=%s',(request_id,)).fetchone()
            if not request:raise Missing('control_request_missing')
            group=db.execute('SELECT * FROM remote_control_groups WHERE agent_id=%s FOR UPDATE',(request['agent_id'],)).fetchone()
            if group['pending_request']!=request_id:
                if request['phase']=='succeeded':return True
                raise Conflict('control_request_not_current')
            batch=db.execute('SELECT * FROM remote_control_batches WHERE request_id=%s',(request_id,)).fetchone()
            if not batch:return False
            if batch['contract_sha256']!=group['contract_sha256']:raise Conflict('control_journal_contract_conflict')
            if observations!=group['observed'] or not group['observed_at'] or (datetime.now(timezone.utc)-group['observed_at']).total_seconds()>=15:
                raise Conflict('control_reconciliation_requires_fresh_observation')
            indexed={row['id']:row for row in observations}
            if list(indexed)!=group['slot_ids']:raise ValueError('control_reconciliation_slot_mismatch')
            actions=db.execute('SELECT * FROM remote_control_actions WHERE request_id=%s FOR UPDATE',(request_id,)).fetchall()
            abnormal=[a for a in actions if a['phase']=='sent' and not indexed[a['worker_id']]['running']
                      and indexed[a['worker_id']].get('exit_code') not in (None,0)]
            if abnormal:
                for action in abnormal:
                    db.execute("UPDATE remote_control_actions SET phase='unknown',updated_at=now() WHERE id=%s",(action['id'],))
                db.execute("UPDATE remote_control_requests SET phase='unknown',error_code='control_abnormal_worker_exit',updated_at=now() WHERE request_id=%s",(request_id,))
                return False
            uncertain=any(a['phase'] in ('issuing','unknown') for a in actions)
            if uncertain:
                db.execute("UPDATE remote_control_requests SET phase='unknown',error_code=coalesce(error_code,'control_signal_ack_missing'),updated_at=now() WHERE request_id=%s",(request_id,))
                return False
            confirmed=True
            for action in actions:
                if action['phase']=='confirmed':continue
                if action['phase']!='sent':confirmed=False;continue
                observed=indexed[action['worker_id']]
                if action['action']=='start':
                    started=utc(observed.get('started_at'))
                    reached=observed['running'] and started is not None and started>=action['issued_at']
                else:
                    received=utc(observed.get('report_received_at'))
                    reached=(not observed['running'] and observed.get('exit_code')==0 and observed.get('report_state')=='stopped'
                             and action['before_boot_id'] is not None and observed.get('boot_id')==action['before_boot_id']
                             and received is not None and received>=action['issued_at'])
                if reached:db.execute("UPDATE remote_control_actions SET phase='confirmed',updated_at=now() WHERE id=%s",(action['id'],))
                else:confirmed=False
            desired=[i<request['replicas'] for i in range(len(group['slot_ids']))]
            if confirmed and [r['running'] for r in observations]==desired:
                db.execute("UPDATE remote_control_requests SET phase='succeeded',error_code=NULL,updated_at=now() WHERE request_id=%s AND phase IN ('applying','unknown')",(request_id,))
                db.execute('UPDATE remote_control_groups SET pending_request=NULL WHERE agent_id=%s',(request['agent_id'],))
                return True
            return False
