"""Read-only log projection contracts: synthetic metadata, no DB/provider/media I/O."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from video_service.postgres.task_logs import TaskLogs, project_logs


def run(**changes):
    return dict(id='a' * 32, node_id='transcribe', node_type='transcribe',
                status='running', started_at=None, completed_at=None,
                error_code=None, **changes)


def role(width=1, phase='sent', name='transcription'):
    return {'task_id': 'b' * 32, 'role': name, 'phase': phase,
            'candidate_count': width, 'task': {
                'version': 2, 'role_policy_version': 2, 'role': name,
                'chunk_frames': 960000, 'max_calls': 128,
                'timeline': [{'source_start': 0, 'source_end': 5715.136,
                              'packed_start': 0, 'packed_end': 5715.136}],
                'models': [{'secret': 'DO-NOT-ECHO'}]}}


def call(index, status):
    return {'chunk_index': index, 'status': status, 'error_code': None,
            'created_at': None}


class ProgressProjectionTest(unittest.TestCase):
    def progress(self, mapping=None, calls=(), execution=None):
        return project_logs(execution or run(), mapping, list(calls))['progress']

    def test_asr_plan_is_96_not_budget_and_zero_calls_are_not_finished(self):
        mapping = role()
        before = deepcopy(mapping)
        self.assertEqual(self.progress(mapping), {
            'planned_segments': 96, 'completed_segments': 0, 'failed_segments': 0,
            'active_segments': [], 'unresolved_segments': 0, 'observed_segments': 0,
            'total_calls': 0, 'finished_segments': 0})
        mapping['task']['max_calls'] = 1
        self.assertEqual(self.progress(mapping)['planned_segments'], 96)
        mapping['task']['max_calls'] = 128
        self.assertEqual(mapping, before)
        self.assertNotIn('DO-NOT-ECHO', str(self.progress(mapping)))

    def test_missing_invalid_or_legacy_plan_is_null(self):
        for task in [None, {}, [], {'chunk_frames': 1},
                     {'chunk_frames': 0, 'timeline': []}]:
            with self.subTest(task=task):
                mapping = role(); mapping['task'] = task
                self.assertIsNone(self.progress(mapping)['planned_segments'])
        for value in [0, -1, True, 1.5, '960000', 960001]:
            with self.subTest(chunk_frames=value):
                mapping = role(); mapping['task']['chunk_frames'] = value
                self.assertIsNone(self.progress(mapping)['planned_segments'])
        for timeline in [None, [], {}, [{'packed_end': 60}],
                         [{'source_start': 0, 'source_end': 1,
                           'packed_start': 0, 'packed_end': float('nan')}],
                         [{'source_start': 0, 'source_end': 1,
                           'packed_start': 0.0000625, 'packed_end': 1.0000625}]]:
            with self.subTest(timeline=timeline):
                mapping = role(); mapping['task']['timeline'] = timeline
                self.assertIsNone(self.progress(mapping)['planned_segments'])
        self.assertIsNone(self.progress(None)['planned_segments'])

    def test_translation_and_vocalization_do_not_guess_from_budget_or_bytes(self):
        for name in ['translation', 'vocalization']:
            mapping = role(name=name)
            mapping['task']['audio'] = {'bytes': 3200000}
            self.assertIsNone(self.progress(mapping, [call(0, 'completed')])['planned_segments'])

    def test_candidate_fallback_groups_success_failure_and_pending(self):
        calls = [call(0, 'failed'), call(1, 'completed'),
                 call(2, 'failed'), call(3, 'started'),
                 call(4, 'failed'), call(5, 'failed'), call(6, 'failed')]
        self.assertEqual(self.progress(role(2), calls), {
            'planned_segments': 96, 'completed_segments': 1, 'failed_segments': 1,
            'active_segments': [2], 'unresolved_segments': 1, 'observed_segments': 4,
            'total_calls': 7, 'finished_segments': 2})
        self.assertEqual(self.progress(role(2), [call(1, 'failed')])['failed_segments'], 0)
        self.assertEqual(self.progress(role(2), [call(0, 'completed'), call(1, 'unknown')])['completed_segments'], 1)

    def test_unknown_is_unresolved_and_stopped_calls_never_stay_active(self):
        calls = [call(0, 'unknown'), call(1, 'started')]
        for phase in ['held', 'unknown', 'cancelled', 'completed']:
            with self.subTest(phase=phase):
                progress = self.progress(role(phase=phase), calls)
                self.assertEqual(progress['active_segments'], [])
                self.assertEqual(progress['unresolved_segments'], 2)
                self.assertEqual(progress['finished_segments'], 0)
        execution = run(); execution['status'] = 'cancelled'
        self.assertEqual(self.progress(role(), calls, execution)['unresolved_segments'], 2)
        execution = run(); execution['dispatch'] = {'phase': 'held'}
        self.assertEqual(self.progress(role(), calls, execution)['active_segments'], [])
        self.assertEqual(self.progress(role(), [call(0, 'unknown')])['active_segments'], [])

    def test_invalid_candidate_width_does_not_divide_by_zero(self):
        for width in [0, None, -1, True, 'two']:
            with self.subTest(width=width):
                progress = self.progress(role(width), [call(0, 'started')])
                self.assertEqual(progress['total_calls'], 1)
                self.assertEqual(progress['observed_segments'], 1)

    def test_sparse_calls_do_not_invent_observed_or_planned_segments(self):
        mapping = role(); mapping.pop('task')
        progress = self.progress(mapping, [call(0, 'completed'), call(100, 'started')])
        self.assertIsNone(progress['planned_segments'])
        self.assertEqual(progress['observed_segments'], 2)
        self.assertEqual(progress['active_segments'], [101])

    def test_single_pcm_frame_and_exact_chunk_boundary(self):
        for duration, expected in [(1 / 16000, 1), (60, 1), (60 + 1 / 16000, 2)]:
            mapping = role()
            mapping['task']['timeline'][0].update(source_end=duration, packed_end=duration)
            self.assertEqual(self.progress(mapping)['planned_segments'], expected)


class FakeDatabase:
    def __init__(self, calls):
        self.calls = calls
        self.queries = []

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        if sql.startswith('SET TRANSACTION READ ONLY'):
            rows = []
        elif 'FROM jobs ' in sql:
            rows = [{'owner_id': 'c' * 32, 'id': 'd' * 32}]
        elif 'FROM node_runs ' in sql:
            rows = [run()]
        elif 'FROM broker_dispatch_queue ' in sql:
            rows = []
        elif 'to_regclass' in sql:
            rows = [{'value': 'model_role_tasks'}]
        elif 'FROM model_role_tasks m ' in sql:
            rows = [role(2)]
        elif 'FROM model_role_tool_calls ' in sql:
            if 'count(*)' in sql:
                rows = [{'n': len(self.calls)}]
            else:
                rows = sorted(self.calls, key=lambda c: c['chunk_index'], reverse='DESC' in sql)
                if 'LIMIT 200' in sql:
                    rows = rows[:200]
        else:
            raise AssertionError('Unexpected SQL: ' + sql)
        return SimpleNamespace(fetchall=lambda: deepcopy(rows),
                               fetchone=lambda: deepcopy(rows[0]) if rows else None)


class ProgressReadTest(unittest.TestCase):
    def test_more_than_200_calls_use_global_totals_and_preserve_console(self):
        # The first segment's failed candidate and success are outside the display.
        calls = [call(0, 'failed'), call(1, 'completed')]
        calls += [call(i * 2, 'completed') for i in range(1, 202)]
        database = FakeDatabase(calls)
        native = {'lines': [{'at': '2026-11-13T12:00:00+00:00', 'stream': 'stdout',
                             'text': '[output body withheld]'}],
                  'available': True, 'truncated': False,
                  'content_policy': 'private_diagnostics_v1'}
        with patch('video_service.private_task_console.read_private_console', return_value=native) as read:
            value = TaskLogs(SimpleNamespace(database=database)).get(None, 'd' * 32, 'a' * 32)
        self.assertEqual(value['received_responses'], 202)
        self.assertEqual(value['progress']['completed_segments'], 202)
        self.assertEqual(value['progress']['observed_segments'], 202)
        self.assertEqual(value['progress']['total_calls'], 203)
        self.assertEqual(value['total_calls'], 203)
        self.assertEqual(value['shown_calls'], 200)
        self.assertTrue(value['has_more'])
        self.assertEqual(len(value['entries']), 400)
        self.assertFalse(any('구간 1 ' in row['message'] for row in value['entries']))
        self.assertEqual(value['console'], native)
        self.assertNotIn('[output body withheld]', str(value['entries']))
        self.assertNotIn('DO-NOT-ECHO', str(value))
        read.assert_called_once_with('a' * 32)
        self.assertTrue(all(sql.startswith(('SELECT', 'SET TRANSACTION READ ONLY'))
                            for sql, _ in database.queries))
        self.assertTrue(any("m.envelope->'task'" in sql for sql, _ in database.queries))

    def test_unknown_outside_display_window_still_affects_global_progress(self):
        calls = [call(0, 'unknown')] + [call(i * 2, 'completed') for i in range(1, 201)]
        with patch('video_service.private_task_console.read_private_console', return_value={}):
            value = TaskLogs(SimpleNamespace(database=FakeDatabase(calls))).get(None, 'd' * 32, 'a' * 32)
        self.assertEqual(value['display_state'], 'failed')
        self.assertEqual(value['progress']['unresolved_segments'], 1)
        self.assertEqual(value['progress']['completed_segments'], 200)
        self.assertEqual(value['progress']['observed_segments'], 201)
        self.assertEqual(value['shown_calls'], 200)
        self.assertTrue(value['has_more'])
        with patch('video_service.private_task_console.read_private_console', return_value={}):
            exact = TaskLogs(SimpleNamespace(database=FakeDatabase(calls[1:]))).get(None, 'd' * 32, 'a' * 32)
        self.assertEqual(exact['shown_calls'], 200)
        self.assertFalse(exact['has_more'])

    def test_zero_calls_has_no_phantom_display_rows(self):
        with patch('video_service.private_task_console.read_private_console', return_value={}):
            value = TaskLogs(SimpleNamespace(database=FakeDatabase([]))).get(None, 'd' * 32, 'a' * 32)
        self.assertEqual(value['shown_calls'], 0)
        self.assertEqual(value['total_calls'], 0)
        self.assertFalse(value['has_more'])
        self.assertEqual(value['entries'], [])
        self.assertEqual(value['progress']['planned_segments'], 96)


if __name__ == '__main__':
    unittest.main()
