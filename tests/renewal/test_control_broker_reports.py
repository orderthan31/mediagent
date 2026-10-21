"""Controller observes bound broker reports, never substitutes process liveness."""
import importlib
from uuid import uuid4
import pytest
from test_control_journal import actor, case
from video_service.agent_control import ControlError
from video_service.postgres.worker_telemetry import WorkerTelemetry
from video_service.worker_telemetry import WorkerReporter, exchange


def reports(store,snapshot,*,second_role='encode'):
    sink=WorkerTelemetry(store.database);sink.beat()
    for index,row in enumerate(snapshot):
        role=second_role if index else 'encode'
        sender=lambda report,sink=sink,role=role:sink.accept(report,exchange('cpu',role),expected_worker_id=report['worker_id'])
        WorkerReporter(row['id'],'cpu',role,sender).emit('ready')


def reader_type():
    module=importlib.import_module('video_service.durable_control')
    assert hasattr(module,'BrokerReports'),'bound broker report reader missing'
    return module.BrokerReports


def test_reader_uses_authenticated_ids_and_collector_health(actor):
    cls=reader_type();store,journal,group,contract,snapshot,request,command=case(actor)
    reports(store,snapshot)
    reader=cls(store.database,{group:('cpu','encode')})
    observed=reader.read(group,[r['id'] for r in snapshot])
    assert set(observed)=={r['id'] for r in snapshot}
    assert all(r['state']=='ready' for r in observed.values())
    with store.database.connection() as db:db.execute("UPDATE telemetry_observer SET received_at=now()-interval '60 seconds'")
    with pytest.raises(ControlError,match='broker_observer_unavailable'):reader.read(group,[r['id'] for r in snapshot])


def test_reader_rejects_a_different_role_reusing_a_slot_id(actor):
    cls=reader_type();store,journal,group,contract,snapshot,request,command=case(actor)
    reports(store,snapshot,second_role='validate_video')
    with pytest.raises(ControlError,match='broker_worker_identity_mismatch'):
        cls(store.database,{group:('cpu','encode')}).read(group,[r['id'] for r in snapshot])
