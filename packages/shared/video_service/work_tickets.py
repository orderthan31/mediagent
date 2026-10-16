"""New registry-bound product tickets; old ticket namespaces stay unchanged."""
from copy import deepcopy
from pathlib import Path
from .decision_tickets import DecisionTicketStore
from .review_tickets import ReviewTicketStore
from .parallel_workflow import compile_graph
from .parallel_scheduler import NodeFailure
from .workflow_graph import validate_graph
from .workflow_tickets import TicketConflict
from .model_registry import ModelRegistry, MODEL_ROLES, ModelUnavailable


def decision_descriptor(binding):
    return {'id':'registered-model:'+binding['model_id'],'revision':str(binding['revision']),'schema_version':1,'paid':True}


def compile_work(graph, options=None, routes=None):
    validation=validate_graph(graph)
    reasons=list(validation['issues'])
    if validation['valid']:
        for node in graph['nodes']:
            if node['type'] in MODEL_ROLES and 'model_ref' not in node:
                reasons.append({'node_id':node['id'],'edge_id':None,'message':'모델 사용 노드에 호환 등록 모델의 정확한 revision을 연결하세요.'})
    if reasons:
        return {'supported':False,'reasons':reasons,'steps':[],'paid_roles':[],'choices':{}}
    native=deepcopy(graph)
    for node in native['nodes']:
        node.pop('model_ref',None)
    result=compile_graph(native,(options or {}).get('branch_choices',{}),allow_review=True,allow_decision=True,decision_routes=routes)
    refs={n['id']:n['model_ref'] for n in graph['nodes'] if 'model_ref' in n}
    for step in result['steps']:
        if step['id'] in refs:
            step['model_ref']=deepcopy(refs[step['id']])
    result['notice']='저장 워크플로우와 노드별 고정 등록 모델을 사용합니다. 모델 없는 노드는 처리 옵션만 적용합니다. 계획 확인과 실제 실행은 별도입니다.'
    return result


class WorkTicketStore(DecisionTicketStore):
    execution_contract='work-v1'

    def __init__(self,root,owner=None):
        self.registry=ModelRegistry(root,owner)
        super().__init__(root,owner)
        self.directory=(Path(root)/'.workflow-work-tickets'/self.directory.name).resolve()

    def _compile_definition(self, graph, options):
        return compile_work(graph,options)

    def _execution_sequence(self, record):
        frozen=record.get('decisions',self._decisions(record))
        routes={node:row['selected_port'] for node,row in frozen.items() if row['status']=='succeeded'}
        graph={key:record['definition'][key] for key in ('catalog_version','revision','name','inputs','nodes','edges')}
        return compile_work(graph,record['options'],routes)

    def _save(self,record):
        if 'model_bindings' not in record:
            record['model_bindings']={n['id']:self.registry.resolve(n['model_ref'],n['type']) for n in record['definition']['nodes'] if 'model_ref' in n}
        for step in record['steps']:
            binding=record['model_bindings'].get(step['id'])
            if binding:
                step.setdefault('model_snapshot',deepcopy(binding))
                if step.get('serving_snapshot') is not None:
                    role=MODEL_ROLES[step['type']]
                    step['serving_snapshot'].update({role+'_provider':binding['provider'],role+'_model':binding['model'],role+'_fallback_model':'',
                                                      'fallback_on_error':False,'fallback_on_block':False})
        record.pop('model_availability',None)
        super()._save(record)

    def _admission(self, record, identity, *, active=True):
        node=next(n for n in record['definition']['nodes'] if n['id']==identity)
        current=self.registry.resolve(node['model_ref'],node['type'],require_active=active)
        if current!=record['model_bindings'][identity]:
            raise TicketConflict('고정 모델 snapshot/revision이 다릅니다. 새 정의·계획·티켓으로 분리하세요.')
        return current

    def get(self,identity):
        record=super().get(identity)
        record['model_availability']={}
        for node in record['definition']['nodes']:
            if 'model_ref' in node:
                self._admission(record,node['id'],active=False)
                record['model_availability'][node['id']]=self.registry.availability(node['model_ref'],node['type'])
        return record

    def _pending_models(self,record):
        states={n['id']:n['status'] for n in record['steps']}
        judged=record.get('decisions',self._decisions(record))
        return [n for n in self._execution_sequence(record)['steps'] if n['selected'] and n['id'] in record['model_bindings'] and states[n['id']] not in {'succeeded','failed','blocked','skipped'} and judged.get(n['id'],{}).get('status')!='succeeded']

    def _plan_extension(self,record):
        availability={}
        for node in self._pending_models(record):
            self._admission(record,node['id'],active=False)
            state=self.registry.availability(node['model_ref'],node['type'])
            availability[node['id']]={k:state[k] for k in ('model_id','revision','active','state_revision')}
        return {'registered_models':record['model_bindings'],'model_admission':availability,'decisions':self._decisions(record)}

    def plan(self,identity,preferences):
        result=ReviewTicketStore.plan(self,identity,preferences)
        record=self.get(identity)
        extension=self._plan_extension(record)
        roles=set(result['paid_roles'])
        if any(n['type']=='decision' and n['id'] in result['eligible_steps'] for n in self._pending_models(record)):
            roles.add('decision')
        return {**result,'paid_roles':sorted(roles),'model_bindings':record['model_bindings'],'model_availability':record['model_availability'],
                'decision_bindings':record['decisions'],'model_admission':extension['model_admission'],
                'notice':'노드별 고정 model_id/revision·미실행 경로·서빙·현재 사용 상태를 확인합니다. 사용 중지 모델 호출은 차단하고 독립/완료 결과는 보존합니다. 변경은 명시 모델 교체·새 정의·계획·티켓입니다. 등록/목록/키 보유는 실연결·추론 성공이 아닙니다.'}

    def _bound_preferences(self,record,bound,identity):
        binding=self._admission(record,identity)
        role=MODEL_ROLES[next(n['type'] for n in record['steps'] if n['id']==identity)]
        value=deepcopy(bound)
        value.update({role+'_provider':binding['provider'],role+'_model':binding['model'],role+'_fallback_model':'',
                      'fallback_on_error':False,'fallback_on_block':False,'model_binding':binding})
        value['api_keys']={binding['provider']:bound.get('api_keys',{}).get(binding['provider'],'')}
        value['api_key']=value['api_keys'].get('gemini','')
        return value

    def _make_executor(self,record,bound,factory,execution):
        # Each processing node receives its own bound configuration/provider instance.
        def local(identity):
            preferences=self._bound_preferences(record,bound,identity) if identity in record['model_bindings'] else deepcopy(bound)
            return factory(preferences,deepcopy(record['options']),deepcopy(execution),deepcopy(record['model_bindings']))
        def execute(step,inputs,work,check):
            return local(step['id'])(step,inputs,work,check)
        execute.decision_provider_for_node=lambda identity:getattr(local(identity),'decision_provider',None)
        return execute

    def _decision_profile(self,record,step,plan):
        return decision_descriptor(record['model_bindings'][step['id']])

    def _confirmed_decision_profile(self,plan,step):
        return decision_descriptor(plan['model_bindings'][step['id']])

    def _decision_provider(self,execute,record,step):
        return execute.decision_provider_for_node(step['id'])

    def _admit_decision(self,record,step):
        try:
            self._admission(record,step['id'])
        except ModelUnavailable as exc:
            raise NodeFailure({},exc) from None
