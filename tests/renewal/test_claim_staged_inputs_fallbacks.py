"""Explicit conservative fallback and optional closure boundaries."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from test_claim_cold_gate import admin, db, movie, prepared, observe, counts
from test_claim_staged_inputs import audio_ready
from test_execution import graph
from video_service.canonical import canonical
from video_service.object_store import ObjectIntegrityError


def test_full_control_chain_with_active_sibling_reaches_one_external_command(db, admin, movie, tmp_path, monkeypatch):
    definition = graph('encode','select','validate_video')
    definition['nodes'][1]['options']={'data_type':'video','selection':'a'}
    definition['edges'][1]['source']={'node':'$input','port':'video'}
    definition['edges'][1]['target']['port']='value'
    definition['edges'][2]['source']['port']='a'
    runtime,owner,job,client=prepared(db,admin,movie,tmp_path,definition)
    observe(db)
    first=runtime.claim_next(owner,job['id'])
    assert first['agent']['id']=='encode'
    preflight=runtime._preflight_cpu_inputs
    called=[]
    def broad(*args,**kwargs):
        called.append(True)
        return preflight(*args,**kwargs)
    monkeypatch.setattr(runtime,'_preflight_cpu_inputs',broad)
    monkeypatch.setattr(runtime,'_stage_claim_candidate',lambda *args:pytest.fail('control closure must use full fallback'))
    second=runtime.claim_next(owner,job['id'])
    assert called==[True] and second['agent']['id']=='validate_video'
    with db.connection() as conn:
        rows=runtime._runs(conn,owner,job['id'])
    assert {r['node_id']:r['status'] for r in rows}=={'n0':'running','n1':'completed','n2':'running'}
    assert counts(db,job)==(3,2,0)
    assert runtime.claim_next(owner,job['id']) is None
    assert counts(db,job)==(3,2,0)


def test_review_keeps_full_sweep_and_no_external_command(db, admin, movie, tmp_path, monkeypatch):
    runtime,owner,job,client=prepared(db,admin,movie,tmp_path,graph('review','encode'))
    monkeypatch.setattr(runtime,'_stage_claim_candidate',lambda *args:pytest.fail('review closure must use full fallback'))
    assert runtime.claim_next(owner,job['id']) is None
    with db.connection() as conn:
        assert conn.execute('SELECT count(*) n FROM review_tasks WHERE job_id=%s',(job['id'],)).fetchone()['n']==1
    assert counts(db,job)==(1,0,0) and client.content_reads


@pytest.mark.parametrize('change',['clean','corrupt_optional','wrong_optional_type','cross_owner'])
def test_unit_selected_optional_reference_is_verified_not_dropped(db, admin, movie, tmp_path, monkeypatch, change):
    """Stage unit on a real frozen PG job; no injected candidate is inserted."""
    runtime,owner,job,client=audio_ready(db,admin,movie,tmp_path,monkeypatch)
    with db.connection() as conn:
        current=runtime._job(conn,owner,job['id'])
        runs=runtime._runs(conn,owner,job['id'])
    node=next(n for n in current['snapshot']['definition']['nodes'] if n['type']=='preprocess_audio')
    inputs=deepcopy(next(r['inputs'] for r in runs if r['node_type']=='preprocess_audio'))
    optional=runtime.store.put(owner,[canonical({'version':1,'protected':[],'removals':[]})],'audio_regions')
    key=runtime.store._key(owner,optional['storage_key'])
    if change=='corrupt_optional':
        raw=client.objects[key]['raw'];client.objects[key]['raw']=bytes([raw[0]^1])+raw[1:]
    elif change=='wrong_optional_type':
        optional={**optional,'type':'transcript'}
    elif change=='cross_owner':
        optional={**optional,'source_owner_id':'f'*32}
    inputs['regions']=optional
    # Only the actual stage method is under test; authority insertion remains private.
    from mideagent_orchestrator.execution import public
    candidate=canonical({'actor':owner,'job':public(current),'node':node,'inputs':inputs})
    client.calls.clear();client.byte_reads.clear()
    if change=='clean':
        _,command=runtime._stage_claim_candidate(candidate)
        assert json.loads(command)['inputs']['regions']==optional
        assert key in client.content_reads
    else:
        with pytest.raises((ValueError,KeyError,OSError)):
            runtime._stage_claim_candidate(candidate)
    # Stage-only units add nothing to the two CPU commands + acceptance events.
    assert counts(db,job)==(2,4,0)


def test_command_builder_extraction_preserves_deferred_pool_exclusion():
    import ast
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    source=ast.parse((root/'apps/orchestrator/mideagent_orchestrator/execution.py').read_text())
    cls=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='Execution')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_insert_run')
    predicate=next(n.value for n in method.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='deferred' for t in n.targets))
    expected=ast.parse("status == 'running' and node['type'] in getattr(self, 'defer_broker_agents', ()) and DispatchQueue.managed_in(db, node['type']) and not AgentPool.enrolled_in(db,job)",mode='eval').body
    assert ast.dump(predicate)==ast.dump(expected)
