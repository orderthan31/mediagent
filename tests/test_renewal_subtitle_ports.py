import unittest
from video_service.renewal_contracts import validate


def document(mode, connected):
    return {
        "catalog_version": 1,
        "revision": 0,
        "name": "자막 포트 계약",
        "inputs": {"video": "video", "subtitles": "subtitle"},
        "nodes": [
            {
                "id": "encode",
                "type": "encode",
                "options": {"subtitle_mode": mode},
                "position": {"x": 0, "y": 0},
            }
        ],
        "edges": [
            {
                "id": "e" + str(index),
                "source": {"node": "$input", "port": port},
                "target": {"node": "encode", "port": port},
            }
            for index, port in enumerate(connected)
        ],
    }


class SubtitlePortTests(unittest.TestCase):
    def test_burn_requires_and_accepts_connected_subtitle(self):
        self.assertTrue(validate(document("burn", ["video", "subtitles"]))["valid"])
        self.assertFalse(validate(document("burn", ["video"]))["valid"])

    def test_none_rejects_connected_subtitle(self):
        self.assertTrue(validate(document("none", ["video"]))["valid"])
        self.assertFalse(validate(document("none", ["video", "subtitles"]))["valid"])


class AudioProducerTests(unittest.TestCase):
    def test_transcription_audio_and_clock_require_the_same_producer(self):
        nodes = [
            {
                "id": identity,
                "type": kind,
                "options": options,
                "position": {"x": index * 100, "y": 0},
            }
            for index, (identity, kind, options) in enumerate(
                [
                    ("audio", "extract_audio", {}),
                    (
                        "prepare_a",
                        "preprocess_audio",
                        {"audio_filter": "off", "vad_mode": "off"},
                    ),
                    (
                        "prepare_b",
                        "preprocess_audio",
                        {"audio_filter": "off", "vad_mode": "off"},
                    ),
                    ("asr", "transcribe", {}),
                ]
            )
        ]
        for clock_source, expected in [("prepare_a", True), ("prepare_b", False)]:
            links = [
                ("$input", "video", "audio", "video"),
                ("audio", "audio", "prepare_a", "audio"),
                ("audio", "audio", "prepare_b", "audio"),
                ("prepare_a", "audio", "asr", "audio"),
                (clock_source, "timeline", "asr", "timeline"),
            ]
            graph = {
                "catalog_version": 1,
                "revision": 0,
                "name": "오디오 시계 생산자",
                "inputs": {"video": "video"},
                "nodes": nodes,
                "edges": [
                    {
                        "id": "e" + str(index),
                        "source": {"node": a, "port": p},
                        "target": {"node": b, "port": q},
                    }
                    for index, (a, p, b, q) in enumerate(links)
                ],
            }
            with self.subTest(clock_source=clock_source):
                self.assertEqual(validate(graph)["valid"], expected)


if __name__ == "__main__":
    unittest.main()
