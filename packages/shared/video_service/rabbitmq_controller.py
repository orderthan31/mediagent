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
        # This rollout enrolls only new attempts for the registered encode group.
        # Existing attempts and unregistered/other-role transports stay unchanged.
        self.runtime.defer_broker_agents = frozenset({"encode"})
        self.client_factory = client_factory
        self.engine_client_factory = getattr(client_factory, "engine_factory", None)
        self.registered_client_factory = getattr(
            client_factory, "registered_factory", None
        )
        if self.registered_client_factory is not None:
            for role in ("translation", "transcription"):
                configured = getattr(runtime, role + "_runtime")
                if (
                    configured is None
                    or configured
                    is not getattr(client_factory, role + "_runtime", None)
                    or configured.credentials.database is not runtime.database
                    or not getattr(configured, "policy_sha256", None)
                    or configured.policy_sha256
                    != getattr(client_factory, "registered_policy_sha256", None)
                ):
                    raise ValueError("registered_broker_runtime_binding_mismatch")
        self.transport = DurableTransport(runtime)

    def publish_exact(self, owner, job_id, attempt_id):
        def send(message_id, message_type, body):
            from .engine_protocol import (
                COMMAND as ENGINE_COMMAND,
            )
            from .engine_protocol import (
                envelope as engine_envelope,
            )

            if message_type == ENGINE_COMMAND:
                if self.engine_client_factory is None:
                    raise BrokerError("engine_transport_not_configured")
                factory, encode = self.engine_client_factory, engine_envelope
            elif message_type == "registered.command.v1":
                from .registered_broker import reference

                if self.registered_client_factory is None:
                    raise BrokerError("registered_transport_not_configured")
                factory, encode = self.registered_client_factory, reference
            elif message_type == "agent.command.v1":
                factory, encode = self.client_factory, envelope
            else:
                raise BrokerError("unsupported_outbox_message")
            command = json.loads(body)
            if command["run_id"] != job_id or command["attempt_id"] != message_id:
                raise BrokerError("outbox_identity_mismatch")
            # FastAPI handlers and result workers each get their own IO-thread-owned
            # connection. Never share a BlockingConnection across request threads.
            with factory() as client:
                return client.publish(encode(owner, command))

        from .model_role_coordinator import ModelRoleCoordinator

        with self.runtime.database.connection() as db:
            run = db.execute(
                "SELECT request FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, job_id, attempt_id),
            ).fetchone()
        role = (
            "vocalization"
            if run and run["request"].get("vocalization")
            else "transcription"
            if run and run["request"].get("transcription")
            else "translation"
            if run and run["request"].get("translation")
            else None
        )
        if role and ModelRoleCoordinator.enrolled(
            self.runtime, owner, job_id, role=role
        ):
            return ModelRoleCoordinator(self.runtime, self.client_factory).publish(
                owner, run["request"]
            )
        return self.transport.publish_exact(owner, job_id, attempt_id, send)

    def dispatch(self, owner, job_id):
        # One explicitly authorized job only, including its previously reserved
        # unpublished attempt after a transport failure. Never scan pending jobs.
        state = self.runtime.get(owner, job_id)
        from .postgres.agent_pool import AgentPool
        if AgentPool(self.runtime).blocked(owner,job_id):
            return state
        limit = len(state["snapshot"]["definition"]["nodes"]) + 1
        for _ in range(limit):
            before = {(run["id"], run["status"]) for run in state["runs"]}
            self.runtime.claim_next(owner, job_id)
            state = self.runtime.get(owner, job_id)
            for run in state["runs"]:
                if run["status"] == "running" or (
                    run["status"] == "waiting" and run.get("dispatch")
                ):
                    self.publish_exact(owner, job_id, run["id"])
            state = self.runtime.get(owner, job_id)
            after = {(run["id"], run["status"]) for run in state["runs"]}
            if (
                state["status"] not in {"waiting", "running"}
                or any(run["status"] in {"running", "waiting"} for run in state["runs"])
                or before == after
            ):
                break
        return state

    def receive(self, delivery):
        from .engine_protocol import RESULT as ENGINE_RESULT
        from .engine_protocol import decode as engine_decode

        decoder = engine_decode if delivery.message_type == ENGINE_RESULT else decode
        value = decoder(delivery, result=True)
        # accept() commits before this returns. serve() ACKs only after this whole
        # handler finishes; a repeated result is fenced by the durable inbox.
        self.runtime.accept(value["owner"], value["command"], value["result"])
        self.dispatch(value["owner"], value["command"]["run_id"])
