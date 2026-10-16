"""Explicit WF08 approval for existing *positive* isolated API fixtures only.

Negative tests use raw TestClient.post and never receive this helper's consent.
No operating app, provider, Worker or pricing endpoint is accessed.
"""
from uuid import uuid4
from video_service.workflow_tickets import digest


def approved_post(client,path,*,json,headers=None):
    from app.api.execution_approval_routes import router
    if not getattr(client.app.state,'fixture_approval_routes',False):
        client.app.include_router(router);client.app.state.fixture_approval_routes=True
    cache=getattr(client,'_fixture_execution_approvals',{})
    key=digest({'path':path,'payload':json})
    if key not in cache:
        selection={'path':path,'payload':json}
        quoted=client.post('/api/execution-approvals/plan',json=selection)
        assert quoted.status_code==200,quoted.text
        grant=client.post('/api/execution-approvals/confirm',json={**selection,'token':quoted.json()['token'],'request_id':str(uuid4()),
                           'paid_confirmed':quoted.json()['cost']['state']=='may_charge','risk_confirmed':quoted.json().get('risk_required',False)})
        assert grant.status_code==200,grant.text
        cache[key]={'X-Execution-Approval':grant.json()['id'],'X-Execution-Request':json.get('request_id',str(uuid4()))}
        client._fixture_execution_approvals=cache
    return client.post(path,json=json,headers={**(headers or {}),**cache[key]})
