"""Admission for the explicitly supported sequential subset, not a template rewrite."""
import os
from .workflow_graph import validate_graph
from .node_contracts import NODES


def compile_sequence(definition):
    validation = validate_graph(definition)
    reasons = list(validation['issues'])
    def reject(message, identity=None):
        reasons.append({'node_id': identity, 'edge_id': None, 'message': message})
    if not validation['valid']:
        return {'supported': False, 'reasons': reasons, 'steps': [], 'paid_roles': []}
    nodes = {n['id']: n for n in definition['nodes']}
    specs = {n['id']: n for n in NODES}
    if definition['inputs'] != {'video': 'video'}:
        reject('이번 순차 실행은 외부 video 입력 하나만 지원합니다. 외부 음성/자막/세션 반입은 기존 고정 workflow를 사용하세요.')
    bindings = {identity:{} for identity in nodes}
    parents = {identity:set() for identity in nodes};children={identity:set() for identity in nodes}
    for e in definition['edges']:
        a,b=e['source'],e['target'];bindings[b['node']][b['port']]=dict(a)
        if a['node']!='$input':parents[b['node']].add(a['node']);children[a['node']].add(b['node'])
    roots = [identity for identity in nodes if not parents[identity]]
    if len(roots)!=1 or any(len(v)>1 for v in parents.values()) or any(len(v)>1 for v in children.values()):
        reject('단일 처리 사슬만 실행할 수 있습니다. 분리된 처리·분기·합류 실행은 S5 범위입니다.')
    order=[]
    if len(roots)==1:
        current=roots[0]
        while current not in order:
            order.append(current)
            if len(children[current])!=1:break
            current=next(iter(children[current]))
    if len(order)!=len(nodes):reject('모든 노드가 하나의 순차 사슬에 포함되어야 합니다.')
    steps=[]
    for identity,n in nodes.items():
        kind=n['type'];b=bindings[identity]
        options={k:v[0] for k,v in specs[kind]['options'].items()};options.update(n['options'])
        def producer(port):
            source=b.get(port,{}).get('node');return nodes[source]['type'] if source in nodes else source
        if kind in {'select','join','review','decision'}:reject('수동 분기/결과 합류는 새 병렬 티켓으로 생성하세요. 기존 순차 티켓에는 적용하지 않습니다.',identity)
        if kind=='faceswap':reject('얼굴 합성의 세션/preview 실행 어댑터는 새 순차 경로에 아직 연결되지 않았습니다. 기존 얼굴 합성 흐름을 사용하세요.',identity)
        if kind=='analyze' and len(nodes)!=1:reject('분석은 단독 실행만 지원합니다. metadata를 무시하고 다른 사슬 앞에 삽입하지 않습니다.',identity)
        if kind=='preprocess_audio':
            if os.getenv('VOCALIZATION_FILTER_ENABLED','false').lower()!='false' and options['audio_filter']!='off':
                reject('유료 발성분석이 활성화된 환경의 전처리는 새 순차 계획에서 아직 지원하지 않습니다. off 또는 기존 고정 workflow를 사용하세요.',identity)
            if producer('audio')!='extract_audio':reject('전처리는 같은 사슬의 오디오 추출 결과를 받아야 합니다.',identity)
            if options['vad_mode']!='off':reject('새 순차 어댑터의 GPU VAD는 아직 미지원입니다. off를 선택하세요.',identity)
        if kind=='transcribe' and (producer('audio')!='preprocess_audio' or b.get('timeline',{}).get('node')!=b.get('audio',{}).get('node')):
            reject('전사는 동일 전처리 노드의 audio와 timeline을 함께 받아야 합니다. 서로 다른 clock map은 실행할 수 없습니다.',identity)
        if kind=='translate' and producer('transcript')!='transcribe':reject('번역은 이 사슬의 원본 시간축 전사 결과만 지원합니다.',identity)
        if kind=='generate_subtitle' and producer('transcript') not in {'transcribe','translate'}:reject('자막 생성은 이 사슬의 전사/번역 결과만 지원합니다.',identity)
        if kind in {'extract_audio','encode','analyze'} and producer('video')!='$input':reject('이 단계의 video는 선택한 원본 video 입력이어야 합니다.',identity)
        if kind=='encode' and 'subtitles' in b and producer('subtitles')!='generate_subtitle':reject('인코딩 자막은 같은 사슬의 자막 생성 결과여야 합니다.',identity)
        if kind=='validate_video' and producer('video')!='encode':reject('영상 검증은 같은 사슬의 인코딩 출력만 지원합니다.',identity)
        steps.append({'id':identity,'type':kind,'options':options,'bindings':b,'outputs':dict(specs[kind]['outputs'])})
    by_id={n['id']:n for n in steps}
    return {'supported':not reasons,'reasons':reasons,'steps':[by_id[n] for n in order] if not reasons else [],
            'paid_roles':sorted({{'transcribe':'transcription','translate':'translation'}[n['type']] for n in steps if n['type'] in {'transcribe','translate'}}),
            'notice':'정의 기반 순차 경로입니다. 파일/엔진·서빙/유료 확인과 실제 Worker 실행은 별도입니다.'}
