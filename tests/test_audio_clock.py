import unittest


class AudioClockTests(unittest.TestCase):
    def test_clock_validation_does_not_need_a_placeholder_transcript(self):
        from video_service.audio_clock import validate_clock

        self.assertEqual(
            validate_clock(
                [
                    {
                        "source_start": 0,
                        "source_end": 1,
                        "packed_start": 0,
                        "packed_end": 1,
                    }
                ]
            ),
            1,
        )

    def test_packed_gpu_audio_maps_back_to_original_clock(self):
        from video_service.audio_clock import restore_clock

        spans = [
            {
                "source_start": 1.0,
                "source_end": 2.0,
                "packed_start": 0.0,
                "packed_end": 1.0,
            },
            {
                "source_start": 4.0,
                "source_end": 5.0,
                "packed_start": 1.0,
                "packed_end": 2.0,
            },
        ]
        restored = restore_clock(
            [
                {"start": 0.5, "end": 1.0, "text": "first"},
                {"start": 1.0, "end": 1.5, "text": "second"},
            ],
            spans,
        )
        self.assertEqual(
            [(row["start"], row["end"]) for row in restored], [(1.5, 2.0), (4.0, 4.5)]
        )
        with self.assertRaises(ValueError):
            restore_clock([{"start": 0, "end": 4, "text": "outside"}], spans)
        with self.assertRaises(ValueError):
            restore_clock([], list(reversed(spans)))


if __name__ == "__main__":
    unittest.main()
