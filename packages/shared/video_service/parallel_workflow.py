"""Native branch admission and approved manual routing/typed manifest joins.

Reuse existing causal-chain contracts without rewriting nodes as templates.
The old sequential compiler remains separate from new graph admission.
"""
from copy import deepcopy
from .workflow_graph import validate_graph
from .sequential_workflow import compile_sequence


def compile_parallel(definition):
    validation = validate_graph(definition)
    result = {'supported': False, 'reasons': list(validation['issues']), 'steps': [], 'paid_roles': [],
              'notice': '독립 병렬 실행 범위 검사입니다. 수동 선택/합류 자료 정책은 별도 승인 전 미지원입니다. 엔진 연결·파일 무결성·유료 확인은 별도입니다.'}
    if not validation['valid']:
        return result
    nodes = {n['id']: n for n in definition['nodes']}
    parents = {identity: set() for identity in nodes}
    children = {identity: set() for identity in nodes}
    for edge in definition['edges']:
        source, target = edge['source']['node'], edge['target']['node']
        if source != '$input':
            parents[target].add(source)
            children[source].add(target)
    for identity, required in parents.items():
        if len(required) > 1:
            result['reasons'].append({'node_id': identity, 'edge_id': None,
                                      'message': '여러 처리 선행의 자료/시간축 결합은 합류 정책 승인 전 실행하지 않습니다.'})
    if result['reasons']:
        return result
    admitted, roles = {}, set()
    for leaf in (identity for identity in nodes if not children[identity]):
        path = []
        current = leaf
        while True:
            path.append(current)
            if not parents[current]:
                break
            current = next(iter(parents[current]))
        included = set(path)
        chain = deepcopy(definition)
        chain['nodes'] = [n for n in chain['nodes'] if n['id'] in included]
        chain['edges'] = [e for e in chain['edges'] if e['target']['node'] in included]
        compiled = compile_sequence(chain)
        for reason in compiled['reasons']:
            if reason not in result['reasons']:
                result['reasons'].append(reason)
        for step in compiled['steps']:
            step['dependencies'] = sorted(parents[step['id']])
            admitted[step['id']] = step
        roles.update(compiled['paid_roles'])
    if not result['reasons']:
        result.update(supported=True, steps=list(admitted.values()), paid_roles=sorted(roles))
    return result


def compile_graph(definition, choices=None, *, allow_review=False, allow_decision=False, decision_routes=None):
    """Approved manual routing plus typed manifest joins; no data/clock merge."""
    from .node_contracts import node_spec
    validation = validate_graph(definition)
    result = {'supported': False, 'reasons': list(validation['issues']), 'steps': [], 'paid_roles': [], 'choices': {},
              'notice': '수동 선택을 생성 시 고정합니다. 합류는 선택된 결과 참조 목록이며 미디어/clock 병합이 아닙니다. 운영 실행기 연결/유료 확인은 별도입니다.'}
    def reject(message, identity=None):
        result['reasons'].append({'node_id': identity, 'edge_id': None, 'message': message})
    if not validation['valid']:
        return result
    nodes = {n['id']: n for n in definition['nodes']}
    deciders = {identity for identity, n in nodes.items() if n['type'] == 'decision'}
    if deciders and not allow_decision:
        reject('AI 판단은 신규 AI 판단 티켓만 지원합니다. 기존 수동 선택/순차/검수 티켓에 소급하지 않습니다.')
        return result
    routes = {} if decision_routes is None else decision_routes
    if not isinstance(routes, dict) or set(routes) - deciders or any(v not in ('a', 'b') for v in routes.values()):
        reject('서버가 검증한 고정 판단 경로가 필요합니다.')
        return result
    reviewers = {identity for identity, n in nodes.items() if n['type'] == 'review'}
    if reviewers and not allow_review:
        reject('사람 검수는 신규 검수 지원 티켓으로 생성하세요. 기존 순차/병렬 티켓에 소급하지 않습니다.')
        return result
    selectors = {identity for identity, n in nodes.items() if n['type'] == 'select'}
    supplied = {} if choices is None else choices
    if not isinstance(supplied, dict) or set(supplied) - selectors or any(v not in ('a', 'b', 'both') for v in supplied.values()):
        reject('수동 분기 ID와 a/b/both 선택을 확인하세요.')
        return result
    chosen = {identity: supplied.get(identity, nodes[identity]['options'].get('selection', 'a')) for identity in sorted(selectors)}
    result['choices'] = chosen
    bindings = {identity: {} for identity in nodes}
    for e in definition['edges']:
        bindings[e['target']['node']][e['target']['port']] = dict(e['source'])
    order, visited = [], set()
    def visit(identity):
        if identity in visited:
            return
        for b in bindings[identity].values():
            if b['node'] != '$input':
                visit(b['node'])
        visited.add(identity)
        order.append(identity)
    for identity in nodes:
        visit(identity)
    def origin(binding):
        if binding['node'] in selectors | reviewers | deciders and binding['port'] != 'result':
            return origin(bindings[binding['node']]['value'])
        return dict(binding)
    native = deepcopy(definition)
    native['nodes'] = [n for n in native['nodes'] if n['type'] not in {'select', 'join', 'review', 'decision'}]
    native_ids = {n['id'] for n in native['nodes']}
    native['edges'] = [{**deepcopy(e), 'source': origin(e['source'])} for e in native['edges'] if e['target']['node'] in native_ids]
    if definition['inputs'] != {'video': 'video'}:
        reject('새 병렬 티켓은 계정 소유 원본 video 입력 하나만 지원합니다.')
    normalized = {}
    if native['nodes']:
        compiled = compile_parallel(native)
        result['reasons'].extend(compiled['reasons'])
        normalized = {n['id']: n for n in compiled['steps']}
    if result['reasons']:
        return result
    active = {}
    steps = []
    for identity in order:
        node = nodes[identity]
        spec = node_spec(node['type'], node['options'])
        assert spec is not None  # validate_graph has already admitted this type.
        opts = {k: v[0] for k, v in spec['options'].items()}
        opts.update(node['options'])
        if node['type'] == 'select':
            opts['selection'] = chosen[identity]
        def edge_active(binding):
            parent, port = binding['node'], binding['port']
            return parent == '$input' or (active[parent] and (parent not in selectors or chosen[parent] == 'both' or chosen[parent] == port) and (parent not in deciders or port == 'result' or parent not in routes or routes[parent] == port))
        required = {port: b for port, b in bindings[identity].items() if edge_active(b)}
        selected = bool(required) if node['type'] == 'join' else len(required) == len(bindings[identity])
        active[identity] = selected
        step = {'id': identity, 'type': node['type'], 'options': opts, 'bindings': bindings[identity],
                'outputs': dict(spec['outputs']), 'selected': selected, 'active_bindings': required,
                'dependencies': sorted({b['node'] for b in required.values() if b['node'] != '$input'})}
        if identity in normalized:
            step['native_bindings'] = normalized[identity]['bindings']
        if allow_decision:
            parents = {b['node'] for b in required.values()}
            unresolved = identity in deciders and identity not in routes
            unresolved = unresolved or any(n.get('routing_state') == 'unresolved' for n in steps if n['id'] in parents)
            step['routing_state'] = 'unresolved' if selected and unresolved else 'fixed'
        steps.append(step)
    result.update(supported=True, steps=steps,
                  paid_roles=sorted({{'transcribe': 'transcription', 'translate': 'translation'}[n['type']] for n in steps if n['selected'] and n['type'] in {'transcribe', 'translate'}}))
    return result
