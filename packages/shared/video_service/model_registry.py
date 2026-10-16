"""Owner-scoped registered model entities, immutable versions, no credentials.

Compatibility means a supported adapter contract, never model availability or
successful inference. The registry never calls providers or changes role prefs.
"""
from copy import deepcopy
from pathlib import Path
from .workflow_definitions import DefinitionStore
from .workflow_tickets import digest
from .storage import read_json, write_json_atomic
from .locking import _file_lock
from .llm_providers import PROVIDERS, valid_model, valid_stt_model

MODEL_ROLES = {'transcribe':'transcription','translate':'translation','decision':'decision'}


class ModelConflict(ValueError):
    pass


class ModelUnavailable(ValueError):
    pass


def compatible_uses(provider, model):
    if provider not in PROVIDERS or not valid_model(provider,model):
        return []
    uses=[]
    is_gemini = provider=='gemini' and model.startswith('gemini-') and 'embedding' not in model.lower()
    if valid_stt_model(provider,model) and (provider!='gemini' or is_gemini):
        uses.append('transcription')
    stt_only = 'transcribe' in model.lower() or model.lower().startswith('whisper-') or 'whisper-' in model.lower()
    chat = is_gemini or provider=='openai' and model.startswith(('gpt-','o1','o3','o4')) or provider=='xai' and model.startswith('grok-') or provider=='anthropic' and model.startswith('claude-')
    # OpenRouter model IDs use a namespace; still reject known non-text families.
    chat = chat or provider=='openrouter' and '/' in model and any(prefix in model.lower() for prefix in ('gpt-','gemini-','claude-','grok-','llama-','deepseek-','qwen'))
    if chat and not stt_only and not any(tag in model.lower() for tag in ('embedding','tts','image','realtime','voice')):
        uses.extend(['translation','decision'])
    return sorted(uses)


def valid_reference(reference):
    if not isinstance(reference,dict) or set(reference)!={'model_id','revision'} or type(reference['revision']) is not int or reference['revision']<1:
        raise ValueError('model_id와 정확한 정수 revision을 고정하세요.')
    DefinitionStore('.').path(reference['model_id'])
    return deepcopy(reference)


class ModelRegistry:
    def __init__(self, root, owner=None):
        scope=DefinitionStore(root,owner).directory.name
        self.directory=Path(root)/'.model-registry'/scope

    def path(self, identity):
        DefinitionStore(self.directory).path(identity)
        return self.directory/(identity+'.json')

    def get(self, identity):
        row=read_json(self.path(identity))
        if row['id']!=identity:
            raise ModelConflict('등록 모델 식별자가 다릅니다.')
        for key,version in row['versions'].items():
            if version['model_id']!=identity or str(version['revision'])!=key:
                raise ModelConflict('모델 참조 ID/revision과 등록 entity 내부 식별자가 다릅니다.')
            value={k:v for k,v in version.items() if k!='sha256'}
            if digest(value)!=version['sha256']:
                raise ModelConflict('등록 모델 불변 revision의 무결성이 다릅니다.')
        return row

    def list(self):
        return [self.get(p.stem) for p in sorted(self.directory.glob('*.json'))]

    def save(self, identity, payload):
        path=self.path(identity)
        if not isinstance(payload,dict) or set(payload)!={'revision','name','provider','model','uses'}:
            raise ValueError('등록 모델의 revision/이름/provider/model/용도만 허용합니다. 키/URL은 저장하지 않습니다.')
        if type(payload['revision']) is not int or payload['revision']<0 or not isinstance(payload['name'],str) or not 1<=len(payload['name'].strip())<=80:
            raise ValueError('등록 모델의 이름과 수정 revision을 확인하세요.')
        provider,model,uses=payload['provider'],payload['model'],payload['uses']
        if not isinstance(provider,str) or not isinstance(model,str) or not isinstance(uses,list) or not uses or any(not isinstance(use,str) for use in uses) or len(uses)!=len(set(uses)) or set(uses)-set(compatible_uses(provider,model)):
            raise ValueError('해당 provider/model에 지원되는 서버 adapter 용도만 등록하세요. 실연결/추론은 별도입니다.')
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        with _file_lock(self.directory/'registry.lock'):
            current=self.get(identity) if path.exists() else {'id':identity,'revision':0,'current_revision':0,'state_revision':0,'active':True,'versions':{}}
            if current['revision']!=payload['revision']:
                raise ModelConflict('등록 모델이 변경되었습니다. 기존 pin은 보존하고 새 값을 명시 조회하세요.')
            version=current['current_revision']+1
            if version>1000:
                raise ValueError('모델 revision 상한을 초과했습니다.')
            value={'model_id':identity,'revision':version,'name':payload['name'].strip(),'provider':provider,'model':model,'uses':sorted(uses)}
            current['versions'][str(version)]={**value,'sha256':digest(value)}
            current.update(revision=current['revision']+1,current_revision=version,connection='unverified')
            write_json_atomic(path,current)
            return deepcopy(current)

    def set_active(self, identity, revision, active):
        if type(revision) is not int or type(active) is not bool:
            raise ValueError('현재 수정 revision과 사용 가능 여부가 필요합니다.')
        with _file_lock(self.directory/'registry.lock'):
            row=self.get(identity)
            if row['revision']!=revision:
                raise ModelConflict('등록 모델 사용 상태가 변경되었습니다. 다시 조회하세요.')
            if row['active']!=active:
                row.update(revision=revision+1,state_revision=row['state_revision']+1,active=active)
                write_json_atomic(self.path(identity),row)
            return row

    def resolve(self, reference, node_type, *, require_active=True):
        reference=valid_reference(reference)
        if node_type not in MODEL_ROLES:
            raise ValueError('이 노드는 모델을 사용하지 않습니다. 모델 참조를 연결하지 마세요.')
        row=self.get(reference['model_id'])
        value=row['versions'].get(str(reference['revision']))
        if value is None:
            raise ModelConflict('참조한 모델 revision이 없습니다. 최신판으로 자동 교체하지 않습니다.')
        role=MODEL_ROLES[node_type]
        if role not in value['uses'] or role not in compatible_uses(value['provider'],value['model']):
            raise ValueError('노드와 등록 모델의 서버 adapter 용도가 호환되지 않습니다.')
        if require_active and not row['active']:
            raise ModelUnavailable('등록 모델이 사용 중지되었습니다. 활성 모델로 새 정의·계획·티켓을 만드세요.')
        return deepcopy(value)

    def availability(self, reference, node_type):
        value=self.resolve(reference,node_type,require_active=False)
        row=self.get(reference['model_id'])
        return {'model_id':value['model_id'],'revision':value['revision'],'active':row['active'],'state_revision':row['state_revision'],
                'new_revision_available':row['current_revision']>value['revision'],'connection':'unverified'}
