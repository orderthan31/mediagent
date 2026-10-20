"""Actual TLS MQ + S3 + offline ASR; its namespace is not the product queues."""

import json, os, tempfile, threading, unittest, wave
from pathlib import Path
from uuid import uuid4


@unittest.skipUnless(
    os.environ.get("MIDEAGENT_TEST_LOCAL_MODELS") == "1", "explicit live model fixture"
)
class EngineBrokerLiveTests(unittest.TestCase):
    def test_real_model_command_result_confirm_and_ack(self):
        from video_service.engine_service import EngineHandler
        from video_service.engine_object_agent import EngineObjectExecutor
        from video_service.engine_protocol import make_command, envelope, decode
        from video_service.transport_files import (
            object_config,
            document,
            engine_broker_factory,
        )
        from video_service.local_model_engines import model_identity
        from video_service.object_store import from_config

        namespace = "mideagent.acceptance_" + uuid4().hex[:12] + ".engine"
        owner = uuid4().hex
        fixture = Path("/fixture")
        model = fixture / "models/whisper-tiny-en"
        with tempfile.TemporaryDirectory() as temporary:
            config, secrets = object_config("/run/bootstrap/objects.json")
            config["cache_root"] = temporary
            store = from_config(config, environ=secrets)
            audio = store.put(
                owner, [(fixture / "voice-16k.wav").read_bytes()], "audio"
            )
            with wave.open(str(fixture / "voice-16k.wav"), "rb") as stream:
                duration = stream.getnframes() / stream.getframerate()
            clock = store.put(
                owner,
                [
                    json.dumps(
                        [
                            {
                                "source_start": 0,
                                "source_end": duration,
                                "packed_start": 0,
                                "packed_end": duration,
                            }
                        ]
                    ).encode()
                ],
                "timeline_map",
            )
            descriptor = {
                "role": "transcribe",
                "family": "model",
                "engine": "whisper-tiny-en",
                "model_sha256": model_identity(model),
                "source_language": "en",
                "target_language": None,
            }
            command = make_command(
                "transcribe",
                run_id=uuid4().hex,
                attempt_id=uuid4().hex,
                generation=1,
                inputs={"audio": audio, "timeline": clock},
                options={},
                runtime=descriptor,
            )
            broker = document(document("/run/bootstrap/api.json")["broker_config_file"])
            broker["namespace"] = namespace
            path = Path(temporary) / "engine-broker.json"
            path.write_text(json.dumps(broker))
            factory = engine_broker_factory(path)
            with factory() as client:
                client.declare()
            stop = threading.Event()
            done = threading.Event()
            received = []
            errors = []

            def worker():
                try:
                    with factory() as client:
                        client.serve(
                            "transcribe",
                            EngineHandler(
                                "transcribe",
                                EngineObjectExecutor(
                                    store,
                                    {"descriptor": descriptor, "model_dir": str(model)},
                                ),
                            ),
                            stop,
                        )
                except Exception as error:
                    errors.append(type(error).__name__)
                    done.set()

            def collect(delivery):
                received.append(decode(delivery, result=True))
                done.set()

            def receiver():
                try:
                    with factory() as client:
                        client.serve("result", collect, stop)
                except Exception as error:
                    errors.append(type(error).__name__)
                    done.set()

            threads = [
                threading.Thread(target=worker),
                threading.Thread(target=receiver),
            ]
            for thread in threads:
                thread.start()
            try:
                with factory() as client:
                    self.assertTrue(client.publish(envelope(owner, command)))
                self.assertTrue(done.wait(45), "real model result timed out")
            finally:
                stop.set()
                for thread in threads:
                    thread.join(10)
            self.assertFalse(errors, errors)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            result = received[0]["result"]
            self.assertEqual(result["status"], "completed")
            self.assertIn(
                "local",
                " ".join(
                    row["text"]
                    for row in json.loads(
                        store.read(owner, result["outputs"]["transcript"])
                    )
                ).lower(),
            )
            with factory() as client:
                counts = {
                    role: client.channel.queue_declare(
                        queue=client.config.queue(role), passive=True
                    ).method.message_count
                    for role in ["transcribe", "result"]
                }
            self.assertEqual(counts, {"transcribe": 0, "result": 0})
            (fixture / "engine-model-mq-acceptance.json").write_text(
                json.dumps(
                    {
                        "namespace": namespace,
                        "fixture_owner": owner,
                        "command": command,
                        "result": result,
                        "queue_ready_after_ack": counts,
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    unittest.main()
