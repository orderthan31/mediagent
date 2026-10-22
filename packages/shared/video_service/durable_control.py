"""Opt-in nonblocking signals for explicitly pinned, no-restart worker slots.

SIGTERM only: never SIGKILL, never a timed kill of the media process. The native
CLI timeout bounds only delivery of a signal, not the duration of job draining.
"""
import json
from contextlib import contextmanager, nullcontext

from .agent_control import ControlError, DockerControl


class SignalControl(DockerControl):
    def details(self, group):
        self._snapshot(group)
        targets=self._targets(group)
        try:
            raw=json.loads(self.run(['container','inspect',*[t.container_id for t in targets]]))
            rows={r['Id']:r for r in raw}
            if len(raw)!=len(targets) or set(rows)!={t.container_id for t in targets}:raise ValueError
            result=[]
            for target in targets:
                row=rows[target.container_id];state=row['State']
                if row['Image']!=target.image_id or any(row['Config']['Labels'].get(k)!=v for k,v in target.labels):
                    raise ControlError('control_target_identity_mismatch')
                if state['Paused'] or state['Dead'] or state['Status'] not in ('created','running','exited') or type(state['Running']) is not bool:
                    raise ControlError('control_target_state_unavailable')
                policy=row['HostConfig']['RestartPolicy']['Name']
                if policy!='no':raise ControlError('signal_control_requires_no_restart_policy')
                result.append({'id':target.container_id,'running':state['Running'],'state':state['Status'],
                               'exit_code':state['ExitCode'],'started_at':state['StartedAt'],'restart_policy':policy})
            return {'agent_id':group,'capacity':len(targets),'running':sum(r['running'] for r in result),'instances':result}
        except (TypeError,ValueError,KeyError):raise ControlError('invalid_control_observation') from None

    def signal(self, group, index, action):
        targets=self._targets(group)
        if type(index) is not int or not 0<=index<len(targets) or action not in ('start','stop'):
            raise ControlError('invalid_control_signal')
        with self.locks[group], (self.native_authority(group) if hasattr(self, "native_authority") else nullcontext()):
            observed=self.details(group)
            running=observed['instances'][index]['running']
            if action=='start' and not running:
                self.run(['container','start',targets[index].container_id]);return True
            elif action=='stop' and running:
                self.run(['container','kill','--signal','SIGTERM',targets[index].container_id]);return True
            return False


class BrokerReports:
    """Read-only, ID/family/role-bound telemetry; no access to job/password tables."""
    def __init__(self, database, profiles):
        from .worker_telemetry import exchange
        for family,role in profiles.values():exchange(family,role)
        self.database,self.profiles=database,profiles

    def read(self, group, worker_ids):
        if group not in self.profiles:raise ControlError('broker_control_group_not_allowed')
        with self.database.connection() as db:
            healthy=db.execute("SELECT received_at>now()-interval '15 seconds' AS healthy FROM telemetry_observer WHERE singleton=true").fetchone()
            if not healthy or not healthy['healthy']:raise ControlError('broker_observer_unavailable')
            rows=db.execute('SELECT * FROM worker_observations WHERE worker_id=ANY(%s)',(worker_ids,)).fetchall()
        family,role=self.profiles[group]
        if any(r['family']!=family or r['role']!=role for r in rows):raise ControlError('broker_worker_identity_mismatch')
        return {r['worker_id']:dict(r) for r in rows}


from datetime import datetime, timezone

from .control_host import HostControl, _time
from .postgres.control_journal import ControlJournal


class DurableHost(HostControl):
    """Signal once, observe indefinitely; recover acknowledged sends read-only."""
    def __init__(self, store, adapter, slots, reports, *, receipts=None, recovery=None):
        if (receipts is None)!=(recovery is None):raise ControlError('recovery_requires_private_ack_store')
        self.receipts,self.recovery=receipts,recovery
        if not isinstance(adapter,SignalControl):raise ControlError('signal_adapter_required')
        self.reports=reports
        super().__init__(store,adapter,slots)
        self.journal=ControlJournal(store)
        self.adapter.native_authority = self._native_authority

    @contextmanager
    def _native_authority(self, group):
        # Held original session + row share lock span inspect and native POST.
        # Never reconnect a stale owner, and never act on a retired contract.
        with self.owner.transaction():
            row = self.owner.execute('SELECT contract_sha256,pending_handover FROM remote_control_groups WHERE agent_id=%s FOR SHARE', (group,)).fetchone()
            if not row or row[0] != self.contracts[group] or row[1] is not None:
                raise ControlError('retired_host_native_signal_blocked')
            yield

    def observe(self, group):
        actual=self.adapter.details(group)
        reports=self.reports.read(group,self.slots[group]);now=datetime.now(timezone.utc)
        observations=[]
        for physical,wid,target in zip(actual['instances'],self.slots[group],self.adapter._targets(group)):
            report=reports.get(wid);received=report['received_at'] if report else None
            started=_time(physical['started_at'])
            same_boot=bool(report and started and isinstance(received,datetime) and received>=started)
            state='stopped' if not physical['running'] else 'unknown'
            if physical['running'] and same_boot and isinstance(received,datetime) and 0<=(now-received).total_seconds()<15:
                state=report['state'] if report['state']!='stopped' else 'unknown'
            observations.append({'id':wid,'target_id':physical['id'],'image_id':target.image_id,'running':physical['running'],'state':state,
                                 'exit_code':physical['exit_code'],'started_at':physical['started_at'],'restart_policy':physical['restart_policy'],
                                 'boot_id':report['boot_id'] if same_boot else None,
                                 'received_at':received.isoformat() if received else None,
                                 'report_state':report['state'] if same_boot else None,
                                 'report_received_at':received.isoformat() if isinstance(received,datetime) and same_boot else None,
                                 'ticket_id':report['ticket_id'] if same_boot and state in ('busy','stopping') else None,
                                 'attempt_id':report['attempt_id'] if same_boot and state in ('busy','stopping') else None,
                                 'ticket_number':None})
        self.store.publish(group,self.contracts[group],observations)
        return observations

    def step(self):
        self.owner.execute('SELECT 1')
        for group,ids in self.slots.items():
            try:observed=self.observe(group)
            except ControlError:
                with self.store.database.connection() as db:
                    db.execute('UPDATE remote_control_groups SET observed_at=NULL WHERE agent_id=%s',(group,))
                continue
            command=self.journal.pending(group)
            if not command:
                if self.recovery:self.recovery.apply_pending(group)
                continue
            if command['phase']=='queued':command=self.store.claim(group,self.contracts[group])
            if not command:
                if self.recovery:self.recovery.apply_pending(group)
                continue
            # Never signal an unauthenticated/unobserved running consumer.
            removing=[r for index,r in enumerate(observed) if index>=command['replicas'] and r['running']]
            if any(r['state']=='unknown' or not r['boot_id'] for r in removing):
                self._review(group,command)
                continue
            self.journal.prepare(command,self.contracts[group],observed)
            actions=self.journal.actions(command['request_id'])
            if not any(a['phase'] in ('issuing','unknown') for a in actions):
                for action in actions:
                    if action['phase']!='planned':continue
                    if self.journal.begin(action['id'],owner=self.owner):
                        try:
                            index=ids.index(action['worker_id'])
                            action=next(a for a in self.journal.actions(command['request_id']) if a['id']==action['id'])
                            delivered=self.adapter.signal(group,index,action['action'])
                            if self.receipts:
                                if delivered is not True:raise ControlError('native_ack_not_observed')
                                after=self.adapter.details(group)['instances'][index]
                                self.receipts.record(action,self.contracts[group],self.adapter._targets(group)[index],after)
                        except ControlError:self.journal.unknown(action['id'])
                        else:self.journal.sent(action['id'])
            fresh=self.observe(group)
            self.journal.reconcile(command['request_id'],fresh)
            self._review(group,command)

    def _review(self,group,command):
        if not self.recovery or not self.receipts:return
        for action in self.journal.actions(command['request_id']):
            if not action['issued_at']:continue
            target=self.adapter._targets(group)[self.slots[group].index(action['worker_id'])]
            try:proof=self.receipts.read(action,self.contracts[group],target)
            except ControlError:self.recovery.publish_evidence(action['id'],None,error_code='ack_receipt_invalid')
            else:self.recovery.publish_evidence(action['id'],proof)
        self.recovery.apply_pending(group)
