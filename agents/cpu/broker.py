"""Explicit opt-in CPU broker runner; no DB, workflow or downstream knowledge."""

import argparse
import logging
import os
import signal
import threading

from video_service.object_agent import ObjectAgentExecutor
from video_service.object_store import ObjectStoreError
from video_service.rabbitmq_transport import (
    CPU_AGENTS,
    BrokerConfig,
    InvalidMessage,
    RabbitClient,
    decode,
    envelope,
)


class CpuHandler:
    def __init__(self, role, executor):
        if role not in CPU_AGENTS:
            raise ValueError("Unsupported CPU role")
        self.role, self.executor = role, executor

    def __call__(self, delivery):
        value = decode(delivery, role=self.role)
        try:
            result = self.executor(value["owner"], value["command"])
        except ObjectStoreError:
            raise InvalidMessage("attempt_unknown") from None
        return envelope(value["owner"], value["command"], result)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-broker", action="store_true")
    parser.add_argument("--agent", required=True, choices=sorted(CPU_AGENTS))
    parser.add_argument("--telemetry-config-file")
    broker = parser.add_mutually_exclusive_group(required=True)
    broker.add_argument("--broker-config-env")
    broker.add_argument("--broker-config-file")
    objects = parser.add_mutually_exclusive_group(required=True)
    objects.add_argument("--object-config-env")
    objects.add_argument("--object-config-file")
    args = parser.parse_args(argv)
    if not args.enable_broker:
        parser.error("Broker consumption is disabled without --enable-broker")
    # SDK diagnostics must not print private connection parameters.
    logging.getLogger("pika").disabled = True
    try:
        from video_service.transport_files import broker_factory, object_executor

        factory = (
            broker_factory(args.broker_config_file)
            if args.broker_config_file
            else lambda: RabbitClient.connect(
                BrokerConfig.from_env(args.broker_config_env, environ=os.environ),
                environ=os.environ,
            )
        )
        executor = (
            object_executor(args.object_config_file)
            if args.object_config_file
            else ObjectAgentExecutor(args.object_config_env, environ=os.environ)
        )
        handler = CpuHandler(args.agent, executor)
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        with factory() as client:
            from video_service.worker_telemetry import reporter_from_file

            client.serve(args.agent, handler, stop,
                         telemetry=reporter_from_file(args.telemetry_config_file, "cpu", args.agent))
        return 0
    except Exception:  # noqa: BLE001 -- CLI must suppress paths, endpoints and credentials
        print(
            '{"status":"failed","error":{"code":"cpu_broker_stopped","retryable":false}}'
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
