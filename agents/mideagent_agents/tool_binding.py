"""Role-local binding of allowed standard tools to the admitted task context."""
import hashlib
import json
from mideagent_tool_hub.standard import standard_tools
from mideagent_agents.tool_audit import record

def invoke(agent, task, identity, execute, *, index=0):
    reference = task['audio'] if agent.registration['role'] == 'transcription' else task['transcript']
    source = {'storage_key': 'blobs/'+reference['sha256'], 'sha256': reference['sha256'],
              'bytes': reference['bytes'], 'type': 'audio' if 'audio' in task else 'transcript'}
    def registered(source_reference):
        if source_reference != source:
            raise ValueError('bound_tool_input_changed')
        return execute()
    def bound(source):
        return registered(source)
    tool = standard_tools('agent:'+agent.registration['id'], {identity: bound})[0]
    result = tool.invoke({'source': source})
    schema = tool.get_input_schema().model_json_schema()
    sha = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
    with agent.state.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS agent_tool_steps(task TEXT NOT NULL,tool_id TEXT NOT NULL,idx INTEGER NOT NULL,tool_name TEXT NOT NULL,input_schema_sha256 TEXT NOT NULL,source_sha256 TEXT NOT NULL,completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(task,tool_id,idx))")
        db.execute('INSERT OR IGNORE INTO agent_tool_steps(task,tool_id,idx,tool_name,input_schema_sha256,source_sha256)VALUES(?,?,?,?,?,?)',
                   (task['task_id'],identity,index,tool.name,sha,source['sha256']))
    if identity in {'speech.transcribe','text.translate'}:
        record(agent.state,task['task_id'],index,tool,source)
    return result
