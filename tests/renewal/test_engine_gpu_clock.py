"""Use actual CUDA VAD output as the input to actual offline ASR, no hand transcript."""

import json, os, tempfile, unittest
from pathlib import Path
from uuid import uuid4


@unittest.skipUnless(
    os.environ.get("MIDEAGENT_TEST_LOCAL_MODELS") == "1",
    "explicit GPU-output/model bridge",
)
class GpuClockBridgeTests(unittest.TestCase):
    def test_actual_gpu_clock_and_audio_are_transcribed_without_fallback(self):
        from video_service.engine_object_agent import EngineObjectExecutor
        from video_service.engine_protocol import make_command
        from video_service.local_model_engines import model_identity
        from video_service.transport_files import object_config
        from video_service.object_store import from_config

        fixture = Path("/fixture")
        prepared = json.loads((fixture / "gpu-vad-s3-acceptance.json").read_text())
        owner = prepared["fixture_owner"]
        model = fixture / "models/whisper-tiny-en"
        with tempfile.TemporaryDirectory() as temporary:
            config, secrets = object_config("/run/bootstrap/objects.json")
            config["cache_root"] = temporary
            store = from_config(config, environ=secrets)
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
                inputs=prepared["result"]["outputs"],
                options={},
                runtime=descriptor,
            )
            result = EngineObjectExecutor(
                store, {"descriptor": descriptor, "model_dir": str(model)}
            ).execute(owner, command)
            self.assertEqual(result["status"], "completed", result.get("error"))
            segments = json.loads(store.read(owner, result["outputs"]["transcript"]))
            self.assertIn("local", " ".join(row["text"] for row in segments).lower())
            self.assertLessEqual(
                segments[-1]["end"], prepared["clock"]["spans"][-1]["source_end"]
            )
            (fixture / "gpu-clock-asr-acceptance.json").write_text(
                json.dumps(
                    {
                        "scope": "ACTUAL_GPU_TO_ASR_FIXTURE",
                        "command": command,
                        "result": result,
                        "segments": segments,
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    unittest.main()
