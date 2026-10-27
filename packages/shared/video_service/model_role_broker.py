"""Role-only command/cancel publisher and application result receiver.

The worker has separate credentials; this is the application principal only.
"""

import re

from .cpu_agents import canonical
from .rabbitmq_transport import BrokerConfig, BrokerError, RabbitClient


class ModelRoleBrokerConfig(BrokerConfig):
    @property
    def commands(self):
        return self.namespace + ".transcription.commands.v1"

    @property
    def results(self):
        return self.namespace + ".transcription.results.v1"

    def queue(self, role):
        if role != "result":
            raise BrokerError("model_role_result_queue_only")
        return self.namespace + ".transcription.result_inbox.v1"


class ModelRoleRabbitClient(RabbitClient):
    roles = frozenset({"result"})

    def _publish_packet(self, packet, kind, routing):
        self._owner()
        task = (
            packet.get("task", {}).get("task_id")
            if kind == "command"
            else packet.get("task_id")
        )
        if (
            not isinstance(task, str)
            or not re.fullmatch("[a-f0-9]{32}", task)
            or packet.get("role") != "transcription"
        ):
            raise BrokerError("invalid_model_role_packet")
        body = canonical(packet)
        if len(body) > 16 * 1024 * 1024:
            raise BrokerError("model_role_packet_budget_exceeded")
        try:
            self.channel.basic_publish(
                exchange=self.config.commands,
                routing_key=routing,
                body=body,
                mandatory=True,
                properties=self.sdk.BasicProperties(
                    content_type="application/json",
                    content_encoding="utf-8",
                    delivery_mode=2,
                    type="mideagent.model." + kind + ".v1",
                    message_id=task,
                ),
            )
        except (OSError, self.sdk.exceptions.AMQPError):
            raise BrokerError("model_role_publish_unconfirmed") from None
        return True

    def publish_command(self, packet):
        return self._publish_packet(packet, "command", "transcription")

    def publish_cancel(self, packet):
        return self._publish_packet(packet, "cancel", "cancel")
