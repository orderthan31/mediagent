"""Explicit, pre-job start intents. Internal outbox records are never messages.

Only requested records are discovered. Each domain mutation and its receipt share
one SQL transaction. Session locks select a consumer; row-locked epochs AND the
live session lock fence its mutations. Slow validation holds neither intent nor
job locks. No dispatch, provider calls, or adoption of historical drafts occurs.
"""
from contextlib import contextmanager
from copy import deepcopy
from typing import NamedTuple
from datetime import datetime, timedelta, timezone
import logging
import threading
from uuid import uuid4

from psycopg.types.json import Jsonb
from video_service.canonical import canonical, digest
from video_service.postgres import Conflict, Missing
from video_service.postgres.intake import public_asset, request_id
from video_service.postgres.registry import resource_id

PREFIX = 'internal.start.'
REQUESTED = PREFIX + 'requested.v1'
STAGE = PREFIX + 'stage.v1'
EPOCH = PREFIX + 'epoch.v1'
TERMINAL = PREFIX + 'terminal.v1'
LOCK_NAMESPACE = 1937006962
TERMINALS = {'admitted', 'blocked', 'failed', 'expired', 'cancelled', 'uncertain'}
CODES = {'start_blocked', 'intent_expired', 'start_cancelled', 'mutation_uncertain',
         'scope_changed', 'actor_inactive', 'validation_failed'}


class Fenced(Conflict):
    pass


def _scope(job):
    return {k: job[k] for k in ('id', 'snapshot_sha256', 'generation', 'revision')}


def _account(c, owner, *, lock=False):
    row = c.execute('SELECT active,role FROM accounts WHERE id=%s' +
                    (' FOR SHARE' if lock else ''), (owner,)).fetchone()
    if not row or not row['active']:
        raise Fenced('actor_inactive')
    return row['role']


class _Issued(NamedTuple):
    service: object
    runtime: object
    root: dict
    state: dict
    epoch: int
    pid: int


# Only claim() issues entries, and its finally block revokes the exact object.
# Python reflection is not a security boundary; callers cannot mint authority by
# constructing/copying a public class or changing the values returned by a view.
_issued = {}


def require_guard(guard, *, runtime=None):
    issued = _issued.get(guard) if type(guard) is MutationGuard else None
    if (issued is None or issued.service.runtime is not issued.runtime
            or (runtime is not None and issued.runtime is not runtime)):
        raise Fenced('unsupported_start_guard')
    return guard


class MutationGuard:
    __slots__ = ()

    def __init__(self, service, root, state, epoch, pid):
        # Construction does not issue authority. Keep the signature compatible
        # with historical callers, but only the claim registry can authorize it.
        pass

    def _issued(self):
        require_guard(self)
        return _issued[self]

    @property
    def service(self):
        return self._issued().service

    @property
    def root(self):
        return deepcopy(self._issued().root)

    @property
    def state(self):
        return deepcopy(self._issued().state)

    @property
    def epoch(self):
        return self._issued().epoch

    @property
    def pid(self):
        return self._issued().pid

    def authorize(self, operation, owner, identity, nonce):
        issued = self._issued()
        # No locks survive this pre-I/O authorization. The mutation transaction
        # must call check() again, using the persisted payload and stage.
        with issued.runtime.database.connection() as c:
            root, state = self._checked(c)
            phases = {'create': 'queued', 'enroll': 'roles_frozen',
                      'confirm': 'planned', 'admit': 'confirmed'}
            payload = root['payload']
            if (operation not in phases or owner != root['owner_id']
                    or state['phase'] != phases[operation]
                    or nonce != payload['nonces'][operation]
                    or (operation == 'create' and (payload['kind'] != 'raw' or identity is not None))
                    or (operation != 'create' and identity != state['job_id'])):
                raise Fenced('unsupported_start_scope')

    def _checked(self, c, job=None, *, authority=True):
        issued = self._issued()
        s = issued.service
        root = s._root(c, issued.root['owner_id'], issued.root['id'], lock=True)
        current = s._state(c, root)
        if current != issued.state or current['phase'] in TERMINALS:
            raise Fenced('start_stage_changed')
        epoch = s._epoch(c, root)
        live = c.execute(
            "SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=%s "
            "AND classid=%s::oid AND objid=(hashtext(%s)::bigint & 4294967295)::oid "
            "AND objsubid=2 AND granted", (issued.pid, LOCK_NAMESPACE, root['id'])
        ).fetchone()
        if not live or epoch != {'epoch': issued.epoch, 'pid': issued.pid} or s.stopping.is_set():
            raise Fenced('start_owner_lost')
        if authority:
            s._authority(c, root, current, job)
        return root, current

    def check(self, c, job=None, *, authority=True):
        return self._checked(c, job, authority=authority)[1]

    def finish(self, c, phase, **data):
        root, state = self._checked(c, authority=False)
        allowed = {'queued': 'created' if root['payload']['kind'] == 'raw' else 'roles_frozen',
                   'created': 'roles_frozen', 'roles_frozen': 'enrolled',
                   'enrolled': 'planned', 'planned': 'confirmed', 'confirmed': 'admitted'}
        if phase != allowed.get(state['phase']) and phase not in TERMINALS - {'admitted'}:
            raise Fenced('unsupported_start_scope')
        if phase not in TERMINALS or phase == 'admitted':
            self.service._authority(c, root, state)
        self.service._append(c, root, state, phase, **data)


class StartRequests:
    def __init__(self, runtime, *, selection_plan=None, capabilities=(), enabled=True):
        self.runtime = runtime
        self.selection_plan = selection_plan
        self.capabilities = tuple(sorted(set(capabilities)))
        if set(self.capabilities) - {'transcription', 'translation', 'vocalization'}:
            raise ValueError('unsupported_start_capability')
        self.enabled = enabled
        self.factory = None
        self.stopping = threading.Event()
        self.cursor = None

    def _write(self, c, owner, rid, kind, payload, identity=None):
        c.execute('INSERT INTO message_outbox(id,owner_id,aggregate_id,message_type,payload) '
                  'VALUES(%s,%s,%s,%s,%s)',
                  (identity or uuid4().hex, owner, rid, kind, Jsonb(payload)))

    def _root(self, c, owner, rid, *, lock=False):
        row = c.execute('SELECT * FROM message_outbox WHERE owner_id=%s AND id=%s '
                        'AND message_type=%s' + (' FOR UPDATE' if lock else ''),
                        (owner, resource_id(rid), REQUESTED)).fetchone()
        if not row:
            raise Missing('start_request_missing')
        return row

    def _state(self, c, root):
        row = c.execute('SELECT payload FROM message_outbox WHERE owner_id=%s '
                        'AND aggregate_id=%s AND message_type IN (%s,%s) '
                        "ORDER BY (payload->>'seq')::int DESC LIMIT 1",
                        (root['owner_id'], root['id'], STAGE, TERMINAL)).fetchone()
        return row['payload'] if row else {'seq': 0, 'phase': 'queued',
                    'job_id': root['payload'].get('job_id'),
                    'scope': root['payload'].get('scope')}

    def _epoch(self, c, root):
        row = c.execute('SELECT payload FROM message_outbox WHERE owner_id=%s '
                        'AND aggregate_id=%s AND message_type=%s '
                        "ORDER BY (payload->>'epoch')::int DESC LIMIT 1",
                        (root['owner_id'], root['id'], EPOCH)).fetchone()
        return row['payload'] if row else {'epoch': 0, 'pid': None}

    def _append(self, c, root, previous, phase, **data):
        value = {**previous, **data, 'seq': previous['seq'] + 1, 'phase': phase}
        self._write(c, root['owner_id'], root['id'],
                    TERMINAL if phase in TERMINALS else STAGE, value,
                    digest({'start': root['id'], 'seq': value['seq']})[:32])
        return value

    def _project(self, root, state):
        phase = state['phase']
        state_name = phase if phase in TERMINALS | {'queued'} else 'preparing'
        status = {'id': root['id'], 'state': state_name}
        if state.get('code') in CODES:
            status['code'] = state['code']
        return {**status, 'job_id': state.get('job_id'), 'start_request': status}

    def _lookup_nonce(self, c, owner, nonce):
        return c.execute('SELECT * FROM message_outbox WHERE owner_id=%s AND message_type=%s '
                         "AND payload->>'nonce'=%s", (owner, REQUESTED, nonce)).fetchone()

    def _anchors(self, c, owner, body, *, lock=False):
        asset = self.runtime._shared_asset(c, body['asset_id'])
        workflow_owner, definition = self.runtime._job_definition(
            c, owner, body['definition_id'], body['definition_revision'])
        if lock:
            # 005/032 make source identity immutable and prohibit deletion.
            # Native SELECT+INSERT cannot row-lock assets. Availability is a
            # fresh logical check (not a claim of serializing library removal);
            # retained CAS bytes and identity cannot change after this read.
            # Owner/workflow/intent locks still fence mutable start authority.
            c.execute('SELECT id FROM workflows WHERE owner_id=%s AND id=%s FOR SHARE',
                      (workflow_owner, body['definition_id'])).fetchone()
            c.execute('SELECT id FROM accounts WHERE id=%s FOR SHARE', (workflow_owner,)).fetchone()
            # Re-read after locking so a change during initial reads is not accepted.
            asset = self.runtime._shared_asset(c, body['asset_id'])
            workflow_owner, definition = self.runtime._job_definition(
                c, owner, body['definition_id'], body['definition_revision'])
        accepted = {}
        selectors = body['options'].get('accepted_inputs', {})
        if type(selectors) is not dict or set(selectors) - {'audio', 'transcript'}:
            raise ValueError('invalid_start_inputs')
        for port, selector in sorted(selectors.items()):
            if (type(selector) is not dict or set(selector) != {'job_id', 'run_id', 'port'}
                    or selector['port'] != port):
                raise ValueError('invalid_start_inputs')
            source_job = self.runtime._shared_job(c, resource_id(selector['job_id']))
            if lock:
                c.execute('SELECT id FROM jobs WHERE owner_id=%s AND id=%s FOR SHARE',
                          (source_job['owner_id'], source_job['id'])).fetchone()
                source_job = self.runtime._shared_job(c, selector['job_id'])
            run = c.execute('SELECT id,status,result,request_sha256 FROM node_runs '
                'WHERE owner_id=%s AND job_id=%s AND id=%s' + (' FOR SHARE' if lock else ''),
                (source_job['owner_id'], source_job['id'], resource_id(selector['run_id']))).fetchone()
            if (source_job['status'] != 'completed' or source_job.get('library_removed_at')
                    or not run or run['status'] != 'completed'):
                raise Fenced('scope_changed')
            accepted[port] = {'job': _scope(source_job), 'owner': source_job['owner_id'],
                              'run': digest(run)}
        return {'asset': digest(public_asset(asset)), 'definition': digest(definition),
                'workflow_owner': workflow_owner, 'accepted_inputs': accepted}

    def _authority(self, c, root, state, job=None):
        p, owner = root['payload'], root['owner_id']
        if _account(c, owner, lock=True) != p['actor_role']:
            raise Fenced('scope_changed')
        now = c.execute('SELECT clock_timestamp() AS value').fetchone()['value']
        if now >= datetime.fromisoformat(p['deadline']):
            raise Fenced('intent_expired')
        if tuple(p['capabilities']) != self.capabilities or not self.enabled:
            raise Fenced('scope_changed')
        if p['kind'] == 'raw' and self._anchors(c, owner, p['body'], lock=True) != p['anchors']:
            raise Fenced('scope_changed')
        if job is not None:
            from video_service.postgres.job_processing_review import JobProcessingReview
            if (state.get('scope') != _scope(job) or job['status'] != 'draft'
                    or job['cancel_requested'] or job['active_claim_id']
                    or job.get('library_removed_at')
                    or JobProcessingReview.blocked_in(c, owner, job['id'])
                    or self.runtime._runs(c, owner, job['id'])):
                raise Fenced('scope_changed')

    def _submit(self, owner, nonce, scope, kind, body=None, job_id=None, revision=None):
        request_id(nonce)
        fingerprint = digest(scope)
        with self.runtime.database.connection() as c:
            _account(c, owner)
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                      ('start-intake:' + owner + ':' + nonce,))
            prior = self._lookup_nonce(c, owner, nonce)
            if prior:
                if prior['payload']['fingerprint'] != fingerprint:
                    raise Conflict('start_request_changed')
                result = self._project(prior, self._state(c, prior))
            else:
                if not self.enabled:
                    raise Conflict('start_disabled')
                role = _account(c, owner, lock=True)
                payload = {'version': 1, 'kind': kind, 'nonce': nonce,
                           'fingerprint': fingerprint, 'actor_role': role,
                           'capabilities': list(self.capabilities),
                           'deadline': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}
                if kind == 'raw':
                    payload.update(body=body, anchors=self._anchors(c, owner, body, lock=True))
                else:
                    job = self.runtime._job(c, owner, job_id, lock=True)
                    if job['revision'] != revision:
                        raise Conflict('scope_changed')
                    payload.update(job_id=job_id, scope=_scope(job),
                        paid_authorized=bool(job['snapshot'].get('translation_paid_authorized')))
                    root = {'owner_id': owner, 'payload': payload}
                    self._authority(c, root, {'scope': _scope(job)}, job)
                rid = uuid4().hex
                payload['nonces'] = {stage: digest({'start_request': rid, 'stage': stage})
                                     for stage in ('create', 'enroll', 'confirm', 'admit')}
                self._write(c, owner, rid, REQUESTED, payload, rid)
                root = self._root(c, owner, rid)
                result = self._project(root, self._state(c, root))
        return {'id': job_id if kind == 'saved' else result['id'],
                'job_id': result['job_id'], 'start_request': result['start_request']}

    def submit_raw(self, owner, body):
        from video_service.timed_subtitles import MAX_INPUT_OPTIONS_BYTES
        if (set(body) != {'asset_id', 'definition_id', 'definition_revision',
                         'options', 'recovery_enabled', 'request_id', 'token', 'paid_confirmed'}
                or body['recovery_enabled'] is not False
                or type(body['options']) is not dict
                or len(canonical(body['options'])) > MAX_INPUT_OPTIONS_BYTES
                or type(body['paid_confirmed']) is not bool):
            raise ValueError('invalid_start_request')
        resource_id(body['asset_id']); resource_id(body['definition_id'])
        if (type(body['definition_revision']) is not int or body['definition_revision'] < 1
                or not isinstance(body['token'], str) or len(body['token']) != 64
                or any(ch not in '0123456789abcdef' for ch in body['token'])):
            raise ValueError('invalid_start_request')
        return self._submit(owner, body['request_id'], body, 'raw', body=body)

    def submit_saved(self, owner, job_id, revision, nonce):
        resource_id(job_id)
        if type(revision) is not int or revision < 1:
            raise ValueError('invalid_start_revision')
        return self._submit(owner, nonce, {'job': job_id, 'revision': revision},
                            'saved', job_id=job_id, revision=revision)

    def get(self, owner, rid):
        with self.runtime.database.connection() as c:
            c.execute('SET TRANSACTION READ ONLY')
            _account(c, owner)
            root = self._root(c, owner, rid)
            return self._project(root, self._state(c, root))

    def by_nonce(self, owner, nonce):
        request_id(nonce)
        with self.runtime.database.connection() as c:
            c.execute('SET TRANSACTION READ ONLY')
            _account(c, owner)
            root = self._lookup_nonce(c, owner, nonce)
            if not root:
                raise Missing('start_request_missing')
            return self._project(root, self._state(c, root))

    def list(self, owner):
        with self.runtime.database.connection() as c:
            c.execute('SET TRANSACTION READ ONLY')
            _account(c, owner)
            roots = c.execute('SELECT r.* FROM message_outbox r WHERE r.owner_id=%s AND r.message_type=%s '
                'AND NOT EXISTS(SELECT 1 FROM message_outbox t WHERE t.owner_id=r.owner_id '
                'AND t.aggregate_id=r.id AND t.message_type=%s AND t.payload->>\'phase\'=\'admitted\') '
                'ORDER BY r.created_at DESC,r.id DESC LIMIT 100', (owner, REQUESTED, TERMINAL)).fetchall()
            return {'requests': [p for r in roots
                    if (p := self._project(r, self._state(c, r)))['state'] != 'admitted']}

    def for_job(self, owner, job_id):
        with self.runtime.database.connection() as c:
            c.execute('SET TRANSACTION READ ONLY')
            _account(c, owner)
            self.runtime._job(c, owner, job_id)
            root = c.execute('SELECT r.* FROM message_outbox r WHERE r.owner_id=%s '
                'AND r.message_type=%s AND (r.payload->>\'job_id\'=%s OR EXISTS '
                '(SELECT 1 FROM message_outbox s WHERE s.owner_id=r.owner_id AND s.aggregate_id=r.id '
                'AND s.message_type IN (%s,%s) AND s.payload->>\'job_id\'=%s)) '
                'ORDER BY r.created_at DESC,r.id DESC LIMIT 1',
                (owner, REQUESTED, job_id, STAGE, TERMINAL, job_id)).fetchone()
            return {'id': job_id, 'job_id': job_id, 'start_request':
                    self._project(root, self._state(c, root))['start_request'] if root else None}

    def cancel(self, owner, rid):
        with self.runtime.database.connection() as c:
            _account(c, owner, lock=True)
            root = self._root(c, owner, rid, lock=True)
            state = self._state(c, root)
            admitted = self._matching_claim(c, root, state)
            if admitted and state['phase'] not in TERMINALS:
                state = self._append(c, root, state, 'admitted', claim_id=admitted)
            if state['phase'] == 'admitted':
                return self._project(root, state)
            if state['phase'] not in TERMINALS:
                state = self._append(c, root, state, 'cancelled', code='start_cancelled')
            return self._project(root, state)

    def _matching_claim(self, c, root, state):
        if state['phase'] != 'confirmed':
            return None
        # Root -> job is the guarded mutation order. Normal admission takes the
        # job lock too, so its claim cannot commit between this lookup and a
        # terminal append in the same transaction. Never hold this during I/O.
        c.execute('SELECT id FROM jobs WHERE owner_id=%s AND id=%s FOR UPDATE',
                  (root['owner_id'], state['job_id'])).fetchone()
        from video_service.start_queue_policy import claim_digest
        nonce = root['payload']['nonces']['admit']
        row = c.execute('SELECT * FROM execution_claims WHERE owner_id=%s AND request_id=%s',
                        (root['owner_id'], nonce)).fetchone()
        if not row:
            return None
        if (row['job_id'] != state['job_id'] or row['consent_id'] != state['consent_id']
                or row['generation'] != state['scope']['generation']
                or row['request_sha256'] != claim_digest(state['job_id'], state['consent_id'])):
            raise Fenced('scope_changed')
        return row['id']

    @contextmanager
    def claim(self, owner, rid):
        with self.runtime.database.connection() as session:
            locked = session.execute('SELECT pg_try_advisory_lock(%s,hashtext(%s)) AS ok',
                                     (LOCK_NAMESPACE, rid)).fetchone()['ok']
            session.commit()
            if not locked:
                yield None
                return
            guard = None
            try:
                pid = session.info.backend_pid
                with self.runtime.database.connection() as c:
                    root = self._root(c, owner, rid, lock=True)
                    state = self._state(c, root)
                    if state['phase'] in TERMINALS or self.stopping.is_set():
                        guard = None
                    else:
                        epoch = self._epoch(c, root)['epoch'] + 1
                        self._write(c, owner, rid, EPOCH, {'epoch': epoch, 'pid': pid})
                        guard = MutationGuard(self, root, state, epoch, pid)
                        _issued[guard] = _Issued(self, self.runtime, deepcopy(root),
                                                deepcopy(state), epoch, pid)
                yield guard
            finally:
                if guard is not None:
                    _issued.pop(guard, None)
                if not session.closed:
                    session.execute('SELECT pg_advisory_unlock(%s,hashtext(%s))',
                                    (LOCK_NAMESPACE, rid))
                    session.commit()

    def _roles(self, job):
        from .model_roles import _supported_transcription
        chosen = []
        for role, kind in [('transcription', 'transcribe'), ('translation', 'translate'),
                           ('vocalization', 'vocalize')]:
            nodes = [n for n in job['snapshot']['definition']['nodes'] if n['type'] == kind]
            if (role in self.capabilities and nodes and all(n.get('model_ref') for n in nodes)
                    and (role != 'transcription' or all(_supported_transcription(job['snapshot'], n) for n in nodes))):
                chosen.append(role)
        return chosen

    def _step(self, g):
        p, s = g.root['payload'], g.state
        owner, rid = g.root['owner_id'], g.root['id']
        nonce = p['nonces'].__getitem__
        if s['phase'] == 'queued' and p['kind'] == 'raw':
            if self.selection_plan is None:
                raise Fenced('scope_changed')
            plan = self.selection_plan(owner, p['body'])
            if plan['token'] != p['body']['token'] or (plan['paid_roles'] and not p['body']['paid_confirmed']):
                raise Fenced('scope_changed')
            b = p['body']
            self.runtime.create(owner, b['asset_id'], b['definition_id'], b['definition_revision'],
                request_id=nonce('create'), options=b['options'], paid_confirmed=b['paid_confirmed'],
                input_plan_sha256=plan.get('input_bindings_sha256'), _start_guard=g)
        elif s['phase'] in {'queued', 'created'}:
            with self.runtime.database.connection() as c:
                g.check(c)
                job = self.runtime._job(c, owner, s['job_id'], lock=True)
                g.check(c, job)
                roles = self._roles(job)
                existing = c.execute('SELECT response FROM model_role_enrollments WHERE '
                    'owner_id=%s AND job_id=%s AND generation=%s AND snapshot_sha256=%s',
                    (owner, job['id'], job['generation'], job['snapshot_sha256'])).fetchone()
                if existing:
                    existing_roles = existing['response'].get('roles', [existing['response'].get('role')])
                    if sorted(existing_roles) != sorted(roles):
                        raise Fenced('scope_changed')
                    roles = []
                g.finish(c, 'roles_frozen', roles=roles)
        elif s['phase'] == 'roles_frozen':
            if s['roles']:
                from .model_roles import ModelRoleCoordinator
                ModelRoleCoordinator(self.runtime, self.factory).enroll_job(owner, s['job_id'],
                    s['scope']['revision'], nonce('enroll'), roles=s['roles'], _start_guard=g)
            else:
                with self.runtime.database.connection() as c:
                    g.check(c)
                    job = self.runtime._job(c, owner, s['job_id'], lock=True)
                    g.check(c, job)
                    g.finish(c, 'enrolled')
        elif s['phase'] == 'enrolled':
            plan = self.runtime.plan(owner, s['job_id'])
            if not plan['ready']:
                raise Fenced('start_blocked')
            with self.runtime.database.connection() as c:
                g.check(c)
                job = self.runtime._job(c, owner, s['job_id'], lock=True)
                g.check(c, job)
                if plan['paid_roles'] and not job['snapshot'].get('translation_paid_authorized'):
                    raise Fenced('start_blocked')
                g.finish(c, 'planned', plan_token=plan['token'])
        elif s['phase'] == 'planned':
            self.runtime.confirm(owner, s['job_id'], s['plan_token'], nonce('confirm'), _start_guard=g)
        elif s['phase'] == 'confirmed':
            self.runtime.admit(owner, s['job_id'], s['consent_id'], nonce('admit'), _start_guard=g)
        else:
            raise Fenced('scope_changed')

    def process(self, owner, rid):
        with self.claim(owner, rid) as guard:
            if guard is None:
                return
            try:
                with self.runtime.database.connection() as c:
                    guard.check(c, authority=False)
                    claim = self._matching_claim(c, guard.root, guard.state)
                    if claim:
                        self._append(c, guard.root, guard.state, 'admitted', claim_id=claim)
                        return
                    guard.check(c)
                self._step(guard)
            except Exception as exc:
                # A lost reply may follow a committed atomic mutation+receipt.
                # Never replace a newer stage/admission with an error or retry it.
                with self.runtime.database.connection() as c:
                    try:
                        guard.check(c, authority=False)
                    except Fenced:
                        return
                    root = self._root(c, owner, rid, lock=True)
                    state = self._state(c, root)
                    claim = self._matching_claim(c, root, state)
                    if claim:
                        # Reconciliation recognizes a committed exact claim; it
                        # does not renew authority, consent, or replay admission.
                        self._append(c, root, state, 'admitted', claim_id=claim)
                        return
                    code = str(exc) if isinstance(exc, Fenced) and str(exc) in CODES else (
                        'start_blocked' if isinstance(exc, (Conflict, Missing, PermissionError)) else
                        'validation_failed' if isinstance(exc, ValueError) else 'mutation_uncertain')
                    phase = 'expired' if code == 'intent_expired' else 'uncertain' if code == 'mutation_uncertain' else 'blocked'
                    guard.finish(c, phase, code=code)

    def tick(self, limit=16):
        if self.stopping.is_set() or not self.enabled:
            return
        with self.runtime.database.connection() as c:
            # Keyset traversal avoids an occupied oldest page starving newer work.
            rows = c.execute('SELECT r.owner_id,r.id FROM message_outbox r WHERE r.message_type=%s '
                'AND NOT EXISTS(SELECT 1 FROM message_outbox t WHERE t.owner_id=r.owner_id '
                'AND t.aggregate_id=r.id AND t.message_type=%s) AND r.id>%s ORDER BY r.id LIMIT %s',
                (REQUESTED, TERMINAL, self.cursor or '', min(max(limit, 1), 64))).fetchall()
        if not rows:
            self.cursor = None
            return
        for row in rows:
            if self.stopping.is_set():
                break
            self.cursor = row['id']
            try:
                self.process(row['owner_id'], row['id'])
            except Exception:
                logging.getLogger(__name__).warning('start_request_poll_unconfirmed')
