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
    parser.add_argument('--agent', required=True, choices=['encode'])
    parser.add_argument('--enable-broker', action='store_true')
    parser.add_argument('--enable-dispatch', action='store_true')
    args = parser.parse_args()
    if not args.enable_broker or not args.enable_dispatch:
        parser.error('Explicit broker and dispatch opt-ins are required')
    logging.getLogger('pika').disabled = True
    try:
        from app.server import load_bootstrap
        from app.operator import runtime_components
        from video_service.postgres import Database
        from video_service.postgres.execution import Execution
        from video_service.postgres.dispatch_queue import DispatchQueue
        from video_service.rabbitmq_controller import BrokerController
        config, dsn = load_bootstrap(args.bootstrap_file)
        db = Database(dsn)
        store, _, factory = runtime_components(db, config, enable_broker=True)
        runtime = Execution(db, store)
        controller = BrokerController(runtime, factory)
        queue = DispatchQueue(runtime)
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        while not stop.is_set():
            queue.tick(controller, agent=args.agent)
            stop.wait(.25)
    except Exception:
        print(json.dumps({'status': 'failed', 'code': 'encode_dispatch_stopped'}), flush=True)
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
