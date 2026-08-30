"""
test_scene_gating.py -- Unit tests for 3-signal Scene Gate (Scoreboard vs. Cutaway).
"""

import unittest
import numpy as np
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from scene_gate import classify_frame


class TestSceneGateClassification(unittest.TestCase):
    """Verifies that 3-signal scene gating correctly separates scoreboard from non-scoreboard frames."""

    def test_scoreboard_signals_classified_correctly(self):
        # Scoreboard: low diff (5.0), high blue coverage (0.35), high edge density (0.06)
        label = classify_frame(5.0, 0.35, 0.06)
        self.assertEqual(label, "SCOREBOARD")

    def test_cutaway_high_diff_classified_correctly(self):
        # Cutaway: sudden scene switch (high diff 50.0)
        label = classify_frame(50.0, 0.10, 0.02)
        self.assertEqual(label, "CUTAWAY")

    def test_cutaway_low_blue_classified_correctly(self):
        # Cutaway: alley view with low blue coverage (0.05)
        label = classify_frame(2.0, 0.05, 0.04)
        self.assertEqual(label, "CUTAWAY")


if __name__ == "__main__":
    unittest.main()
