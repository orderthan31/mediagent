"""Admin review intents and host-only resolution. Never issues native signals.

Original action phase/count is immutable here. A missing ACK proof permits only
hold. Verified normal outcome is a distinct reviewed state; abnormal termination
is a failed/quarantined outcome, never a successful job or automatic retry.
"""
import hashlib
import json
import re
from datetime import datetime,timezone
from uuid import uuid4
from psycopg.types.json import Jsonb
from . import Conflict,Missing
from .control_journal import utc


def public(value):
    if isinstance(value,datetime):return value.isoformat()
    raise TypeError('unsupported_review_value')


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=public).encode()).hexdigest()


def identity(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):raise ValueError('invalid_review_identity')


def admin(db, actor, *, lock=True):
    # Host role reads only these authorization columns. A row lock would require
    # account UPDATE rights; never widen that role to permit a read-time check.
    row=db.execute('SELECT active,role FROM accounts WHERE id=%s'+(' FOR SHARE' if lock else ''),(actor,)).fetchone()
    if not row or not row['active'] or row['role']!='admin':raise PermissionError('관리자 권한이 필요합니다.')


class ControlRecovery:
    def __init__(self, store):self.store,self.database=store,store.database

    def publish_evidence(self, action_id, proof, *, error_code=None):
        """Host-only. Caller has verified its private signed receipt against pins."""
        identity(action_id)
        with self.database.connection() as db:
            row=db.execute('SELECT a.*,g.contract_sha256 FROM remote_control_actions a JOIN remote_control_requests r ON r.request_id=a.request_id JOIN remote_control_groups g ON g.agent_id=r.agent_id WHERE a.id=%s',(action_id,)).fetchone()
            if not row:raise Missing('control_action_missing')
            if proof:
                facts=proof['facts']
                if any(facts.get(k)!=row[v] for k,v in [('action_id','id'),('request_id','request_id'),('worker_id','worker_id'),('action','action'),('before_boot_id','before_boot_id'),('contract_sha256','contract_sha256')]):
                    raise Conflict('ack_evidence_binding_mismatch')
                if utc(facts['issued_at'])!=row['issued_at'] or facts['native_return_code']!=0 or not re.fullmatch('[a-f0-9]{64}',proof['sha256']):raise ValueError('invalid_ack_evidence')
            db.execute('INSERT INTO remote_control_ack_evidence(action_id,receipt_sha256,facts,valid,error_code) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(action_id) DO UPDATE SET receipt_sha256=excluded.receipt_sha256,facts=excluded.facts,valid=excluded.valid,error_code=excluded.error_code,verified_at=now()',
                       (action_id,proof['sha256'] if proof else None,Jsonb(proof['facts']) if proof else None,bool(proof),error_code))

    def _locked(self, db, group):
        row=db.execute('SELECT * FROM remote_control_groups WHERE agent_id=%s FOR UPDATE',(group,)).fetchone()
        if not row:raise Missing('control_group_missing')
        db.execute('INSERT INTO remote_control_review_heads(agent_id) VALUES(%s) ON CONFLICT DO NOTHING',(group,))
        head=db.execute('SELECT * FROM remote_control_review_heads WHERE agent_id=%s FOR UPDATE',(group,)).fetchone()
        return row,head

    def _context(self, db, group, review_revision):
        if not group['pending_request']:raise Conflict('no_unresolved_control_request')
        if not group['observed_at'] or not 0<=(datetime.now(timezone.utc)-group['observed_at']).total_seconds()<15:raise Conflict('review_requires_fresh_observation')
        request=db.execute('SELECT * FROM remote_control_requests WHERE request_id=%s',(group['pending_request'],)).fetchone()
        if request['phase']!='unknown':raise Conflict('control_request_not_unknown')
        actions=[dict(r) for r in db.execute('SELECT * FROM remote_control_actions WHERE request_id=%s ORDER BY worker_id',(request['request_id'],)).fetchall()]
        observations=group['observed'] or []
        if [r['id'] for r in observations]!=group['slot_ids']:raise Conflict('review_slot_binding_mismatch')
        critical=('id','target_id','image_id','running','state','boot_id','ticket_id','attempt_id','exit_code','started_at','restart_policy','report_state')
        observed=[{k:r.get(k) for k in critical} for r in observations]
        indexed={r['id']:r for r in observations};evidence=[];all_ack=bool(actions);normal=True;bound=True
        for action in actions:
            row=db.execute('SELECT * FROM remote_control_ack_evidence WHERE action_id=%s',(action['id'],)).fetchone()
            fresh=bool(row and row['valid'] and 0<=(datetime.now(timezone.utc)-row['verified_at']).total_seconds()<15)
            ev={'action_id':action['id'],'valid':fresh,'receipt_sha256':row['receipt_sha256'] if row else None,'facts':row['facts'] if row else None,'error_code':row['error_code'] if row else None}
            evidence.append(ev)
            ack=fresh or action['phase']=='confirmed'
            all_ack=all_ack and ack and action['phase']!='planned' and action['issue_count']==1
            current=indexed[action['worker_id']]
            facts=row['facts'] if fresh else None
            same_start=bool(not facts or facts['after_started_at']==current.get('started_at'))
            same_boot=bool(current.get('boot_id') and (action['action']=='start' or current['boot_id']==action['before_boot_id']))
            pin=bool(current.get('target_id') and current.get('image_id') and (not facts or (facts['target_id']==current['target_id'] and facts['image_id']==current['image_id'])))
            bound=bound and same_start and same_boot and pin and current.get('restart_policy')=='no'
            if action['action']=='stop':
                received=utc(current.get('report_received_at'))
                normal=normal and not current['running'] and current.get('exit_code')==0 and current.get('report_state')=='stopped' and received is not None and received>=action['issued_at']
            else:
                started=utc(current.get('started_at'))
                normal=normal and current['running'] and started is not None and started>=action['issued_at'] and current['state'] in ('connected','ready','busy')
        allowed=['hold']
        goal=[r['running'] for r in observations]==[i<request['replicas'] for i in range(len(observations))]
        if all_ack and bound and goal and normal:allowed.append('confirm_observed')
        if all_ack and bound and all(not r['running'] for r in observations) and any(r.get('exit_code') not in (None,0) for r in observations):allowed.append('quarantine_failed')
        context={'agent_id':group['agent_id'],'request':{k:request[k] for k in ('request_id','actor_id','revision','replicas','payload_sha256','phase','error_code')},
                 'contract_sha256':group['contract_sha256'],'slot_ids':group['slot_ids'],'group_revision':group['revision'],'observation_revision':group['observation_revision'],'review_revision':review_revision,
                 'observed':observed,'actions':[{k:r[k] for k in ('id','request_id','worker_id','action','phase','issue_count','before_boot_id','issued_at')} for r in actions],'ack_evidence':evidence,'allowed':allowed}
        context['targets']=[{'worker_id':r['id'],'target_id':r.get('target_id'),'image_id':r.get('image_id')} for r in observations]
        return context,digest(context)

    def preview(self, actor, group):
        with self.database.connection() as db:
            admin(db,actor);row,head=self._locked(db,group)
            if head['pending_decision']:raise Conflict('review_decision_in_progress')
            context,sha=self._context(db,row,head['revision']);plan_id=uuid4().hex
            db.execute('INSERT INTO remote_control_review_plans(id,agent_id,request_id,actor_id,context_sha256,context,allowed) VALUES(%s,%s,%s,%s,%s,%s,%s)',(plan_id,group,row['pending_request'],actor,sha,Jsonb(json.loads(json.dumps(context,default=public))),Jsonb(context['allowed'])))
            return {'id':plan_id,'context_sha256':sha,'context':json.loads(json.dumps(context,default=public)),'allowed':context['allowed']}

    def _decision(self, db, row):
        result=db.execute('SELECT outcome,evidence,created_at FROM remote_control_review_results WHERE decision_id=%s',(row['id'],)).fetchone()
        return {**{k:public(v) if isinstance(v,datetime) else v for k,v in row.items()},'result':{k:public(v) if isinstance(v,datetime) else v for k,v in result.items()} if result else None}

    def submit(self, actor, group, *, plan_id, decision_id, choice, reason):
        identity(plan_id);identity(decision_id)
        if choice not in ('hold','confirm_observed','quarantine_failed') or not isinstance(reason,str) or not reason.strip() or len(reason)>1000:raise ValueError('invalid_review_decision')
        if re.search(r'(?i)(postgres(?:ql)?://|amqps?://|password\s*=|token\s*=)',reason):raise ValueError('review_reason_must_not_include_credentials')
        payload=digest({'actor':actor,'group':group,'plan':plan_id,'choice':choice,'reason':reason})
        with self.database.connection() as db:
            admin(db,actor);db.execute("SELECT pg_advisory_xact_lock(hashtextextended('review-decision:'||%s,0))",(decision_id,))
            row,head=self._locked(db,group)
            previous=db.execute('SELECT * FROM remote_control_review_decisions WHERE id=%s',(decision_id,)).fetchone()
            if previous:
                if previous['payload_sha256']!=payload:raise Conflict('review_decision_id_reused')
                return self._decision(db,previous)
            if head['pending_decision']:raise Conflict('review_decision_in_progress')
            plan=db.execute('SELECT *,expires_at>now() AS valid FROM remote_control_review_plans WHERE id=%s',(plan_id,)).fetchone()
            if not plan or plan['actor_id']!=actor or plan['agent_id']!=group or not plan['valid']:raise Conflict('review_plan_invalid_or_expired')
            context,sha=self._context(db,row,head['revision'])
            if plan['context_sha256']!=sha or choice not in context['allowed']:raise Conflict('review_context_changed_or_decision_not_allowed')
            accepted=db.execute('INSERT INTO remote_control_review_decisions(id,agent_id,request_id,actor_id,plan_id,choice,reason,payload_sha256,review_revision) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *',(decision_id,group,row['pending_request'],actor,plan_id,choice,reason,payload,head['revision']+1)).fetchone()
            db.execute('UPDATE remote_control_review_heads SET revision=revision+1,pending_decision=%s,last_decision=%s WHERE agent_id=%s',(decision_id,decision_id,group))
            return self._decision(db,accepted)

    def apply_pending(self, group):
        """Fixed host only: recheck all evidence after admission, without a signal."""
        with self.database.connection() as db:
            row,head=self._locked(db,group)
            if not head['pending_decision']:return None
            decision=db.execute('SELECT * FROM remote_control_review_decisions WHERE id=%s',(head['pending_decision'],)).fetchone()
            plan=db.execute('SELECT *,expires_at>now() AS valid FROM remote_control_review_plans WHERE id=%s',(decision['plan_id'],)).fetchone()
            valid=False;context=None;sha=None
            try:
                admin(db,decision['actor_id'],lock=False)
                context,sha=self._context(db,row,decision['review_revision']-1)
                valid=bool(plan['valid'] and head['revision']==decision['review_revision'] and sha==plan['context_sha256'] and decision['choice'] in context['allowed'])
            except (Conflict,PermissionError):pass
            outcome='rejected_stale'
            if valid:
                if decision['choice']=='hold':outcome='held'
                elif decision['choice']=='confirm_observed':
                    outcome='observed_completed'
                    db.execute("UPDATE remote_control_requests SET phase='reviewed_completed',updated_at=now() WHERE request_id=%s",(decision['request_id'],))
                    db.execute('UPDATE remote_control_groups SET pending_request=NULL,revision=revision+1 WHERE agent_id=%s',(group,))
                else:
                    outcome='failed_quarantined'
                    db.execute("UPDATE remote_control_requests SET phase='reviewed_failed',updated_at=now() WHERE request_id=%s",(decision['request_id'],))
                    db.execute('UPDATE remote_control_groups SET pending_request=NULL,quarantined=true,revision=revision+1 WHERE agent_id=%s',(group,))
            evidence={'plan_sha256':plan['context_sha256'],'current_sha256':sha,'current_context':json.loads(json.dumps(context,default=public)) if context else None,'original_issue_history_unchanged':True,'native_signal_issued_by_recovery':False}
            db.execute('INSERT INTO remote_control_review_results(decision_id,outcome,evidence) VALUES(%s,%s,%s)',(decision['id'],outcome,Jsonb(evidence)))
            db.execute('UPDATE remote_control_review_heads SET pending_decision=NULL WHERE agent_id=%s',(group,))
            return {'decision_id':decision['id'],'outcome':outcome}

    def status(self, group):
        with self.database.connection() as db:
            row=db.execute('SELECT revision,pending_request,quarantined,observation_revision,observed_at FROM remote_control_groups WHERE agent_id=%s',(group,)).fetchone()
            if not row:raise Missing('control_group_missing')
            head=db.execute('SELECT * FROM remote_control_review_heads WHERE agent_id=%s',(group,)).fetchone()
            decisions=db.execute('SELECT d.*,a.username AS actor_name FROM remote_control_review_decisions d JOIN accounts a ON a.id=d.actor_id WHERE d.agent_id=%s ORDER BY d.review_revision DESC LIMIT 8',(group,)).fetchall()
            return {'group_revision':row['revision'],'request_id':row['pending_request'],'quarantined':row['quarantined'],'observation_revision':row['observation_revision'],
                    'review_revision':head['revision'] if head else 0,'pending_decision':head['pending_decision'] if head else None,'history':[self._decision(db,r) for r in decisions]}
