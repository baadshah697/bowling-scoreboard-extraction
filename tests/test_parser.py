"""
Unit tests for ScoreVision parser, column indexing, bowling rules, and candidate fusion.
"""

import unittest
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import config
from bowling_rules import _parse_rolls, compute_cumulative_scores, check_rules
from ocr_engine import fuse_candidates


class TestCandidateFusion(unittest.TestCase):
    """Amendment 2: Disagreeing candidates must NEVER concatenate or string-join."""

    def test_no_concatenation(self):
        cand_a = ("70", 0.9, ["70"])
        cand_b = ("1", 0.85, ["1"])
        chosen, boxes = fuse_candidates(cand_a, cand_b, is_pinfall=False)
        self.assertIn(chosen, ["70", "1"])
        self.assertNotEqual(chosen, "701")
        self.assertNotEqual(chosen, "70 1")

    def test_symbolic_preference_spare(self):
        cand_a = ("1 /", 0.60, ["1", "/"])
        cand_b = ("1", 0.85, ["1"])
        chosen, _ = fuse_candidates(cand_a, cand_b, is_pinfall=True)
        self.assertEqual(chosen, "1 /")

    def test_symbolic_preference_strike(self):
        cand_a = ("X", 0.70, ["X"])
        cand_b = ("7", 0.80, ["7"])
        chosen, _ = fuse_candidates(cand_a, cand_b, is_pinfall=True)
        self.assertEqual(chosen, "X")

    def test_symbolic_preference_dash(self):
        cand_a = ("5 -", 0.55, ["5", "-"])
        cand_b = ("5", 0.75, ["5"])
        chosen, _ = fuse_candidates(cand_a, cand_b, is_pinfall=True)
        self.assertEqual(chosen, "5 -")


class TestColumnIndexing(unittest.TestCase):
    def test_frame_column_index_mapping(self):
        self.assertEqual(config.FRAME_COLUMN_INDEX[0], 1)
        self.assertEqual(config.FRAME_COLUMN_INDEX[9], 10)
        self.assertEqual(len(config.FRAME_COLUMN_INDEX), 10)

    def test_col_x_bounds_length(self):
        self.assertEqual(len(config.COL_X_BOUNDS), 11)
        self.assertEqual(config.COL_X_BOUNDS[0], 266)
        self.assertEqual(config.COL_X_BOUNDS[10], 1656)


class TestBowlingScoringRules(unittest.TestCase):
    def test_perfect_game(self):
        pinfalls = ["X"] * 9 + ["XXX"]
        computed = compute_cumulative_scores(pinfalls)
        expected = [30, 60, 90, 120, 150, 180, 210, 240, 270, 300]
        self.assertEqual(computed, expected)

    def test_row_p_scoring_chain(self):
        # Frame 1: X, Frame 2: 4/, Frame 3: 9-, Frame 4: 6-
        pinfalls = ["X", "4/", "9-", "6-"]
        computed = compute_cumulative_scores(pinfalls)
        # F1: 10 + 4 + 6 = 20
        # F2: 20 + 10 + 9 = 39
        # F3: 39 + 9 + 0 = 48
        # F4: 48 + 6 + 0 = 54
        self.assertEqual(computed[:4], [20, 39, 48, 54])

    def test_row_t_scoring_chain(self):
        # Frame 1: 61, Frame 2: 1/, Frame 3: 8-, Frame 4: 34
        pinfalls = ["61", "1/", "8-", "34"]
        computed = compute_cumulative_scores(pinfalls)
        # F1: 6 + 1 = 7
        # F2: 7 + 10 + 8 = 25
        # F3: 25 + 8 + 0 = 33
        # F4: 33 + 3 + 4 = 40
        self.assertEqual(computed[:4], [7, 25, 33, 40])

    def test_row_j_scoring_chain(self):
        # Frame 1: X, Frame 2: 5-, Frame 3: -7, Frame 4: 4-
        pinfalls = ["X", "5-", "-7", "4-"]
        computed = compute_cumulative_scores(pinfalls)
        # F1: 10 + 5 + 0 = 15
        # F2: 15 + 5 + 0 = 20
        # F3: 20 + 0 + 7 = 27
        # F4: 27 + 4 + 0 = 31
        self.assertEqual(computed[:4], [15, 20, 27, 31])


if __name__ == "__main__":
    unittest.main()
