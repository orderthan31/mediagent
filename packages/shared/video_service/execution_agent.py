"""Admission of explicitly guarded legacy jobs, never retrofit old queued records."""
from contextlib import contextmanager
from .execution_authorization import AuthorizationStore, AuthorizationConflict, execution_scope
from .workflow_tickets import public_preferences, digest
from .llm_settings import LLMSettingsStore
from .graph_tickets import file_sha
from .storage import resolve_under


@contextmanager
def legacy_execution(repo,record):
    metadata=record.metadata.get('execution_authorization')
    if metadata is None:
        yield {}
        return
    owner=record.metadata.get('owner_id')
    if metadata.get('owner')!=owner:raise AuthorizationConflict('실행 승인 owner가 다릅니다.')
    store=AuthorizationStore(repo.storage_root,owner)
    grant=store.get(metadata['grant_id'])
    if grant.get('execution_id')!=metadata['execution_id']:raise AuthorizationConflict('승인과 영속 실행 claim이 다릅니다.')
    execution=store.execution(metadata['execution_id']);context=execution['context']
    preferences=LLMSettingsStore(repo.storage_root).resolve(owner)
    if public_preferences(preferences)!=context['settings'] or digest(preferences.get('api_keys',{}))!=context['key_context']:
        raise AuthorizationConflict('큐 입장 뒤 서빙/키 context가 바뀌었습니다. 자동 실행하지 않고 현재 계획 확인이 필요합니다.')
    from .execution_authorization import serving_environment
    if serving_environment()!=context['execution_environment']:raise AuthorizationConflict('서빙 endpoint/SDK/환경 경로가 승인 뒤 바뀌었습니다. 자동 실행하지 않습니다.')
    options=record.options.to_dict()
    if any(options.get(k)!=v for k,v in context['options'].items()):raise AuthorizationConflict('실제 사용할 옵션이 승인과 다릅니다.')
    files={k:resolve_under(repo.storage_root,p) for k,p in execution.get('sealed_inputs',{}).items()}
    if set(files)!=set(context['inputs']):raise AuthorizationConflict('승인 입력 snapshot이 없습니다.')
    for key,path in files.items():
        if file_sha(path)!=context['inputs'][key]['sha256'] or path.stat().st_size!=context['inputs'][key]['bytes']:
            raise AuthorizationConflict('실제 사용할 고정 입력 SHA가 다릅니다.')
    if context.get('render_draft'):
        from .review import read_draft
        if read_draft(repo,record)!=context['render_draft']:raise AuthorizationConflict('큐 입장 뒤 검수 입력이 변경되었습니다. 자동으로 다른 자막을 렌더하지 않습니다.')
    store.begin_worker(metadata['execution_id'],job_id=record.job_id)
    with execution_scope(store,metadata['execution_id']):
        try:yield files
        finally:
            current=repo.read(record.job_id)
            store.finish(metadata['execution_id'],{'job_id':record.job_id,'status':current.status.value})


def approved_review(repo,record):
    from .execution_authorization import active_authorization
    from .review import read_draft
    active=active_authorization()
    if active is not None:
        context=active['store'].execution(active['execution_id'])['context']
        if context.get('render_draft') is not None:return context['render_draft']
    return read_draft(repo,record)
