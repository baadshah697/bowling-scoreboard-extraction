"""
test_pawan_row.py -- Dedicated unit test for Row P (PAWAN) scoring calculations,
monotonic verification, and match total.
"""

import unittest
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from bowling_rules import reconcile_row_state, compute_cumulative_scores, compute_bowler_total


class TestPawanRowScoring(unittest.TestCase):
    """Verifies Row P (PAWAN) 10-pin bowling calculations."""

    def test_pawan_exact_game_math(self):
        # Frame 1: X (Strike)
        # Frame 2: 4/ (Four Spare) -> Frame 1 score = 10 + 4 + 6 = 20, Cumulative = 20
        # Frame 3: 9- (Nine Dash) -> Frame 2 score = 10 + 9 = 19, Cumulative = 20 + 19 = 39
        # Frame 4: 6- (Six Dash) -> Frame 3 score = 9, Cumulative = 39 + 9 = 48
        # Frame 4 cumulative = 48 + 6 = 54
        # Total TTL = 54
        raw_frames = {
            "1": {"pinfall": "X", "cumulative": 20},
            "2": {"pinfall": "4/", "cumulative": 39},
            "3": {"pinfall": "9-", "cumulative": 48},
            "4": {"pinfall": "6-", "cumulative": 54},
        }

        reconciled = reconcile_row_state(raw_frames)

        self.assertEqual(reconciled["pinfalls"][:4], ["X", "4/", "9-", "6-"])
        self.assertEqual(reconciled["cumulative"][:4], [20, 39, 48, 54])
        self.assertEqual(reconciled["total"], 54)


if __name__ == "__main__":
    unittest.main()
