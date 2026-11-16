"""Bounded job-wide captured evidence and explicitly labelled failure ledger reads.

No lifecycle projection, Docker access, media access, or execution. Authentication
is owned by the route; job lookup uses the same cross-owner shared-read contract.
Archive I/O happens only after the read-only DB snapshot has closed.
"""
import datetime
import hashlib
import json
import re

from . import Conflict, Missing
from .registry import resource_id
from .task_logs import ERRORS, candidate_width
from ..diagnostic_codes import safe_code
from ..private_task_console import read_private_console, _safe_diagnostic, WITHHELD
from ..task_console import read_console

MAX_RUNS = 64
MAX_CALLS = 2000
ARCHIVE_BYTES = 128 * 1024  # at most 8 MiB across the run window
MAX_RECORDS = 1000
PRIVATE_NODES = {'transcribe', 'translate', 'vocalize', 'transcription_agent', 'translation_agent'}


def timestamp(value):
    if isinstance(value, datetime.datetime):
        value = value.isoformat()
    if type(value) is not str or len(value) > 40:
        return None
    try:
        return value if datetime.datetime.fromisoformat(value).tzinfo is not None else None
    except ValueError:
        return None


def captured_records(run, console):
    private = console.get('content_policy') == 'private_diagnostics_v1'
    for index, line in enumerate(console['lines']):
        text = line['text']
        row = {'id': run['id'] + ':capture:' + str(index) + ':' + hashlib.sha256(
                   json.dumps(line, sort_keys=True).encode()).hexdigest()[:16],
               'at': timestamp(line.get('at')), 'level': 'UNKNOWN', 'message': text,
               'run_id': run['id'], 'node_id': run['node_id'],
               'source': 'console', 'provenance': 'captured'}
        if private and text != WITHHELD and _safe_diagnostic(text):
            event = json.loads(text)
            row['source'] = 'diagnostic'
            row['level'] = event.get('level', 'UNKNOWN')  # never invent legacy severity
            location = event.get('tool_id', event.get('operation', event.get('kind')))
            row['message'] = f"{event['role']} · {location}: {event['state']}"
            for key in ('tool_id', 'unit_index', 'candidate_index', 'error_code', 'error_type', 'elapsed_ms'):
                if key in event:
                    row[key] = event[key]
            if event.get('error_code'):
                row['message'] += ' · ' + ERRORS.get(event['error_code'], event['error_code'])
            # Canonical private diagnostics are not stdout bodies; no raw field.
        elif not private:
            row['raw'] = text
            match = re.match(r'^\[?(INFO|WARNING|ERROR)\]?(?:[: \t])', text)
            if match:
                row['level'] = match[1]
        yield row


def stored_failures(run, role, calls):
    def record(suffix, code, unknown=False, **extra):
        safe = safe_code(code)
        fallback = ('처리 결과 불명 상태가 저장돼 있습니다.' if unknown else '처리 실패 상태가 저장돼 있습니다.')
        fallback += ' 발생 시각·원문은 기록되지 않았습니다.'
        return {'id': run['id'] + ':failure:' + suffix, 'at': None,
                'level': 'WARNING' if unknown else 'ERROR',
                'message': ERRORS.get(safe or '', fallback),
                'run_id': run['id'], 'node_id': run['node_id'],
                'source': 'stored_failure', 'provenance': 'recorded_state',
                **({'error_code': safe} if safe else {}), **extra}
    for call in calls:
        if call['status'] not in {'failed', 'unknown'}:
            continue
        unit, candidate = divmod(call['chunk_index'], candidate_width(role))
        yield record('call:' + str(call['chunk_index']), call.get('error_code'),
                     call['status'] == 'unknown', unit_index=unit, candidate_index=candidate)
    if run.get('error_code') or run.get('status') == 'failed':
        yield record('run', run.get('error_code'))
    if role and role.get('phase') in {'held', 'unknown'}:
        yield record('role', role.get('held_reason'), True)


class JobLogs:
    def __init__(self, runtime):
        self.database = runtime.database

    def get(self, actor, identity):
        resource_id(identity)
        snapshots = []
        calls_remaining = MAX_CALLS
        clipped = False
        with self.database.connection() as db:
            db.execute('SET TRANSACTION READ ONLY')
            jobs = db.execute('SELECT owner_id,id FROM jobs WHERE id=%s LIMIT 2', (identity,)).fetchall()
            if not jobs:
                raise Missing('작업을 찾을 수 없습니다.')
            if len(jobs) != 1:
                raise Conflict('작업 식별자가 중복됩니다.')
            owner = jobs[0]['owner_id']
            runs = db.execute('''SELECT id,node_id,node_type,status,error_code,started_at,completed_at
                FROM node_runs WHERE owner_id=%s AND job_id=%s
                ORDER BY generation DESC,attempt DESC,started_at DESC NULLS LAST,id LIMIT %s''',
                (owner, identity, MAX_RUNS + 1)).fetchall()
            clipped = len(runs) > MAX_RUNS
            present = db.execute("SELECT to_regclass('model_role_tasks') value").fetchone()['value']
            for run in runs[:MAX_RUNS]:
                role = None
                calls = []
                calls_clipped = False
                if present:
                    role = db.execute('''SELECT task_id,phase,held_reason,
                        envelope->>'role' role,jsonb_array_length(frozen_candidates) candidate_count
                        FROM model_role_tasks WHERE owner_id=%s AND job_id=%s AND attempt_id=%s''',
                        (owner, identity, run['id'])).fetchone()
                    if role:
                        calls = db.execute('''SELECT chunk_index,status,error_code FROM model_role_tool_calls
                            WHERE task_id=%s AND status IN ('failed','unknown')
                            ORDER BY chunk_index DESC LIMIT %s''',
                            (role['task_id'], calls_remaining + 1)).fetchall()
                        calls_clipped = len(calls) > calls_remaining
                        calls = calls[:calls_remaining]
                        calls_remaining -= len(calls)
                snapshots.append((run, role, calls, calls_clipped))
        # No DB connection/transaction/lock is held while touching the archive.
        records, sources = [], []
        for run, role, calls, calls_clipped in snapshots:
            private = role is not None or run['node_type'] in PRIVATE_NODES
            reader = read_private_console if private else read_console
            try:
                console = reader(run['id'], limit=ARCHIVE_BYTES)
            except (OSError, ValueError):
                console = {'available': False, 'truncated': False, 'lines': []}
            policy = 'private_diagnostics_v1' if private else 'redacted_console'
            source = {'run_id': run['id'], 'node_id': run['node_id'],
                      'available': console['available'],
                      'raw_available': console['available'] and not private and bool(console['lines']),
                      'policy': policy, 'truncated': console['truncated'] or calls_clipped}
            sources.append(source)
            records.extend(captured_records(run, console))
            records.extend(stored_failures(run, role, calls))
            clipped = clipped or source['truncated']
        total = len(records)
        # Prefer recent captured evidence and retained failures. Unknown times stay unknown.
        records.sort(key=lambda row: (row['at'] is None, row['at'] or '', row['id']))
        shown = records[-MAX_RECORDS:]
        if total > len(shown):
            retained = {row['id'] for row in shown}
            omitted_runs = {row['run_id'] for row in records if row['id'] not in retained}
            for source in sources:
                source['truncated'] |= source['run_id'] in omitted_runs
            clipped = True
        return {'job_id': identity, 'records': shown, 'has_more': clipped,
                'truncated': clipped, 'sources': sources, 'total_records': total}
