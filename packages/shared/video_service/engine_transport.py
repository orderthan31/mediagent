"""Versioned GPU/model exchanges; publisher confirms and ACK semantics reused."""

from .engine_protocol import ENGINE_ROLES, RESULT, decode
from .rabbitmq_transport import BrokerConfig, BrokerError, RabbitClient


class EngineBrokerConfig(BrokerConfig):
    @property
    def commands(self):
        return self.namespace + ".commands.v2"

    @property
    def results(self):
        return self.namespace + ".results.v2"

    @property
    def dead(self):
        return self.namespace + ".dead.v2"

    def queue(self, role):
        if role not in ENGINE_ROLES | {"result"}:
            raise ValueError("invalid_engine_role")
        return self.namespace + "." + role + ".v2"


class EngineRabbitClient(RabbitClient):
    roles = ENGINE_ROLES

    def publish(self, delivery):
        self._owner()
        result = delivery.message_type == RESULT
        value = decode(delivery, result=result)
        try:
            self.channel.basic_publish(
                exchange=self.config.results if result else self.config.commands,
                routing_key="result" if result else value["command"]["agent"]["id"],
                body=delivery.body,
                mandatory=True,
                properties=self.sdk.BasicProperties(
                    content_type="application/json",
                    content_encoding="utf-8",
                    delivery_mode=2,
                    type=delivery.message_type,
                    message_id=delivery.message_id,
                    correlation_id=delivery.correlation_id,
                    expiration=None if result else "60000",
                ),
            )
        except (OSError, self.sdk.exceptions.AMQPError):
            raise BrokerError("engine_publish_unconfirmed") from None
        return True
