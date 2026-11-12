"""Durable goal decisions over verified tool receipts; no provider I/O or lifecycle authority."""
from copy import deepcopy
from video_service.renewal_contracts import spec
from video_service.object_store import validate_reference

class GoalAgent:
    kind = ""
    label = ""
    tool_order = ()
    primary = ""
    requires_parent = True
    option_roles = None
    output_ports = {"transcript": "transcript"}

    def __init__(self, node, *, tool_bindings=None, verify_references=False):
        self.node = deepcopy(node)
        self.identity = node["id"]
        self.bindings = tool_bindings or {}
        self.verify_references = verify_references
        self.tool_order = self.roles(node)

    @classmethod
    def roles(cls, node):
        return cls.tool_order

    def tool_id(self, role):
        return self.bindings.get(role, self.identity + "__" + role)

    def tool(self, role, defaults=None, *, model=False):
        configured = self.node.get("tool_settings", {}).get(role, {})
        options = {**(defaults or {}), **configured}
        if self.option_roles is None and role == self.primary:
            options.update(self.node.get("options", {}))
        elif self.option_roles is not None:
            options.update({k: v for k, v in self.node.get("options", {}).items()
                            if self.option_roles.get(k) == role})
        value = {"id":self.tool_id(role), "type":role,
                 "position":{"x":0,"y":0}, "options":options}
        if model:
            for key in ("model_ref", "fallback_refs"):
                if key in self.node:
                    value[key] = deepcopy(self.node[key])
            value["options"]["model_source"] = "registered_api"
        return value

    def outputs(self, media):
        """Publish only this goal's declared results, never pass-through context."""
        owned = {self.tool_id(role) for role in self.tool_order}
        return {port: media[key] for port, key in self.output_ports.items()
                if key in media and media[key][0] in owned}

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
            receipt = run.get("result") or {}
            outputs = receipt.get("outputs", {}) if isinstance(receipt, dict) else {}
            if not isinstance(outputs, dict) or any(not isinstance(outputs.get(name), dict) or outputs[name].get("type") != kind for name,kind in expected.items()):
                return {"state":"failed", "tool":None,"reason":"완료된 도구 결과를 확인할 수 없습니다."}
            if self.verify_references:
                try:
                    for name in expected:
                        validate_reference(outputs[name])
                except ValueError:
                    return {"state":"failed", "tool":None,"reason":"완료된 도구 파일 참조가 유효하지 않습니다."}
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
