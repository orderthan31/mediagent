"""Actual mounted recovery and normal-run routes; fake providers/dispatch only."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.renewal_routes import mount_runtime
from video_service.postgres.unit_recovery import RoleUnitRecovery


def test_zero_call_confirmation_prepares_only_then_explicit_continue_adopts_and_dispatches_once(monkeypatch):
    events = []
    job = 'a' * 32
    run = 'b' * 32
    runtime = SimpleNamespace(
        store=object(), database=object(),
        accept_role_recovery=lambda *args: events.append(('adopt', args)) or {'id': job},
        get=lambda *args: {'id': job},
    )
    monkeypatch.setattr(RoleUnitRecovery, 'inspect', lambda *args: {'access': {'can_manage': True}})
    monkeypatch.setattr(RoleUnitRecovery, 'preview', lambda *args: {'ready': True, 'additional_call_limit': 0})
    def decide(self, owned, identity, attempt, body):
        assert owned == 'owner' and identity == job and attempt == run
        assert body['approve_calls'] is False
        events.append(('decide', body['decisions']))
        return {'recovery': {'additional_call_limit': 0}}
    monkeypatch.setattr(RoleUnitRecovery, 'decide', decide)
    monkeypatch.setattr(RoleUnitRecovery, 'execute', lambda *args: events.append(('execute_zero', args)) or {'recovery': {'can_continue': True}})
    monkeypatch.setattr('mideagent_orchestrator.agent_pool.AgentPool', lambda *args: SimpleNamespace(
        enroll=lambda *args: events.append(('enroll', args))))
    monkeypatch.setattr('mideagent_orchestrator.controller.BrokerController', lambda *args: SimpleNamespace(
        dispatch=lambda *args: events.append(('dispatch', args)) or {'id': job}))
    app = FastAPI()
    mount_runtime(app, runtime, lambda: {'user': {'id': 'owner'}}, lambda: None,
                  local_execution=True, broker_factory=object())
    base = f'/api/renewal/jobs/{job}/runs/{run}/unit-recovery'
    body = dict(job_revision=1, recovery_revision=0, context_sha256='c' * 64,
                decisions=[{'unit_index': 7, 'action': 'skip'}])
    with TestClient(app) as client:
        assert client.post(base + '/preview', json=body).status_code == 200
        response = client.post(base + '/decisions', json={**body, 'request_id': 'explicit-zero',
            'preview_sha256': 'd' * 64, 'approve_calls': False})
        assert response.status_code == 200, response.text
        assert client.post(base + '/execute', json={'request_id': 'explicit-zero'}).status_code == 200
        assert [event[0] for event in events] == ['decide', 'execute_zero']
        response = client.post(base + '/continue', json={'request_id':'explicit-zero'})
        assert response.status_code == 200, response.text
        assert [event[0] for event in events] == ['decide', 'execute_zero', 'adopt', 'enroll', 'dispatch']
        assert events[-1][1] == ('owner', job)
