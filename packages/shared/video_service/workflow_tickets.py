"""Held, owner-scoped sequential tickets; never publish into the legacy job queue."""
import copy
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from .locking import _file_lock
from .storage import read_json, write_json_atomic, resolve_under
from .workflow_definitions import DefinitionStore
from .sequential_workflow import compile_sequence


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',',':'), allow_nan=False).encode()).hexdigest()


def public_preferences(preferences):
    return {key:value for key,value in preferences.items() if key=='revision' or key in {'fallback_on_error','fallback_on_block'} or key in {role+'_'+suffix for role in ('transcription','translation') for suffix in ('model','provider','fallback_model','fallback_provider')}}


class TicketConflict(ValueError):
    pass


class TicketStore:
    def __init__(self, root, owner=None):
        scope=DefinitionStore(root,owner).directory.name
        self.directory=(Path(root)/'.workflow-tickets'/scope).resolve()

    def directory_for(self, identity):
        # Reuse strict 32-lowercase-hex ID validation, not user-controlled paths.
        DefinitionStore(self.directory).path(identity)
        return self.directory/identity

    def get(self, identity):
        record=read_json(self.directory_for(identity)/'ticket.json')
        if record['id']!=identity:raise ValueError('티켓 식별자가 다릅니다.')
        return record

    def list(self):
        return [self.get(p.parent.name) for p in sorted(self.directory.glob('*/ticket.json'))]

    def _save(self, record):
        record['revision']+=1
        write_json_atomic(self.directory_for(record['id'])/'ticket.json',record)

    def _compile_definition(self, graph, options):
        return compile_sequence(graph)

    def create(self, request_id, identity, definition_loader, asset_loader):
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        with _file_lock(self.directory/'admission.lock'):
            for existing in self.list():
                if existing['request_id']==request_id:
                    if existing['request']!=identity:raise TicketConflict('같은 요청 ID에 다른 입력을 사용할 수 없습니다.')
                    return existing
            definition=copy.deepcopy(definition_loader());asset=copy.deepcopy(asset_loader())
            if definition['id']!=identity['definition_id'] or definition['revision']!=identity['definition_revision'] or asset['asset_id']!=identity['asset_id']:
                raise TicketConflict('선택한 정의/입력이 변경되었습니다. 다시 선택하세요.')
            graph={k:definition[k] for k in ('catalog_version','revision','name','inputs','nodes','edges')}
            plan=self._compile_definition(graph, identity['options'])
            if not plan['supported']:raise ValueError('지원하지 않는 순차 정의입니다. 실행 범위 검사 이유를 확인하세요.')
            record={'id':uuid4().hex,'revision':0,'request_id':request_id,'request':copy.deepcopy(identity),
                    'definition':definition,'definition_sha256':digest(definition),'asset':asset,'options':copy.deepcopy(identity['options']),
                    'sequence':plan,'status':'held','confirmation':None,'settings_snapshot':None,
                    'steps':[{'id':n['id'],'type':n['type'],'status':'pending','artifacts':{},'partial_artifacts':{}} for n in plan['steps']]}
            self._save(record);return record

    def plan(self, identity, preferences):
        record=self.get(identity)
        if digest(record['definition'])!=record['definition_sha256']:raise TicketConflict('실행 정의 snapshot 무결성이 다릅니다.')
        graph={k:record['definition'][k] for k in ('catalog_version','revision','name','inputs','nodes','edges')}
        compiled=self._compile_definition(graph, record['options'])
        if not compiled['supported'] or compiled!=record['sequence']:
            raise TicketConflict('저장된 순서/포트/옵션이 고정 정의와 다르거나 현재 실행 범위에서 지원하지 않습니다.')
        public=public_preferences(preferences)
        # Only an opaque digest binds the runtime key context; no key/ciphertext is copied to tickets or responses.
        key_context=digest(preferences.get('api_keys',{}))
        token=digest({'definition':record['definition_sha256'],'asset':record['asset'],'options':record['options'],'settings':public,'key_context':key_context})
        return {'token':token,'settings':public,'paid_roles':record['sequence']['paid_roles'],'steps':record['sequence']['steps'],
                'definition_id':record['definition']['id'],'definition_revision':record['definition']['revision'],
                'notice':'생성 때 고정한 정의입니다. 계획/서빙이 바뀌면 재확인해야 합니다. 키는 복사하지 않습니다. 생성·확인은 실행/큐 등록이 아닙니다.'}

    def confirm(self, identity, revision, token, paid_confirmed, preferences):
        with _file_lock(self.directory_for(identity)/'state.lock'):
            record=self.get(identity);plan=self.plan(identity,preferences)
            if record['revision']!=revision or record['status'] not in {'held','confirmed'} or token!=plan['token']:
                raise TicketConflict('계획 또는 티켓/서빙 revision이 바뀌었습니다. 새 계획을 확인하세요.')
            if plan['paid_roles'] and paid_confirmed is not True:raise ValueError('전사/번역 provider 호출의 비용 확인이 필요합니다.')
            record.update(status='confirmed',settings_snapshot=plan['settings'],confirmation={'token':token,'paid_confirmed':paid_confirmed})
            self._save(record);return record

    def _artifact(self, ticket_dir, node_work, path, kind):
        path=Path(path).resolve()
        if node_work.resolve() not in path.parents or not path.is_file():raise ValueError('노드 출력은 자신의 작업 폴더 안의 실제 파일이어야 합니다.')
        with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        return {'type':kind,'path':path.relative_to(ticket_dir).as_posix(),'sha256':sha,'bytes':path.stat().st_size}

    def artifact_path(self, identity, node_id, port, *, partial=False):
        record=self.get(identity);step=next((s for s in record['steps'] if s['id']==node_id),None)
        if step is None:raise FileNotFoundError()
        meta=step['partial_artifacts' if partial else 'artifacts'].get(port)
        if meta is None:raise FileNotFoundError()
        path=resolve_under(self.directory_for(identity),meta['path'])
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=meta['sha256']:raise TicketConflict('산출물 무결성 확인에 실패했습니다.')
        return path

    def run(self, identity, preferences, source, executor_factory):
        ticket_dir=self.directory_for(identity)
        with _file_lock(ticket_dir/'execution.lock'):
            with _file_lock(ticket_dir/'state.lock'):
                record=self.get(identity);plan=self.plan(identity,preferences)
                if record['status']!='confirmed' or record['confirmation']['token']!=plan['token'] or record['settings_snapshot']!=plan['settings']:
                    raise TicketConflict('확인한 계획/서빙과 다릅니다. 실행하지 않고 재확인을 요구합니다.')
                source=Path(source).resolve();stat=source.stat()
                if (stat.st_size,stat.st_mtime_ns)!=(record['asset']['size_bytes'],record['asset']['source_mtime_ns']):
                    raise TicketConflict('선택한 원본 snapshot 정보가 바뀌었습니다.')
                record['status']='running';self._save(record)
            def check():
                current=source.stat()
                if (current.st_size,current.st_mtime_ns)!=(stat.st_size,stat.st_mtime_ns):raise TicketConflict('원본이 실행 중 변경되었습니다.')
            current_step=None
            try:
                bound={**record['settings_snapshot'],'api_keys':dict(preferences.get('api_keys',{}))}
                bound['api_key']=bound['api_keys'].get('gemini','')
                execute=executor_factory(bound,record['options'])
                with source.open('rb') as stream:source_sha=hashlib.file_digest(stream,'sha256').hexdigest()
                values={('$input','video'):{'path':str(source),'sha256':source_sha,'type':'video'}}
                for selected in record['sequence']['steps']:
                    current_step=next(s for s in record['steps'] if s['id']==selected['id'])
                    check();work=ticket_dir/'work'/selected['id'];work.mkdir(parents=True,exist_ok=True)
                    current_step['status']='running';self._save(record)
                    inputs={}
                    for port,binding in selected['bindings'].items():
                        value=values[(binding['node'],binding['port'])]
                        path=Path(value['path']) if binding['node']=='$input' else resolve_under(ticket_dir,value['path'])
                        with path.open('rb') as stream:
                            if hashlib.file_digest(stream,'sha256').hexdigest()!=value['sha256']:raise TicketConflict('입력 산출물 무결성이 바뀌었습니다.')
                        inputs[port]=path
                    outputs=execute(selected,inputs,work,check)
                    if set(outputs)!=set(selected['outputs']):raise ValueError('정의와 다른 출력 포트입니다.')
                    artifacts={port:self._artifact(ticket_dir,work,path,selected['outputs'][port]) for port,path in outputs.items()}
                    check();current_step.update(status='succeeded',artifacts=artifacts);self._save(record)
                    values.update({(selected['id'],port):meta for port,meta in artifacts.items()})
                record['status']='completed';self._save(record)
            except Exception as exc:
                if current_step:
                    current_step['status']='failed';work=ticket_dir/'work'/current_step['id']
                    current_step['partial_artifacts']={p.stem:self._artifact(ticket_dir,work,p,'partial') for p in work.glob('partial-*') if p.is_file() and p.suffix in {'.json','.srt','.smi'}}
                record['status']='failed';record['error']='단계 처리 실패 · '+type(exc).__name__+' (자동 재시도/재개 없음)';self._save(record)
            return self.get(identity)
