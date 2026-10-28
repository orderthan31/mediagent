"""Domain tool definitions/permissions. No custom public invocation protocol."""
from copy import deepcopy
from pydantic import BaseModel,ConfigDict,Field,StrictInt,create_model

class ArtifactReference(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    storage_key:str=Field(pattern=r'^blobs/[a-f0-9]{64}$')
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    bytes:StrictInt=Field(gt=0)
    type:str=Field(min_length=1,max_length=80)
    source_owner_id:str|None=None

_DATA=[
 ('media.analyze','analyze','영상 분석',{'video':'영상'},{'metadata':'영상 정보'},[]),
 ('media.extract_audio','extract_audio','음성 추출',{'video':'영상'},{'audio':'PCM 오디오'},[]),
 ('media.preprocess_audio','preprocess_audio','음성 전처리',{'audio':'PCM 오디오','regions':'선택 음성 구간'},{'audio':'전처리 오디오','timeline':'원본 시각'},['음성 필터','음성 구간']),
 ('media.generate_subtitle','generate_subtitle','자막 생성',{'transcript':'전사문','metadata':'영상 정보'},{'subtitle':'자막 파일'},['자막 언어','자막 형식']),
 ('media.encode','encode','영상 인코딩',{'video':'영상','subtitle':'선택 자막'},{'video':'인코딩 영상'},['영상 품질','해상도','자막 표시']),
 ('media.validate_video','validate_video','영상 확인',{'video':'출력 영상','metadata':'원본 영상 정보'},{'report':'재생 확인 결과'},[]),
 ('speech.transcribe','transcription','음성 전사',{'source':'PCM 오디오'},{'transcript':'시간 정보가 있는 전사문'},['음성 인식 모델','원문 언어']),
 ('text.translate','translation','자막 번역',{'source':'시간 정보가 있는 전사문'},{'transcript':'번역 전사문'},['번역 모델','대상 언어']),
 ('audio.vocal_regions','vocalization','음성 구간 분석',{'source':'PCM 오디오'},{'regions':'음성 보존 구간'},['분석 모델']),
]
DEFINITIONS={}
for identity,role,name,inputs,outputs,settings in _DATA:
    optional={'regions','subtitle'}
    fields={key:((ArtifactReference|None if key in optional else ArtifactReference),Field(default=None if key in optional else ...,title=label,description=label))for key,label in inputs.items()}
    args=create_model(identity.replace('.','_')+'_input',__config__=ConfigDict(extra='forbid',strict=True),**fields)
    DEFINITIONS[identity]={'id':identity,'executor':role,'name':name,'args_schema':args,'outputs':outputs,'settings':settings,'requires_model':role in {'transcription','translation','vocalization'}}
CALLER_TOOLS={('model:'if d['requires_model']else'cpu:')+d['executor']:(identity,)for identity,d in DEFINITIONS.items()}

def allowed_definitions(caller):
    if caller not in CALLER_TOOLS:raise ValueError('unknown_tool_caller')
    return [DEFINITIONS[identity]for identity in CALLER_TOOLS[caller]]

def describe(definition):
    schema=definition['args_schema'].model_json_schema()
    return {'id':definition['id'],'executor':definition['executor'],'name':definition['name'],'inputs':{key:prop.get('title',key)for key,prop in schema['properties'].items()},'input_schema':schema,'outputs':deepcopy(definition['outputs']),'settings':list(definition['settings']),'requires_model':definition['requires_model'],'autonomous':False}

def catalog():return [describe(d)for d in DEFINITIONS.values()]
def tool_for_executor(role):return next((d['id']for d in DEFINITIONS.values()if d['executor']==role),None)
