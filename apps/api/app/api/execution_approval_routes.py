"""WF08 server admission. Original ticket contracts remain separate from approvals."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from video_service.execution_authorization import AuthorizationStore, AuthorizationConflict, execution_scope
from video_service.workflow_tickets import digest, public_preferences, TicketConflict
from video_service.graph_tickets import file_sha
from video_service.llm_settings import LLMSettingsStore

LEGACY_CREATE=re.compile(r'^/api/videos/([0-9a-f]{32})/jobs$')
TICKET_RUN=re.compile(r'^/api/settings/(workflow|graph|review|decision|work|recovery)-tickets/([0-9a-f]{32})/(start|continue)$')
LEGACY_RUN=re.compile(r'^/api/jobs/([0-9a-f]{32})/(start|retry)$')
LEGACY_RENDER=re.compile(r'^/api/jobs/([0-9a-f]{32})/subtitles$')


def protected(path,method,payload):
    return (method=='POST' and bool(LEGACY_CREATE.fullmatch(path) or TICKET_RUN.fullmatch(path) or LEGACY_RUN.fullmatch(path))) or (method=='PUT' and LEGACY_RENDER.fullmatch(path) and payload.get('action')=='render')


def authorize(request):
    from .settings_routes import authorize as settings_authorize
    settings_authorize(request)
    request.state.owner_id=request.state.settings_owner
    return request.state.settings_owner


def root_for(path):
    if path.startswith('/api/settings/'):
        from .settings_routes import settings
        return settings.storage_root
    from .routes import repository
    return repository.storage_root


def classify(roles):
    if not isinstance(roles,list) or any(r not in {'transcription','translation','decision','vocalization'} for r in roles):
        return {'state':'unknown','amount':None,'notice':'비용 분류 누락/오류: 실행 차단'}
    return {'state':'may_charge' if roles else 'no_external_call','amount':None,
            'notice':'유료 발생 가능·금액 미산정. 무료/0원·비용 상한 보장이 아닙니다.' if roles else '계획상 외부 provider 호출 없음. 금액 견적/요금 보장은 아닙니다.'}


def describe(request,path,payload):
    owner=request.state.settings_owner;root=root_for(path)
    preferences=LLMSettingsStore(root).resolve(owner)
    context={'version':1,'target':path,'payload_digest':digest(payload),'owner_scope':AuthorizationStore(root,owner).directory.name,
             'settings':public_preferences(preferences),'key_context':digest(preferences.get('api_keys',{}))}
    files={}
    match=LEGACY_CREATE.fullmatch(path)
    if match:
        from .workflow_routes import WorkflowCreate
        from .routes import repository
        from video_service.assets import VideoAssetRepository
        from video_service.artifacts import SubtitleArtifactRepository
        from video_service.workflows import workflow_plan
        from video_service.models import JobStatus
        selection=WorkflowCreate.model_validate(payload);assets=VideoAssetRepository(repository)
        asset=assets.read(match[1],owner_id=owner);source=assets.source_path(asset)
        plan=workflow_plan(selection.template,subtitle_input=bool(selection.subtitle_artifact_id),subtitle_mode=selection.options.subtitle_mode,audio_input=bool(selection.audio_job_id))
        roles=[{'transcribe':'transcription','translate':'translation'}[stage] for stage in plan['paid_stages']]
        if os.getenv('VOCALIZATION_FILTER_ENABLED','false').lower()=='true' and 'extract_audio' in plan['stages']:roles.append('vocalization')
        context.update(plan=plan,options=selection.options.model_dump(),asset=asset)
        files['source']=source
        if selection.subtitle_artifact_id:
            artifacts=SubtitleArtifactRepository(assets);context['subtitle']=artifacts.read(match[1],selection.subtitle_artifact_id,owner_id=owner)
            files['subtitle']=artifacts._path(match[1],selection.subtitle_artifact_id)
        if selection.audio_job_id:
            audio=repository.read(selection.audio_job_id)
            if audio.metadata.get('owner_id')!=owner or audio.metadata.get('asset_id')!=match[1] or audio.status!=JobStatus.COMPLETED or audio.metadata.get('results_expired_at'):
                raise AuthorizationConflict('선택 오디오의 owner/완료 상태/출처가 다릅니다.')
            files['audio']=repository.job_dir(audio.job_id)/'work/audio.wav'
    elif (match:=LEGACY_RUN.fullmatch(path)) or (match:=LEGACY_RENDER.fullmatch(path)):
        from .routes import repository
        from video_service.workflows import workflow_plan
        from video_service.models import JobStatus
        from video_service.storage import read_json
        record=repository.read(match[1])
        if record.metadata.get('owner_id')!=owner:raise FileNotFoundError('이 owner의 작업이 없습니다.')
        operation='render' if LEGACY_RENDER.fullmatch(path) else match[2]
        allowed={'start':{JobStatus.READY},'retry':{JobStatus.FAILED,JobStatus.CANCELLED},'render':{JobStatus.AWAITING_REVIEW}}
        if record.status not in allowed[operation]:raise AuthorizationConflict('현재 작업 상태에 맞는 새 실행 입장이 아닙니다.')
        workflow=record.metadata.get('workflow',{})
        if record.metadata.get('faceswap_operation'):
            if record.metadata['faceswap_operation'] not in {'analyze_source','analyze_reference','preview','render'}:raise AuthorizationConflict('알 수 없는 native 작업의 비용을 무료로 취급하지 않습니다.')
            plan={'stages':['faceswap-native'],'reused':[],'paid_stages':[]}
            context['native_faceswap']={k:v for k,v in record.metadata.items() if k.startswith('faceswap') or k in {'preview_frame','analysis_frame','preview_resolution'}}
        else:
            plan=workflow_plan(workflow.get('template','full'),subtitle_input=bool(record.metadata.get('subtitle_input')),subtitle_mode=record.options.subtitle_mode,audio_input=bool(record.metadata.get('audio_input')))
        if operation=='render':plan={'stages':['encode','validate_video'],'reused':['approved_subtitles'],'paid_stages':[]}
        roles=[{'transcribe':'transcription','translate':'translation'}[stage] for stage in plan['paid_stages']]
        if operation!='render' and os.getenv('VOCALIZATION_FILTER_ENABLED','false').lower()=='true' and 'extract_audio' in plan['stages']:roles.append('vocalization')
        files['source']=repository.source_path(record)
        for name in ('subtitle','audio'):
            if record.metadata.get(name+'_input'):files[name]=repository.job_dir(record.job_id)/('input/'+name+('.json' if name=='subtitle' else '.wav'))
        context.update(plan=plan,options=record.options.to_dict(),job_status=record.status.value,
                       metadata={k:record.metadata.get(k) for k in ('workflow','subtitle_input','audio_input','review_ready','subtitle_revision','retry_count','execution_authorization')})
        context['checkpoints']={}
        for p in sorted((repository.job_dir(record.job_id)/'work/checkpoints').glob('*.json')):
            context['checkpoints'][p.name]=file_sha(p)
        context['risk_required']=bool(record.metadata.get('paid_operation_in_flight'))
        previous=record.metadata.get('execution_authorization')
        if previous:
            prior=AuthorizationStore(root,owner).execution(previous['execution_id'])
            context['risk_required']=any(r['state']=='unknown' for r in prior['external_requests'].values()) or (prior.get('worker_started') and prior['state']=='claimed') or bool(record.metadata.get('paid_operation_in_flight'))
        if operation=='render':
            from video_service.review import read_draft,prepare_draft
            from .routes import SubtitleUpdate
            proposed=SubtitleUpdate.model_validate(payload)
            context['review']=read_draft(repository,record)
            if proposed.revision!=context['review']['revision']:raise AuthorizationConflict('자막 입력 revision이 바뀌었습니다. 현재 검수본을 다시 확인하세요.')
            tracks={name:[cue.model_dump(exclude_none=True) for cue in cues] for name,cues in proposed.tracks.items()}
            context['render_draft']=prepare_draft(record,tracks,float(context['review']['duration']),proposed.revision+1)
    elif (match:=TICKET_RUN.fullmatch(path)):
        from .workflow_ticket_routes import verify_input
        from video_service.workflow_tickets import TicketStore
        from video_service.graph_tickets import GraphTicketStore
        from video_service.review_tickets import ReviewTicketStore
        from video_service.decision_tickets import DecisionTicketStore
        from video_service.work_tickets import WorkTicketStore
        from video_service.recovery_tickets import RecoveryTicketStore
        cls={'workflow':TicketStore,'graph':GraphTicketStore,'review':ReviewTicketStore,'decision':DecisionTicketStore,'work':WorkTicketStore,'recovery':RecoveryTicketStore}[match[1]]
        s=cls(root,owner,adapter_profile=getattr(request.app.state,'decision_adapter_descriptor',None)) if match[1]=='decision' else cls(root,owner)
        record=s.get(match[2]);plan=s.plan(record['id'],preferences)
        if record['revision']!=payload.get('revision') or plan['token']!=payload.get('token'):
            raise AuthorizationConflict('정확한 현재 티켓/남은 계획 revision/token이 필요합니다.')
        expected='continue' if record.get('phase',0)>0 else 'start'
        if match[3]!=expected or not record.get('confirmation') or record['confirmation']['token']!=plan['token']:
            raise AuthorizationConflict('현재 구간의 별도 계획 확인과 올바른 실행 진입이 필요합니다.')
        if 'ready' in plan and not plan['ready']:raise AuthorizationConflict('현재 실행 가능한 미실행 구간이 없습니다.')
        source=verify_input(request,record)
        factory_name={'workflow':'workflow','graph':'graph','review':'review','decision':'decision','work':'work','recovery':'work'}[match[1]]+'_executor_factory'
        factory=getattr(request.app.state,factory_name,None)
        context['runtime']={'connected':callable(factory),'type':getattr(factory,'__module__','')+'.'+getattr(factory,'__qualname__',type(factory).__name__)}
        files['source']=source;roles=plan['paid_roles']
        context.update(plan=plan,ticket_revision=record['revision'],ticket_status=record['status'],confirmation=record['confirmation'],
                       phase=record.get('phase',0),generation=record.get('execution_generation'),model_bindings=record.get('model_bindings'),
                       risk=record.get('recovery_risk'),reuse=record.get('reuse_origins'))
        # Persist actual bytes of existing producer artifacts in the approval context, not merely their mtime.
        def artifact_files(value):
            if isinstance(value,dict):
                if isinstance(value.get('path'),str) and 'sha256' in value:
                    from video_service.storage import resolve_under
                    p=resolve_under(s.directory_for(record['id']),value['path'])
                    if file_sha(p)!=value['sha256']:raise AuthorizationConflict('계획 입력 산출물 bytes/SHA가 다릅니다.')
                    files['artifact-'+digest(value['path'])]=p
                for v in value.values():artifact_files(v)
            elif isinstance(value,list):
                for v in value:artifact_files(v)
        artifact_files(record.get('scheduler',{}))
    else:
        raise AuthorizationConflict('이 실행 진입의 현재 계획을 구성할 수 없습니다. 확인 없이 실행하지 않습니다.')
    context['cost']=classify(roles)
    allowed=[]
    if TICKET_RUN.fullmatch(path):
        eligible=set(plan.get('eligible_steps',[n['id'] for n in plan['steps'] if n.get('selected',True)]))
        for step in plan['steps']:
            if step['id'] not in eligible or step['type'] not in {'transcribe','translate','decision'}:continue
            binding=record.get('model_bindings',{}).get(step['id'])
            if binding:provider,model=binding['provider'],binding['model']
            elif step['type']=='decision':
                adapter=plan.get('decision_adapter')
                if not isinstance(adapter,dict):context['cost']=classify(None);continue
                provider,model='adapter:'+adapter['id'],adapter['revision']
            else:
                role={'transcribe':'transcription','translate':'translation'}[step['type']]
                provider,model=preferences.get(role+'_provider','gemini'),preferences.get(role+'_model')
            allowed.append({'node':step['id'],'provider':provider,'model':model})
    else:
        for role in roles:
            provider='gemini' if role=='vocalization' else preferences.get(role+'_provider','gemini')
            if role=='vocalization':
                from media_agent.providers import GeminiProvider
                model=GeminiProvider(preferences).audio_filter_model
            else:model=preferences.get(role+'_model')
            allowed.append({'node':'*','role':role,'provider':provider,'model':model})
    if any(not isinstance(a['provider'],str) or not a['provider'] or not isinstance(a['model'],str) or not a['model'] for a in allowed) or (roles and not allowed):context['cost']=classify(None)
    context['allowed_models']=allowed
    context['inputs']={name:{'sha256':file_sha(p),'bytes':p.stat().st_size} for name,p in files.items()}
    from video_service.execution_authorization import serving_environment
    context['execution_environment']=serving_environment()
    if LEGACY_RUN.fullmatch(path):
        from media_agent.checkpoints import checkpoint_binding
        from video_service.storage import read_json,resolve_under
        binding=checkpoint_binding(context);completed=[]
        for filename,sha in context['checkpoints'].items():
            p=repository.job_dir(record.job_id)/'work/checkpoints'/filename;saved=read_json(p)
            if 'authorization_execution' not in saved:raise AuthorizationConflict('과거 checkpoint에 입력 SHA/승인 receipt가 없습니다. 원 자료는 보존하며 추정 재사용·자동 전체 재실행은 하지 않습니다. 새 작업을 명시 선택하세요.')
            receipt=AuthorizationStore(root,owner).execution(saved['authorization_execution']).get('checkpoint_receipts',{}).get(p.relative_to(root).as_posix())
            if receipt!={'sha256':sha,'binding':binding,'name':saved.get('name')} or saved.get('binding')!=binding:raise AuthorizationConflict('checkpoint 원 출처/입력·옵션·서빙 binding이 다릅니다. 자동 재실행하지 않습니다.')
            for relative,expected in saved['file_hashes'].items():
                if file_sha(resolve_under(repository.job_dir(record.job_id),'work/'+relative))!=expected:raise AuthorizationConflict('재사용 checkpoint 파일 bytes가 다릅니다.')
            completed.append(saved['name'])
        if 'transcribe-packed-60-v2' in completed:roles=[r for r in roles if r!='transcription']
        languages=[record.options.target_language,*record.options.additional_languages]
        if languages and all('translate-packed-40-v2-'+language in completed for language in languages):roles=[r for r in roles if r!='translation']
        if 'vocalizations' in completed:roles=[r for r in roles if r!='vocalization']
        context['plan']['verified_completed_checkpoints']=completed
        context['cost']=classify(roles)
        permitted_nodes={'transcription':'TRANSCRIBING','translation':'TRANSLATING','vocalization':'PREPROCESSING_AUDIO'}
        context['allowed_models']=[{**a,'node':permitted_nodes[a['role']]} for a in allowed if a['role'] in roles]
    elif LEGACY_CREATE.fullmatch(path):
        permitted_nodes={'transcription':'TRANSCRIBING','translation':'TRANSLATING','vocalization':'PREPROCESSING_AUDIO'}
        context['allowed_models']=[{**a,'node':permitted_nodes[a['role']]} for a in allowed if a['role'] in roles]
    if LEGACY_RUN.fullmatch(path):
        context['partial_queues']={}
        for subdirectory in ('transcription','translation'):
            for p in sorted((repository.job_dir(record.job_id)/'work'/subdirectory).glob('*.json')):
                saved=read_json(p)
                if not saved.get('authorization_binding'):raise AuthorizationConflict('과거 부분 chunk 캐시의 승인 출처가 없습니다. 보존하되 추정 재사용·자동 전체 재호출하지 않습니다.')
                slot=p.relative_to(root).as_posix();known=AuthorizationStore(root,owner).verified_chunks(slot,saved['authorization_binding'])
                if any(known.get(int(index))!=value for index,value in saved['results'].items()):raise AuthorizationConflict('부분 chunk 캐시와 영속 완료 receipt가 다릅니다.')
                context['partial_queues'][slot]=file_sha(p)
    return context,files


def freeze_inputs(store,execution,files,context):
    from video_service.capacity import assert_capacity
    target=context['target']
    if LEGACY_CREATE.fullmatch(target):
        from .workflow_routes import settings
    elif target.startswith('/api/settings/'):
        from .settings_routes import settings
    else:
        from .routes import settings
    root=store.root
    assert_capacity(root,settings.service_quota_bytes,settings.min_free_space_bytes,additional=sum(p.stat().st_size for p in files.values())+262144)
    result={}
    for name,source in files.items():
        path=store.directory/'inputs'/execution['execution_id']/(name+source.suffix)
        path.parent.mkdir(parents=True,exist_ok=True)
        stat=source.stat();shutil.copyfile(source,path);os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        if file_sha(path)!=context['inputs'][name]['sha256'] or file_sha(source)!=context['inputs'][name]['sha256']:
            raise AuthorizationConflict('입력이 승인/복사 중 변경되었습니다. 실제 사용할 bytes가 다릅니다.')
        result[name]=path
    store.seal_inputs(execution['execution_id'],{name:p.relative_to(store.root).as_posix() for name,p in result.items()})
    return result


def public_grant(grant):
    import time
    return {k:grant[k] for k in ('id','state','confirmed_at','expires_at')}|{'cost':grant['context']['cost'],'server_time':time.time()}


class GuardedRoute(APIRoute):
    def get_route_handler(self):
        original=super().get_route_handler()
        async def handler(request):
            path=request.url.path
            if request.method not in {'POST','PUT'} or not (LEGACY_CREATE.fullmatch(path) or TICKET_RUN.fullmatch(path) or LEGACY_RUN.fullmatch(path) or LEGACY_RENDER.fullmatch(path)):
                return await original(request)
            raw=await request.body()
            if len(raw)>2*1024*1024:raise HTTPException(413,'실행 요청이 너무 큽니다.')
            try:payload=json.loads(raw) if raw else {}
            except ValueError:raise HTTPException(422,'JSON 실행 요청이 필요합니다.') from None
            if not isinstance(payload,dict):raise HTTPException(422,'실행 payload가 필요합니다.')
            if not protected(path,request.method,payload):return await original(request)
            owner=authorize(request);store=AuthorizationStore(root_for(path),owner)
            grant_id=request.headers.get('x-execution-approval','');request_id=request.headers.get('x-execution-request','')
            if not re.fullmatch('[0-9a-f]{32}',grant_id) or not re.fullmatch('[0-9a-f-]{36}',request_id):
                raise HTTPException(409,'현재 미실행 계획의 서버 비용 확인/실행 요청 ID가 필요합니다.')
            if payload.get('request_id') is not None and payload['request_id']!=request_id:raise HTTPException(409,'body와 실행 요청 ID가 다릅니다.')
            def prepare():
                prior=store.replay_request(request_id,grant_id,path,digest(payload))
                if prior is not None:return prior,None,None
                context,files=describe(request,path,payload)
                claim=store.claim(grant_id,request_id,context)
                if claim['replay']:return claim,None,None
                frozen=freeze_inputs(store,claim,files,context)
                return claim,context,frozen
            try:claim,context,frozen=await run_in_threadpool(prepare)
            except TicketConflict as exc:raise HTTPException(409,str(exc)) from None
            if context is None:
                response=claim.get('response')
                return JSONResponse(response['body'],status_code=response['status']) if response else JSONResponse({'execution_id':claim['execution_id'],'state':claim['state'],'notice':'입장한 실행입니다. 진행/중단 결과를 새 호출 없이 확인하세요.'},status_code=202)
            request.state.execution_authorization={'execution_id':claim['execution_id'],'owner':owner,'grant_id':grant_id}
            request.state.execution_frozen_files=frozen
            with execution_scope(store,claim['execution_id']):
                response=await original(request)
            try:body=json.loads(response.body)
            except (ValueError,AttributeError):raise HTTPException(503,'실행 입장 결과를 확정하지 못했습니다. 재호출하지 않습니다.') from None
            await run_in_threadpool(store.publish_response,claim['execution_id'],response.status_code,body)
            if TICKET_RUN.fullmatch(path):await run_in_threadpool(store.finish,claim['execution_id'],body)
            return response
        return handler


router=APIRouter(prefix='/api/execution-approvals')


async def selection(request):
    authorize(request)
    raw=await request.body()
    if len(raw)>2*1024*1024:raise HTTPException(413,'요청이 너무 큽니다.')
    try:body=json.loads(raw)
    except ValueError:raise HTTPException(422,'JSON 계획 요청이 필요합니다.') from None
    if not isinstance(body,dict) or not isinstance(body.get('path'),str) or not isinstance(body.get('payload'),dict):raise HTTPException(422,'서버 대상 path/payload가 필요합니다.')
    if not protected(body['path'],'PUT' if LEGACY_RENDER.fullmatch(body['path']) else 'POST',body['payload']):raise HTTPException(422,'실행 진입이 아닌 대상입니다.')
    return body


@router.post('/plan')
async def plan(request:Request):
    body=await selection(request)
    try:
        context,_=await run_in_threadpool(describe,request,body['path'],body['payload'])
        return {'token':digest(context),'cost':context['cost'],'input_sha256':context['inputs']['source']['sha256'],'risk_required':bool(context.get('risk_required')),'notice':'계획 조회/확인은 실행이 아닙니다. 미소비 승인만 15분 만료됩니다.'}
    except TicketConflict as exc:raise HTTPException(409,str(exc)) from None
    except (ValueError,TypeError):raise HTTPException(422,'현재 owner의 입력/옵션/계획을 확인하세요.') from None


@router.post('/confirm')
async def confirm(request:Request):
    body=await selection(request)
    if not isinstance(body.get('request_id'),str) or not re.fullmatch('[0-9a-f-]{36}',body['request_id']) or type(body.get('paid_confirmed')) is not bool:raise HTTPException(422,'명시 확인과 확인 요청 ID가 필요합니다.')
    def save():
        context,_=describe(request,body['path'],body['payload'])
        if body.get('token')!=digest(context):raise AuthorizationConflict('오래된 계획입니다. 현재 입력/옵션/서빙/경로를 다시 확인하세요.')
        return public_grant(AuthorizationStore(root_for(body['path']),request.state.settings_owner).confirm(body['request_id'],context,body['paid_confirmed'],risk_confirmed=body.get('risk_confirmed') is True))
    try:return await run_in_threadpool(save)
    except TicketConflict as exc:raise HTTPException(409,str(exc)) from None
    except (ValueError,TypeError):raise HTTPException(422,'현재 입력/계획/명시 확인을 점검하세요.') from None
