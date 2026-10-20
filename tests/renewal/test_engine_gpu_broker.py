"""Both GPU roles execute NEW attempts through TLS MQ; not cached receipt replay."""

import json, os, tempfile, threading, unittest
from pathlib import Path
from uuid import uuid4


@unittest.skipUnless(
    os.environ.get("MIDEAGENT_TEST_GPU") == "1", "explicit actual GPU broker acceptance"
)
class GpuBrokerLiveTests(unittest.TestCase):
    def test_cuda_vad_and_faceswap_command_result_and_ack(self):
        from video_service.engine_service import EngineHandler
        from video_service.engine_object_agent import EngineObjectExecutor
        from video_service.engine_protocol import make_command, envelope, decode
        from video_service.transport_files import (
            document,
            object_config,
            engine_broker_factory,
        )
        from video_service.object_store import from_config

        fixture = Path("/fixture")
        namespace = "mideagent.acceptance_" + uuid4().hex[:12] + ".gpu"
        with tempfile.TemporaryDirectory() as temporary:
            config, secrets = object_config("/run/bootstrap/objects.json")
            config["cache_root"] = temporary
            store = from_config(config, environ=secrets)
            broker = document(document("/run/bootstrap/api.json")["broker_config_file"])
            broker["namespace"] = namespace
            path = Path(temporary) / "broker.json"
            path.write_text(json.dumps(broker))
            factory = engine_broker_factory(path)
            with factory() as client:
                client.declare()
            templates = [
                json.loads((fixture / name).read_text())
                for name in [
                    "gpu-vad-s3-acceptance.json",
                    "gpu-faceswap-s3-acceptance.json",
                ]
            ]
            commands = []
            stop = threading.Event()
            done = threading.Event()
            received = {}
            errors = []
            threads = []

            def consume(role, handler):
                try:
                    with factory() as client:
                        client.serve(role, handler, stop)
                except Exception as error:
                    errors.append({"role": role, "type": type(error).__name__})
                    done.set()

            def collect(delivery):
                value = decode(delivery, result=True)
                received[value["command"]["attempt_id"]] = value
                done.set()

            for template in templates:
                old = template["command"]
                role = old["agent"]["id"]
                command = make_command(
                    role,
                    run_id=uuid4().hex,
                    attempt_id=uuid4().hex,
                    generation=1,
                    inputs=old["inputs"],
                    options=old["options"],
                    runtime=old["runtime"],
                )
                self.assertNotEqual(command["attempt_id"], old["attempt_id"])
                commands.append((template["fixture_owner"], command))
                locator = {
                    "descriptor": command["runtime"],
                    "model_dir": "/opt/models"
                    if role == "preprocess_audio"
                    else "/opt/facefusion",
                }
                if role == "faceswap":
                    locator["python"] = "/opt/facefusion-env/bin/python"
                threads.append(
                    threading.Thread(
                        target=consume,
                        args=(
                            role,
                            EngineHandler(role, EngineObjectExecutor(store, locator)),
                        ),
                    )
                )
            threads.append(threading.Thread(target=consume, args=("result", collect)))
            for thread in threads:
                thread.start()
            try:
                for owner, command in commands:
                    done.clear()
                    with factory() as client:
                        self.assertTrue(client.publish(envelope(owner, command)))
                    self.assertTrue(done.wait(150), "actual GPU result timed out")
                    self.assertFalse(errors, errors)
                    self.assertIn(command["attempt_id"], received)
                    result = received[command["attempt_id"]]["result"]
                    self.assertEqual(result["status"], "completed", result.get("error"))
                    for reference in result["outputs"].values():
                        store.path(owner, reference)
            finally:
                stop.set()
                for thread in threads:
                    thread.join(10)
            self.assertFalse(errors, errors)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            with factory() as client:
                counts = {
                    role: client.channel.queue_declare(
                        queue=client.config.queue(role), passive=True
                    ).method.message_count
                    for role in ["preprocess_audio", "faceswap", "result"]
                }
            self.assertEqual(set(counts.values()), {0})
            (fixture / "gpu-broker-acceptance.json").write_text(
                json.dumps(
                    {
                        "scope": "SYNTHETIC_FIXTURES_NEW_INFERENCE_ATTEMPTS",
                        "namespace": namespace,
                        "results": list(received.values()),
                        "queue_ready_after_ack": counts,
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    unittest.main()
