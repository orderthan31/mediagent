"""Pure editor graph validation. This does not select assets or execute a graph."""
import math
import re
from .node_contracts import NODES, VALUE_TYPES, node_spec, validate_node


def validate_graph(payload):
    issues = []
    def issue(message, node_id=None, edge_id=None):
        row = {'message': message, 'node_id': node_id, 'edge_id': edge_id}
        if row not in issues:
            issues.append(row)
    def result():
        return {'valid': not issues, 'issues': issues, 'executable': False,
                'notice': '편집 정의의 유형/연결 검사입니다. 파일·시간축·엔진·실행 가능성/성공은 검증하지 않습니다.'}
    if not isinstance(payload, dict) or set(payload) != {'catalog_version','revision','name','inputs','nodes','edges'}:
        issue('편집 정의 필드가 올바르지 않습니다.'); return result()
    if type(payload['catalog_version']) is not int or payload['catalog_version'] != 1:
        issue('현재 catalog version 1 정의만 편집할 수 있습니다.')
    if type(payload['revision']) is not int or payload['revision'] < 0:
        issue('편집 revision은 0 이상의 정수여야 합니다.')
    if not isinstance(payload['name'], str) or not 1 <= len(payload['name'].strip()) <= 80:
        issue('이름은 1~80자로 입력하세요.')
    templates = {n['id']: n for n in NODES}
    types = {t for n in NODES for t in n['inputs'].values()} | set(VALUE_TYPES)
    inputs, nodes, edges = payload['inputs'], payload['nodes'], payload['edges']
    if not isinstance(inputs, dict) or len(inputs) > 20 or any(not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,39}', k) or not isinstance(v,str) or v not in types for k,v in inputs.items()):
        issue('외부 입력 이름/유형을 확인하세요. 최대20개입니다.'); return result()
    if not isinstance(nodes,list) or not 1 <= len(nodes) <= 100 or not isinstance(edges,list) or len(edges) > 300:
        issue('노드1~100개·연결300개 이하로 편집하세요.'); return result()
    indexed = {}
    for n in nodes:
        if not isinstance(n,dict) or set(n) != {'id','type','position','options'} or not isinstance(n['id'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',n['id']):
            issue('노드 ID/속성 형식이 올바르지 않습니다.'); continue
        identity = n['id']
        if identity in indexed:
            issue('노드 ID가 중복되었습니다.',identity); continue
        if not isinstance(n['type'],str) or n['type'] not in templates:
            issue('지원하는 실행 경로가 없는 노드입니다.',identity); continue
        indexed[identity] = n
        position = n['position']
        if not isinstance(position,dict) or set(position) != {'x','y'} or any(type(position[k]) not in (int,float) or not math.isfinite(position[k]) or not 0 <= position[k] <= limit for k,limit in [('x',4000),('y',3000)]):
            issue('노드 배치는 유한한 x0~4000/y0~3000 좌표여야 합니다.',identity)
    resolved = {identity:(node_spec(n['type'], n['options']) or {}) for identity,n in indexed.items()}
    incoming = {identity:{} for identity in indexed}; adjacency = {identity:[] for identity in indexed}; targets=set(); edge_ids=set()
    for e in edges:
        if not isinstance(e,dict) or set(e) != {'id','source','target'} or not isinstance(e['id'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',e['id']):
            issue('연결 ID/속성 형식이 올바르지 않습니다.'); continue
        identity=e['id']
        if identity in edge_ids: issue('연결 ID가 중복되었습니다.',edge_id=identity)
        edge_ids.add(identity)
        if any(not isinstance(e[k],dict) or set(e[k]) != {'node','port'} or any(not isinstance(e[k][f],str) for f in ('node','port')) for k in ('source','target')):
            issue('연결 포트 형식이 올바르지 않습니다.',edge_id=identity); continue
        a,b=e['source'],e['target']
        outputs = inputs if a['node']=='$input' else resolved[a['node']]['outputs'] if a['node'] in indexed else {}
        target_inputs = resolved[b['node']]['inputs'] if b['node'] in indexed else {}
        if a['port'] not in outputs or b['port'] not in target_inputs:
            issue('존재하지 않는 노드/포트에 연결되었습니다.',edge_id=identity); continue
        if a['node'] != '$input': adjacency[a['node']].append((b['node'],identity))
        key=(b['node'],b['port'])
        if key in targets: issue('입력 하나에는 출력 하나만 연결하세요. 결과 목록 합류는 join의 서로 다른 입력 포트를 사용하세요.',b['node'],identity)
        targets.add(key)
        if outputs[a['port']] != target_inputs[b['port']]:
            issue('출력과 입력의 자료 유형이 맞지 않습니다.',b['node'],identity); continue
        incoming[b['node']][b['port']]=outputs[a['port']]
    for identity,n in indexed.items():
        template=resolved[identity]
        missing=set(template['inputs'])-set(template['optional_inputs'])-set(incoming[identity])
        if missing: issue('필수 입력 연결이 없습니다: '+', '.join(sorted(missing)),identity)
        for ports in (dict(template['inputs']),incoming[identity]):
            if template['id']=='encode' and isinstance(n['options'],dict) and n['options'].get('subtitle_mode','burn')=='none' and ports != incoming[identity]:
                ports.pop('subtitles',None)
            try: validate_node({'node':n['type'],'inputs':ports,'options':n['options']})
            except (ValueError,TypeError) as exc: issue(str(exc),identity)
    visited={}; stack=[]
    def visit(identity):
        visited[identity]=1;stack.append(identity)
        for other,edge in adjacency[identity]:
            if visited.get(other)==1:
                for member in stack[stack.index(other):]: issue('순환 연결에 포함된 노드입니다.',member)
                issue('순환을 만드는 연결입니다.',edge_id=edge)
            elif not visited.get(other):visit(other)
        stack.pop();visited[identity]=2
    for identity in indexed:
        if not visited.get(identity):visit(identity)
    return result()
