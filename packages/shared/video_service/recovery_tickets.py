"""WF07 A opt-in recovery. Existing namespaces and legacy jobs are untouched."""
from copy import deepcopy
from pathlib import Path
import json
import shutil
from uuid import uuid4
from .work_tickets import WorkTicketStore
from .workflow_tickets import TicketStore, TicketConflict, digest
from .graph_tickets import file_sha
from .storage import read_json, write_json_atomic, resolve_under
from .locking import _file_lock, JobBusyError
from contextlib import contextmanager, ExitStack
import time


@contextmanager
def control_lock(path):
    # Retry lock acquisition only, never replay the protected operation.
    deadline=time.monotonic()+5
    with ExitStack() as stack:
        while True:
            try:
                stack.enter_context(_file_lock(path))
                break
            except JobBusyError:
                if time.monotonic()>=deadline:raise
                time.sleep(.005)
        yield



class RecoveryTicketStore(WorkTicketStore):
    execution_contract = 'recovery-v1'

    def __init__(self, root, owner=None):
        super().__init__(root, owner)
        self.directory = (Path(root)/'.workflow-recovery-tickets'/self.directory.name).resolve()
        self.owner_scope = self.directory.name
        self._sessions = {}

    def _control(self, identity):
        path=self.directory_for(identity)/'control.json'
        return read_json(path) if path.is_file() else {'revision':0,'generation':None,'cancel_requested':False,'retired':False,'claims':{},'requests':{},'closed':False}

    def _write_control(self, identity, control):
        control['revision']+=1
        write_json_atomic(self.directory_for(identity)/'control.json',control)

    def _admit_dispatch(self, record, step):
        identity=record['id']
        with control_lock(self.directory_for(identity)/'control.lock'):
            control=self._control(identity)
            if control['cancel_requested'] or control['retired'] or control['generation']!=self._sessions.get(identity):
                return False
            control['claims'][step['id']]={'generation':control['generation'],'status':'admitted','type':step['type']}
            self._write_control(identity,control)
            return True

    def _before_node(self, record, step):
        identity=record['id']
        with control_lock(self.directory_for(identity)/'control.lock'):
            control=self._control(identity)
            if control['cancel_requested'] or control['retired'] or control['generation']!=self._sessions.get(identity):
                raise TicketConflict('취소/이전 세대는 새 노드를 dispatch하지 않습니다.')
            control['claims'][step['id']]={'generation':control['generation'],'status':'running','type':step['type']}
            self._write_control(identity,control)

    def _verify_meta(self, record, meta, seen=None):
        seen = set() if seen is None else set(seen)
        if 'reference' in meta:
            b = meta['reference']; key = (b['node'],b['port'])
            if key in seen: raise TicketConflict('복구 자료 참조가 순환합니다.')
            seen.add(key)
            if b['node'] == '$input':
                if meta['sha256'] != record['source_sha256']: raise TicketConflict('복구 원본 참조 SHA가 다릅니다.')
            else:
                parent = next(s for s in record['steps'] if s['id']==b['node'])['artifacts'][b['port']]
                if parent['sha256'] != meta['sha256']: raise TicketConflict('복구 참조 SHA가 다릅니다.')
                self._verify_meta(record,parent,seen)
        elif 'path' in meta:
            p=resolve_under(self.directory_for(record['id']),meta['path'])
            if file_sha(p)!=meta['sha256'] or p.stat().st_size!=meta['bytes']:
                raise TicketConflict('복구 산출물 bytes/SHA가 다릅니다.')
            if meta['type']=='artifact_manifest':
                for value in read_json(p)['members'].values(): self._verify_meta(record,value,seen)
        elif meta.get('asset_id')!=record['asset']['asset_id'] or meta['sha256']!=record['source_sha256']:
            raise TicketConflict('복구 입력 출처가 다릅니다.')

    def review_document(self, identity, node):
        from .review_documents import ReviewDocuments
        raw=TicketStore.get(self,identity)
        context=raw.get('reuse_origins',{}).get(node,{}).get('review_context')
        if context:
            return ReviewDocuments(self.directory_for(identity)/'work'/node/'review',context)
        return super().review_document(identity,node)

    def _review_view(self, record, state):
        from .review_documents import ReviewDocuments
        context=record.get('reuse_origins',{}).get(state['id'],{}).get('review_context',{'ticket':record['id'],'node':state['id']})
        doc=ReviewDocuments(self.directory_for(record['id'])/'work'/state['id']/'review',context)
        return doc.get() if doc.index.is_file() else None

    def _is_complete(self, record, state):
        return state['status']=='succeeded' or state.get('wait',{}).get('kind')=='decision_confirmation' or (state['type']=='review' and state['status']=='waiting' and bool((self._review_view(record,state) or {}).get('approval')))

    def _receipt(self, record, state):
        selected = next(s for s in self._execution_sequence(record)['steps'] if s['id']==state['id'])
        inputs={}
        for port,b in selected['active_bindings'].items():
            if b['node']=='$input': value={'asset':record['asset'],'sha256':record['source_sha256']}
            else:
                value=next(s for s in record['steps'] if s['id']==b['node'])['artifacts'][b['port']]
                self._verify_meta(record,value)
            inputs[port]={'binding':b,'value':value}
        for value in state['artifacts'].values(): self._verify_meta(record,value)
        frozen = self._decisions(record).get(state['id']) if state['type']=='decision' else None
        review=None
        if state['type']=='review':
            view=self._review_view(record,state)
            if view:review={k:view[k] for k in ('target','revision','sha256','document_sha256','approval')}
        return {'version':1,'owner_scope':self.owner_scope,'definition_sha256':record['definition_sha256'],
                'options_sha256':digest(record['options']),'source_sha256':record['source_sha256'],
                'node':state['id'],'step_sha256':digest(selected),'inputs_sha256':digest(inputs),
                'model_pin':deepcopy(record['model_bindings'].get(state['id'])),
                'outputs':{} if frozen or review and review['approval'] else deepcopy(state['artifacts']),'frozen_decision':frozen,'review':review}

    def _save(self, record):
        identity=record['id']
        self.directory_for(identity).mkdir(parents=True,exist_ok=True,mode=0o700)
        with control_lock(self.directory_for(identity)/'control.lock'):
            control=self._control(identity)
            if record['status']=='running' and (control['generation'] is None or control['closed']):
                if control['cancel_requested'] or control['retired']:raise TicketConflict('취소/종료된 세대는 실행하지 않습니다.')
                control.update(generation=uuid4().hex,closed=False,claims={})
                self._sessions[identity]=control['generation']
                self._write_control(identity,control)
            expected=self._sessions.get(identity)
            if expected and (control['generation']!=expected or control['retired']):
                write_json_atomic(self.directory_for(identity)/'late-results'/(uuid4().hex+'.json'),{'generation':expected,'steps':record['steps']})
                raise TicketConflict('이전 세대 결과는 현재 티켓 상태를 갱신하지 않습니다.')
            quarantined=control.setdefault('quarantined_nodes',{})
            changed=False
            for state in record['steps']:
                if (control['cancel_requested'] and state['id'] in control['claims'] and state['id'] not in record.get('receipts',{})
                        and state['status'] in {'succeeded','waiting'} and state['id'] not in quarantined):
                    quarantined[state['id']]={'generation':control['generation'],'reason':'취소 접수 뒤 도착한 결과: 보존/다운로드만 허용, 정상 receipt 재사용 불가'}
                    changed=True
                if state['id'] in quarantined:
                    state.update(status='quarantined',quarantine=quarantined[state['id']])
                    scheduler=record.get('scheduler',{})
                    outcome=scheduler.get('nodes',{}).get(state['id'])
                    if outcome is not None:
                        outcome['status']='quarantined'
                        if 'result' in outcome:outcome['quarantined_result']=outcome.pop('result')
                        if state['id'] not in scheduler.setdefault('unresolved',[]):scheduler['unresolved'].append(state['id'])
                if state['id'] in control['claims'] and state['status'] in {'succeeded','failed','waiting','quarantined'}:
                    control['claims'][state['id']]['status']=state['status']
            if changed:self._write_control(identity,control)
            if expected and record['status']!='running':
                control['closed']=True
                if control['cancel_requested']:
                    record['status']='cancelled'
                    record.pop('error',None)
                self._write_control(identity,control)
        record.setdefault('recovery_policy_version',1)
        receipts=record.setdefault('receipts',{})
        if record.get('source_sha256'):
            for state in record['steps']:
                if self._is_complete(record,state):
                    receipt=self._receipt(record,state)
                    if state['id'] in receipts and receipts[state['id']]!=receipt:
                        raise TicketConflict('완료 receipt를 다른 결과/입력으로 바꿀 수 없습니다.')
                    receipts[state['id']]=receipt
        super()._save(record)

    def list(self):
        return [self.get(p.parent.name) for p in sorted(self.directory.glob('*/ticket.json'))]

    def get(self, identity):
        result=super().get(identity)
        if result.get('recovery_policy_version')!=1: raise TicketConflict('복구 opt-in 티켓이 아닙니다.')
        control=self._control(identity)
        result['control_revision']=control['revision']
        result['execution_generation']=control['generation']
        result['active_generation']=control['generation'] if not control['closed'] and not control['retired'] else None
        result['recovery_unknown_nodes']=self._unknown_nodes(result,control)
        result['cancel_requested']=control['cancel_requested']
        for node in control.get('quarantined_nodes',{}):
            if node in result.get('decisions',{}):result['decisions'][node]['status']='quarantined'
            if node in result.get('model_availability',{}):result['model_availability'][node]['complete']=False
        if control['cancel_requested'] and result['status'] not in {'completed','failed','cancelled'}:
            result['status']='cancelling' if not control['closed'] and control['generation'] else 'cancelled'
        return result

    def _unknown_nodes(self, record, control):
        states={s['id']:s for s in record['steps']}
        return sorted(node for node in control['claims'] if not self._is_complete(record,states[node]) and (
            states[node]['status'] in {'running','quarantined'} or (states[node]['status']=='failed' and states[node]['type'] in {'transcribe','translate','decision'}
            and states[node].get('error_type')!='ModelUnavailable')))

    def _plan_extension(self, record):
        return {**super()._plan_extension(record),'recovery_context':{'ticket_id':record['id'],'contract':self.execution_contract,
                'parent':record.get('recovery_parent'),'risk':record.get('recovery_risk'),'reuse':record.get('reuse_origins',{})}}

    def plan(self, identity, preferences):
        record=self.get(identity)
        for state in record['steps']:
            if self._is_complete(record,state):
                receipt=self._receipt(record,state)
                approved_wait=state['type']=='review' and state['status']=='waiting' and bool(receipt['review']['approval'])
                if not approved_wait and record['receipts'].get(state['id'])!=receipt:
                    raise TicketConflict('재사용할 완료 receipt 누락/불일치입니다. 새 호출 전에 차단합니다.')
        result=super().plan(identity,preferences)
        finalization=bool(record.get('recovery_parent')) and not result['eligible_steps'] and bool(record.get('scheduler')) and all(
            s['status'] in {'succeeded','skipped'} for s in record['scheduler']['nodes'].values())
        if finalization:
            result.update(ready=True,finalization_only=True,notice='완료 receipt만 검증하여 상태를 마무리합니다. 새 노드 호출/재판정/합류 실행은 없습니다. 이 계획의 확인과 별도 실행 요청이 필요합니다.')
        return result

    def fork(self, identity, request_id, revision, source, *, risk_confirmed=False, capacity_check=None):
        self.directory.mkdir(parents=True,exist_ok=True)
        with _file_lock(self.directory/'recovery-admission.lock'), _file_lock(self.directory_for(identity)/'execution.lock'):
            fingerprint=digest({'parent':identity,'revision':revision,'risk_confirmed':risk_confirmed})
            for existing in self.list():
                if existing.get('recovery_request_id')==request_id:
                    if existing['recovery_fingerprint']!=fingerprint: raise TicketConflict('같은 복구 요청의 대상/위험 확인이 다릅니다.')
                    return self.get(existing['id'])
            parent=self.get(identity)
            frozen={k:parent['definition'][k] for k in ('catalog_version','revision','name','inputs','nodes','edges')}
            if (digest(parent['definition'])!=parent['definition_sha256'] or self._compile_definition(frozen,parent['options'])!=parent['sequence']
                    or [(s['id'],s['type']) for s in parent['steps']]!=[(s['id'],s['type']) for s in parent['sequence']['steps']]):
                raise TicketConflict('복구 원본 정의/실행 순서 snapshot 무결성이 다릅니다.')
            if parent['revision']!=revision or parent['status'] not in {'failed','cancelled','running'}:
                raise TicketConflict('실패/취소/중단된 정확한 티켓만 새 복구 티켓으로 분리할 수 있습니다.')
            control=self._control(identity)
            if control.get('recovery_child'):
                raise TicketConflict('이미 분리한 복구 티켓이 있습니다. 해당 자식 티켓을 확인하세요.')
            unknown=self._unknown_nodes(parent,control)
            if unknown and risk_confirmed is not True:
                raise TicketConflict('결과 불명 호출이 있습니다. 중복 호출/과금 위험을 별도로 확인해야 합니다.')
            actual_sha=file_sha(source)
            stat=Path(source).stat()
            if (stat.st_size,stat.st_mtime_ns)!=(parent['asset']['size_bytes'],parent['asset']['source_mtime_ns']):
                raise TicketConflict('고정 입력 정보가 다릅니다.')
            if parent.get('source_sha256') is None and not control['claims']:
                parent['source_sha256']=actual_sha  # Never executed; bind only the new child, not the parent file.
            if actual_sha!=parent.get('source_sha256'):
                raise TicketConflict('고정 원본 SHA가 다릅니다. 추정 재사용하지 않습니다.')
            verified={}
            for state in parent['steps']:
                if self._is_complete(parent,state):
                    receipt=self._receipt(parent,state)
                    approved_wait=state['type']=='review' and state['status']=='waiting' and bool(receipt['review']['approval'])
                    if not approved_wait and receipt!=parent['receipts'].get(state['id']): raise TicketConflict('완료 receipt 누락/불일치입니다.')
                    verified[state['id']]=receipt
            admission=self.directory/'.recovery-requests'/(digest(request_id)+'.json')
            if admission.is_file():
                admitted=read_json(admission)
                if admitted['fingerprint']!=fingerprint:raise TicketConflict('미완료 복구 요청의 대상/확인이 다릅니다.')
            else:
                admitted={'fingerprint':fingerprint,'child_id':uuid4().hex,'attempt_id':uuid4().hex}
                write_json_atomic(admission,admitted)
            child=deepcopy(parent)
            child.update(id=admitted['child_id'],revision=0,request_id='recovery:'+request_id,status='held',phase=0,
                         confirmation=None,settings_snapshot=None,run_requests={},receipts={},reuse_origins={},
                         recovery_request_id=request_id,recovery_fingerprint=fingerprint,
                         recovery_risk={'acknowledged':bool(risk_confirmed),'unknown_nodes':unknown,'notice':'결과 불명 호출의 중복 호출/과금 가능성을 확인했습니다. 실행/비용 계획 확인은 별도입니다.'},
                         recovery_parent={'ticket_id':identity,'revision':revision,'attempt_id':admitted['attempt_id']})
            for key in ('error','entry_confirmation','decisions','execution_view','reviews','model_availability','control_revision'):
                child.pop(key,None)
            child_dir=self.directory_for(child['id'])
            seed={}
            for state in child['steps']:
                node=state['id']
                if node in verified:
                    child['reuse_origins'][node]={'ticket_id':identity,'receipt_sha256':digest(verified[node])}
                    seed[node]=deepcopy(parent.get('scheduler',{}).get('nodes',{}).get(node,{'status':state['status'],'result':{'artifacts':state['artifacts']}}))
                    paths=[m['path'] for m in state['artifacts'].values() if 'path' in m]
                    if state['type']=='decision': paths+=['work/'+node+'/decision.json','work/'+node+'/route.json']
                    if state['type']=='review':
                        doc=self.review_document(identity,node);index=doc._read()
                        child['reuse_origins'][node]['review_context']=deepcopy(doc.context)
                        prefix='work/'+node+'/review/'
                        paths.append(prefix+'review.json')
                        for row in index['versions'].values():
                            for key,sha in (('document_path','document_sha256'),('output_path','sha256')):
                                if row.get(key):
                                    relative=prefix+row[key]
                                    if file_sha(resolve_under(self.directory_for(identity),relative))!=row[sha]:raise TicketConflict('검수 이력 SHA가 다릅니다.')
                                    paths.append(relative)
                    for relative in set(paths):
                        src=resolve_under(self.directory_for(identity),relative);dst=resolve_under(child_dir,relative)
                        if capacity_check:capacity_check(src.stat().st_size+524288)
                        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
                elif state['status']=='skipped':
                    seed[node]={'status':'skipped','reason':state.get('reason','unselected')}
                else:
                    state.update(status='pending',artifacts={},partial_artifacts={})
                    for key in ('wait','error_type','blocked_by','reason','serving_snapshot','quarantine'):state.pop(key,None)
                    seed[node]={'status':'pending'}
            child['scheduler']={'revision':0,'nodes':seed,'unresolved':[n for n,s in seed.items() if s['status']=='pending']}
            self._save(child)
            with control_lock(self.directory_for(identity)/'control.lock'):
                control=self._control(identity)
                control.update(retired=True,recovery_child=child['id'])
                self._write_control(identity,control)
            return self.get(child['id'])

    def cancel(self, identity, revision, request_id):
        with _file_lock(self.directory_for(identity)/'state.lock'), control_lock(self.directory_for(identity)/'control.lock'):
            record=TicketStore.get(self,identity);control=self._control(identity)
            fingerprint=digest({'operation':'cancel','revision':revision})
            if request_id in control['requests']:
                if control['requests'][request_id]!=fingerprint:raise TicketConflict('같은 취소 요청의 CAS가 다릅니다.')
            else:
                if control['revision']!=revision or record['status'] in {'completed','failed','cancelled'}:
                    raise TicketConflict('오래된 취소 요청이거나 이미 정리된 티켓입니다. 완료를 뒤집지 않습니다.')
                control['cancel_requested']=True
                control['requests'][request_id]=fingerprint
                self._write_control(identity,control)
        return self.get(identity)
