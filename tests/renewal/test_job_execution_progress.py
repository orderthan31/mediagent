"""Job cards receive the same authoritative counts as the task log endpoint."""
from copy import deepcopy

from video_service.postgres.task_logs import decorate_status_in
from mideagent_orchestrator.execution import Execution


def role():
    return {'task_id': 'b' * 32, 'attempt_id': 'a' * 32, 'phase': 'held',
            'held_reason': 'role_checkpoint_held', 'role': 'transcription',
            'candidate_count': 1, 'task': {'role': 'transcription', 'chunk_frames': 960000,
                'max_calls': 128, 'timeline': [{'source_start': 0, 'source_end': 5715.136,
                    'packed_start': 0, 'packed_end': 5715.136}],
                'models': [{'credential_ref': 'DO-NOT-EXPOSE-PRIVATE'}]}}


class Rows:
    def __init__(self, rows): self.rows = rows
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows


class ReadDB:
    def __init__(self, mapping, calls): self.mapping, self.calls, self.queries = mapping, calls, []
    def execute(self, sql, args=()):
        self.queries.append(sql)
        if 'to_regclass' in sql: return Rows([{'value': True}])
        if 'FROM model_role_tasks' in sql: return Rows([self.mapping])
        if 'FROM model_role_tool_calls' in sql: return Rows(self.calls)
        raise AssertionError(sql)


def test_job_card_gets_95_success_1_failed_of_96_not_the_128_call_budget():
    mapping = role()
    calls = [{'chunk_index': i, 'status': 'failed' if i == 7 else 'completed',
              'error_code': 'invalid_response' if i == 7 else None, 'created_at': None} for i in range(96)]
    db = ReadDB(mapping, calls)
    original = {'id': 'a' * 32, 'node_id': 'speech__transcribe', 'node_type': 'transcribe',
                'status': 'running', 'generation': 1}
    runs, status = decorate_status_in(db, {'owner_id': 'owner', 'id': 'job', 'generation': 1, 'status': 'running'}, [original])
    assert status == 'failed'
    p = runs[0]['progress']
    assert p['planned_segments'] == 96 and p['completed_segments'] == 95 and p['failed_segments'] == 1
    assert p['finished_segments'] == 96 and p['active_segments'] == []
    assert 'DO-NOT-EXPOSE' not in str(p) and 'progress' not in original
    assert all(not any(word in sql.upper() for word in ['INSERT ', 'UPDATE ', 'DELETE ']) for sql in db.queries)
    assert len(db.queries) == 3  # reuse the status reader, no extra per-node HTTP/SQL loop
    assert 'envelope' in db.queries[1] and 'candidate_count' in db.queries[1]


def test_public_job_preserves_safe_progress_but_not_raw_task_credentials():
    p = {'planned_segments': 96, 'completed_segments': 95, 'failed_segments': 1,
         'active_segments': [], 'finished_segments': 96, 'unresolved_segments': 0,
         'observed_segments': 96, 'total_calls': 96}
    source = {'owner_id': 'owner', 'snapshot': {}, 'runs': [{'id': 'a' * 32, 'progress': p,
              'envelope': role(), 'frozen_candidates': [{'secret': 'DO-NOT-EXPOSE'}]}]}
    saved = deepcopy(source)
    for actor in ['owner', 'reader']:
        public = Execution._shared_view(source, actor)
        assert public['runs'][0]['progress'] == p
        assert 'DO-NOT-EXPOSE' not in str(public)
        assert public['access']['can_manage'] == (actor == 'owner')
    assert source == saved
