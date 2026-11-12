"""Frozen publication policy for new goal snapshots; no storage or lifecycle I/O."""


def output_stage(snapshot, node_id, port):
    pair = {"node": node_id, "port": port}
    if snapshot.get("agent_output_policy") == 1:
        published = any(pair == binding for outputs in snapshot.get("agent_output_bindings", {}).values()
                        for binding in outputs.values())
        return "final" if published else "intermediate"
    # Historical manifests retain their original consumption-based classification.
    used = any(edge["source"] == pair for edge in snapshot["definition"]["edges"])
    return "intermediate" if used else "final"
