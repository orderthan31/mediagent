import unittest


class EngineBrokerBoundaryTests(unittest.TestCase):
    def test_gpu_and_model_queues_are_not_cpu_queues(self):
        from video_service.engine_transport import (
            EngineBrokerConfig,
            EngineRabbitClient,
        )

        config = EngineBrokerConfig(
            namespace="mideagent.engine",
            url_env="TEST_BROKER_URL",
            ca_file="/not-loaded-ca.pem",
        )
        self.assertEqual(config.queue("transcribe"), "mideagent.engine.transcribe.v2")
        self.assertEqual(config.queue("result"), "mideagent.engine.result.v2")
        with self.assertRaises(ValueError):
            config.queue("encode")
        self.assertNotEqual(config.commands, "mideagent.commands.v1")
        self.assertEqual(
            EngineRabbitClient.roles,
            {"transcribe", "translate", "preprocess_audio", "faceswap"},
        )


if __name__ == "__main__":
    unittest.main()
