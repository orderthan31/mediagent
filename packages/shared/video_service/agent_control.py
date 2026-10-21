"""Host-only primitive for fixed, pre-provisioned agent slots.

Not an API/RPC endpoint or an authorization layer. A trusted controller must bind
admin admission/revisions before calling this adapter. It never creates/removes
containers, changes images/mounts, or exposes Docker access to the product API.
"""
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import json
import re
import subprocess
import threading


class ControlError(RuntimeError):
    """Sanitized outcome; never surface inspect environment or CLI stderr."""


@dataclass(frozen=True)
class Target:
    container_id: str
    image_id: str
    labels: tuple

    def __post_init__(self):
        if (not isinstance(self.container_id,str) or not re.fullmatch(r'[a-f0-9]{64}',self.container_id)
            or not isinstance(self.image_id,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',self.image_id)
            or not isinstance(self.labels,tuple) or not all(isinstance(p,tuple) and len(p)==2
                and all(isinstance(v,str) and v for v in p) for p in self.labels)):
            raise ControlError('invalid_control_target')
        keys=[k for k,_ in self.labels]
        if len(set(keys))!=len(keys) or not {'com.docker.compose.project','com.docker.compose.service'}<=set(keys):
            raise ControlError('control_target_labels_required')


def _cli(context,args):
    try:
        result=subprocess.run(['docker','--context',context,*args],capture_output=True,text=True,timeout=30,check=False)
        if result.returncode:
            raise ControlError('control_command_failed')
        return result.stdout
    except (OSError,subprocess.TimeoutExpired):
        # A timeout is unknown/pending, not confirmation that the daemon stopped it.
        raise ControlError('control_outcome_unknown') from None


class DockerControl:
    def __init__(self,groups,*,runner=None,context=None):
        if not isinstance(groups,dict) or not groups:
            raise ControlError('control_groups_required')
        self.groups={}
        seen=set()
        for name,targets in groups.items():
            if not isinstance(name,str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{0,63}',name):
                raise ControlError('invalid_control_group')
            if not isinstance(targets,tuple) or not 1<=len(targets)<=32 or not all(isinstance(t,Target) for t in targets):
                raise ControlError('invalid_control_slots')
            for target in targets:
                if target.container_id in seen:raise ControlError('duplicate_control_target')
                seen.add(target.container_id)
            self.groups[name]=targets
        if runner is None:
            if not isinstance(context,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',context):
                raise ControlError('explicit_docker_context_required')
            runner=lambda args:_cli(context,args)
        self.run=runner
        self.locks={name:threading.Lock() for name in groups}

    def _targets(self,group):
        if not isinstance(group,str) or group not in self.groups:
            raise ControlError('control_group_not_allowed')
        return self.groups[group]

    def _snapshot(self,group):
        targets=self._targets(group)
        try:
            rows=json.loads(self.run(['container','inspect',*[t.container_id for t in targets]]))
            if not isinstance(rows,list) or len(rows)!=len(targets):raise ValueError
            indexed={r['Id']:r for r in rows}
            if set(indexed)!={t.container_id for t in targets}:raise ValueError
            states=[]
            for target in targets:
                row=indexed[target.container_id]
                if row['Image']!=target.image_id or any(row['Config']['Labels'].get(k)!=v for k,v in target.labels):
                    raise ControlError('control_target_identity_mismatch')
                state=row['State']
                if state['Paused'] or state['Dead'] or state['Status'] not in ('running','exited','created'):
                    raise ControlError('control_target_state_unavailable')
                if type(state['Running']) is not bool:raise ValueError
                states.append({'id':target.container_id,'running':state['Running'],'state':state['Status']})
            return {'agent_id':group,'capacity':len(targets),'running':sum(s['running'] for s in states),'instances':states}
        except (ValueError,KeyError,TypeError,AttributeError):
            raise ControlError('invalid_control_observation') from None

    def observe(self,group):
        self._targets(group)
        with self.locks[group]:return self._snapshot(group)

    def apply(self,group,replicas):
        targets=self._targets(group)
        if type(replicas) is not int or not 0<=replicas<=len(targets):
            raise ControlError('control_count_out_of_range')
        with self.locks[group]:
            before=self._snapshot(group)  # Validate every identity before any mutation.
            for index,target in enumerate(targets):
                running=before['instances'][index]['running']
                if index<replicas and not running:
                    self.run(['container','start',target.container_id])
            removed=[targets[index] for index in range(len(targets)-1,replicas-1,-1)
                     if before['instances'][index]['running']]
            if removed:
                # Signal every removed slot before waiting on any long task.
                # No timed SIGKILL: each target cooperatively drains its own work.
                with ThreadPoolExecutor(max_workers=len(removed)) as stopping:
                    calls=[stopping.submit(self.run,['container','stop','--timeout','-1',target.container_id])
                           for target in removed]
                    for call in calls:call.result()
            after=self._snapshot(group)
            if after['running']!=replicas:raise ControlError('control_target_not_reached')
            return after
