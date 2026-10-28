"""Product metadata for the shared tool boundary. No worker activation on GET."""
from fastapi import Depends,HTTPException
from video_service.tool_hub import catalog,allowed_definitions,describe,tool_for_executor

# No fixed processor is manufactured into an autonomous agent registration.
AGENTS={}

def mount_tool_hub(app,administrator,database):
    def describe():
        with database.connection()as db:
            present=db.execute("SELECT to_regclass('agent_pool_roles') value").fetchone()['value']
            roles={r['role']for r in db.execute('SELECT role FROM agent_pool_roles WHERE enabled').fetchall()}if present else set()
        return [{**tool,'availability':'on_demand'if tool['executor']in roles else'unknown'}for tool in catalog()]
    @app.get('/api/tool-hub/tools')
    def tools(actor=Depends(administrator)):
        return {'tools':describe()}
    @app.get('/api/tool-hub/tools/{identity}')
    def tool(identity:str,actor=Depends(administrator)):
        found=next((item for item in describe()if item['id']==identity),None)
        if found is None:raise HTTPException(404,'툴을 찾을 수 없습니다.')
        return found
    @app.get('/api/tool-hub/executors/{identity}')
    def executor(identity:str,actor=Depends(administrator)):
        role={'transcribe':'transcription','translate':'translation','vocalize':'vocalization'}.get(identity,identity)
        tool_id=tool_for_executor(role)
        if tool_id is None:raise HTTPException(404,'실행기를 찾을 수 없습니다.')
        item=next(t for t in catalog()if t['id']==tool_id)
        caller=('model:'if item['requires_model']else'cpu:')+role
        return {'kind':'tool_executor','autonomous':False,'tools':[describe(d)for d in allowed_definitions(caller)]}
    @app.get('/api/agent-hub/agents')
    def agents(actor=Depends(administrator)):
        return {'agents':list(AGENTS.values())}
    @app.get('/api/agent-hub/agents/{identity}')
    def agent(identity:str,actor=Depends(administrator)):
        item=AGENTS.get(identity)
        if item is None:raise HTTPException(404,'에이전트를 찾을 수 없습니다.')
        return {**item,'tools':[t for t in catalog()if t['id']in item['allowed_tools']]}
