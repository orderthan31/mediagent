import hashlib
import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from uuid import uuid4
from video_service.cpu_agents import run


class PreprocessAgentTests(unittest.TestCase):
    def test_cpu_normalization_emits_real_audio_and_clock_map(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "blobs").mkdir()
            (root / "outputs").mkdir()
            source = root / "speech-fixture.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                audio.writeframes(
                    b"".join(
                        struct.pack("<h", int(1000 * math.sin(i / 10)))
                        for i in range(16000)
                    )
                )
            raw = source.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            (root / "blobs" / sha).write_bytes(raw)
            command = {
                "protocol_version": 1,
                "run_id": uuid4().hex,
                "attempt_id": uuid4().hex,
                "generation": 1,
                "agent": {"id": "preprocess_audio", "revision": "1"},
                "inputs": {
                    "audio": {
                        "storage_key": "blobs/" + sha,
                        "sha256": sha,
                        "bytes": len(raw),
                        "type": "audio",
                    }
                },
                "options": {"audio_filter": "off", "vad_mode": "off"},
            }
            result = run(command, root, root / "outputs", agent="preprocess_audio")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(set(result["outputs"]), {"audio", "timeline"})
            mapping = json.loads(
                (
                    root / "outputs" / result["outputs"]["timeline"]["storage_key"]
                ).read_bytes()
            )
            self.assertEqual(mapping[0]["source_start"], 0)
            self.assertAlmostEqual(mapping[0]["source_end"], 1.0)
            for value in result["outputs"].values():
                self.assertEqual(
                    hashlib.sha256(
                        (root / "outputs" / value["storage_key"]).read_bytes()
                    ).hexdigest(),
                    value["sha256"],
                )


if __name__ == "__main__":
    unittest.main()
