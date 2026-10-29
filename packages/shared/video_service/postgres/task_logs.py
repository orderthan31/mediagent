"""Public task logs from durable facts; no container logs, secrets, model calls or writes."""
from . import Missing, Conflict
from .registry import resource_id

ERRORS = {
    'outcome_unknown': '모델 응답 여부를 확인하지 못했습니다. 자동으로 다시 요청하지 않습니다.',
    'model_reply_unknown': '모델 응답 여부를 확인하지 못해 처리를 보류했습니다.',
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

def project_logs(run, role, calls):
    entries = []
    def add(at, level, message):
        entries.append({'at': stamp(at), 'level': level, 'message': message})
    if run.get('started_at'):
        add(run['started_at'], 'info', '태스크 처리를 시작했습니다.')
    if role and role.get('created_at'):
        add(role['created_at'], 'info', '모델 처리 작업을 전달할 준비를 마쳤습니다.')
    for call in calls:
        role_name = role.get('role') if role else None
        role_name = role_name or {'transcribe':'transcription','translate':'translation'}.get(run['node_type'])
        candidates = max(1, (role or {}).get('candidate_count') or 1)
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
        state = 'held'
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
    return {'run_id':run['id'], 'node_id':run['node_id'], 'state':state,
            'received_responses':sum(c['status']=='completed' for c in calls), 'entries':entries}

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
            present=db.execute("SELECT to_regclass('model_role_tasks') value").fetchone()['value']
            role=None; calls=[]; total=0
            if present:
                role=db.execute("""SELECT m.task_id,m.phase,m.held_reason,m.created_at,m.used_calls,m.envelope->>'role' role,jsonb_array_length(m.frozen_candidates) candidate_count,
                     m.result_message->>'status' result_status,
                     (SELECT min(received_at) FROM message_inbox i WHERE i.payload_sha256=m.result_sha256) received_at
                     FROM model_role_tasks m WHERE m.owner_id=%s AND m.job_id=%s AND m.attempt_id=%s""",(owner,identity,run_id)).fetchone()
                if role:
                    total=db.execute('SELECT count(*) n FROM model_role_tool_calls WHERE task_id=%s',(role['task_id'],)).fetchone()['n']
                    calls=db.execute('SELECT chunk_index,status,error_code,created_at FROM model_role_tool_calls WHERE task_id=%s ORDER BY chunk_index DESC LIMIT 200',(role['task_id'],)).fetchall()[::-1]
        return {**project_logs(run,role,calls),'shown_calls':len(calls),'total_calls':total,'has_more':total>len(calls)}
