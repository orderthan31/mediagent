"""New review-enabled tickets: durable gates, immutable approvals, explicit passes.

Never enqueue a legacy render/retry or resume a failed/cancelled/crashed run.
"""
from copy import deepcopy
from pathlib import Path
import re
from .graph_tickets import GraphTicketStore, file_sha
from .workflow_tickets import TicketStore, TicketConflict, digest
from .parallel_workflow import compile_graph
from .parallel_scheduler import run_ready, NodeWait, NodeFailure
from .review_documents import ReviewDocuments, LIMIT
from .locking import _file_lock
from .storage import resolve_under, write_json_atomic


class ReviewTicketStore(GraphTicketStore):
    execution_contract = 'review-v1'
    boundary_types = {'review'}
    confirmation_statuses = {'held', 'confirmed', 'awaiting_review', 'continuation_confirmed'}

    def _make_executor(self, record, bound, factory, execution):
        return factory(bound, deepcopy(record['options']))

    def _execution_sequence(self, record):
        return record['sequence']

    def _gate_approval(self, record, identity):
        return record['reviews'].get(identity, {}).get('approval')

    def _resume_gate(self, record, plan, identity):
        return plan['review_signatures'].get(identity, {}).get('approval')

    def _plan_extension(self, record):
        return {}

    def _execute_extension(self, step, incoming, work, resolve, execute, record, plan):
        return None

    def _admit_dispatch(self, record, step) -> bool:
        return True

    def _before_node(self, record, step):
        """Default no-op; opt-in recovery can gate dispatch without retrofitting v1."""
        return None

    def _waiting_status(self, record):
        return 'awaiting_review'

    def _preserve_serving(self, step):
        return False

    def __init__(self, root, owner=None):
        super().__init__(root, owner)
        self.directory = (Path(root) / '.workflow-review-tickets' / self.directory.name).resolve()

    def _compile_definition(self, graph, options):
        return compile_graph(graph, options.get('branch_choices', {}), allow_review=True)

    def _save(self, record):
        record.pop('reviews', None)
        record.setdefault('execution_contract', self.execution_contract)
        record.setdefault('phase', 0)
        record.setdefault('run_requests', {})
        super()._save(record)

    def list(self):
        return [TicketStore.get(self, p.parent.name) for p in sorted(self.directory.glob('*/ticket.json'))]

    def review_document(self, identity, node):
        record = TicketStore.get(self, identity)
        if not re.fullmatch('[A-Za-z0-9_-]{1,64}', node) or not any(s['id'] == node and s['type'] == 'review' for s in record['sequence']['steps']):
            raise FileNotFoundError('이 티켓의 검수 노드가 없습니다.')
        return ReviewDocuments(self.directory_for(identity) / 'work' / node / 'review', {'ticket': identity, 'node': node})

    def review_input_path(self, identity, node, source):
        record = self.get(identity)
        meta = self.review_document(identity, node).get()['source']
        def resolve(value, seen):
            if 'reference' in value:
                binding = value['reference']
                key = (binding['node'], binding['port'])
                if key in seen:
                    raise TicketConflict('검수 입력 참조가 순환합니다.')
                parent = record['scheduler']['nodes'][key[0]]['result']['artifacts'][key[1]] if key[0] != '$input' else {'asset_id': record['asset']['asset_id'], 'sha256': record['source_sha256']}
                path = resolve(parent, seen | {key})
            elif value.get('asset_id') == record['asset']['asset_id']:
                path = Path(source).resolve()
            else:
                path = resolve_under(self.directory_for(identity), value['path'])
            if file_sha(path) != value['sha256']:
                raise TicketConflict('검수 입력 bytes/SHA가 변경되었습니다.')
            return path
        return resolve(meta, set())

    def get(self, identity):
        record = super().get(identity)
        if record.get('execution_contract') != self.execution_contract:
            raise TicketConflict('신규 검수 지원 티켓이 아닙니다.')
        record['reviews'] = {}
        for step in record['sequence']['steps']:
            if step['type'] == 'review':
                doc = self.review_document(identity, step['id'])
                if doc.index.is_file():
                    record['reviews'][step['id']] = doc.get()
        return record

    def plan(self, identity, preferences):
        base = super().plan(identity, preferences)
        record = self.get(identity)
        state = record.get('scheduler', {}).get('nodes', {})
        available = {k for k, v in state.items() if v['status'] == 'succeeded'}
        eligible = []
        approved_gates = []
        execution = self._execution_sequence(record)
        for step in execution['steps']:
            status = state.get(step['id'], {}).get('status', 'pending')
            if not step['selected'] or status in {'succeeded', 'failed', 'blocked', 'skipped'}:
                continue
            if not all(p in available for p in step['dependencies']):
                continue
            approval = self._gate_approval(record, step['id'])
            if status == 'waiting' and not approval:
                continue
            eligible.append(step['id'])
            if step['type'] in self.boundary_types:
                if approval:
                    available.add(step['id'])
                    approved_gates.append(step['id'])
            else:
                available.add(step['id'])
        signatures = {node: {k: doc[k] for k in ('target', 'revision', 'state_revision', 'sha256', 'document_sha256', 'approval')} for node, doc in record['reviews'].items()}
        token_fields = {'base': base['token'], 'phase': record['phase'], 'reviews': signatures,
                        'state': state, 'eligible': eligible, 'source_sha256': record.get('source_sha256')}
        token_fields.update(self._plan_extension(record))
        token = digest(token_fields)
        roles = sorted({{'transcribe': 'transcription', 'translate': 'translation'}[n['type']] for n in execution['steps'] if n['id'] in eligible and n['type'] in {'transcribe', 'translate'}})
        return {**base, 'steps': execution['steps'], 'token': token, 'phase': record['phase'], 'review_signatures': signatures, 'eligible_steps': eligible,
                'paid_roles': roles, 'ready': bool(eligible) and (record['phase'] == 0 or bool(approved_gates)),
                'notice': '저장·자료 승인·계획 확인·이어 실행은 별도입니다. 승인 revision/SHA와 미실행 단계·서빙을 결합합니다. 완료 단계는 재실행하지 않습니다.'}

    def confirm(self, identity, revision, token, paid_confirmed, preferences):
        with _file_lock(self.directory_for(identity) / 'state.lock'):
            record = self.get(identity)
            plan = self.plan(identity, preferences)
            if (record['revision'] != revision or record['status'] not in self.confirmation_statuses
                    or token != plan['token'] or not plan['ready']):
                raise TicketConflict('검수/수정본/계획/서빙이 바뀌었거나 승인 대기 중입니다. 새 계획을 확인하세요.')
            if plan['paid_roles'] and paid_confirmed is not True:
                raise ValueError('이번 미실행 부분의 모델 비용 확인이 필요합니다.')
            record.update(status='confirmed' if record['phase'] == 0 else 'continuation_confirmed',
                          settings_snapshot=plan['settings'], confirmation={'token': token, 'paid_confirmed': paid_confirmed, 'phase': record['phase']})
            self._save(record)
        return self.get(identity)

    def replay(self, identity, request_id, revision, token, operation):
        record = self.get(identity)
        fingerprint = digest({'revision': revision, 'token': token, 'operation': operation})
        existing = record['run_requests'].get(request_id)
        if existing:
            if existing['digest'] != fingerprint:
                raise TicketConflict('같은 실행 요청 ID의 대상/계획이 다릅니다.')
            return record
        return None

    def run(self, identity, preferences, source, executor_factory, *, request_id, revision, token, operation):
        replay = self.replay(identity, request_id, revision, token, operation)
        if replay is not None:
            return replay
        ticket_dir = self.directory_for(identity)
        with _file_lock(ticket_dir / 'execution.lock'):
            replay = self.replay(identity, request_id, revision, token, operation)
            if replay is not None:
                return replay
            with _file_lock(ticket_dir / 'state.lock'):
                record = self.get(identity)
                plan = self.plan(identity, preferences)
                expected_status = 'confirmed' if record['phase'] == 0 else 'continuation_confirmed'
                expected_operation = 'start' if record['phase'] == 0 else 'continue'
                if (record['status'] != expected_status or operation != expected_operation or record['revision'] != revision
                        or not plan['ready'] or token != plan['token'] or record['confirmation']['token'] != token
                        or record['settings_snapshot'] != plan['settings']):
                    raise TicketConflict('정확한 승인 수정본/미실행 계획/서빙을 새로 확인하세요. 재시도/복구는 제공하지 않습니다.')
                source = Path(source).resolve()
                stat = source.stat()
                from .execution_authorization import approved_input
                if (stat.st_size, stat.st_mtime_ns) != (record['asset']['size_bytes'], record['asset']['source_mtime_ns']) and not approved_input(source,record):
                    raise TicketConflict('고정한 원본 정보가 변경되었습니다.')
                source_sha = file_sha(source)
                if record.get('source_sha256', source_sha) != source_sha:
                    raise TicketConflict('이전 검수 패스의 원본 내용이 변경되었습니다.')
                record['source_sha256'] = source_sha
                record['status'] = 'running'
                record['run_requests'][request_id] = {'digest': digest({'revision': revision, 'token': token, 'operation': operation}), 'phase': record['phase'], 'status': 'running'}
                self._save(record)
            def check():
                current = source.stat()
                if (current.st_size, current.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
                    raise TicketConflict('원본이 실행 중 변경되었습니다.')
            try:
                bound = {**record['settings_snapshot'], 'api_keys': dict(preferences.get('api_keys', {}))}
                bound['api_key'] = bound['api_keys'].get('gemini', '')
                clock = {'basis': 'original', 'asset_id': record['asset']['asset_id'], 'source_sha256': source_sha}
                values = {('$input', 'video'): {'type': 'video', 'sha256': source_sha, 'bytes': stat.st_size, 'asset_id': record['asset']['asset_id'], 'clock': clock}}
                seed = deepcopy(record.get('scheduler'))
                if seed:
                    for node, outcome in seed['nodes'].items():
                        if outcome['status'] == 'succeeded':
                            values.update({(node, port): deepcopy(meta) for port, meta in outcome['result']['artifacts'].items()})
                        elif outcome['status'] == 'waiting' and self._resume_gate(record, plan, node):
                            seed['nodes'][node] = {'status': 'pending'}
                execution = self._execution_sequence(record)
                if seed:
                    for step in execution['steps']:
                        if not step['selected'] and seed['nodes'][step['id']]['status'] == 'pending':
                            seed['nodes'][step['id']] = {'status': 'skipped', 'reason': 'unselected'}
                def resolve(meta, seen=None):
                    if 'reference' in meta:
                        b = meta['reference']
                        key = (b['node'], b['port'])
                        seen = set() if seen is None else set(seen)
                        if key in seen:
                            raise TicketConflict('산출물 참조가 순환합니다.')
                        seen.add(key)
                        return resolve(values[key], seen)
                    path = source if 'asset_id' in meta else resolve_under(ticket_dir, meta['path'])
                    if file_sha(path) != meta['sha256']:
                        raise TicketConflict('이전 성공 산출물/검수 입력 무결성이 변경되었습니다.')
                    return path
                for meta in list(values.values()):
                    resolve(meta)
                execute = self._make_executor(record, bound, executor_factory, execution)
                def node_execute(step):
                    from .execution_authorization import node_scope
                    generation=getattr(self,'_sessions',{}).get(identity,str(record.get('phase',0)))
                    with node_scope(step['id'],generation):return node_execute_unscoped(step)
                def node_execute_unscoped(step):
                    self._before_node(record, step)
                    check()
                    work = ticket_dir / 'work' / step['id']
                    work.mkdir(parents=True, exist_ok=True)
                    incoming = {p: deepcopy(values[(b['node'], b['port'])]) for p, b in step['active_bindings'].items()}
                    for meta in incoming.values():
                        resolve(meta)
                    extension = self._execute_extension(step, incoming, work, resolve, execute, record, plan)
                    if extension is not None:
                        return extension
                    if step['type'] == 'review':
                        meta = incoming['value']
                        content = None
                        duration = None
                        if meta['type'] in {'transcript', 'subtitle', 'media_metadata', 'timeline_map', 'validation_report', 'artifact_manifest'} and meta['bytes'] <= LIMIT:
                            content = resolve(meta).read_bytes()
                        if meta['type'] in {'transcript', 'subtitle'} and meta.get('clock', {}).get('basis') == 'original':
                            duration = getattr(execute, 'review_duration', None)
                            if duration is None:
                                from media_worker.media import probe
                                duration = probe(source, work, check)['duration']
                        doc = self.review_document(identity, step['id'])
                        view = doc.open(meta, content, duration=duration)
                        selected = plan['review_signatures'].get(step['id'], {})
                        if not view['approval'] or selected.get('approval') != view['approval'] or selected.get('sha256') != view['sha256']:
                            raise NodeWait({'target': view['target'], 'revision': view['revision'], 'sha256': view['sha256']})
                        output, approval = doc.approved_output()
                        if output is None:
                            result = {k: deepcopy(v) for k, v in {**meta, 'reference': step['bindings']['value']}.items() if k != 'path'}
                        else:
                            result = self._artifact(ticket_dir, work, output, meta['type'])
                            result['clock'] = deepcopy(meta.get('clock', {}))
                        result['review_provenance'] = {**approval, 'node': step['id']}
                        return {'artifacts': {'value': result}}
                    if step['type'] == 'select':
                        ports = ('a', 'b') if step['options']['selection'] == 'both' else (step['options']['selection'],)
                        return {'artifacts': {p: {k: deepcopy(v) for k, v in {**incoming['value'], 'reference': step['bindings']['value']}.items() if k != 'path'} for p in ports}}
                    if step['type'] == 'join':
                        members = {b['node'] + '.' + b['port']: incoming[port] for port, b in step['active_bindings'].items()}
                        output = work / 'manifest.json'
                        write_json_atomic(output, {'version': 1, 'kind': 'artifact_manifest', 'members': members})
                        return {'artifacts': {'manifest': self._artifact(ticket_dir, work, output, 'artifact_manifest')}}
                    if step['id'] not in plan['eligible_steps']:
                        raise TicketConflict('확인한 미실행 단계 계획에 없습니다.')
                    try:
                        outputs = execute(deepcopy(step), {p: resolve(m) for p, m in incoming.items()}, work, check)
                        if set(outputs) != set(step['outputs']):
                            raise ValueError('정의와 다른 출력 포트입니다.')
                        artifacts = {p: self._artifact(ticket_dir, work, path, step['outputs'][p]) for p, path in outputs.items()}
                        for meta in artifacts.values():
                            meta['clock'] = deepcopy(clock)
                        if step['type'] == 'preprocess_audio':
                            artifacts['audio']['clock'] = {**clock, 'basis': 'packed', 'timeline': {'node': step['id'], 'port': 'timeline', 'sha256': artifacts['timeline']['sha256']}}
                            artifacts['timeline']['clock'] = {**clock, 'basis': 'packed_to_original'}
                        return {'artifacts': artifacts}
                    except Exception as exc:
                        partial = {p.name: self._artifact(ticket_dir, work, p, 'partial') for p in work.glob('partial-*') if p.is_file() and p.suffix in {'.json', '.srt', '.smi'}}
                        raise NodeFailure(partial, exc) from None
                def publish(snapshot):
                    with _file_lock(ticket_dir / 'state.lock'):
                        for step in record['steps']:
                            outcome = snapshot['nodes'][step['id']]
                            step['status'] = outcome['status']
                            if outcome['status'] == 'running' and not self._preserve_serving(step):
                                step['serving_snapshot'] = deepcopy(record['settings_snapshot'])
                            for key in ('wait', 'error_type', 'blocked_by', 'reason'):
                                if key in outcome:
                                    step[key] = deepcopy(outcome[key])
                            step['artifacts'] = deepcopy(outcome.get('result', {}).get('artifacts', {}))
                            step['partial_artifacts'] = deepcopy(outcome.get('partial', {}))
                            if step['status'] == 'succeeded':
                                values.update({(step['id'], p): deepcopy(m) for p, m in step['artifacts'].items()})
                        record['scheduler'] = deepcopy(snapshot)
                        self._save(record)
                settled = run_ready(execution['steps'], node_execute, publish, max_workers=2, settle=True, initial=seed, admit=lambda step:self._admit_dispatch(record,step))
                check()
                if file_sha(source) != source_sha:
                    raise TicketConflict('원본 내용 무결성이 변경되었습니다.')
                statuses = {n['status'] for n in settled['nodes'].values()}
                if 'waiting' in statuses:
                    record['status'] = self._waiting_status(record)
                elif statuses & {'pending', 'running'}:
                    raise TicketConflict('필수 단계가 정리되지 않았습니다. 완료하지 않습니다.')
                else:
                    record['status'] = 'failed' if statuses & {'failed', 'blocked'} else 'completed'
                record['phase'] += 1
                record['confirmation'] = None
                record['run_requests'][request_id]['status'] = 'settled'
            except Exception as exc:
                record['status'] = 'failed'
                record['error'] = '검수 실행 조정 실패 · ' + type(exc).__name__ + ' (자동 재시도/복구 없음)'
                record['run_requests'][request_id]['status'] = 'settled'
            with _file_lock(ticket_dir / 'state.lock'):
                self._save(record)
        return self.get(identity)
