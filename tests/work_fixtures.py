"""Actual registered store with controlled request transport, never inference."""
from pathlib import Path
from test_workflow_decision import decision_graph
from video_service.model_registry import ModelRegistry
from video_service.work_tickets import WorkTicketStore
from media_worker.registered_nodes import RegisteredDecisionProvider


class WorkHarness:
    def __init__(self, root, *, dual=False, source=None):
        self.root=Path(root);self.registry=ModelRegistry(root)
        self.registry.save('c'*32,{'revision':0,'name':'controlled registered model','provider':'openai','model':'gpt-4o-mini','uses':['decision']})
        self.graph=decision_graph();reference={'model_id':'c'*32,'revision':1}
        self.graph['nodes'][0]['model_ref']=reference.copy()
        if dual:
            for node in self.graph['nodes']:
                if node['id']=='gate':
                    node.update(type='decision',options={'data_type':'video'},model_ref=reference.copy())
            for edge in self.graph['edges']:
                if edge['source']['node']=='gate':
                    edge['source']['port']='a'
        self.source=Path(source) if source else self.root/'input.fixture'
        if source is None:
            self.source.write_bytes(b'controlled fixture input')
        self.asset={'asset_id':'b'*32,'size_bytes':self.source.stat().st_size,'source_mtime_ns':self.source.stat().st_mtime_ns}
        self.store=WorkTicketStore(root)
        self.ticket=self.store.create('controlled-create',{'definition_id':self.graph['id'],'definition_revision':1,'asset_id':'b'*32,'options':{}},lambda:self.graph,lambda:self.asset)
        self.preferences={'revision':0,'api_keys':{}}
        self.native=[];self.calls=[];self.sequence=0

    def factory(self,bound,options,admitted,bindings):
        def execute(step,inputs,work,check):
            self.native.append(step['id']);result={}
            for port in step['outputs']:
                path=work/(port+'.fixture');path.write_text('{}');result[port]=path
            return result
        def transport(provider,model,key,context):
            self.calls.append({'provider':provider,'model':model,'binding':bound['model_binding']})
            return {'version':1,'label':'pass','confidence':.9,'reason':'controlled JSON request transport, NOT live inference'}
        execute.decision_provider=RegisteredDecisionProvider(bound,paid_allowed=True,transport=transport) if bound.get('decision_model') else None
        return execute

    def confirm(self):
        current=self.store.get(self.ticket['id']);plan=self.store.plan(current['id'],self.preferences)
        return self.store.confirm(current['id'],current['revision'],plan['token'],bool(plan['paid_roles']),self.preferences),plan

    def run(self, operation='start', confirmed=None, plan=None):
        if confirmed is None:
            confirmed,plan=self.confirm()
        self.sequence+=1
        return self.store.run(self.ticket['id'],self.preferences,self.source,self.factory,request_id='run-'+str(self.sequence),revision=confirmed['revision'],token=plan['token'],operation=operation)

    def stop(self):
        current=self.registry.get('c'*32)
        return self.registry.set_active('c'*32,current['revision'],False)
