"""Role-local standard Tool evidence. Does not change call intent/budget state."""
import hashlib,json

def record(state,task,index,tool,source):
    schema=tool.get_input_schema().model_json_schema()
    sha=hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest()
    with state.connect()as db:
        db.execute("CREATE TABLE IF NOT EXISTS standard_tool_calls(task TEXT NOT NULL,idx INTEGER NOT NULL,tool_name TEXT NOT NULL,input_schema_sha256 TEXT NOT NULL,source_sha256 TEXT NOT NULL,PRIMARY KEY(task,idx))")
        db.execute("INSERT OR IGNORE INTO standard_tool_calls(task,idx,tool_name,input_schema_sha256,source_sha256)VALUES(?,?,?,?,?)",(task,index,tool.name,sha,source['sha256']))
