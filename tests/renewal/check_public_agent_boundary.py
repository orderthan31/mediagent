"""No job creation/provider/GPU: public graph vs agent-owned native transport boundary."""
from copy import deepcopy
from mideagent_orchestrator.execution import Execution
from mideagent_orchestrator.workflow import default_definition,compile_definition
from mideagent_orchestrator.agent_view import project_agents

def check_snapshot(snapshot):
 original=deepcopy(snapshot)
 job={"id":"1"*32,"owner_id":"2"*32,"snapshot":snapshot,"generation":1,"status":"draft","runs":[],"reviews":[]}
 job["agent_workflow"]=project_agents(job,[],[],[])
 public=Execution._shared_view(job,job["owner_id"])
 assert public["snapshot"]["definition"]["catalog_version"]==2,"public graph still exposes native tool transport"
 assert [n["type"]for n in public["snapshot"]["definition"]["nodes"]]==["transcription_agent","translation_agent","subtitle_video_agent"]
 assert public["snapshot"]["tool_definition"]==snapshot["definition"],"tool details lost their exact frozen native plan"
 assert public["agent_workflow"]["definition"]==public["snapshot"]["definition"]
 assert snapshot==original,"display serialization mutated the frozen original"
 # A client without observational agent_workflow must still never receive a native public graph.
 job["agent_workflow"]=None
 fallback=Execution._shared_view(job,job["owner_id"])
 assert fallback["snapshot"]["definition"]["catalog_version"]==2
 assert snapshot==original
 return public


def check_creation_handler(snapshot,route_source):
    SNAPSHOT=snapshot
    ROUTE_SOURCE=route_source

    import ast,copy,types
    from app.renewal_routes import Create
    from mideagent_orchestrator.execution import Execution
    from mideagent_orchestrator.agent_view import project_agents
    snapshot=SNAPSHOT
    job={"id":"1"*32,"owner_id":"2"*32,"snapshot":snapshot,"generation":1,"status":"draft","runs":[],"reviews":[]}
    job["agent_workflow"]=project_agents(job,[],[],[])
    called=[]
    class ReadOnlyCreationSpy:
     def create(self,*args,**kwargs):
      called.append((args,kwargs))
      return copy.deepcopy(job)
     _shared_view=staticmethod(Execution._shared_view)
    body=Create(asset_id="3"*32,definition_id=snapshot["agent_definition"]["id"],definition_revision=snapshot["agent_definition"]["revision"],options={"source_language":"auto","target_language":"ko"},request_id="offline-handler-only",token="a"*64,paid_confirmed=True)
    tree=ast.parse(ROUTE_SOURCE)
    mount=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=="mount_runtime")
    handler=copy.deepcopy(next(n for n in mount.body if isinstance(n,ast.FunctionDef)and n.name=="create"));handler.decorator_list=[];handler.args.defaults=[]
    space={"Create":Create,"runtime":ReadOnlyCreationSpy(),"broker_factory":None,"selection_plan":lambda owner,selection:{"paid_roles":[],"token":"a"*64},"Selection":__import__("app.renewal_routes",fromlist=["Selection"]).Selection}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[handler],type_ignores=[])),"actual-create-handler","exec"),space)
    result=space["create"](body,"2"*32)
    assert result["snapshot"]["definition"]["catalog_version"]==2
    assert len(result["snapshot"]["definition"]["nodes"])==3
    assert len(result["snapshot"]["tool_definition"]["nodes"])==8
    assert called[0][0][1:]==("3"*32,snapshot["agent_definition"]["id"],snapshot["agent_definition"]["revision"])
    assert called[0][1]["options"]==body.options
    assert snapshot==SNAPSHOT
    print("actual creation handler/input contract passed with persistence spy; no product creation, admission or dispatch")

def main(route_source=None):
 public=default_definition();public["id"]="4"*32;public["revision"]=2
 compiled=compile_definition(public)
 snapshot={**compiled,"asset":{},"options":{},"inputs":{}}
 check_snapshot(snapshot)
 if route_source is None:
  import inspect,app.renewal_routes
  route_source=inspect.getsource(app.renewal_routes)
 check_creation_handler(snapshot,route_source)
 print("public creation/detail graph: agents only; exact tool detail plan; immutable original")
if __name__=="__main__":main()
