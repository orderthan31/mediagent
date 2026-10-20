"""GPU/model wire is separate from the CPU-v1 allowlist; no fabricated engine work."""

import unittest
from uuid import uuid4


class EngineProtocolTests(unittest.TestCase):
    def test_pinned_model_request_result_and_exact_output_ports(self):
        from video_service.engine_protocol import make_command, envelope, decode
        from video_service.rabbitmq_transport import InvalidMessage
        from video_service.cpu_agents import digest, CPU_AGENTS

        self.assertNotIn("transcribe", CPU_AGENTS)
        runtime = {
            "role": "transcribe",
            "family": "model",
            "engine": "whisper-tiny-en",
            "model_sha256": "c" * 64,
            "source_language": "en",
            "target_language": None,
        }
        command = make_command(
            "transcribe",
            run_id=uuid4().hex,
            attempt_id=uuid4().hex,
            generation=1,
            inputs={
                "audio": {
                    "storage_key": "blobs/" + "a" * 64,
                    "sha256": "a" * 64,
                    "bytes": 10,
                    "type": "audio",
                },
                "timeline": {
                    "storage_key": "blobs/" + "b" * 64,
                    "sha256": "b" * 64,
                    "bytes": 10,
                    "type": "timeline_map",
                },
            },
            options={},
            runtime=runtime,
        )
        self.assertEqual(command["agent"]["revision"], digest(runtime))
        owner = uuid4().hex
        delivery = envelope(owner, command)
        self.assertEqual(decode(delivery, role="transcribe")["command"], command)
        self.assertNotEqual(delivery.message_type, "agent.command.v1")
        self.assertEqual(delivery.message_type, "agent.engine.command.v2")
        bad = {**command, "runtime": {**runtime, "model_sha256": "d" * 64}}
        with self.assertRaises(InvalidMessage):
            envelope(owner, bad)
        result = {
            **{
                k: command[k]
                for k in [
                    "protocol_version",
                    "run_id",
                    "attempt_id",
                    "generation",
                    "agent",
                ]
            },
            "request_sha256": digest(command),
            "status": "completed",
            "transport": "s3_engine",
            "outputs": {
                "transcript": {
                    "storage_key": "blobs/" + "e" * 64,
                    "sha256": "e" * 64,
                    "bytes": 25,
                    "type": "transcript",
                }
            },
        }
        self.assertEqual(
            decode(envelope(owner, command, result), result=True)["result"], result
        )
        with self.assertRaises(InvalidMessage):
            envelope(
                owner,
                command,
                {**result, "credential": "not-an-allowed-response-field"},
            )

    def test_response_numeric_types_and_output_object_are_strict(self):
        from video_service.engine_protocol import make_command, envelope
        from video_service.cpu_agents import digest
        from video_service.rabbitmq_transport import InvalidMessage

        runtime = {
            "role": "transcribe",
            "family": "model",
            "engine": "whisper-tiny-en",
            "model_sha256": "c" * 64,
            "source_language": "en",
            "target_language": None,
        }
        command = make_command(
            "transcribe",
            run_id=uuid4().hex,
            attempt_id=uuid4().hex,
            generation=1,
            inputs={
                "audio": {
                    "storage_key": "blobs/" + "a" * 64,
                    "sha256": "a" * 64,
                    "bytes": 10,
                    "type": "audio",
                },
                "timeline": {
                    "storage_key": "blobs/" + "b" * 64,
                    "sha256": "b" * 64,
                    "bytes": 10,
                    "type": "timeline_map",
                },
            },
            options={},
            runtime=runtime,
        )
        result = {
            **{
                k: command[k]
                for k in [
                    "protocol_version",
                    "run_id",
                    "attempt_id",
                    "generation",
                    "agent",
                ]
            },
            "request_sha256": digest(command),
            "status": "completed",
            "transport": "s3_engine",
            "outputs": {
                "transcript": {
                    "storage_key": "blobs/" + "e" * 64,
                    "sha256": "e" * 64,
                    "bytes": 25,
                    "type": "transcript",
                }
            },
        }
        for changes in [
            {"generation": True},
            {"protocol_version": 2.0},
            {"outputs": ["transcript"]},
        ]:
            with self.subTest(changes=changes), self.assertRaises(InvalidMessage):
                envelope(uuid4().hex, command, {**result, **changes})


if __name__ == "__main__":
    unittest.main()
