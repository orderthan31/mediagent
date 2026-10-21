"""Separate trusted host controller. Never imported by the product API.

Only pinned targets from an explicit local configuration can receive lifecycle
signals. API writes a durable desired-count mailbox; it cannot submit Docker IDs,
images, labels, command arguments, or a socket path.
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import psycopg
from .agent_control import DockerControl, ControlError


def _time(value):
    if not value:return None
    try:return datetime.fromisoformat(value.replace('Z','+00:00'))
    except (ValueError,AttributeError):return None


class HostControl:
    def __init__(self, store, adapter, slots):
        if set(slots)!=set(adapter.groups):raise ControlError('control_slot_groups_mismatch')
        all_ids=[worker_id for ids in slots.values() for worker_id in ids]
        if len(set(all_ids))!=len(all_ids):raise ControlError('duplicate_worker_identity')
        self.store,self.adapter,self.slots=store,adapter,slots
        self.observer=DockerControl(adapter.groups,runner=adapter.run)
        self.contracts={}
        for group,targets in adapter.groups.items():
            ids=slots[group]
            if len(ids)!=len(targets) or len(set(ids))!=len(ids):raise ControlError('invalid_control_slot_mapping')
            for target,worker_id in zip(targets,ids):
                if dict(target.labels).get('mideagent.worker_id')!=worker_id:
                    raise ControlError('worker_identity_pin_required')
            contract=[{'container_id':t.container_id,'image_id':t.image_id,'labels':t.labels,'worker_id':wid} for t,wid in zip(targets,ids)]
            digest=hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest()
            self.contracts[group]=digest
            store.provision(group,digest,ids)
        self.owner=psycopg.connect(store.database.dsn,autocommit=True,connect_timeout=5)
        got=self.owner.execute("SELECT pg_try_advisory_lock(hashtextextended(current_database()||':'||current_schema()||':fixed-host-control-v1',0))").fetchone()[0]
        if not got:
            self.owner.close();raise ControlError('control_host_already_owned')
        self.pool=ThreadPoolExecutor(max_workers=len(slots),thread_name_prefix='fixed-control')
        self.active={}

    def observe(self, group):
        actual=self.observer.observe(group)
        # StartedAt fences reports from a previous boot even if they are recent.
        raw=json.loads(self.adapter.run(['container','inspect',*[t.container_id for t in self.adapter.groups[group]]]))
        started={row['Id']:_time(row['State'].get('StartedAt')) for row in raw}
        with self.store.database.connection() as db:
            reports={row['worker_id']:dict(row) for row in db.execute('SELECT * FROM remote_control_reports WHERE agent_id=%s',(group,)).fetchall()}
        now=datetime.now(timezone.utc);instances=[]
        for inspected,wid in zip(actual['instances'],self.slots[group]):
            report=reports.get(wid);state='stopped' if not inspected['running'] else 'unknown'
            timestamp=report['received_at'] if report else None
            boot_after=started.get(inspected['id'])
            if inspected['running'] and report and timestamp is not None and boot_after and timestamp>=boot_after and 0<=(now-timestamp).total_seconds()<10:
                state=report['state'] if report['state']!='stopped' else 'unknown'
            instances.append({'id':wid,'running':inspected['running'],'state':state,
                              'received_at':timestamp.isoformat() if timestamp else None,
                              'boot_id':report['boot_id'] if report else None,
                              'ticket_id':report['ticket_id'] if report and state in ('busy','stopping') else None,
                              'ticket_number':report['ticket_number'] if report and state in ('busy','stopping') else None})
        self.store.publish(group,self.contracts[group],instances)
        return actual

    def step(self):
        # Loss of the held connection means loss of authority; never reconnect/adopt.
        self.owner.execute('SELECT 1')
        for group in self.slots:
            self.observe(group)
            active=self.active.get(group)
            if active and active[1].done():
                command,future=active
                try:
                    future.result()
                    self.observe(group)
                    self.store.finish(command['request_id'],succeeded=True)
                except Exception as error:
                    code=str(error) if isinstance(error,ControlError) else 'control_outcome_unknown'
                    self.store.finish(command['request_id'],succeeded=False,error_code=code)
                del self.active[group]
            if group not in self.active:
                command=self.store.claim(group,self.contracts[group])
                if command:
                    self.active[group]=(command,self.pool.submit(self.adapter.apply,group,command['replicas']))

    def close(self):
        # No forced kill. An already-admitted cooperative stop may still finish.
        self.pool.shutdown(wait=True,cancel_futures=False)
        self.owner.close()
