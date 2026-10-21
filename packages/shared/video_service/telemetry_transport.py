"""Dedicated status-only credentials/connections; never consumes job queues."""

import json
from contextlib import suppress

from .rabbitmq_transport import BrokerConfig
from .transport_files import document, secret_file
from .worker_telemetry import PREFIX, exchange, validate_report


def status_connection(config):
    import pika

    params = BrokerConfig(PREFIX, "TELEMETRY_URL", ca_file=config["ca_file"]).parameters(
        environ={"TELEMETRY_URL": secret_file(config["url_file"])}, sdk=pika
    )
    params.heartbeat = 6
    params.socket_timeout = 1
    params.stack_timeout = 2
    params.blocked_connection_timeout = 1
    return pika.BlockingConnection(params)


class StatusSender:
    def __init__(self, path):
        self.config = document(path)
        if set(self.config) != {"worker_id", "family", "role", "url_file", "ca_file"}:
            raise ValueError("invalid_telemetry_config")
        self.exchange = exchange(self.config["family"], self.config["role"])
        self.connection = self.channel = None

    def __call__(self, report):
        import pika

        validate_report(report, self.exchange)
        if report["worker_id"] != self.config["worker_id"]:
            return False
        try:
            if self.connection is None or not self.connection.is_open:
                self.connection = status_connection(self.config)
                self.channel = self.connection.channel()
                self.channel.confirm_delivery()
            self.channel.basic_publish(
                exchange=self.exchange, routing_key="status", mandatory=True,
                body=json.dumps(report, separators=(",", ":")).encode(),
                properties=pika.BasicProperties(content_type="application/json", type="worker.status.v1",
                                                delivery_mode=1, expiration="10000"),
            )
            self.connection.process_data_events(time_limit=0)
            return True
        except Exception:  # never leak endpoint/credential SDK errors to a job
            self.close()
            return False

    def close(self):
        with suppress(Exception):
            if self.connection is not None and self.connection.is_open:
                self.connection.close()
        self.connection = self.channel = None
