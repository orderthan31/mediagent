"""Durable goal decisions over verified tool receipts; no provider I/O or lifecycle authority."""
from copy import deepcopy
from video_service.renewal_contracts import spec

class GoalAgent:
    kind = ""
    label = ""
    tool_order = ()
    primary = ""

    def __init__(self, node, *, tool_bindings=None):
        self.node = deepcopy(node)
        self.identity = node["id"]
        self.bindings = tool_bindings or {}

    def tool_id(self, role):
        return self.bindings.get(role, self.identity + "__" + role)

    def tool(self, role, defaults=None, *, model=False):
        configured = self.node.get("tool_settings", {}).get(role, {})
        options = {**(defaults or {}), **configured}
        if role == self.primary:
            options.update(self.node.get("options", {}))
        value = {"id":self.tool_id(role), "type":role,
                 "position":{"x":0,"y":0}, "options":options}
        if model:
            for key in ("model_ref", "fallback_refs"):
                if key in self.node:
                    value[key] = deepcopy(self.node[key])
            value["options"]["model_source"] = "registered_api"
        return value

    def next_tool(self, indexed, definition):
        """The agent, not the outer workflow, selects its next native tool.

        Existing active/failed/ambiguous attempts are never adopted or retried.
        A completed receipt must publish the tool's contracted output references.
        """
        nodes = {n["id"]:n for n in definition["nodes"]}
        for role in self.tool_order:
            identity = self.tool_id(role)
            run = indexed.get(identity)
            if run is None:
                return {"state":"ready", "tool":identity}
            state = run.get("display_status", run["status"])
            if state != "completed":
                return {"state":"failed" if state in {"failed","held","unknown","blocked","quarantined"} else state,
                        "tool":None, "reason":run.get("display_reason") or run.get("error_code")}
            expected = spec(role, nodes[identity]["options"])["outputs"]
            outputs = (run.get("result") or {}).get("outputs", {})
            if any(name not in outputs or outputs[name].get("type") != kind for name,kind in expected.items()):
                return {"state":"failed", "tool":None,"reason":"완료된 도구 결과를 확인할 수 없습니다."}
        return {"state":"completed", "tool":None}

    def advance(self, indexed, definition, invoke):
        """Invoke only the tool selected by this goal using the bound native adapter.

        The adapter owns transport/capacity mechanics, not this agent's tool flow.
        No call is made while an attempt is running, failed or outcome-unknown.
        """
        decision = self.next_tool(indexed, definition)
        if decision["state"] != "ready" or decision["tool"] is None:
            return None
        return invoke(decision["tool"])

    def publication(self):
        return self.tool_id(self.primary)
