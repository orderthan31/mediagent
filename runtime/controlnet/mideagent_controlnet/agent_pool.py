"""Orchestrator policy for a bounded on-demand role pool. No runtime authority."""

def decide(policy, instances, *, queued, inflight, now, available_memory):
    limit=policy['max_instances'];memory=policy['memory_bytes']
    if min(limit,memory,policy['idle_seconds'])<=0 or min(queued,inflight,available_memory)<0:
        raise ValueError('invalid_pool_policy_or_demand')
    live=[i for i in instances if i['phase']in {'creating','starting','ready','busy'}]
    wanted=min(limit,queued+inflight)
    start=min(max(0,wanted-len(live)),available_memory//memory)
    drain=[]
    if queued==0 and inflight==0:
        for item in live:
            completed=item.get('last_completed_at')
            since=completed if completed is not None else item.get('ready_at')
            if item['phase']=='ready' and since is not None and now-since>=policy['idle_seconds']:
                drain.append(item['id'])
    return {'start':start,'drain':drain}


def transient_observation(error):
    import json
    return isinstance(error,(OSError,json.JSONDecodeError))or str(error)=='native_engine_outcome_unknown'
