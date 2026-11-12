"""Read-only DTO projection over synthetic rows, without importing an API/DB."""
import ast
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('phase', [None, 'pending', 'sending', 'sent', 'received', 'unknown'])
def test_list_projects_existing_status_without_claims_or_progress_invention(phase):
    path = ROOT / 'apps/api/app/renewal_routes.py'
    method = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == 'ledger')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    job = {
        'id': 'a' * 32, 'ticket_number': 32, 'status': 'waiting', 'display_status': 'waiting',
        'execution_state': None, 'active_claim_id': 'PRIVATE CLAIM',
        'asset_id': 'b' * 32, 'workflow_id': 'c' * 32, 'workflow_revision': 1, 'created_at': '2026-01-01',
        'snapshot': {'asset': {'original_filename': 'literal name.mp4', 'size_bytes': 42}, 'definition': {'name': 'literal saved workflow', 'nodes': []}},
        'runs': [] if phase is None else [{'status': 'running', 'dispatch': {'phase': phase, 'worker_id': 'PRIVATE WORKER'}}],
    }
    before = deepcopy(job)
    result = namespace['ledger'](job)
    assert result['metadata']['raw_status'] == result['metadata']['display_status'] == 'waiting'
    assert result['metadata']['dispatch_phase'] == phase
    assert result['metadata']['execution_state'] is None
    assert result['status'] == 'QUEUED' and result['ticket_number'] == '32'
    assert result['original_filename'] == 'literal name.mp4'
    assert result['metadata']['workflow']['name'] == 'literal saved workflow'
    assert job == before and 'PRIVATE' not in str(result)
    job['runs'].append({'status': 'completed', 'dispatch': {'phase': 'unknown'}})
    assert namespace['ledger'](job)['metadata']['dispatch_phase'] == phase
