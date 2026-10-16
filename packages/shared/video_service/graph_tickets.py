"""New graph-only held tickets, outside sequential tickets and the legacy queue."""
from copy import deepcopy
import hashlib
from pathlib import Path
from threading import Lock
from .workflow_tickets import TicketStore, TicketConflict
from .parallel_workflow import compile_graph
from .parallel_scheduler import run_ready, NodeFailure
from .locking import _file_lock
from .storage import resolve_under, write_json_atomic


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class GraphTicketStore(TicketStore):
    def __init__(self, root, owner=None):
        super().__init__(root, owner)
        self.directory = (Path(root) / '.workflow-graph-tickets' / self.directory.name).resolve()

    def _compile_definition(self, graph, options):
        return compile_graph(graph, options.get('branch_choices', {}))

    def plan(self, identity, preferences):
        plan = super().plan(identity, preferences)
        sequence = self.get(identity)['sequence']
        return {**plan, 'choices': sequence['choices'], 'notice': sequence['notice']}

    def artifact_path(self, identity, node_id, port, *, partial=False):
        record = self.get(identity)
        step = next((s for s in record['steps'] if s['id'] == node_id), None)
        meta = (step or {}).get('partial_artifacts' if partial else 'artifacts', {}).get(port, {})
        if 'path' not in meta:
            raise FileNotFoundError('참조 출력은 원본 파일 다운로드를 추가하지 않습니다.')
        return super().artifact_path(identity, node_id, port, partial=partial)

    def run(self, identity, preferences, source, executor_factory):
        ticket_dir = self.directory_for(identity)
        with _file_lock(ticket_dir / 'execution.lock'):
            with _file_lock(ticket_dir / 'state.lock'):
                record = self.get(identity)
                plan = self.plan(identity, preferences)
                if (record['status'] != 'confirmed' or record['confirmation']['token'] != plan['token']
                        or record['settings_snapshot'] != plan['settings']):
                    raise TicketConflict('확인한 계획/서빙/수동 선택과 다릅니다. 새 확인이 필요합니다.')
                source = Path(source).resolve()
                initial = source.stat()
                from .execution_authorization import approved_input
                if (initial.st_size, initial.st_mtime_ns) != (record['asset']['size_bytes'], record['asset']['source_mtime_ns']) and not approved_input(source,record):
                    raise TicketConflict('선택한 원본 snapshot 정보가 변경되었습니다.')
                expected = [(n['id'], n['type']) for n in record['sequence']['steps']]
                if ([(n['id'], n['type']) for n in record['steps']] != expected
                        or any(n['status'] != 'pending' or n['artifacts'] or n['partial_artifacts'] for n in record['steps'])):
                    raise TicketConflict('새 티켓 단계 상태가 고정 계획과 다릅니다. 자동 재시도/재개는 없습니다.')
                record['status'] = 'running'
                self._save(record)
            def check():
                current = source.stat()
                if (current.st_size, current.st_mtime_ns) != (initial.st_size, initial.st_mtime_ns):
                    raise TicketConflict('원본이 실행 중 변경되었습니다.')
            try:
                bound = {**record['settings_snapshot'], 'api_keys': dict(preferences.get('api_keys', {}))}
                bound['api_key'] = bound['api_keys'].get('gemini', '')
                execute = executor_factory(bound, deepcopy(record['options']))
                source_sha = file_sha(source)
                original_clock = {'basis': 'original', 'asset_id': record['asset']['asset_id'], 'source_sha256': source_sha}
                values = {('$input', 'video'): {'type': 'video', 'sha256': source_sha, 'bytes': initial.st_size,
                                               'asset_id': record['asset']['asset_id'], 'clock': original_clock}}
                values_lock = Lock()
                def resolve(meta):
                    if 'reference' in meta:
                        b = meta['reference']
                        return resolve(values[(b['node'], b['port'])])
                    if 'asset_id' in meta:
                        path = source
                    else:
                        path = resolve_under(ticket_dir, meta['path'])
                    if file_sha(path) != meta['sha256']:
                        raise TicketConflict('입력 산출물 무결성이 바뀌었습니다.')
                    return path
                def node_execute(step):
                    from .execution_authorization import node_scope
                    generation=getattr(self,'_sessions',{}).get(identity,str(record.get('phase',0)))
                    with node_scope(step['id'],generation):return node_execute_unscoped(step)
                def node_execute_unscoped(step):
                    check()
                    work = ticket_dir / 'work' / step['id']
                    work.mkdir(parents=True, exist_ok=True)
                    with values_lock:
                        incoming = {port: deepcopy(values[(b['node'], b['port'])]) for port, b in step['active_bindings'].items()}
                    if step['type'] == 'select':
                        meta = incoming['value']
                        # Verify the referenced bytes even though this control does not copy them.
                        resolve(meta)
                        ports = ('a', 'b') if step['options']['selection'] == 'both' else (step['options']['selection'],)
                        return {'artifacts': {port: {k: deepcopy(v) for k, v in {**meta, 'reference': step['bindings']['value']}.items() if k != 'path'} for port in ports}}
                    if step['type'] == 'join':
                        members = {}
                        for port, meta in incoming.items():
                            resolve(meta)
                            b = step['active_bindings'][port]
                            members[b['node'] + '.' + b['port']] = meta
                        path = work / 'manifest.json'
                        write_json_atomic(path, {'version': 1, 'kind': 'artifact_manifest', 'members': members,
                                                'notice': '선택 결과의 참조 목록입니다. 내용/clock 병합이 아닙니다.'})
                        return {'artifacts': {'manifest': self._artifact(ticket_dir, work, path, 'artifact_manifest')}}
                    inputs = {port: resolve(meta) for port, meta in incoming.items()}
                    try:
                        outputs = execute(deepcopy(step), inputs, work, check)
                        if set(outputs) != set(step['outputs']):
                            raise ValueError('정의와 다른 출력 포트입니다.')
                        artifacts = {port: self._artifact(ticket_dir, work, path, step['outputs'][port]) for port, path in outputs.items()}
                        for meta in artifacts.values():
                            meta['clock'] = deepcopy(original_clock)
                        if step['type'] == 'preprocess_audio':
                            artifacts['audio']['clock'] = {**original_clock, 'basis': 'packed',
                                                          'timeline': {'node': step['id'], 'port': 'timeline', 'sha256': artifacts['timeline']['sha256']}}
                            artifacts['timeline']['clock'] = {**original_clock, 'basis': 'packed_to_original'}
                        check()
                        return {'artifacts': artifacts}
                    except Exception as exc:
                        partial = {p.name: self._artifact(ticket_dir, work, p, 'partial') for p in work.glob('partial-*') if p.is_file() and p.suffix in {'.json', '.srt', '.smi'}}
                        raise NodeFailure(partial, exc) from None
                def publish(snapshot):
                    with _file_lock(ticket_dir / 'state.lock'):
                        with values_lock:
                            for step in record['steps']:
                                outcome = snapshot['nodes'][step['id']]
                                step['status'] = outcome['status']
                                for key in ('reason', 'blocked_by', 'error_type'):
                                    if key in outcome:
                                        step[key] = outcome[key]
                                step['artifacts'] = outcome.get('result', {}).get('artifacts', {})
                                step['partial_artifacts'] = outcome.get('partial', {})
                                if step['status'] == 'succeeded':
                                    values.update({(step['id'], port): meta for port, meta in step['artifacts'].items()})
                        self._save(record)
                settled = run_ready(record['sequence']['steps'], node_execute, publish, max_workers=2, settle=True)
                check()
                if file_sha(source) != source_sha:
                    raise TicketConflict('실행 중 원본 내용 무결성이 변경되었습니다.')
                statuses = {n['status'] for n in settled['nodes'].values()}
                if statuses & {'pending', 'running'}:
                    raise TicketConflict('필수 단계가 정리되지 않았습니다. 완료로 표시하지 않습니다.')
                record['status'] = 'failed' if statuses & {'failed', 'blocked'} else 'completed'
                if record['status'] == 'failed':
                    record['error'] = '선택 단계 실패/차단 · 독립 성공/부분 결과 보존 (자동 재시도/재개 없음)'
            except Exception as exc:
                record['status'] = 'failed'
                record['error'] = '실행 조정 실패 · ' + type(exc).__name__ + ' (결과 보존·자동 재개 없음)'
            with _file_lock(ticket_dir / 'state.lock'):
                self._save(record)
            return self.get(identity)
