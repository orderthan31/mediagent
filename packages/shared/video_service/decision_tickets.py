"""WF06 A decision tickets: frozen structured judgments, separate route passes."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from .review_tickets import ReviewTicketStore
from .workflow_tickets import TicketConflict, digest
from .parallel_workflow import compile_graph
from .parallel_scheduler import NodeWait, NodeFailure
from .decision_adapter import invoke_decision, descriptor, DecisionFormatError, DecisionInputError
from .decision_conditions import evaluate, conditions, DecisionConditionError
from .graph_tickets import file_sha
from .storage import read_json, write_json_atomic


class DecisionAdapterError(RuntimeError):
    pass


class DecisionTicketStore(ReviewTicketStore):
    execution_contract = 'decision-v1'
    boundary_types = {'review', 'decision'}
    confirmation_statuses = ReviewTicketStore.confirmation_statuses | {'awaiting_decision'}

    def __init__(self, root, owner=None, *, adapter_profile=None):
        super().__init__(root, owner)
        self.directory = (Path(root) / '.workflow-decision-tickets' / self.directory.name).resolve()
        self.adapter_profile = None if adapter_profile is None else descriptor(SimpleNamespace(descriptor=adapter_profile))

    def _make_executor(self, record, bound, factory, execution):
        # Only the server's current frozen-route plan is supplied, never a client plan.
        return factory(bound, deepcopy(record['options']), deepcopy(execution))

    def _compile_definition(self, graph, options):
        return compile_graph(graph, options.get('branch_choices', {}), allow_review=True, allow_decision=True)

    def _save(self, record):
        record.pop('decisions', None)
        record.pop('execution_view', None)
        super()._save(record)

    def _decisions(self, record):
        result = {}
        for step in record['sequence']['steps']:
            if step['type'] != 'decision':
                continue
            work = self.directory_for(record['id']) / 'work' / step['id']
            report_path, route_path, failure_path = work / 'decision.json', work / 'route.json', work / 'decision-error.json'
            if failure_path.is_file():
                result[step['id']] = {**read_json(failure_path), 'status': 'failed', 'error_sha256': file_sha(failure_path)}
            elif route_path.is_file():
                route = read_json(route_path)
                report = read_json(report_path)
                expected = evaluate(report['judgment'], step['options'])
                node_state = next(n for n in record['steps'] if n['id'] == step['id'])
                pin = node_state.get('wait')
                if pin and (pin.get('report_sha256') != file_sha(report_path) or pin.get('route_sha256') != file_sha(route_path) or pin.get('selected_port') != expected['selected_port']):
                    raise TicketConflict('성공 때 고정한 판단 결과/조건/선택 SHA와 다릅니다. 자동 재판정하지 않습니다.')
                if (route['report_sha256'] != file_sha(report_path) or route['input_sha256'] != report['input']['sha256']
                        or route['evaluation'] != expected or route['definition_hash'] != record['definition_sha256']):
                    raise TicketConflict('고정 판단 입력/결과/조건/정의가 다릅니다. 재판정은 새 티켓으로 분리하세요.')
                result[step['id']] = {'status': 'succeeded', 'sha256': file_sha(route_path), 'report_sha256': route['report_sha256'],
                                      'input': report['input'], 'input_sha256': route['input_sha256'], **expected, 'adapter': report['adapter'], 'judgment': report['judgment']}
            elif report_path.is_file():
                result[step['id']] = {'status': 'incomplete', 'code': 'incomplete_frozen_report', 'notice': '중단된 판단의 자동 재판정/crash 복구는 지원하지 않습니다.'}
        return result

    def get(self, identity):
        record = super().get(identity)
        record['decisions'] = self._decisions(record)
        record['execution_view'] = self._execution_sequence(record)
        return record

    def _execution_sequence(self, record):
        frozen = record.get('decisions', self._decisions(record))
        routes = {node: row['selected_port'] for node, row in frozen.items() if row['status'] == 'succeeded'}
        graph = {key: record['definition'][key] for key in ('catalog_version', 'revision', 'name', 'inputs', 'nodes', 'edges')}
        return compile_graph(graph, record['options'].get('branch_choices', {}), allow_review=True, allow_decision=True, decision_routes=routes)

    def _gate_approval(self, record, identity):
        frozen = record.get('decisions', self._decisions(record)).get(identity)
        if frozen and frozen['status'] == 'succeeded':
            return frozen
        return super()._gate_approval(record, identity)

    def _resume_gate(self, record, plan, identity):
        return plan['decision_bindings'].get(identity, {}).get('status') == 'succeeded' or super()._resume_gate(record, plan, identity)

    def _plan_extension(self, record):
        frozen = record.get('decisions', self._decisions(record))
        execution = self._execution_sequence(record)
        needs_adapter = any(s['type'] == 'decision' and s['selected'] and s['id'] not in frozen for s in execution['steps'])
        return {'decisions': frozen, 'pending_adapter_profile': self.adapter_profile if needs_adapter else None}

    def plan(self, identity, preferences):
        result = super().plan(identity, preferences)
        record = self.get(identity)
        pending = [n['id'] for n in result['steps'] if n['type'] == 'decision' and n['id'] in result['eligible_steps'] and n['id'] not in record['decisions']]
        if pending:
            result['paid_roles'] = sorted(set(result['paid_roles']) | {'decision'})
            if self.adapter_profile is None:
                result['ready'] = False
        return {**result, 'decision_bindings': record['decisions'], 'decision_adapter': self.adapter_profile,
                'unresolved_routes': [n['id'] for n in result['steps'] if n.get('routing_state') == 'unresolved' and n['selected']],
                'notice': '최초 판단도 계획/비용 명시 확인 후 실행합니다. 판단 전 경로/비용은 미확정이며 skipped/비용0이 아닙니다. 성공 판단을 고정하고 선택 후행은 결과·미실행 경로·서빙의 새 확인 뒤 별도 이어실행합니다. 재판정은 새 티켓입니다.'}

    def _preserve_serving(self, step):
        return step['type'] == 'decision' and bool(step.get('serving_snapshot'))

    def _waiting_status(self, record):
        return 'awaiting_decision' if any(n['type'] == 'decision' and n['status'] == 'waiting' for n in record['steps']) else 'awaiting_review'

    def _execute_extension(self, step, incoming, work, resolve, execute, record, plan):
        if step['type'] != 'decision':
            return None
        meta = incoming['value']
        existing = self._decisions(record).get(step['id'])
        if existing:
            if existing['status'] != 'succeeded' or plan['decision_bindings'].get(step['id']) != existing or existing['input_sha256'] != meta['sha256']:
                raise TicketConflict('확인한 고정 판단/입력이 아닙니다. 자동 재판정하지 않습니다.')
            port = existing['selected_port']
            alias = {k: deepcopy(v) for k, v in {**meta, 'reference': step['bindings']['value']}.items() if k != 'path'}
            alias['decision_provenance'] = {key: deepcopy(existing[key]) for key in ('sha256', 'report_sha256', 'input_sha256', 'selected_port', 'adapter')}
            return {'artifacts': {port: alias, 'result': self._artifact(self.directory_for(record['id']), work, work/'decision.json', 'decision_result')}}
        try:
            provider = getattr(execute, 'decision_provider', None)
            if provider is None or descriptor(provider) != self.adapter_profile or plan['decision_adapter'] != self.adapter_profile:
                raise DecisionFormatError('확인한 adapter ID/revision이 아닙니다.')
            report = invoke_decision(provider, meta, resolve(meta), work)
            evaluation = evaluate(report['judgment'], step['options'])
            write_json_atomic(work/'route.json', {'version': 1, 'kind': 'decision_route', 'definition_hash': record['definition_sha256'],
                                                'input_sha256': meta['sha256'], 'report_sha256': file_sha(work/'decision.json'), 'evaluation': evaluation})
        except Exception as exc:
            error = exc if isinstance(exc, (DecisionInputError, DecisionFormatError, DecisionConditionError)) else DecisionAdapterError()
            code = 'input_integrity_error' if isinstance(error, DecisionInputError) else 'format_error' if isinstance(error, DecisionFormatError) else 'condition_error' if isinstance(error, DecisionConditionError) else 'adapter_error'
            failure = {'version': 1, 'kind': 'decision_error', 'code': code, 'error_type': type(error).__name__,
                       'input_sha256': meta['sha256'], 'conditions': conditions(step['options']), 'adapter': self.adapter_profile}
            write_json_atomic(work/'decision-error.json', failure)
            artifacts = {'decision_error': self._artifact(self.directory_for(record['id']), work, work/'decision-error.json', 'decision_result')}
            if (work/'decision.json').is_file():
                artifacts['judgment'] = self._artifact(self.directory_for(record['id']), work, work/'decision.json', 'decision_result')
            raise NodeFailure(artifacts, error) from None
        raise NodeWait({'kind': 'decision_confirmation', 'report_sha256': file_sha(work/'decision.json'), 'route_sha256': file_sha(work/'route.json'), 'selected_port': evaluation['selected_port']})
