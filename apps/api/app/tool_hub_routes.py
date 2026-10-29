"""Protected goal-agent and tool reads. No activation or role-state filesystem access."""
from fastapi import Depends, HTTPException
from video_service.tool_hub import catalog, allowed_definitions, describe as describe_definition, tool_for_executor
from video_service.task_agents import AGENTS, registration


def project_execution(row):
    phase, node = row['phase'], row['node_status']
    if phase == 'accepted' and node == 'completed':
        status = 'completed'
    elif row['cancel_requested'] or phase == 'cancelled' or node == 'cancelled':
        status = 'cancelled'
    elif phase in {'held', 'unknown'} or node in {'failed', 'held'}:
        status = 'held'
    elif node == 'running' and not row['lease_valid']:
        status = 'unknown'
    elif phase in {'ready', 'sending'}:
        status = 'preparing'
    elif row['lease_valid'] and phase in {'sent', 'adopting'}:
        status = 'processing'
    else:
        status = 'unknown'
    return {key: row[key] for key in ['task_id', 'job_id', 'ticket_number', 'completed_calls', 'created_at', 'completed_at']} | {'status': status}


def mount_tool_hub(app, administrator, database):
    def describe_tools():
        with database.connection() as db:
            present = db.execute("SELECT to_regclass('agent_pool_roles') value").fetchone()['value']
            roles = {r['role'] for r in db.execute('SELECT role FROM agent_pool_roles WHERE enabled').fetchall()} if present else set()
        return [{**tool, 'availability': 'on_demand' if tool['executor'] in roles else 'unknown'} for tool in catalog()]

    def describe_agent(identity):
        item = registration(identity)
        if item is None:
            raise HTTPException(404, '에이전트를 찾을 수 없습니다.')
        with database.connection() as db:
            policy = db.execute('SELECT enabled FROM agent_pool_roles WHERE role=%s', (item['role'],)).fetchone()
            pool = db.execute("SELECT count(*) FILTER(WHERE phase IN('ready','busy') AND observed_at>now()-interval '5 seconds') ready,count(*) FILTER(WHERE phase IN('reserved','creating','starting')) preparing,count(*) FILTER(WHERE phase IN('ready','busy') AND (observed_at IS NULL OR observed_at<=now()-interval '5 seconds')) stale FROM agent_pool_instances WHERE role=%s AND phase<>'removed'", (item['role'],)).fetchone()
            rows = db.execute("""SELECT m.task_id,m.job_id,j.ticket_number,m.phase,n.status node_status,
                (n.lease_expires_at>now()) IS TRUE lease_valid,j.cancel_requested,m.held_reason,m.created_at,n.completed_at,
                (SELECT count(*) FROM model_role_tool_calls c WHERE c.task_id=m.task_id AND c.status='completed') completed_calls
                FROM model_role_tasks m JOIN jobs j ON j.owner_id=m.owner_id AND j.id=m.job_id
                JOIN node_runs n ON n.owner_id=m.owner_id AND n.job_id=m.job_id AND n.id=m.attempt_id
                WHERE m.envelope->>'role'=%s ORDER BY m.created_at DESC,m.task_id DESC LIMIT 12""", (item['role'],)).fetchall()
        executions = [project_execution(row) for row in rows]
        active = [row for row in executions if row['status'] in {'preparing', 'processing'}]
        return {key: item[key] for key in ['id', 'name', 'goal', 'allowed_tools', 'model_driven_selection']} | {
            'kind': 'task_agent', 'autonomous': False,
            'availability': 'on_demand' if policy and policy['enabled'] else 'unknown',
            'status': 'processing' if any(row['status']=='processing' for row in active) else 'preparing' if active or pool['preparing'] else 'unknown' if pool['stale'] else 'ready' if pool['ready'] else 'idle',
            'instances': None if pool['stale'] else pool['ready'], 'executions': executions,
            'tools': [tool for tool in describe_tools() if tool['id'] in item['allowed_tools']],
        }

    @app.get('/api/tool-hub/tools')
    def tools(actor=Depends(administrator)):
        return {'tools': describe_tools()}

    @app.get('/api/tool-hub/tools/{identity}')
    def tool(identity: str, actor=Depends(administrator)):
        found = next((item for item in describe_tools() if item['id']==identity), None)
        if found is None:
            raise HTTPException(404, '툴을 찾을 수 없습니다.')
        return found

    @app.get('/api/tool-hub/executors/{identity}')
    def executor(identity: str, actor=Depends(administrator)):
        goal = registration(identity)
        role = goal['role'] if goal else {'vocalize':'vocalization'}.get(identity,identity)
        tool_id = tool_for_executor(role)
        if tool_id is None:
            raise HTTPException(404, '실행기를 찾을 수 없습니다.')
        item = next(t for t in catalog() if t['id']==tool_id)
        caller = 'agent:'+goal['id'] if goal else ('model:' if item['requires_model'] else 'cpu:')+role
        return {'kind':'task_agent' if goal else 'tool_executor', 'agent_id':goal['id'] if goal else None, 'autonomous':False,
                'tools':[describe_definition(d) for d in allowed_definitions(caller)]}

    @app.get('/api/agent-hub/agents')
    def agents(actor=Depends(administrator)):
        return {'agents':[describe_agent(identity) for identity in AGENTS]}

    @app.get('/api/agent-hub/agents/{identity}')
    def agent(identity: str, actor=Depends(administrator)):
        return describe_agent(identity)
