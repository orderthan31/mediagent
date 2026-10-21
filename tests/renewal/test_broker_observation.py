"""Read-only AMQP observations. Channel seams, not live-worker readiness proof."""

import unittest
from types import SimpleNamespace

import pika

from video_service.rabbitmq_transport import BrokerConfig, BrokerError, RabbitClient


class ObservationChannel:
    def __init__(self):
        self.calls = []
        self.failure = None

    def confirm_delivery(self):
        pass

    def queue_declare(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return SimpleNamespace(method=SimpleNamespace(consumer_count=2, message_count=3))


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.channel = ObservationChannel()
        self.client = RabbitClient(
            BrokerConfig("isolated.observation", "TEST_URL"),
            SimpleNamespace(channel=lambda: self.channel),
            pika,
        )

    def test_observation_reads_connected_consumers_without_creating_or_consuming(self):
        self.assertTrue(callable(getattr(self.client, "observe", None)), "read-only observation missing")
        result = self.client.observe("analyze")
        self.assertEqual(result, {"consumers": 2, "messages_ready": 3})
        self.assertEqual(self.channel.calls, [{"queue": "isolated.observation.analyze.v1", "passive": True}])

    def test_permission_denial_is_not_reported_as_zero_consumers(self):
        self.channel.failure = pika.exceptions.ChannelClosedByBroker(403, "private-endpoint sentinel")
        with self.assertRaisesRegex(BrokerError, "^broker_observation_forbidden$"):
            self.client.observe("analyze")


if __name__ == "__main__":
    unittest.main()
