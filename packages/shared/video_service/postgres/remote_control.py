"""Opt-in fixed-host control mailbox. API cannot submit container IDs or commands.

Only a separately provisioned host process may publish observations/claim work.
Unknown outcomes remain blocked: this module never automatically replays a signal.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from psycopg.types.json import Jsonb
from . import Conflict, Missing


def _id(value, pattern):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError('invalid_control_identity')
    return value


def _receipt(row):
    return {k:row[k] for k in ('request_id','revision','phase','replicas','error_code')}


class RemoteControl:
    def __init__(self, database):
        self.database=database

    def provision(self, agent, contract, slots):
        """Trusted host-only registration, never an HTTP operation."""
        _id(agent,r'[a-z][a-z0-9_.-]{0,63}');_id(contract,r'[a-f0-9]{64}')
        if not isinstance(slots,list) or not 1<=len(slots)<=8 or len(set(slots))!=len(slots):
            raise ValueError('invalid_control_slots')
        for slot in slots:_id(slot,r'[a-f0-9]{32}')
        with self.database.connection() as db:
            db.execute('INSERT INTO remote_control_groups(agent_id,contract_sha256,slot_ids,capacity) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',(agent,contract,Jsonb(slots),len(slots)))
            row=db.execute('SELECT * FROM remote_control_groups WHERE agent_id=%s FOR UPDATE',(agent,)).fetchone()
            if (row['contract_sha256'],row['slot_ids'],row['capacity'])!=(contract,slots,len(slots)):
                raise Conflict('control_target_registration_conflict')

    def publish(self, agent, contract, instances):
        """Accept only allowlisted slot identities; running is inspect evidence, not readiness."""
        with self.database.connection() as db:
            row=db.execute('SELECT * FROM remote_control_groups WHERE agent_id=%s FOR UPDATE',(agent,)).fetchone()
            if not row:raise Missing('control_group_missing')
            if row['contract_sha256']!=contract:raise Conflict('control_contract_mismatch')
            if not isinstance(instances,list) or [i.get('id') for i in instances]!=row['slot_ids']:
                raise ValueError('control_observation_identity_mismatch')
            for instance in instances:
                if type(instance.get('running')) is not bool or instance.get('state') not in ('connected','ready','busy','stopping','stopped','unknown'):
                    raise ValueError('invalid_control_observation')
            db.execute('UPDATE remote_control_groups SET observed=%s,observed_at=now() WHERE agent_id=%s',(Jsonb(instances),agent))

    def _view(self, db, row):
        fresh=bool(row['observed_at'] and (datetime.now(timezone.utc)-row['observed_at']).total_seconds()<15)
        observed=row['observed'] or []
        request=db.execute('SELECT * FROM remote_control_requests WHERE request_id=%s',(row['pending_request'],)).fetchone() if row['pending_request'] else None
        phase=(request['phase'] if fresh else 'unknown') if request else None
        workers=[]
        for instance in observed:
            state=instance['state'] if fresh else 'unknown'
            workers.append({'worker_id':instance['id'],'state':state,'received_at':instance.get('received_at'),
                            'ticket_id':instance.get('ticket_id') if state in ('busy','stopping') else None,
                            'ticket_number':instance.get('ticket_number') if state in ('busy','stopping') else None,
                            'boot_id':instance.get('boot_id'),'node_id':None,'attempt_id':None,'recent_events':[]})
        actual=sum(i['running'] for i in observed) if fresh else None
        state='unknown'
        if fresh and observed:
            state=next((candidate for candidate in ('stopping','busy','unknown','connected','ready','stopped') if any(w['state']==candidate for w in workers)),'unknown')
        return {'agent_id':row['agent_id'],'revision':row['revision'],'enabled':row['enabled'],'replicas':row['replicas'],
                'max_replicas':row['capacity'],'manageable':fresh and phase!='unknown','runtime':'fixed_host',
                'observation_source':'fixed_host','telemetry':True,'collector':{'healthy':fresh,'received_at':row['observed_at'].isoformat() if row['observed_at'] else None},
                'observed_replicas':actual,'ready_replicas':sum(w['state']=='ready' for w in workers) if fresh else None,
                'draining_replicas':sum(w['state']=='stopping' for w in workers) if fresh else None,
                'workers':workers,'instances':[],'dependencies':[],'concurrency_per_instance':1,'state':state,
                'control':{'request_id':request['request_id'] if request else None,'phase':phase,'error_code':request['error_code'] if request else None},
                'unavailable_reason':None if fresh else 'control_observation_unavailable'}

    def get(self, agent):
        with self.database.connection() as db:
            row=db.execute('SELECT * FROM remote_control_groups WHERE agent_id=%s',(agent,)).fetchone()
            if not row:raise Missing('control_group_missing')
            return self._view(db,row)

    def has(self, agent):
        with self.database.connection() as db:
            return bool(db.execute('SELECT 1 FROM remote_control_groups WHERE agent_id=%s',(agent,)).fetchone())

    def configure(self, actor, agent, *, revision, enabled, replicas, request_id):
        _id(request_id,r'[a-f0-9]{32}')
        if type(revision) is not int or revision<0 or type(enabled) is not bool or type(replicas) is not int or replicas<0 or enabled!=(replicas>0):
            raise ValueError('invalid_control_configuration')
        digest=hashlib.sha256(json.dumps({'agent':agent,'revision':revision,'enabled':enabled,'replicas':replicas},sort_keys=True).encode()).hexdigest()
        with self.database.connection() as db:
            account=db.execute('SELECT role,active FROM accounts WHERE id=%s FOR SHARE',(actor,)).fetchone()
            if not account or not account['active'] or account['role']!='admin':raise PermissionError('관리자 권한이 필요합니다.')
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended('control-request:'||%s,0))",(request_id,))
            row=db.execute('SELECT * FROM remote_control_groups WHERE agent_id=%s FOR UPDATE',(agent,)).fetchone()
            if not row:raise Missing('control_group_missing')
            if replicas>row['capacity']:raise ValueError('control_count_out_of_range')
            previous=db.execute('SELECT * FROM remote_control_requests WHERE request_id=%s',(request_id,)).fetchone()
            if previous:
                if previous['actor_id']!=actor or previous['agent_id']!=agent or previous['payload_sha256']!=digest:
                    raise Conflict('control_request_id_reused')
                return _receipt(previous)
            if row['revision']!=revision:raise Conflict('control_revision_conflict')
            if row['pending_request']:raise Conflict('control_request_in_progress')
            if not self._view(db,row)['manageable']:raise Conflict('control_observation_unavailable')
            accepted=db.execute("INSERT INTO remote_control_requests(request_id,agent_id,actor_id,payload_sha256,revision,replicas,phase) VALUES (%s,%s,%s,%s,%s,%s,'queued') RETURNING *",(request_id,agent,actor,digest,revision+1,replicas)).fetchone()
            db.execute('UPDATE remote_control_groups SET revision=revision+1,enabled=%s,replicas=%s,pending_request=%s WHERE agent_id=%s',(enabled,replicas,request_id,agent))
            return _receipt(accepted)

    def claim(self, agent, contract):
        with self.database.connection() as db:
            row=db.execute('SELECT * FROM remote_control_groups WHERE agent_id=%s FOR UPDATE',(agent,)).fetchone()
            if not row or row['contract_sha256']!=contract:raise Conflict('control_contract_mismatch')
            if not row['pending_request']:return None
            command=db.execute("UPDATE remote_control_requests SET phase='applying',updated_at=now() WHERE request_id=%s AND phase='queued' RETURNING *",(row['pending_request'],)).fetchone()
            return dict(command) if command else None

    def finish(self, request_id, *, succeeded, error_code=None):
        with self.database.connection() as db:
            command=db.execute('SELECT * FROM remote_control_requests WHERE request_id=%s',(request_id,)).fetchone()
            if not command:raise Missing('control_request_missing')
            group=db.execute('SELECT * FROM remote_control_groups WHERE agent_id=%s FOR UPDATE',(command['agent_id'],)).fetchone()
            if group['pending_request']!=request_id:raise Conflict('control_request_not_current')
            actual=sum(i['running'] for i in (group['observed'] or []))
            if succeeded and (group['observed'] is None or actual!=command['replicas']):raise Conflict('control_target_not_observed')
            db.execute("UPDATE remote_control_requests SET phase=%s,error_code=%s,updated_at=now() WHERE request_id=%s AND phase='applying'",('succeeded' if succeeded else 'unknown',error_code,request_id))
            if succeeded:db.execute('UPDATE remote_control_groups SET pending_request=NULL WHERE agent_id=%s',(command['agent_id'],))


class ControlledFleet:
    """Overlay explicit registered groups only; no implicit adoption of live agents."""
    def __init__(self, base, control):self.base,self.control=base,control
    def get(self, agent):return self.control.get(agent) if self.control.has(agent) else self.base.get(agent)
    def list(self):return [self.get(item['agent_id']) for item in self.base.list()]
    def configure(self, actor, agent, **body):return self.control.configure(actor,agent,**body)
