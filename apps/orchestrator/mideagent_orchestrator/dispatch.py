"""Explicit application-side dispatcher for newly enrolled encode attempts only.

No Docker/socket authority, queue declaration, historical job scan or retry of an
already-published/unknown attempt. Private TCP bootstrap is deployment-specific.
"""
import argparse
import json
import logging
import signal
import threading


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bootstrap-file', required=True)
    parser.add_argument('--tool', '--agent', dest='tool', required=True, choices=['encode'])
    parser.add_argument('--enable-broker', action='store_true')
    parser.add_argument('--enable-dispatch', action='store_true')
    parser.add_argument('--enable-agent-pool',action='store_true')
    args = parser.parse_args()
    if not args.enable_broker or not args.enable_dispatch:
        parser.error('Explicit broker and dispatch opt-ins are required')
    logging.getLogger('pika').disabled = True
    try:
        from video_service.bootstrap import load_bootstrap
        from mideagent_orchestrator.bootstrap import runtime_components
        from video_service.postgres import Database
        from mideagent_orchestrator.execution import Execution
        from mideagent_orchestrator.dispatch_queue import DispatchQueue
        from mideagent_orchestrator.controller import BrokerController
        config, dsn = load_bootstrap(args.bootstrap_file)
        db = Database(dsn)
        store, _, factory = runtime_components(db,config,enable_broker=True,enable_registered=args.enable_agent_pool,enable_nonpaid=args.enable_agent_pool and 'nonpaid_model_config_file'in config)
        runtime = Execution(db,store,translation_runtime=getattr(factory,'translation_runtime',None),transcription_runtime=getattr(factory,'transcription_runtime',None),vocalization_runtime=getattr(factory,'vocalization_runtime',None),engine_runtime_enabled=bool(getattr(factory,'engine_factory',None)))
        controller = BrokerController(runtime, factory)
        queue = DispatchQueue(runtime)
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        while not stop.is_set():
            queue.tick(controller, agent=args.tool)
            if args.enable_agent_pool:
                from mideagent_orchestrator.agent_pool import AgentPool
                AgentPool(runtime).tick(controller)
            stop.wait(.25)
    except Exception:
        print(json.dumps({'status': 'failed', 'code': 'encode_dispatch_stopped'}), flush=True)
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
