from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agents/media'))
from media_agent.faceswap.bridge import engine_frame_number


class EngineCursorTests(unittest.TestCase):
    def test_one_based_saved_cursors_survive_zero_based_engine_upgrade(self):
        for first_middle_last in (1, 8, 270):
            self.assertEqual(engine_frame_number(first_middle_last, '3.9.0'), first_middle_last - 1)
            self.assertEqual(engine_frame_number(first_middle_last, '3.5.4'), first_middle_last)
