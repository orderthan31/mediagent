"""Explicit status-only collector; never consumes commands or changes jobs."""

import argparse
import json
import logging
import signal
import threading
import time
from contextlib import closing

from video_service.postgres import Database
from video_service.postgres.worker_telemetry import WorkerTelemetry
from video_service.telemetry_transport import status_connection
from video_service.transport_files import document, secret_file
from video_service.worker_telemetry import MAX_REPORT, PREFIX, ID


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-file", required=True)
    args = parser.parse_args(argv)
    logging.getLogger("pika").disabled = True
    try:
        config = document(args.config_file)
        if set(config) != {"url_file", "ca_file", "database_dsn_file", "workers"}:
            raise ValueError("invalid_collector_config")
        if not isinstance(config["workers"], dict) or not 1 <= len(config["workers"]) <= 100:
            raise ValueError("invalid_collector_bindings")
        for key, value in config["workers"].items():
            if not key.startswith(PREFIX + ".") or not isinstance(value, str) or not ID.fullmatch(value):
                raise ValueError("invalid_collector_binding")
        store = WorkerTelemetry(Database(secret_file(config["database_dsn_file"])))
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        with closing(status_connection(config)) as connection:
            channel = connection.channel()
            queue = PREFIX + ".events.v1"
            channel.queue_declare(queue=queue, passive=True)
            channel.basic_qos(prefetch_count=32)

            def received(c, method, properties, body):
                try:
                    expected = config["workers"].get(method.exchange)
                    if (expected is None or len(body) > MAX_REPORT
                        or properties.content_type != "application/json" or properties.type != "worker.status.v1"):
                        raise ValueError("invalid_worker_status_message")
                    report = json.loads(body)
                    store.accept(report, method.exchange, expected_worker_id=expected)
                except (ValueError, TypeError, UnicodeError):
                    c.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                    return
                c.basic_ack(delivery_tag=method.delivery_tag)

            tag = channel.basic_consume(queue=queue, on_message_callback=received, auto_ack=False)
            last = -100.0
            while not stop.is_set():
                connection.process_data_events(time_limit=0.2)
                if time.monotonic() - last >= 2:
                    store.beat()
                    last = time.monotonic()
            channel.basic_cancel(tag)
        return 0
    except Exception:  # never emit SDK, DSN, endpoint or report diagnostics
        print('{"status":"failed","code":"telemetry_collector_failed"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
