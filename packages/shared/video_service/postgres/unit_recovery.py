"""Explicit same-job unit recovery. Never rewrites original calls, grants or leases.

Only the application-owned executor may consume attempt IDs. A sending attempt
is never sent again; an ambiguous outcome requires GET reconciliation, not retry.
"""
import hashlib
import json
import re
from copy import deepcopy
from uuid import uuid4

from psycopg.types.json import Jsonb

from video_service.canonical import canonical, digest
from . import Conflict, Missing
from .registry import resource_id


class RecoveryUnavailable(Exception):
    pass


def clean_error(value):
    # Deliberately small allowlist: provider messages may contain credentials.
    return value if value in {'provider_timeout', 'provider_unavailable', 'invalid_response',
                             'cancelled', 'recovery_attempt_failed', 'recovery_outcome_unknown'} else 'recovery_attempt_failed'


def public_unit(unit):
    result = {key: deepcopy(unit[key]) for key in (
        'index', 'input_sha256', 'status', 'source_ranges', 'source_rows',
        'manual_schema', 'allowed_actions') if key in unit}
    result['error_code'] = clean_error(unit['error_code']) if unit.get('error_code') else None
    result.setdefault('manual_schema', {'type': 'array', 'timing': 'exact_source_rows' if unit.get('source_rows') else 'chunk_local',
                                        'editable_fields': ['text'] if unit.get('source_rows') else ['start', 'end', 'text', 'speaker'],
                                        'duration_seconds': unit.get('end', 0) - unit.get('start', 0) if not unit.get('source_rows') else None})
    result['attempts'] = [{'origin': 'original', 'candidate_index': a.get('candidate_index'),
                           'status': a.get('status'), 'error_code': clean_error(a['error_code']) if a.get('error_code') else None}
                          for a in unit.get('attempts', [])]
    result.setdefault('provenance', {'kind': 'original' if unit.get('status') == 'succeeded' else 'unresolved'})
    return result


def validate_body(body, *, decision=False):
    fields = {'job_revision', 'recovery_revision', 'context_sha256', 'decisions'}
    if decision:
        fields |= {'request_id', 'preview_sha256', 'approve_calls'}
    if type(body) is not dict or set(body) != fields:
        raise Conflict('invalid_unit_recovery_request')
    if any(type(body[k]) is not int or body[k] < 0 for k in ('job_revision', 'recovery_revision')):
        raise Conflict('invalid_unit_recovery_revision')
    for key in ('context_sha256', 'preview_sha256') if decision else ('context_sha256',):
        if not isinstance(body[key], str) or not re.fullmatch('[a-f0-9]{64}', body[key]):
            raise Conflict('invalid_unit_recovery_digest')
    if type(body['decisions']) is not list or len(body['decisions']) > 10000:
        raise Conflict('invalid_unit_recovery_decisions')
    if decision and (type(body['approve_calls']) is not bool or not isinstance(body['request_id'], str)
                     or not 1 <= len(body['request_id']) <= 100):
        raise Conflict('invalid_unit_recovery_approval')


def _core():
    from video_service import unit_recovery
    return unit_recovery


class RoleUnitRecovery:
    def __init__(self, runtime, *, executor=None):
        self.runtime, self.executor = runtime, executor

    @staticmethod
    def _schema(db):
        row = db.execute("SELECT to_regclass('model_role_unit_recoveries') AS name").fetchone()
        if not row['name']:
            raise RecoveryUnavailable('unit_recovery_migration_required')

    def _facts(self, db, actor, job_id, run_id, *, manage=False):
        self._schema(db)
        job = self.runtime._shared_job(db, resource_id(job_id))
        owner = job['owner_id']
        if manage and actor != owner:
            raise PermissionError('unit_recovery_owner_required')
        run = db.execute('SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s FOR UPDATE',
                         (owner, job_id, resource_id(run_id))).fetchone()
        if not run:
            raise Missing('unit_recovery_run_missing')
        task = db.execute('SELECT * FROM model_role_tasks WHERE owner_id=%s AND job_id=%s AND attempt_id=%s FOR UPDATE',
                          (owner, job_id, run_id)).fetchone()
        latest = db.execute('SELECT * FROM model_role_unit_recoveries WHERE owner_id=%s AND job_id=%s AND run_id=%s ORDER BY revision DESC LIMIT 1 FOR UPDATE',
                            (owner, job_id, run_id)).fetchone()
        if not task or task['envelope']['role'] not in {'transcription', 'translation'}:
            return job, run, task, latest, None, None, 'unsupported_role'
        command = run['request']
        calls = db.execute('SELECT * FROM model_role_tool_calls WHERE task_id=%s ORDER BY chunk_index', (task['task_id'],)).fetchall()
        task_body = task['envelope']['task']
        # Do not require/renew the original expired lease: recovery has its own grants.
        blocked = None
        if (job['cancel_requested'] or job['status'] not in {'waiting', 'running'}
            or run.get('result') is not None or not job['active_claim_id']
            or job['generation'] != run['generation']
            or task['generation'] != job['generation'] or job['active_claim_id'] != run['claim_id']
            or run['status'] != 'running' or task['phase'] not in {'held', 'settled'}):
            blocked = 'unit_recovery_root_not_held'
        if (digest(command) != run['request_sha256'] or task['request_sha256'] != run['request_sha256']
            or digest(task['envelope']) != task['envelope_sha256']
            or digest(job['snapshot']) != job['snapshot_sha256']
            or command.get('run_id') != job_id or command.get('attempt_id') != run_id
            or command.get('generation') != run['generation']
            or task_body.get('task_id') != task['task_id']
            or (task['result_sha256'] and digest(task['result_message']) != task['result_sha256'])):
            raise Conflict('unit_recovery_frozen_binding_changed')
        from video_service.role_policy import is_v2
        if not is_v2(task_body):
            return job, run, task, latest, None, None, 'unsupported_role_policy'
        from .model_roles import ModelRoles
        if [ModelRoles._model_binding(p) for p in task['frozen_candidates']] != task_body.get('models'):
            raise Conflict('unit_recovery_model_binding_changed')
        delivery = db.execute('SELECT * FROM model_role_result_deliveries WHERE task_id=%s FOR UPDATE',
                              (task['task_id'],)).fetchone()
        if delivery and delivery['state'] != 'settled':
            blocked = 'unit_recovery_root_delivery_unresolved'
        if delivery and digest(delivery['packet']) != delivery['packet_sha256']:
            raise Conflict('unit_recovery_root_delivery_changed')
        safe_calls = [{k: c[k] for k in ('chunk_index', 'input_sha256', 'model', 'status', 'response', 'error_code')} for c in calls]
        context = {
            'owner_id': owner, 'job_id': job_id, 'run_id': run_id, 'task_id': task['task_id'],
            'generation': job['generation'], 'claim_id': run['claim_id'],
            'job_revision': job['revision'], 'snapshot_sha256': job['snapshot_sha256'],
            'request_sha256': run['request_sha256'], 'envelope_sha256': task['envelope_sha256'],
            'pins_sha256': digest(task['frozen_candidates']), 'calls_sha256': digest(safe_calls),
            'result_sha256': task['result_sha256'], 'phase': task['phase'],
            'delivery': ({k: delivery[k] for k in ('packet_sha256', 'state', 'revision')} if delivery else None),
        }
        role = task_body['role']
        ref = command['inputs']['audio' if role == 'transcription' else 'transcript']
        raw = self.runtime.store.read(owner, ref, limit=ref['bytes'])
        if len(raw) != ref['bytes'] or hashlib.sha256(raw).hexdigest() != ref['sha256']:
            raise Conflict('unit_recovery_source_changed')
        binding = task_body['audio' if role == 'transcription' else 'transcript']
        if binding != {k: ref[k] for k in ('sha256', 'bytes')}:
            raise Conflict('unit_recovery_source_binding_changed')
        source = raw if role == 'transcription' else json.loads(raw)
        try:
            manifest = _core().build_manifest(task_body, source, safe_calls)
        except (ValueError, TypeError, KeyError):
            raise Conflict('unit_recovery_evidence_invalid') from None
        if any(u['status'] in {'unknown', 'active', 'evidence_invalid'} for u in manifest['units']):
            blocked = 'unit_recovery_evidence_unresolved'
        context['source_sha256'] = ref['sha256']
        return job, run, task, latest, context, manifest, blocked

    @staticmethod
    def _attempts(db, recovery):
        if not recovery:
            return []
        return db.execute('SELECT * FROM model_role_unit_attempts WHERE recovery_id=%s ORDER BY unit_index', (recovery['id'],)).fetchall()

    @staticmethod
    def _same_context(recovery, context, manifest):
        return (recovery['context_sha256'] == digest(context)
                and recovery['context'] == context and recovery['manifest'] == manifest)

    @staticmethod
    def _check_record(recovery):
        if (digest(recovery['context']) != recovery['context_sha256']
            or digest({k: v for k, v in recovery['manifest'].items() if k != 'manifest_sha256'})
                != recovery['manifest']['manifest_sha256']):
            raise Conflict('unit_recovery_retained_binding_changed')

    @staticmethod
    def _decisions(recovery):
        reused = recovery.get('reused_attempts', [])
        indices = {p['unit_index'] for p in reused}
        if len(indices) != len(reused) or any(d['unit_index'] in indices for d in recovery['decisions']):
            raise Conflict('unit_recovery_retained_unit_not_editable')
        return recovery['decisions'] + [dict(unit_index=p['unit_index'], action='retry',
                                            candidate_index=p['candidate_index']) for p in reused]

    @staticmethod
    def _assert_no_unresolved(db, facts):
        # Include superseded history: an ambiguous old outcome is never a waiver.
        row = db.execute("SELECT a.id FROM model_role_unit_attempts a JOIN model_role_unit_recoveries r ON r.id=a.recovery_id WHERE r.owner_id=%s AND r.job_id=%s AND r.run_id=%s AND a.status IN ('sending','unknown') LIMIT 1",
                         (facts[0]['owner_id'], facts[0]['id'], facts[1]['id'])).fetchone()
        if row:
            raise Conflict('unit_recovery_previous_attempt_unresolved')

    def _verified_attempt(self, attempt, origin, context, manifest):
        """Bind a completed new call to its immutable approval and frozen input."""
        try:
            self._check_record(origin)
            index, candidate = attempt['unit_index'], attempt['candidate_index']
            unit = manifest['units'][index]
            decision = dict(unit_index=index, action='retry', candidate_index=candidate)
            terminal = {k: attempt[k] for k in ('status', 'response', 'error_code')}
            if (type(index) is not int or index < 0 or type(candidate) is not int or candidate < 0
                or attempt['recovery_id'] != origin['id'] or not self._same_context(origin, context, manifest)
                or any(origin[k] != context[k] for k in ('owner_id', 'job_id', 'run_id', 'task_id'))
                or not origin['approve_calls'] or origin['additional_call_limit'] <= 0
                or decision not in origin['decisions'] or 'retry' not in unit['allowed_actions']
                or any(p['unit_index'] == index for p in origin.get('reused_attempts', []))
                or attempt['input_sha256'] != unit['input_sha256'] or attempt['status'] != 'completed'
                or digest(terminal) != attempt['terminal_sha256']):
                raise ValueError('binding')
            model = manifest['task']['models'][candidate]
            if manifest['role'] == 'translation':
                from video_service.translation_output import decode_output
                rows = decode_output(attempt['response'], unit['source_rows'])
            else:
                from video_service.audio_contract import timed_segments
                rows = timed_segments(attempt['response'], unit['end'] - unit['start'])
            proof = dict(attempt_id=attempt['id'], recovery_id=origin['id'], unit_index=index,
                         candidate_index=candidate, input_sha256=attempt['input_sha256'],
                         terminal_sha256=attempt['terminal_sha256'], model_sha256=digest(model))
            return {'proof': proof, 'response': attempt['response'], 'rows': rows}
        except (ValueError, TypeError, KeyError, IndexError, OverflowError):
            raise Conflict('unit_recovery_retained_evidence_invalid') from None

    def _verified_retries(self, db, recovery, context, manifest):
        """Read exact immutable carry proofs plus this approval's completed rows.

        Attempt completion deliberately does not change the Root context hash.
        A later preview binds the newly observed proofs in its own preview hash.
        """
        self._check_record(recovery)
        if not self._same_context(recovery, context, manifest):
            raise Conflict('unit_recovery_context_changed')
        self._decisions(recovery)
        verified = {}
        for proof in recovery.get('reused_attempts', []):
            attempt = db.execute('SELECT * FROM model_role_unit_attempts WHERE id=%s', (proof['attempt_id'],)).fetchone()
            origin = db.execute('SELECT * FROM model_role_unit_recoveries WHERE id=%s', (proof['recovery_id'],)).fetchone()
            if not attempt or not origin or origin['revision'] >= recovery['revision']:
                raise Conflict('unit_recovery_retained_evidence_invalid')
            value = self._verified_attempt(attempt, origin, context, manifest)
            if proof != value['proof']:
                raise Conflict('unit_recovery_retained_evidence_changed')
            verified[proof['unit_index']] = value
        for attempt in self._attempts(db, recovery):
            if attempt['unit_index'] in verified:
                raise Conflict('unit_recovery_retained_unit_not_editable')
            if attempt['status'] == 'completed':
                verified[attempt['unit_index']] = self._verified_attempt(attempt, recovery, context, manifest)
        return verified

    def _carry_candidates(self, db, facts):
        latest, context, manifest = facts[3:6]
        self._assert_no_unresolved(db, facts)
        if not latest:
            return {}
        self._check_record(latest)
        if not self._same_context(latest, context, manifest):
            return {}  # A new Root context never inherits old retry authority.
        return self._verified_retries(db, latest, context, manifest)

    def _retry_results(self, db, recovery, context, manifest):
        return {str(index): value['response'] for index, value in
                self._verified_retries(db, recovery, context, manifest).items()}

    def _execution_preview(self, manifest, recovery):
        preview = _core().preview_decisions(manifest, self._decisions(recovery))
        if any(not re.fullmatch(r'unit:\d+:unresolved', reason) for reason in preview['blocked_reasons']):
            raise Conflict('unit_recovery_decisions_incomplete')
        if sum(d['action'] == 'retry' for d in recovery['decisions']) != recovery['additional_call_limit']:
            raise Conflict('unit_recovery_attempt_budget_changed')
        return preview

    def _assemble(self, db, recovery, context, manifest):
        result = _core().assemble_resolutions(manifest, self._decisions(recovery),
                                             self._retry_results(db, recovery, context, manifest))
        # The core counts all supplied retry resolutions; only newly selected
        # calls belong to this approval's budget. Keep carry lineage explicit.
        resolution = result['resolution_manifest']
        if not isinstance(resolution, dict):
            raise Conflict('unit_recovery_resolution_missing')
        resolution['additional_call_limit'] = recovery['additional_call_limit']
        resolution['reused_attempts'] = deepcopy(recovery.get('reused_attempts', []))
        return result

    @staticmethod
    def _retained_unit(unit, value):
        proof = value['proof']
        return {**public_unit(unit), 'status': 'succeeded', 'error_code': None, 'allowed_actions': [],
                'provenance': {'kind': 'model_retry', 'recovery_id': proof['recovery_id'],
                               'attempt_id': proof['attempt_id']}}

    def _view(self, db, actor, facts):
        job, run, task, latest, context, manifest, blocked = facts
        units = [public_unit(u) for u in (manifest or {}).get('units', [])]
        attempts = self._attempts(db, latest)
        decisions = {d['unit_index']: d for d in latest['decisions']} if latest else {}
        verified = (self._verified_retries(db, latest, context, manifest)
                    if latest and manifest and self._same_context(latest, context, manifest) else {})
        for unit in units:
            unit['attempts'] += [{k: a[k] for k in ('id', 'status', 'candidate_index')} | {
                'origin': 'recovery', 'error_code': clean_error(a['error_code']) if a['error_code'] else None}
                for a in attempts if a['unit_index'] == unit['index']]
            if unit['index'] in decisions:
                unit['provenance'] = {'kind': decisions[unit['index']]['action'], 'recovery_id': latest['id']}
            if unit['index'] in verified:
                value = verified[unit['index']]
                unit.update({k: v for k, v in self._retained_unit(unit, value).items() if k != 'attempts'})
                if value['proof']['recovery_id'] != latest['id']:
                    unit['attempts'].append({'id': value['proof']['attempt_id'], 'status': 'completed',
                                             'candidate_index': value['proof']['candidate_index'],
                                             'origin': 'recovery', 'retained': True, 'error_code': None})
        counts = {s: sum(u['status'] == s for u in units) for s in ('succeeded','failed','unknown','active','unattempted')}
        counts.update(manual=sum(d['action'] == 'manual' for d in decisions.values()),
                      skipped=sum(d['action'] == 'skip' for d in decisions.values()))
        ready = False
        if latest and not blocked and self._same_context(latest, context, manifest):
            try:
                self._assemble(db, latest, context, manifest)
                ready = True
            except (ValueError, TypeError, KeyError):
                pass
        return {'version': 1, 'supported': manifest is not None, 'blocked_reason': blocked,
                'job_id': job['id'], 'run_id': run['id'], 'task_id': task['task_id'] if task else None,
                'role': task['envelope']['role'] if task else None, 'job_revision': job['revision'],
                'recovery_revision': latest['revision'] if latest else 0,
                'context_sha256': digest(context) if context else None,
                'access': {'can_manage': actor == job['owner_id']}, 'counts': counts, 'units': units,
                'decisions': deepcopy(latest['decisions']) if latest else [],
                'recovery': ({'id': latest['id'], 'status': latest['status'], 'revision': latest['revision'],
                              'request_id': latest['request_id'], 'additional_call_limit': latest['additional_call_limit'],
                              'executed_calls': sum(a['status'] != 'pending' for a in attempts),
                              'can_continue': ready and latest['status'] != 'applied'} if latest else None)}

    def inspect(self, actor, job, run):
        with self.runtime.database.connection() as db:
            return self._view(db, actor, self._facts(db, actor, job, run))

    def _preview(self, facts, body, *, reused=None):
        job, run, task, latest, context, manifest, blocked = facts
        if blocked:
            raise Conflict(blocked)
        if (body['job_revision'] != job['revision'] or body['recovery_revision'] != (latest['revision'] if latest else 0)
            or body['context_sha256'] != digest(context)):
            raise Conflict('unit_recovery_stale_context')
        reused = reused or {}
        if any(type(d) is dict and type(d.get('unit_index')) is int and d['unit_index'] in reused
               for d in body['decisions']):
            raise Conflict('unit_recovery_retained_unit_not_editable')
        carried = [dict(unit_index=i, action='retry', candidate_index=v['proof']['candidate_index'])
                   for i, v in sorted(reused.items())]
        try:
            preview = _core().preview_decisions(manifest, body['decisions'] + carried)
        except (ValueError, TypeError, KeyError):
            raise Conflict('invalid_unit_recovery_decisions') from None
        # Public model identity only; never expose pins, endpoints, options or key refs.
        result = {k: deepcopy(preview[k]) for k in ('ready', 'retained_units', 'execution_units',
                  'additional_call_limit', 'warnings', 'blocked_reasons', 'decisions') if k in preview}
        result.update(version=1, job_revision=job['revision'], recovery_revision=body['recovery_revision'],
                      context_sha256=digest(context), decisions=preview.get('decisions', body['decisions']),
                      models=[{k: p[k] for k in ('model_id','revision')} for p in task['frozen_candidates']])
        for key in ('retained_units', 'execution_units'):
            result[key] = [public_unit(u) | ({'candidate_index': u['candidate_index']} if 'candidate_index' in u else {})
                           for u in preview.get(key, [])]
        result['decisions'] = [d for d in result['decisions'] if d['unit_index'] not in reused]
        result['execution_units'] = [u for u in result['execution_units'] if u['index'] not in reused]
        result['retained_units'] = sorted(result['retained_units'] + [
            self._retained_unit(manifest['units'][i], value) for i, value in reused.items()], key=lambda u: u['index'])
        result['reused_attempts'] = [deepcopy(value['proof']) for i, value in sorted(reused.items())]
        result['additional_call_limit'] = len(result['execution_units'])
        result['preview_sha256'] = digest(result)
        return result

    def preview(self, actor, job, run, body):
        validate_body(body)
        with self.runtime.database.connection() as db:
            facts = self._facts(db, actor, job, run, manage=True)
            return self._preview(facts, body, reused=self._carry_candidates(db, facts))

    def decide(self, actor, job, run, body):
        validate_body(body, decision=True)
        with self.runtime.database.connection() as db:
            facts = self._facts(db, actor, job, run, manage=True)
            previous = db.execute('SELECT * FROM model_role_unit_recoveries WHERE owner_id=%s AND job_id=%s AND run_id=%s AND request_id=%s',
                                  (actor, job, run, body['request_id'])).fetchone()
            if previous:
                if previous['request_sha256'] != digest(body):
                    raise Conflict('unit_recovery_request_id_reused')
                return self._view(db, actor, (*facts[:3], previous, *facts[4:]))
            preview = self._preview(facts, body, reused=self._carry_candidates(db, facts))
            if preview['preview_sha256'] != body['preview_sha256']:
                raise Conflict('unit_recovery_preview_changed')
            if any(not reason.endswith(':unresolved') and reason != 'unit_recovery_empty_output_unsupported'
                   for reason in preview.get('blocked_reasons', [])):
                raise Conflict('invalid_unit_recovery_decisions')
            cap = preview['additional_call_limit']
            if cap and not body['approve_calls']:
                raise Conflict('unit_recovery_calls_not_approved')
            latest = facts[3]
            if latest and (latest['status'] == 'applied' or any(a['status'] in {'sending','unknown'} for a in self._attempts(db, latest))):
                raise Conflict('unit_recovery_previous_attempt_unresolved')
            identity = uuid4().hex
            db.execute('INSERT INTO model_role_unit_recoveries(id,owner_id,job_id,run_id,task_id,revision,request_id,request_sha256,context_sha256,context,manifest,decisions,reused_attempts,preview_sha256,additional_call_limit,approve_calls) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (identity, actor, job, run, facts[2]['task_id'], body['recovery_revision']+1, body['request_id'], digest(body),
                        digest(facts[4]), Jsonb(facts[4]), Jsonb(facts[5]), Jsonb(preview['decisions']), Jsonb(preview['reused_attempts']), body['preview_sha256'], cap, body['approve_calls']))
            by_index = {u['index']: u for u in facts[5]['units']}
            for decision in preview['decisions']:
                if decision['action'] == 'retry':
                    db.execute('INSERT INTO model_role_unit_attempts(id,recovery_id,unit_index,candidate_index,input_sha256) VALUES(%s,%s,%s,%s,%s)',
                               (uuid4().hex, identity, decision['unit_index'], decision.get('candidate_index', 0), by_index[decision['unit_index']]['input_sha256']))
            return self._view(db, actor, self._facts(db, actor, job, run, manage=True))

    def _selected(self, db, owner, job, run, request_id):
        facts = self._facts(db, owner, job, run, manage=True)
        recovery = facts[3]
        if not recovery or recovery['request_id'] != request_id:
            raise Conflict('unit_recovery_request_not_current')
        if facts[6] or digest(facts[4]) != recovery['context_sha256'] or facts[5] != recovery['manifest']:
            raise Conflict(facts[6] or 'unit_recovery_context_changed')
        self._verified_retries(db, recovery, facts[4], facts[5])
        return facts, recovery

    def execute(self, actor, job, run, request_id):
        with self.runtime.database.connection() as db:
            facts, recovery = self._selected(db, actor, job, run, request_id)
            attempts = self._attempts(db, recovery)
            if recovery['status'] == 'applied':
                return self._view(db, actor, facts)
            if any(a['status'] in {'sending','unknown'} for a in attempts):
                raise Conflict('unit_recovery_outcome_requires_read_only_reconciliation')
            pending = [a for a in attempts if a['status'] == 'pending']
            if pending:
                self._execution_preview(facts[5], recovery)
            if pending and self.executor is None:
                raise Conflict('unit_recovery_executor_unavailable')
        for attempt in pending:
            # Bridge owns begin_attempt immediately before approved I/O and finish_attempt.
            self.executor(attempt['id'], recovery['context_sha256'])
        return self.inspect(actor, job, run)

    def load_retry_attempt(self, attempt_id, context_sha256):
        with self.runtime.database.connection() as db:
            return self._grant(db, attempt_id, context_sha256)

    def _grant(self, db, attempt_id, context_sha256):
        self._schema(db)
        row = db.execute('SELECT a.*,r.owner_id,r.job_id,r.run_id,r.task_id,r.context_sha256,r.request_id FROM model_role_unit_attempts a JOIN model_role_unit_recoveries r ON r.id=a.recovery_id WHERE a.id=%s', (resource_id(attempt_id),)).fetchone()
        if not row:
            raise Missing('unit_recovery_attempt_missing')
        facts, recovery = self._selected(db, row['owner_id'], row['job_id'], row['run_id'], row['request_id'])
        if recovery['id'] != row['recovery_id'] or context_sha256 != row['context_sha256'] or recovery['status'] == 'applied':
            raise Conflict('unit_recovery_attempt_scope_changed')
        if not recovery['approve_calls'] or not 0 < recovery['additional_call_limit'] <= 10000:
            raise Conflict('unit_recovery_calls_not_approved')
        attempts = self._attempts(db, recovery)
        if len(attempts) != recovery['additional_call_limit']:
            raise Conflict('unit_recovery_attempt_budget_changed')
        self._execution_preview(facts[5], recovery)
        selected = {d['unit_index']: d for d in recovery['decisions'] if d['action'] == 'retry'}
        for attempt in attempts:
            decision = selected.get(attempt['unit_index'])
            if (not decision or attempt['candidate_index'] != decision['candidate_index']
                or attempt['input_sha256'] != facts[5]['units'][attempt['unit_index']]['input_sha256']):
                raise Conflict('unit_recovery_attempt_scope_changed')
        task = facts[2]
        role = task['envelope']['role']
        ref = facts[1]['request']['inputs']['audio' if role == 'transcription' else 'transcript']
        raw = self.runtime.store.read(row['owner_id'], ref, limit=ref['bytes'])
        source = raw if role == 'transcription' else json.loads(raw)
        return {**dict(row), 'attempt_id': row['id'], 'role': role, 'task': task['envelope']['task'],
                'pin': task['frozen_candidates'][row['candidate_index']], 'source': source,
                'unit': next(u for u in facts[5]['units'] if u['index'] == row['unit_index']),
                'manifest': facts[5], 'command': facts[1]['request']}

    def begin_attempt(self, attempt_id, context_sha256):
        with self.runtime.database.connection() as db:
            grant = self._grant(db, attempt_id, context_sha256)
            row = db.execute('SELECT * FROM model_role_unit_attempts WHERE id=%s FOR UPDATE', (attempt_id,)).fetchone()
            newly = row['status'] == 'pending'
            if newly:
                db.execute("UPDATE model_role_unit_attempts SET status='sending' WHERE id=%s AND status='pending'", (attempt_id,))
            # context manager commits before this grant reaches external I/O.
            grant.update(status='sending' if newly else row['status'], newly_sending=newly)
        return grant

    def finish_attempt(self, attempt_id, status, response=None, error_code=None):
        if status not in {'completed','failed','unknown'} or (status == 'completed' and response is None):
            raise Conflict('invalid_unit_recovery_outcome')
        if status != 'completed':
            response = None
        error_code = clean_error(error_code) if error_code else None
        terminal = {'status': status, 'response': response, 'error_code': error_code}
        if len(canonical(terminal)) > 16 * 1024 * 1024:
            raise Conflict('unit_recovery_response_too_large')
        sha = digest(terminal)
        with self.runtime.database.connection() as db:
            self._schema(db)
            row = db.execute('SELECT * FROM model_role_unit_attempts WHERE id=%s FOR UPDATE', (resource_id(attempt_id),)).fetchone()
            if not row:
                raise Missing('unit_recovery_attempt_missing')
            if row['terminal_sha256']:
                if row['terminal_sha256'] != sha:
                    raise Conflict('unit_recovery_terminal_changed')
                return {'attempt_id': attempt_id, 'status': row['status']}
            if row['status'] != 'sending':
                raise Conflict('unit_recovery_attempt_not_sending')
            db.execute('UPDATE model_role_unit_attempts SET status=%s,response=%s,error_code=%s,terminal_sha256=%s WHERE id=%s',
                       (status, Jsonb(response) if response is not None else None, error_code, sha, attempt_id))
        return {'attempt_id': attempt_id, 'status': status}

    def prepare_adoption(self, owner, job, run, request_id):
        with self.runtime.database.connection() as db:
            self._schema(db)
            saved = db.execute('SELECT * FROM model_role_unit_recoveries WHERE owner_id=%s AND job_id=%s AND run_id=%s AND request_id=%s',
                               (owner, job, run, request_id)).fetchone()
            if saved and saved['status'] == 'applied':
                if not saved['prepared']:
                    raise Conflict('unit_recovery_prepared_receipt_missing')
                task = db.execute('SELECT * FROM model_role_tasks WHERE task_id=%s', (saved['task_id'],)).fetchone()
                return {**saved['prepared'], 'task_row': task}
            facts, recovery = self._selected(db, owner, job, run, request_id)
            if recovery['prepared']:
                return {**recovery['prepared'], 'task_row': facts[2]}
            try:
                resolved = self._assemble(db, recovery, facts[4], facts[5])
            except (ValueError, TypeError, KeyError):
                raise Conflict('unit_recovery_not_ready') from None
            command, task = facts[1]['request'], facts[2]
        rows = resolved['packed_segments'] if task['envelope']['role'] == 'transcription' else resolved['segments']
        if not rows:
            raise Conflict('unit_recovery_empty_result')
        metadata = {'version': 1, 'recovery_id': recovery['id'], 'context_sha256': recovery['context_sha256'],
                    'role_task_id': task['task_id'], 'decisions': recovery['decisions'],
                    'reused_attempts': deepcopy(recovery.get('reused_attempts', [])),
                    'resolution_manifest': resolved['resolution_manifest'], 'additional_call_limit': recovery['additional_call_limit']}
        outputs = {}
        if task['envelope']['role'] == 'transcription':
            # Recovery's assembler preserves per-unit split IDs across omissions;
            # re-projecting here would silently restore global positional IDs.
            projected = resolved['segments']
            trace = deepcopy(resolved['projection_trace'])
            if not isinstance(trace, dict):
                raise Conflict('unit_recovery_projection_missing')
            packed = self.runtime.store.put(owner, [canonical(rows)], 'transcript')
            outputs['transcript'] = self.runtime.store.put(owner, [canonical(projected)], 'transcript')
            trace.update(packed_transcript=packed, audio_sha256=command['inputs']['audio']['sha256'],
                         timeline_sha256=command['inputs']['timeline']['sha256'], unit_recovery=metadata)
            outputs['trace'] = self.runtime.store.put(owner, [canonical(trace)], 'metadata')
        else:
            outputs['transcript'] = self.runtime.store.put(owner, [canonical(rows)], 'transcript')
            outputs['report'] = self.runtime.store.put(owner, [canonical(metadata)], 'metadata')
        role_metadata = {'role_task_id': task['task_id'], 'role_policy_version': 2,
                         'source_language': task['envelope']['task']['source_language'],
                         'resolution_origin': 'explicit_user_decisions',
                         'unit_recovery_id': recovery['id']}
        if task['envelope']['role'] == 'translation':
            role_metadata['target_language'] = task['envelope']['task']['target_language']
        prepared = {'recovery_id': recovery['id'], 'context_sha256': recovery['context_sha256'],
                    'command': command, 'manifest': facts[5], 'outputs': outputs,
                    'receipt_metadata': {'unit_recovery': metadata, task['envelope']['role']: role_metadata}}
        with self.runtime.database.connection() as db:
            _, current = self._selected(db, owner, job, run, request_id)
            if current['prepared']:
                prepared = current['prepared']
            else:
                db.execute('UPDATE model_role_unit_recoveries SET prepared=%s WHERE id=%s', (Jsonb(prepared), recovery['id']))
        return {**prepared, 'task_row': task}

    def check_adoption_in(self, db, owner, job, run, recovery_id, context_sha256):
        job_id = job['id'] if isinstance(job, dict) else job
        run_id = run['id'] if isinstance(run, dict) else run
        row = db.execute('SELECT * FROM model_role_unit_recoveries WHERE id=%s AND owner_id=%s AND job_id=%s AND run_id=%s FOR UPDATE',
                         (recovery_id, owner, job_id, run_id)).fetchone()
        if row and row['status'] == 'applied' and row['context_sha256'] == context_sha256:
            return row
        facts = self._facts(db, owner, job_id, run_id, manage=True)
        recovery = facts[3]
        if (facts[6] or not recovery or recovery['id'] != recovery_id or recovery['status'] != 'approved'
            or recovery['context_sha256'] != context_sha256 or digest(facts[4]) != context_sha256
            or facts[5] != recovery['manifest']):
            raise Conflict('unit_recovery_adoption_changed')
        try:
            self._assemble(db, recovery, facts[4], facts[5])
        except (ValueError, TypeError, KeyError):
            raise Conflict('unit_recovery_not_ready') from None
        return recovery

    @staticmethod
    def mark_applied_in(db, recovery_id, receipt_sha256):
        if not re.fullmatch('[a-f0-9]{64}', receipt_sha256):
            raise Conflict('invalid_unit_recovery_receipt')
        row = db.execute('SELECT * FROM model_role_unit_recoveries WHERE id=%s FOR UPDATE', (recovery_id,)).fetchone()
        if not row:
            raise Missing('unit_recovery_missing')
        if row['status'] == 'applied' and row['receipt_sha256'] != receipt_sha256:
            raise Conflict('unit_recovery_receipt_changed')
        db.execute("UPDATE model_role_unit_recoveries SET status='applied',receipt_sha256=%s WHERE id=%s", (receipt_sha256, recovery_id))
