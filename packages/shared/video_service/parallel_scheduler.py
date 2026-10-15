"""Bounded local scheduling primitive, with serialized persistence callbacks.

No queue, provider, routing/join contract or ticket terminal policy lives here.
Callers admit a frozen DAG and decide what to do with unresolved dependants.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
import json
import re


def _validate(steps, max_workers):
    if type(max_workers) is not int or not 1 <= max_workers <= 4:
        raise ValueError('병렬 실행 수는 1~4의 정수여야 합니다.')
    if not isinstance(steps, list) or len(steps) > 100:
        raise ValueError('실행 노드는 최대 100개입니다.')
    indexed = {}
    for step in steps:
        if (not isinstance(step, dict) or not isinstance(step.get('id'), str)
                or not re.fullmatch('[A-Za-z0-9_-]{1,64}', step['id'])
                or step['id'] in indexed or not isinstance(step.get('dependencies'), list)
                or any(not isinstance(p, str) for p in step['dependencies'])
                or len(set(step['dependencies'])) != len(step['dependencies'])):
            raise ValueError('실행 노드/선행 ID가 올바르지 않습니다.')
        indexed[step['id']] = step
    if sum(len(n['dependencies']) for n in steps) > 300:
        raise ValueError('선행 연결은 최대 300개입니다.')
    for step in steps:
        if any(parent not in indexed for parent in step['dependencies']):
            raise ValueError('존재하지 않는 필수 선행입니다.')
    visited, visiting = set(), set()
    def visit(identity):
        if identity in visiting:
            raise ValueError('순환 실행은 지원하지 않습니다.')
        if identity in visited:
            return
        visiting.add(identity)
        for parent in indexed[identity]['dependencies']:
            visit(parent)
        visiting.remove(identity)
        visited.add(identity)
    for identity in indexed:
        visit(identity)
    try:
        json.dumps(steps, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError('실행 정의는 유한한 JSON 값이어야 합니다.') from exc


class NodeFailure(Exception):
    """A failed executor may attach verified partial-output metadata, not diagnostics."""
    def __init__(self, partial, cause):
        json.dumps(partial, allow_nan=False)
        self.partial = deepcopy(partial)
        self.error_type = type(cause).__name__
        super().__init__(self.error_type)


def run_ready(steps, execute, publish, *, max_workers=2, settle=False):
    """Run ready nodes once; an independent failure does not cancel siblings.

    ``execute`` runs on worker threads and returns JSON-safe result metadata.
    ``publish`` runs only on the coordinator, before submission and after each
    result, and must atomically persist a complete snapshot or raise. Never
    persist exception messages (provider exceptions can contain credentials).
    """
    selected = deepcopy(steps)
    _validate(selected, max_workers)
    nodes: dict[str, dict] = {n['id']: ({'status': 'skipped', 'reason': 'manual_unselected'} if settle and not n.get('selected', True) else {'status': 'pending'}) for n in selected}
    state = {'revision': 0, 'nodes': nodes, 'unresolved': list(nodes)}

    def persist():
        state['revision'] += 1
        state['unresolved'] = [identity for identity, n in nodes.items() if n['status'] == 'pending']
        publish(deepcopy(state))

    persist()
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='workflow-node') as pool:
        running = {}
        while True:
            changed = False
            if settle:
                for step in selected:
                    identity = step['id']
                    if nodes[identity]['status'] == 'pending':
                        failed = [p for p in step['dependencies'] if nodes[p]['status'] in {'failed', 'blocked'}]
                        if failed:
                            nodes[identity] = {'status': 'blocked', 'blocked_by': failed}
                            persist()
                            changed = True
            for step in selected:
                identity = step['id']
                if len(running) >= max_workers:
                    break
                if nodes[identity]['status'] != 'pending':
                    continue
                if not all(nodes[parent]['status'] == 'succeeded' for parent in step['dependencies']):
                    continue
                nodes[identity]['status'] = 'running'
                persist()
                running[pool.submit(execute, deepcopy(step))] = identity
            if not running:
                if changed:
                    continue
                break
            completed, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in completed:
                identity = running.pop(future)
                try:
                    result = future.result()
                    json.dumps(result, allow_nan=False)
                    nodes[identity] = {'status': 'succeeded', 'result': result}
                except NodeFailure as exc:
                    nodes[identity] = {'status': 'failed', 'error_type': exc.error_type, 'partial': exc.partial}
                except Exception as exc:
                    nodes[identity] = {'status': 'failed', 'error_type': type(exc).__name__}
                persist()
    return deepcopy(state)
