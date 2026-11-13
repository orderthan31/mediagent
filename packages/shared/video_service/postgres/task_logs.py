"""Task-bound console archive and status reads; no Docker authority or model calls."""
from . import Missing, Conflict
from .registry import resource_id

ERRORS = {
    'connection_failed': '모델 서버 연결에 실패했습니다. 주소와 통신 경로를 확인하세요.',
    'outcome_unknown': '모델 요청 오류: 응답 여부를 확인하지 못했습니다. 자동으로 다시 요청하지 않습니다.',
    'model_reply_unknown': '모델 요청 오류: 응답 여부를 확인하지 못해 처리가 멈췄습니다.',
    'authentication_failed': '모델 연결 인증이 거부됐습니다.',
    'request_rejected': '모델이 요청을 거부했습니다.',
    'rate_limited': '모델 요청 한도에 도달했습니다.',
    'upstream_failure': '모델 서버에서 오류가 발생했습니다.',
    'invalid_response': '모델 응답 형식이 맞지 않습니다.',
    'invalid_timed_transcription': '전사 응답의 시간 정보가 맞지 않습니다.',
    'call_budget_below_required_chunks': '필요한 구간 수가 설정된 요청 상한을 넘었습니다.',
}

def stamp(value):
    return value.isoformat() if hasattr(value, 'isoformat') else value

def candidate_width(role):
    value = (role or {}).get('candidate_count')
    return value if type(value) is int and value > 0 else 1


# Sidecars are produced only by a completed prepare tool, never console text.
# Kept separate from native JSONL so arbitrary stdout cannot establish a plan.
_PREPARE_TOOLS = {'transcription': 'speech.prepare_audio',
                  'translation': 'text.prepare_batches'}
_PROGRESS_LIMIT = 1024


def _plan_directory(root):
    """Open every directory component without following symlinks (also on races)."""
    import os
    from pathlib import Path
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', flags)
    try:
        for part in Path(os.path.abspath(root)).parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_recorded_plan(task_id, role, *, root=None):
    """Bounded metadata-only read. Missing/legacy/unsafe data stays unknown."""
    import json
    import os
    import stat
    from ..task_console import _identity
    try:
        _identity(task_id)
        expected = _PREPARE_TOOLS.get(role)
        folder = root or os.environ.get('MIDEAGENT_TASK_CONSOLE_ROOT')
        if expected is None or not folder:
            return None
        directory = _plan_directory(folder)
        try:
            fd = os.open(task_id + '.progress.json',
                         os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > _PROGRESS_LIMIT:
                return None
            raw = stream.read(_PROGRESS_LIMIT + 1)
        if len(raw) > _PROGRESS_LIMIT:
            return None
        row = json.loads(raw)
        if (type(row) is not dict or set(row) !=
                {'version', 'task_id', 'role', 'tool_id', 'planned_segments'}):
            return None
        if (type(row['version']) is not int or row['version'] != 1
                or row['task_id'] != task_id or row['role'] != role
                or row['tool_id'] != expected
                or type(row['planned_segments']) is not int
                or not 0 <= row['planned_segments'] < 2**31):
            return None
        return row
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def planned_segments(role):
    """Only the frozen ASR PCM clock establishes a plan; never read media here."""
    task = (role or {}).get('task')
    if not isinstance(task, dict) or task.get('role') != 'transcription':
        return None
    if (role or {}).get('role') != 'transcription':
        return None
    chunk_frames = task.get('chunk_frames')
    if type(chunk_frames) is not int or not 0 < chunk_frames <= 960000:
        return None
    from ..packed_projection import validate_projection_clock
    try:
        frames = round(validate_projection_clock(
            task.get('timeline'), policy='packed_projection_v5') * 16000)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        return None
    return (frames + chunk_frames - 1) // chunk_frames


def project_progress(run, role, calls):
    """Partition observed segments, not the budget or unattempted planned work.

    Success wins. Failure requires every frozen candidate to have failed.
    Unresolved includes unknown outcomes, interrupted intents and incomplete
    fallback chains without an active intent. Finished means completed + failed.
    """
    width = candidate_width(role)
    groups = {}
    for call in calls:
        segment, candidate = divmod(call['chunk_index'], width)
        groups.setdefault(segment + 1, {})[candidate] = call['status']
    live = (run['status'] in {'running', 'waiting'}
            and (role or {}).get('phase') in {'sending', 'sent'}
            and (run.get('dispatch') or {}).get('phase') not in
            {'unknown', 'held', 'failed', 'cancelled', 'completed'})
    completed = failed = unresolved = 0
    active = []
    for number, candidates in sorted(groups.items()):
        statuses = set(candidates.values())
        if 'completed' in statuses:
            completed += 1
        elif len(candidates) == width and statuses == {'failed'}:
            failed += 1
        elif live and 'started' in statuses and 'unknown' not in statuses:
            active.append(number)
        else:
            unresolved += 1
    planned = planned_segments(role)
    if planned is None and role:
        recorded = read_recorded_plan(role.get('task_id'), role.get('role'))
        if recorded is not None:
            planned = recorded['planned_segments']
    return {'planned_segments': planned,
            'completed_segments': completed, 'failed_segments': failed,
            'active_segments': active, 'unresolved_segments': unresolved,
            'observed_segments': len(groups), 'total_calls': len(calls),
            'finished_segments': completed + failed}


def project_logs(run, role, calls, *, display_limit=None):
    entries = []
    def add(at, level, message):
        entries.append({'at': stamp(at), 'level': level, 'message': message})
    if run.get('started_at'):
        add(run['started_at'], 'info', '태스크 처리를 시작했습니다.')
    if role and role.get('created_at'):
        add(role['created_at'], 'info', '모델 처리 작업을 전달할 준비를 마쳤습니다.')
    for call in calls if display_limit is None else calls[-display_limit:]:
        role_name = role.get('role') if role else None
        role_name = role_name or {'transcribe':'transcription','translate':'translation'}.get(run['node_type'])
        candidates = candidate_width(role)
        number = call['chunk_index'] // candidates + 1
        label = f'구간 {number}' if role_name in {'transcription','translation'} else f'모델 요청 {call["chunk_index"] + 1}'
        if candidates > 1:
            label += f' · 후보 {call["chunk_index"] % candidates + 1}'
        add(call['created_at'], 'info', label+' 모델 요청을 기록했습니다.')
        if call['status'] == 'completed':
            add(None, 'info', label+' 모델 응답을 확인했습니다.')
        elif call['status'] in {'failed', 'unknown'}:
            add(None, 'warning' if call['status']=='unknown' else 'error',
                label+': '+ERRORS.get(call.get('error_code'), '모델 처리 오류가 기록됐습니다.'))
    state = run['status']
    if role and role['phase'] in {'held', 'unknown'}:
        state = 'failed' if calls and any(c['status']=='failed' for c in calls) and not any(c['status']in {'unknown','started'} for c in calls) else 'held'
        add(role.get('received_at'), 'warning', ERRORS.get(role.get('held_reason'), '응답이나 처리 결과를 확인할 수 없어 보류했습니다.'))
    elif role and role['phase']=='cancelled':
        state='cancelled'
        add(role.get('received_at'), 'info', '취소 결과를 확인했습니다.')
    if run.get('error_code'):
        add(run.get('completed_at'), 'error', ERRORS.get(run['error_code'], '태스크 처리 오류가 기록됐습니다.'))
    if run.get('completed_at') and run['status']=='completed':
        add(run['completed_at'], 'info', '태스크 결과를 저장했습니다.')
    # A model response timestamp is not stored in every older call row. Leave it absent rather than inventing it.
    entries.sort(key=lambda e: (e['at'] is None, e['at'] or ''))
    dispatch_phase=(run.get('dispatch')or{}).get('phase')
    display_state='failed' if state=='held' else state
    if state not in {'completed','cancelled'} and (dispatch_phase in {'unknown','held','failed'} or any(c['status']=='unknown' for c in calls)):
        display_state='failed'
    elif state in {'running','waiting'} and (dispatch_phase in {'pending','sending','sent'} or role and role['phase'] in {'ready','sending'}):
        display_state='preparing'
    return {'run_id':run['id'], 'node_id':run['node_id'], 'state':state,
            'display_state':display_state,
            'received_responses':sum(c['status']=='completed' for c in calls),
            'progress':project_progress(run,role,calls), 'entries':entries}

class TaskLogs:
    def __init__(self, runtime):
        self.database=runtime.database

    def get(self, actor, identity, run_id):
        resource_id(identity); resource_id(run_id)
        with self.database.connection() as db:
            db.execute('SET TRANSACTION READ ONLY')
            jobs=db.execute('SELECT owner_id,id FROM jobs WHERE id=%s LIMIT 2',(identity,)).fetchall()
            if not jobs:
                raise Missing('작업을 찾을 수 없습니다.')
            if len(jobs)!=1:
                raise Conflict('작업 식별자가 중복됩니다.')
            owner=jobs[0]['owner_id']
            run=db.execute('SELECT id,node_id,node_type,status,error_code,started_at,completed_at FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s',(owner,identity,run_id)).fetchone()
            if not run:
                raise Missing('이 작업의 태스크를 찾을 수 없습니다.')
            from mideagent_orchestrator.dispatch_queue import DispatchQueue
            run=DispatchQueue.decorate_in(db,[run])[0]
            present=db.execute("SELECT to_regclass('model_role_tasks') value").fetchone()['value']
            role=None; calls=[]
            if present:
                role=db.execute("""SELECT m.task_id,m.phase,m.held_reason,m.created_at,m.used_calls,m.envelope->>'role' role,m.envelope->'task' task,jsonb_array_length(m.frozen_candidates) candidate_count,
                     m.result_message->>'status' result_status,
                     (SELECT min(received_at) FROM message_inbox i WHERE i.payload_sha256=m.result_sha256) received_at
                     FROM model_role_tasks m WHERE m.owner_id=%s AND m.job_id=%s AND m.attempt_id=%s""",(owner,identity,run_id)).fetchone()
                if role:
                    # One full metadata read keeps counts consistent with one another,
                    # including successes/unknown outcomes outside the display window.
                    calls=db.execute('SELECT chunk_index,status,error_code,created_at FROM model_role_tool_calls WHERE task_id=%s ORDER BY chunk_index',(role['task_id'],)).fetchall()
        from ..task_console import read_console
        # Only authoritative DB role/run metadata selects the private policy.
        # Legacy private archives have no trustworthy body provenance.
        if role is not None or run['node_type'] in {
                'transcribe', 'translate', 'vocalize',
                'transcription_agent', 'translation_agent'}:
            from ..private_task_console import read_private_console
            read_console = read_private_console
        total=len(calls)
        shown=min(total,200)
        return {**project_logs(run,role,calls,display_limit=200),'console':read_console(run_id),'shown_calls':shown,'total_calls':total,'has_more':total>shown}


def decorate_status_in(db,job,runs):
    result=[dict(r) for r in runs]
    for run in result:
        if run['status'] not in {'completed','cancelled'} and (run.get('dispatch')or{}).get('phase') in {'unknown','held','failed'}:
            run['display_status']='failed'
            run['display_reason']='실행 요청 전달을 확인하지 못했습니다. 자동으로 다시 보내지 않습니다.'
    if db.execute("SELECT to_regclass('model_role_tasks') value").fetchone()['value']:
        roles=db.execute('SELECT task_id,attempt_id,phase,held_reason FROM model_role_tasks WHERE owner_id=%s AND job_id=%s',(job['owner_id'],job['id'])).fetchall()
        for role in roles:
            run=next((r for r in result if r['id']==role['attempt_id']),None)
            if run is None:continue
            calls=db.execute('SELECT chunk_index,status,error_code,created_at FROM model_role_tool_calls WHERE task_id=%s ORDER BY chunk_index',(role['task_id'],)).fetchall()
            projected=project_logs(run,role,calls)
            if projected['display_state']!=run['status']:run['display_status']=projected['display_state']
            reason=next((c['error_code']for c in calls if c.get('error_code')in ERRORS),role.get('held_reason'))
            if projected['display_state']=='failed':run['display_reason']=ERRORS.get(reason,'처리 오류로 멈췄습니다.')
    active=[r for r in result if r.get('generation')==job['generation']]
    state=job['status']
    if state in {'running','waiting'}:
        if any(r.get('display_status')=='held'for r in active):state='held'
        elif any(r.get('display_status',r['status'])=='failed'for r in active):state='failed'
    return result,state
