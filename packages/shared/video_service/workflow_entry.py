"""Product entry inspection; never accept a client-selected execution contract.

This only admits an existing saved workflow shape. It does not create tickets,
connect an executor, resolve credentials or claim engine/model success.
"""
from copy import deepcopy
from .parallel_workflow import compile_graph
from .sequential_workflow import compile_sequence

GRAPH_FIELDS = ('catalog_version','revision','name','inputs','nodes','edges')


def inspect_workflow(definition):
    result = {'supported': False, 'contract': None, 'definition_id': definition.get('id') if isinstance(definition,dict) else None,
              'definition_revision': definition.get('revision') if isinstance(definition,dict) else None,
              'summary': [], 'reasons': [], 'runtime_connected': False,
              'notice': '저장 워크플로우의 흐름·노드 설정을 검사합니다. 실제 입력/모델 참조·계획 확인은 별도이며 생성/조회는 실행·연결 성공이 아닙니다.'}
    if not isinstance(definition,dict) or any(key not in definition for key in GRAPH_FIELDS):
        result['reasons'] = [{'message':'저장 워크플로우의 필수 필드가 없습니다.','node_id':None}]
        return result
    graph = {key:deepcopy(definition[key]) for key in GRAPH_FIELDS}
    if not isinstance(graph['nodes'],list) or any(not isinstance(n,dict) for n in graph['nodes']):
        result['reasons'] = [{'message':'처리 노드 배열을 확인하세요.','node_id':None}]
        return result
    for node in graph['nodes']:
        node.pop('model_ref',None)
    kinds = {n.get('type') for n in graph['nodes'] if isinstance(n.get('type'),str)}
    contract = 'decision' if 'decision' in kinds else 'review' if 'review' in kinds else 'graph'
    compiled = compile_graph(graph,allow_review=contract in {'review','decision'},allow_decision=contract=='decision')
    if contract == 'graph' and compiled['supported']:
        sequential = compile_sequence(graph)
        if sequential['supported']:
            contract, compiled = 'sequential', sequential
    result['reasons'] = deepcopy(compiled['reasons'])
    if not compiled['supported']:
        return result
    result.update(supported=True,contract=contract,summary=[{'id':n['id'],'type':n['type'],'options':deepcopy(next(s for s in compiled['steps'] if s['id']==n['id'])['options']),
                  'inputs':deepcopy(next(s for s in compiled['steps'] if s['id']==n['id'])['bindings'])} for n in graph['nodes']])
    return result


def preview_work(definition,asset,preferences,registry,options):
    from .work_tickets import compile_work
    from .workflow_tickets import digest,public_preferences
    from .model_registry import MODEL_ROLES
    graph={key:deepcopy(definition[key]) for key in GRAPH_FIELDS}
    compiled=compile_work(graph,options)
    if not compiled['supported']:
        raise ValueError(' / '.join(row['message'] for row in compiled['reasons']))
    bindings={node['id']:registry.resolve(node['model_ref'],node['type']) for node in graph['nodes'] if 'model_ref' in node}
    availability={node['id']:{k:value for k,value in registry.availability(node['model_ref'],node['type']).items() if k in {'model_id','revision','active','state_revision'}} for node in graph['nodes'] if 'model_ref' in node}
    available=set();eligible=[]
    for step in compiled['steps']:
        if step['selected'] and all(parent in available for parent in step['dependencies']):
            eligible.append(step['id'])
            if step['type'] not in {'review','decision'}:
                available.add(step['id'])
    paid=sorted({MODEL_ROLES[n['type']] for n in compiled['steps'] if n['id'] in eligible and n['type'] in MODEL_ROLES})
    settings=public_preferences(preferences)
    token=digest({'definition':definition,'asset':asset,'options':options,'settings':settings,'key_context':digest(preferences.get('api_keys',{})),'model_bindings':bindings,'model_availability':availability})
    return {'token':token,'steps':compiled['steps'],'eligible_steps':eligible,'paid_roles':paid,'settings':settings,'model_bindings':bindings,'model_admission':availability,
            'notice':'아직 티켓/큐를 만들지 않았습니다. 이 입력·저장 흐름·모델 revision·서빙·비용 역할을 명시 확인하면 준비 티켓을 만듭니다. 실행은 별도입니다. 판단 뒤 경로·후행 비용은 미확정이며 새 확인이 필요합니다.'}
