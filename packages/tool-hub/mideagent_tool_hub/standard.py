"""Optional agent-facing LangChain adapter. Never imported by CPU executables."""
from langchain_core.tools import StructuredTool
from pydantic import BaseModel
from mideagent_tool_hub.registry import allowed_definitions

def standard_tools(caller,executors):
    definitions=allowed_definitions(caller)
    allowed={d['id']for d in definitions}
    if set(executors)-allowed:raise PermissionError('tool_not_allowed')
    tools=[]
    for definition in definitions:
        if definition['id']not in executors:continue
        registered=executors[definition['id']]
        def execute(_registered=registered,**values):
            normalized={key:(value.model_dump(exclude_none=True)if isinstance(value,BaseModel)else value)for key,value in values.items()}
            return _registered(**normalized)
        tool=StructuredTool.from_function(func=execute,name=definition['id'].replace('.','_'),description=definition['name'],args_schema=definition['args_schema'],infer_schema=False,metadata={'tool_id':definition['id'],'executor':definition['executor'],'output_labels':definition['outputs']})
        tools.append(tool)
    return tools
