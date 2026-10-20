"""Separately enabled topology provisioning or durable result consumption.

Never imported/started by API startup. No migration, provider, Docker or queue scan.
"""

import argparse
import json
import logging
import os
import signal
import threading

from video_service.rabbitmq_transport import BrokerConfig, RabbitClient


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("declare-topology", "consume-results"))
    parser.add_argument("--enable-broker", action="store_true")
    parser.add_argument("--broker-config-env", required=True)
    parser.add_argument("--dsn-env")
    parser.add_argument("--object-config-env")
    args = parser.parse_args(argv)
    if not args.enable_broker:
        parser.error("Broker operations require --enable-broker")
    if args.mode == "consume-results" and not (args.dsn_env and args.object_config_env):
        parser.error("Result consumption requires explicit DB and object config names")
    logging.getLogger("pika").disabled = True
    try:
        config = BrokerConfig.from_env(args.broker_config_env, environ=os.environ)
        factory = lambda: RabbitClient.connect(config, environ=os.environ)
        with factory() as client:
            if args.mode == "declare-topology":
                client.declare()
                return 0
            from video_service.object_store import from_config
            from video_service.postgres import Database
            from video_service.postgres.execution import Execution
            from video_service.rabbitmq_controller import BrokerController

            runtime = Execution(
                Database(os.environ[args.dsn_env]),
                from_config(json.loads(os.environ[args.object_config_env])),
            )
            controller = BrokerController(runtime, factory)
            stop = threading.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: stop.set())
            client.serve("result", controller.receive, stop)
        return 0
    except Exception:  # noqa: BLE001 -- CLI must suppress DSN, endpoint and credential diagnostics
        print(
            '{"status":"failed","error":{"code":"broker_controller_stopped","retryable":false}}'
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
