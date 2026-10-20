"""Opt-in real CUDA role test. It never starts the preserved legacy Worker."""

import json, os, tempfile, unittest, wave
from pathlib import Path
from uuid import uuid4


@unittest.skipUnless(
    os.environ.get("MIDEAGENT_TEST_GPU") == "1", "explicit actual GPU fixture"
)
class GpuEngineAgentTests(unittest.TestCase):
    def test_actual_cuda_vad_has_pinned_report_and_audio_clock(self):
        from video_service.engine_object_agent import EngineObjectExecutor
        from video_service.engine_protocol import make_command
        from video_service.transport_files import object_config
        from video_service.object_store import from_config

        fixture = Path("/fixture")
        expected = json.loads((fixture / "vad-real-cuda.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            config, secrets = object_config("/run/bootstrap/objects.json")
            config["cache_root"] = temporary
            store = from_config(config, environ=secrets)
            owner = uuid4().hex
            audio = store.put(
                owner, [(fixture / "voice-16k.wav").read_bytes()], "audio"
            )
            descriptor = {
                "role": "preprocess_audio",
                "family": "gpu",
                "engine": "nvidia-marblenet",
                "model_sha256": expected["model_sha256"],
                "source_language": None,
                "target_language": None,
            }
            command = make_command(
                "preprocess_audio",
                run_id=uuid4().hex,
                attempt_id=uuid4().hex,
                generation=1,
                inputs={"audio": audio},
                options={"audio_filter": "off", "vad_mode": "nvidia"},
                runtime=descriptor,
            )
            executor = EngineObjectExecutor(
                store, {"descriptor": descriptor, "model_dir": "/opt/models"}
            )
            result = executor.execute(owner, command)
            self.assertEqual(result["status"], "completed", result.get("error"))
            clock = json.loads(store.read(owner, result["outputs"]["timeline"]))
            self.assertEqual(clock["version"], 2)
            self.assertEqual(
                clock["audio_sha256"], result["outputs"]["audio"]["sha256"]
            )
            self.assertEqual(clock["engine"]["device"], "cuda")
            self.assertGreater(clock["engine"]["cuda_peak_allocated_bytes"], 0)
            self.assertEqual(
                clock["engine"]["model_sha256"], descriptor["model_sha256"]
            )
            with wave.open(
                str(store.path(owner, result["outputs"]["audio"])), "rb"
            ) as stream:
                duration = stream.getnframes() / stream.getframerate()
            self.assertAlmostEqual(clock["spans"][-1]["packed_end"], duration)
            self.assertEqual(executor.execute(owner, command), result)
            (fixture / "gpu-vad-s3-acceptance.json").write_text(
                json.dumps(
                    {
                        "scope": "SYNTHETIC_FIXTURE",
                        "fixture_owner": owner,
                        "command": command,
                        "result": result,
                        "clock": clock,
                    },
                    indent=2,
                )
            )

    def test_actual_cuda_faceswap_with_owned_fixture_and_pinned_preview(self):
        from video_service.engine_object_agent import EngineObjectExecutor
        from video_service.engine_protocol import make_command
        from video_service.cpu_agents import canonical, digest
        from video_service.transport_files import object_config
        from video_service.object_store import from_config
        import subprocess

        fixture = Path("/fixture")
        caps = json.loads((fixture / "face-capabilities/result.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            config, secrets = object_config("/run/bootstrap/objects.json")
            config["cache_root"] = temporary
            store = from_config(config, environ=secrets)
            owner = uuid4().hex
            source = store.put(
                owner, [(fixture / "public-domain-astronaut.png").read_bytes()], "image"
            )
            video = store.put(
                owner,
                [(fixture / "public-domain-selfswap-target.mp4").read_bytes()],
                "video",
            )
            image = store.put(
                owner,
                [(fixture / "face-role-preview/preview.png").read_bytes()],
                "image",
            )
            session = {
                "version": 1,
                "source": source,
                "source_position": 0,
                "face_position": 0,
                "reference_frame": 1,
                "distance": 0.6,
                "engine_fingerprint": caps["fingerprint"],
            }
            session_ref = store.put(owner, [canonical(session)], "faceswap_session")
            options = {"preset": "fast", "video_codec": "h264"}
            preview = {
                "version": 1,
                "session_sha256": session_ref["sha256"],
                "target_sha256": video["sha256"],
                "engine_fingerprint": caps["fingerprint"],
                "settings_sha256": digest(options),
                "approved": True,
                "image": image,
            }
            preview_ref = store.put(owner, [canonical(preview)], "faceswap_preview")
            descriptor = {
                "role": "faceswap",
                "family": "gpu",
                "engine": "facefusion-3.9.0",
                "model_sha256": caps["fingerprint"],
                "source_language": None,
                "target_language": None,
            }
            command = make_command(
                "faceswap",
                run_id=uuid4().hex,
                attempt_id=uuid4().hex,
                generation=1,
                inputs={"video": video, "session": session_ref, "preview": preview_ref},
                options=options,
                runtime=descriptor,
            )
            executor = EngineObjectExecutor(
                store,
                {
                    "descriptor": descriptor,
                    "model_dir": "/opt/facefusion",
                    "python": "/opt/facefusion-env/bin/python",
                },
            )
            result = executor.execute(owner, command)
            self.assertEqual(result["status"], "completed", result.get("error"))
            output = store.path(owner, result["outputs"]["video"])
            probe = json.loads(
                subprocess.check_output(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_format",
                        "-of",
                        "json",
                        str(output),
                    ],
                    text=True,
                )
            )
            self.assertGreater(float(probe["format"]["duration"]), 1)
            proof = json.loads(
                (
                    store.owner_root(owner)
                    / "engine-attempts"
                    / command["attempt_id"]
                    / "engine-proof.json"
                ).read_text()
            )
            self.assertGreater(proof["cuda_swapper_sessions"], 0)
            self.assertEqual(executor.execute(owner, command), result)
            (fixture / "gpu-faceswap-s3-acceptance.json").write_text(
                json.dumps(
                    {
                        "scope": "PUBLIC_DOMAIN_SELF_SWAP_FIXTURE_NOT_PRODUCT_SESSION",
                        "fixture_owner": owner,
                        "command": command,
                        "result": result,
                        "proof": proof,
                        "ffprobe": probe,
                    },
                    indent=2,
                )
            )
            (fixture / "gpu-faceswap-role-final.mp4").write_bytes(output.read_bytes())


if __name__ == "__main__":
    unittest.main()
