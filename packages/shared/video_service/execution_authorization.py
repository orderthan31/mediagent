"""Server-owned, durable execution approvals; no payment/refund/exactly-once claim."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
import re
import time
from uuid import uuid4
from .workflow_definitions import DefinitionStore
from .workflow_tickets import TicketConflict, digest
from .locking import _file_lock, JobBusyError
from .storage import read_json, write_json_atomic


class AuthorizationConflict(TicketConflict):
    pass


@contextmanager
def ledger_lock(path):
    deadline=time.monotonic()+10
    while True:
        manager=_file_lock(path)
        try:manager.__enter__();break
        except JobBusyError:
            if time.monotonic()>=deadline:raise
            time.sleep(.005)
    try:yield
    finally:manager.__exit__(None,None,None)


class AuthorizationStore:
    def __init__(self,root,owner=None,*,clock=None):
        self.root=Path(root)
        self.owner=owner
        self.directory=self.root/'.execution-authorizations'/DefinitionStore(root,owner).directory.name
        self.path=self.directory/'ledger.json'
        self.clock=clock or time.time

    def _read(self):
        return read_json(self.path) if self.path.is_file() else {'version':1,'grants':{},'confirm_requests':{},'requests':{},'executions':{}}

    @contextmanager
    def _transaction(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        with ledger_lock(self.directory/'ledger.lock'):
            data=self._read();yield data;write_json_atomic(self.path,data)

    def get(self,identity):
        if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{32}',identity):raise FileNotFoundError('승인이 없습니다.')
        try:return deepcopy(self._read()['grants'][identity])
        except KeyError:raise FileNotFoundError('이 owner의 승인이 없습니다.') from None

    def confirm(self,request_id,context,paid_confirmed,*,risk_confirmed=False):
        cost=context.get('cost',{})
        if cost.get('state') not in {'no_external_call','may_charge'}:raise AuthorizationConflict('비용 분류 누락/오류입니다. 무료로 취급하거나 확인으로 우회하지 않습니다.')
        if cost['state']=='may_charge' and paid_confirmed is not True:raise AuthorizationConflict('유료 가능·금액 미산정이며 0원/비용 상한 보장이 아님을 명시 확인하세요.')
        if context.get('risk_required') and risk_confirmed is not True:raise AuthorizationConflict('이전 legacy 호출의 결과가 불명입니다. 중복 호출/과금 위험의 별도 확인과 새 승인이 필요합니다.')
        fingerprint=digest(context)
        request_digest=digest({'context':context,'paid_confirmed':paid_confirmed,'risk_confirmed':risk_confirmed})
        with self._transaction() as data:
            old=data['confirm_requests'].get(request_id)
            if old:
                if old['digest']!=request_digest:raise AuthorizationConflict('같은 확인 ID에 다른 계획/확인을 사용할 수 없습니다.')
                return deepcopy(data['grants'][old['grant_id']])
            now=self.clock()
            grant=next((g for g in data['grants'].values() if g['fingerprint']==fingerprint and g['state']=='confirmed' and now<g['expires_at']),None)
            if grant is None:
                grant={'id':uuid4().hex,'fingerprint':fingerprint,'context':deepcopy(context),'state':'confirmed','confirmed_at':now,'expires_at':now+900,'paid_confirmed':paid_confirmed,'risk_confirmed':risk_confirmed}
                data['grants'][grant['id']]=grant
            data['confirm_requests'][request_id]={'digest':request_digest,'grant_id':grant['id']}
            return deepcopy(grant)

    def claim(self,identity,request_id,context):
        fingerprint=digest(context)
        with self._transaction() as data:
            existing=data['requests'].get(request_id)
            if existing:
                if existing['grant_id']!=identity or existing['fingerprint']!=fingerprint:raise AuthorizationConflict('같은 실행 요청 ID의 owner/대상/payload/승인이 다릅니다.')
                execution=data['executions'][existing['execution_id']]
                return {**deepcopy(execution),'replay':True}
            grant=data['grants'].get(identity)
            if not grant:raise AuthorizationConflict('이 owner의 서버 실행 승인이 없습니다.')
            if grant['fingerprint']!=fingerprint:raise AuthorizationConflict('현재 입력 bytes/남은 계획/옵션/서빙/pin/경로/세대/비용 상태가 확인 당시와 다릅니다.')
            if grant['state']!='confirmed':raise AuthorizationConflict('이미 소비한 승인입니다. 새 실행에 재사용/자동 충전하지 않습니다.')
            if self.clock()>=grant['expires_at']:raise AuthorizationConflict('미소비 승인 15분이 만료됐습니다. 현재 계획을 명시 재확인하세요.')
            execution_id=uuid4().hex
            execution={'execution_id':execution_id,'grant_id':identity,'fingerprint':fingerprint,'request_id':request_id,'state':'claimed','claimed_at':self.clock(),'context':deepcopy(context),'external_requests':{}}
            grant.update(state='claimed',execution_id=execution_id)
            data['executions'][execution_id]=execution
            data['requests'][request_id]={'grant_id':identity,'fingerprint':fingerprint,'execution_id':execution_id}
            return {**deepcopy(execution),'replay':False}

    def execution(self,identity):
        try:return deepcopy(self._read()['executions'][identity])
        except KeyError:raise AuthorizationConflict('영속 실행 claim이 없습니다.') from None

    def chunk_receipt(self,identity,path,binding,index,value):
        with self._transaction() as data:
            receipts=data['executions'][identity].setdefault('chunk_receipts',{})
            key=digest({'path':path,'binding':binding,'index':index})
            receipt={'path':path,'binding':binding,'index':index,'sha256':digest(value),'value':deepcopy(value)}
            if key in receipts and receipts[key]!=receipt:raise AuthorizationConflict('검증된 chunk 결과를 바꿀 수 없습니다.')
            receipts[key]=receipt

    def verified_chunks(self,path,binding):
        result={}
        for execution in self._read()['executions'].values():
            for receipt in execution.get('chunk_receipts',{}).values():
                if receipt['path']!=path:continue
                if receipt['binding']!=binding:raise AuthorizationConflict('이 chunk 저장소의 고정 입력/옵션/모델/요청 형식이 바뀌었습니다. 자동 재호출하지 않습니다.')
                if digest(receipt['value'])!=receipt['sha256']:raise AuthorizationConflict('chunk receipt 무결성이 다릅니다.')
                index=receipt['index']
                if index in result and result[index]!=receipt['value']:raise AuthorizationConflict('서로 다른 chunk 완료 결과를 임의 선택하지 않습니다.')
                result[index]=deepcopy(receipt['value'])
        return result

    def checkpoint_receipt(self,identity,path,sha256,binding,name):
        with self._transaction() as data:
            execution=data['executions'][identity]
            receipts=execution.setdefault('checkpoint_receipts',{})
            receipt={'sha256':sha256,'binding':binding,'name':name}
            if path in receipts and receipts[path]!=receipt:raise AuthorizationConflict('완료 checkpoint receipt를 바꿀 수 없습니다.')
            receipts[path]=receipt

    def seal_inputs(self,identity,inputs):
        from .storage import resolve_under
        for path in inputs.values():resolve_under(self.root,path)
        with self._transaction() as data:
            execution=data['executions'][identity]
            if execution.get('sealed_inputs') is not None:raise AuthorizationConflict('고정 입력을 다른 파일로 바꿀 수 없습니다.')
            execution['sealed_inputs']=deepcopy(inputs)

    def begin_worker(self,identity,*,job_id=None):
        with self._transaction() as data:
            execution=data['executions'][identity]
            if execution['state']!='claimed' or execution.get('worker_started'):raise AuthorizationConflict('이미 입장했거나 중단 결과가 불명인 실행입니다. 큐 자동 replay 금지입니다.')
            if not execution.get('sealed_inputs'):raise AuthorizationConflict('실제 사용할 고정 입력이 없습니다.')
            execution.update(worker_started=True,worker_started_at=self.clock(),worker_job_id=job_id)
        return True

    def replay_request(self, request_id, grant_id, target, payload_digest):
        data=self._read();row=data['requests'].get(request_id)
        if row is None:return None
        execution=data['executions'][row['execution_id']]
        context=execution['context']
        if row['grant_id']!=grant_id or context.get('target')!=target or context.get('payload_digest')!=payload_digest:
            raise AuthorizationConflict('같은 owner/request_id의 대상·payload·승인이 다릅니다.')
        return deepcopy(execution)

    def publish_response(self, identity, status, body):
        with self._transaction() as data:
            execution=data['executions'][identity]
            response={'status':status,'body':deepcopy(body)}
            if 'response' in execution and execution['response']!=response:raise AuthorizationConflict('입장 응답을 다른 실행으로 바꿀 수 없습니다.')
            execution['response']=response

    def finish(self,identity,result):
        with self._transaction() as data:
            execution=data['executions'][identity]
            if 'result' in execution:
                if execution['result']!=result:raise AuthorizationConflict('이미 기록한 실행 결과를 바꿀 수 없습니다.')
                return
            unknown=any(r['state']=='unknown' for r in execution['external_requests'].values())
            execution.update(state='unknown' if unknown else 'settled',result=deepcopy(result))

    @contextmanager
    def _request_control(self,execution_id,request):
        execution=self.execution(execution_id)
        target=execution['context'].get('target','')
        recovery=re.fullmatch(r'/api/settings/recovery-tickets/([0-9a-f]{32})/(?:start|continue)',target)
        if recovery:
            from .recovery_tickets import RecoveryTicketStore,control_lock
            tickets=RecoveryTicketStore(self.root,self.owner)
            identity=recovery[1]
            with control_lock(tickets.directory_for(identity)/'control.lock'):
                control=tickets._control(identity)
                if control['cancel_requested'] or control['retired'] or control['closed'] or control['generation']!=request['generation']:
                    raise AuthorizationConflict('취소/종료/이전 세대는 새 논리 외부 요청을 전송하지 않습니다.')
                yield
            return
        job_id=execution.get('worker_job_id')
        if job_id:
            from .repository import FilesystemJobRepository
            from .locking import job_lock
            from .models import TERMINAL_STATUSES
            repo=FilesystemJobRepository(self.root)
            with job_lock(repo,job_id):
                record=repo.read(job_id)
                if record.metadata.get('owner_id')!=self.owner or record.metadata.get('cancel_requested') or record.status in TERMINAL_STATUSES or record.metadata.get('execution_authorization',{}).get('execution_id')!=execution_id:
                    raise AuthorizationConflict('취소/종료/교체된 legacy 실행은 새 외부 요청을 전송하지 않습니다.')
                yield
            return
        yield

    def before_external(self,execution_id,request):
        required={'node','generation','input_sha256','provider','model','chunk'}
        if not required.issubset(request) or any(request[k] is None for k in required):raise AuthorizationConflict('외부 요청 출처/입력/model/chunk가 없습니다.')
        identity=digest(request)
        with self._request_control(execution_id,request), self._transaction() as data:
            execution=data['executions'].get(execution_id)
            if not execution or execution['state']!='claimed':raise AuthorizationConflict('활성 실행 claim이 없습니다. 자동 재호출하지 않습니다.')
            if execution['context']['cost']['state']!='may_charge':raise AuthorizationConflict('외부 호출 없는 승인으로 provider를 호출할 수 없습니다.')
            allowed=execution['context'].get('allowed_models')
            if allowed is not None and not any(a['provider']==request['provider'] and a['model']==request['model'] and a['node'] in {'*',request['node']} for a in allowed):
                raise AuthorizationConflict('실제 호출 provider/model/노드가 승인한 고정 미실행 범위와 다릅니다.')
            if identity in execution['external_requests']:raise AuthorizationConflict('동일 논리 요청은 이미 전송됐거나 결과 불명입니다. 자동 replay/retry/fallback 금지입니다.')
            execution['external_requests'][identity]={'state':'unknown','request':deepcopy(request),'recorded_at':self.clock()}
        return identity

    def external_state(self,execution_id,identity):
        return self.execution(execution_id)['external_requests'][identity]

    def finish_external(self,execution_id,identity,state):
        if state!='succeeded':raise AuthorizationConflict('불명 요청을 안전 실패/미과금으로 추정하지 않습니다.')
        with self._transaction() as data:
            record=data['executions'][execution_id]['external_requests'][identity]
            if record['state']!='unknown':raise AuthorizationConflict('외부 요청의 terminal 기록을 덮어쓸 수 없습니다.')
            record.update(state=state,finished_at=self.clock())


_active: ContextVar[dict | None]=ContextVar('execution_authorization',default=None)
_node: ContextVar[dict | None]=ContextVar('execution_authorization_node',default=None)
_logical=ContextVar('execution_authorization_logical',default=False)


def serving_environment():
    """Hash effective routing/credential environment; never persist its secret values."""
    import os
    from importlib.metadata import version,PackageNotFoundError
    from .llm_providers import PROVIDERS
    prefixes=('GEMINI_','GOOGLE_','OPENAI_','ANTHROPIC_','OPENROUTER_','AZURE_','TRANSCRIPTION_','TRANSLATION_')
    names={'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','PAID_LLM_ENABLED'}
    values={k:v for k,v in os.environ.items() if k.startswith(prefixes) or k in names}
    versions={}
    for package in ('google-genai','httpx'):
        try:versions[package]=version(package)
        except PackageNotFoundError:versions[package]='absent'
    return {'vocalization_filter_enabled':os.getenv('VOCALIZATION_FILTER_ENABLED','false').lower()=='true',
            'routing_environment_sha256':digest(values),'provider_routes_sha256':digest({k:v.get('url') for k,v in PROVIDERS.items()}),'sdk_versions':versions}


def approved_input(source,ticket):
    """Only an owned claim's exact, SHA-verified copy may differ in FS mtime precision."""
    active=_active.get()
    if active is None:return False
    from .storage import resolve_under
    import hashlib
    execution=active['store'].execution(active['execution_id'])
    parts=execution['context'].get('target','').split('/')
    if len(parts)<2 or parts[-2]!=ticket['id']:return False
    relative=execution.get('sealed_inputs',{}).get('source')
    if not relative or Path(source).resolve()!=resolve_under(active['store'].root,relative):return False
    expected=execution['context']['inputs']['source']
    if Path(source).stat().st_size!=expected['bytes'] or expected['bytes']!=ticket['asset']['size_bytes']:return False
    with Path(source).open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    pin=ticket.get('source_sha256') or ticket['asset'].get('source_sha256')
    return actual==expected['sha256'] and (not pin or pin==actual)


def active_authorization():return _active.get()


@contextmanager
def execution_scope(store,execution_id):
    token=_active.set({'store':store,'execution_id':execution_id,'counters':{}})
    try:yield
    finally:_active.reset(token)


@contextmanager
def node_scope(node,generation='phase'):
    token=_node.set({'node':node,'generation':generation})
    try:yield
    finally:_node.reset(token)


def fingerprint_input(value):
    import hashlib
    if isinstance(value,(bytes,bytearray,memoryview)):return {'bytes_sha256':hashlib.sha256(value).hexdigest()}
    if isinstance(value,Path):
        with value.open('rb') as stream:return {'file_sha256':hashlib.file_digest(stream,'sha256').hexdigest()}
    if isinstance(value,dict):return {k:fingerprint_input(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [fingerprint_input(v) for v in value]
    if value is None or isinstance(value,(str,int,float,bool)):return value
    raise AuthorizationConflict('외부 요청의 실제 입력을 fingerprint할 수 없습니다.')


def _begin_external(provider,model,input_value):
    active=_active.get()
    if active is None or _logical.get():return None
    node=_node.get() or {'node':'legacy-provider','generation':active['execution_id']}
    # Per-node counters distinguish intentionally repeated chunks. No resume of a claimed generation is permitted.
    key=node['node'];chunk=active['counters'].get(key,0);active['counters'][key]=chunk+1
    descriptor={**node,'provider':provider,'model':model,'input_sha256':digest(fingerprint_input(input_value)),'chunk':chunk}
    identity=active['store'].before_external(active['execution_id'],descriptor)
    return active,identity


def external_call(provider,model,input_value,operation):
    started=_begin_external(provider,model,input_value)
    token=_logical.set(True)
    try:
        result=operation()
        if started:started[0]['store'].finish_external(started[0]['execution_id'],started[1],'succeeded')
        return result
    finally:_logical.reset(token)


async def external_async_call(provider,model,input_value,operation):
    started=_begin_external(provider,model,input_value)
    token=_logical.set(True)
    try:
        result=await operation()
        if started:started[0]['store'].finish_external(started[0]['execution_id'],started[1],'succeeded')
        return result
    finally:_logical.reset(token)
