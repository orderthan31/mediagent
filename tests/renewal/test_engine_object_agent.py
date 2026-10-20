"""Opt-in actual S3 + pinned offline neural engine acceptance (not product login)."""

import json, os, tempfile, unittest, wave
from pathlib import Path
from uuid import uuid4


@unittest.skipUnless(
    os.environ.get("MIDEAGENT_TEST_LOCAL_MODELS") == "1", "explicit live model fixture"
)
class EngineObjectAgentTests(unittest.TestCase):
    def test_real_asr_s3_receipt_and_same_attempt_replay(self):
        from video_service.engine_object_agent import EngineObjectExecutor
        from video_service.engine_protocol import make_command
        from video_service.local_model_engines import model_identity
        from video_service.transport_files import object_config
        from video_service.object_store import from_config

        owner = uuid4().hex
        root = Path("/fixture")
        model = root / "models/whisper-tiny-en"
        with tempfile.TemporaryDirectory() as temporary:
            config, secrets = object_config("/run/bootstrap/objects.json")
            config["cache_root"] = temporary
            store = from_config(config, environ=secrets)
            audio = store.put(owner, [(root / "voice-16k.wav").read_bytes()], "audio")
            with wave.open(str(root / "voice-16k.wav"), "rb") as stream:
                duration = stream.getnframes() / stream.getframerate()
            timeline = store.put(
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
            runtime = {
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
                inputs={"audio": audio, "timeline": timeline},
                options={},
                runtime=runtime,
            )
            executor = EngineObjectExecutor(
                store, {"descriptor": runtime, "model_dir": str(model)}
            )
            result = executor.execute(owner, command)
            self.assertEqual(result["status"], "completed")
            segments = json.loads(store.read(owner, result["outputs"]["transcript"]))
            self.assertIn("local", " ".join(row["text"] for row in segments).lower())
            self.assertEqual(executor.execute(owner, command), result)
            (root / "engine-asr-s3-acceptance.json").write_text(
                json.dumps(
                    {
                        "fixture_owner": owner,
                        "command": command,
                        "result": result,
                        "repeated_result_identical": True,
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    unittest.main()
