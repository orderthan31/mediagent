import json
import os
import unittest
from pathlib import Path


class LocalModelEngineTests(unittest.TestCase):
    def test_missing_model_never_falls_back_to_network_or_environment(self):
        from video_service.local_model_engines import transcribe

        with self.assertRaises(ValueError):
            transcribe(
                Path("/missing/audio.wav"),
                model_dir=Path("/missing/model"),
                model_digest="0" * 64,
                language="en",
            )

    @unittest.skipUnless(
        os.environ.get("MIDEAGENT_TEST_LOCAL_MODELS") == "1",
        "explicit downloaded-model acceptance only",
    )
    def test_real_offline_asr_then_translation(self):
        from video_service.local_model_engines import (
            transcribe,
            translate,
            model_identity,
        )

        root = Path("/fixture")
        models = root / "models"
        transcript = transcribe(
            root / "voice-16k.wav",
            model_dir=models / "whisper-tiny-en",
            model_digest=model_identity(models / "whisper-tiny-en"),
            language="en",
        )
        self.assertTrue(transcript)
        text = " ".join(row["text"] for row in transcript).lower()
        self.assertIn("local", text)
        self.assertIn("video", text)
        translated = translate(
            transcript,
            model_dir=models / "opus-en-de-int8",
            model_digest=model_identity(models / "opus-en-de-int8"),
            source_tokenizer=models / "opus-en-de-int8/source.spm",
            target_tokenizer=models / "opus-en-de-int8/target.spm",
            source_language="en",
            target_language="de",
        )
        self.assertEqual(len(translated), len(transcript))
        self.assertNotEqual(
            [r["text"] for r in translated], [r["text"] for r in transcript]
        )
        for left, right in zip(transcript, translated):
            self.assertEqual(
                (left["start"], left["end"]), (right["start"], right["end"])
            )
        (root / "real-asr-transcript.json").write_text(
            json.dumps(transcript, ensure_ascii=False)
        )
        (root / "real-en-de-translation.json").write_text(
            json.dumps(translated, ensure_ascii=False)
        )


if __name__ == "__main__":
    unittest.main()
