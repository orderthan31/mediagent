"""Application-side exact-job AMQP dispatch. Agents never import this DB layer."""

import json

from .durable_transport import DurableTransport
from .rabbitmq_transport import BrokerError, decode, envelope


class BrokerController:
    def __init__(self, runtime, client_factory):
        if (
            getattr(runtime.store, "storage_kind", None) != "s3"
            or runtime.fleet is not None
        ):
            raise ValueError("Broker execution requires independent object storage")
        self.runtime = runtime
        self.client_factory = client_factory
        self.transport = DurableTransport(runtime)

    def publish_exact(self, owner, job_id, attempt_id):
        def send(message_id, message_type, body):
            if message_type != "agent.command.v1":
                raise BrokerError("unsupported_outbox_message")
            command = json.loads(body)
            if command["run_id"] != job_id or command["attempt_id"] != message_id:
                raise BrokerError("outbox_identity_mismatch")
            # FastAPI handlers and result workers each get their own IO-thread-owned
            # connection. Never share a BlockingConnection across request threads.
            with self.client_factory() as client:
                return client.publish(envelope(owner, command))

        return self.transport.publish_exact(owner, job_id, attempt_id, send)

    def dispatch(self, owner, job_id):
        # One explicitly authorized job only, including its previously reserved
        # unpublished attempt after a transport failure. Never scan pending jobs.
        self.runtime.claim_next(owner, job_id)
        state = self.runtime.get(owner, job_id)
        for run in state["runs"]:
            if run["status"] == "running":
                self.publish_exact(owner, job_id, run["id"])
        return self.runtime.get(owner, job_id)

    def receive(self, delivery):
        value = decode(delivery, result=True)
        # accept() commits before this returns. serve() ACKs only after this whole
        # handler finishes; a repeated result is fenced by the durable inbox.
        self.runtime.accept(value["owner"], value["command"], value["result"])
        self.dispatch(value["owner"], value["command"]["run_id"])
