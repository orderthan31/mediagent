"""API-only enrichment must match the actual broker boot/ticket/attempt."""
from uuid import uuid4
from test_control_journal import actor,case
from video_service.postgres.remote_control import ControlledFleet


def test_managed_worker_ticket_metadata_is_bound_to_same_boot_and_attempt(actor):
    store,journal,group,contract,snapshot,request,command=case(actor)
    attempt=uuid4().hex;snapshot[0]['attempt_id']=attempt
    store.publish(group,contract,snapshot)
    worker={'worker_id':snapshot[0]['id'],'boot_id':snapshot[0]['boot_id'],'ticket_id':snapshot[0]['ticket_id'],'attempt_id':attempt,'ticket_number':42,'node_id':'encode-node','family':'cpu','role':'encode'}
    class Base:
        def get(self,agent):return {'observation_source':'amqp','workers':[worker]}
    fleet=ControlledFleet(Base(),store)
    assert fleet.get(group)['workers'][0]['ticket_number']==42
    assert fleet.get(group)['workers'][0]['attempt_id']==attempt
    worker['attempt_id']=uuid4().hex
    assert fleet.get(group)['workers'][0]['ticket_number'] is None
