"""
test_ocr_accuracy.py -- Comprehensive unit tests for ScoreVision OCR engine,
empty-cell quality gating, domain physics reconciliation, and candidate fusion.
"""

import unittest
import numpy as np
import cv2
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ocr_engine import extract_text_from_cell, fuse_candidates, _reconcile_bowling_pinfall


class TestEmptyCellQualityGate(unittest.TestCase):
    """Verifies that uniform/blank cells bypass OCR immediately with zero hallucinations."""

    def test_solid_blue_cell_returns_empty(self):
        # Create solid blue cell (background of empty bowling frames)
        solid_blue = np.full((70, 130, 3), (150, 80, 0), dtype=np.uint8)
        text, boxes = extract_text_from_cell(solid_blue, is_pinfall=True)
        self.assertEqual(text, "")
        self.assertEqual(boxes, [])

    def test_solid_white_cell_returns_empty(self):
        # Create solid white cell (active bowler row empty frame)
        solid_white = np.full((80, 130, 3), (255, 255, 255), dtype=np.uint8)
        text, boxes = extract_text_from_cell(solid_white, is_pinfall=False)
        self.assertEqual(text, "")
        self.assertEqual(boxes, [])

    def test_none_or_empty_array(self):
        self.assertEqual(extract_text_from_cell(None), ("", []))
        self.assertEqual(extract_text_from_cell(np.array([])), ("", []))


class TestBowlingPhysicsReconciliation(unittest.TestCase):
    """Verifies domain correction for OCR digit confusion."""

    def test_impossible_sum_converted_to_spare(self):
        # 4 + 7 = 11 > 10 (physically impossible open frame -> spare)
        self.assertEqual(_reconcile_bowling_pinfall("47"), "4/")
        self.assertEqual(_reconcile_bowling_pinfall("4 7"), "4/")
        self.assertEqual(_reconcile_bowling_pinfall("65"), "6/")
        self.assertEqual(_reconcile_bowling_pinfall("6 5"), "6/")

    def test_valid_open_frame_preserved(self):
        # 3 + 4 = 7 <= 10 (valid open frame)
        self.assertEqual(_reconcile_bowling_pinfall("34"), "34")
        self.assertEqual(_reconcile_bowling_pinfall("5-"), "5-")
        self.assertEqual(_reconcile_bowling_pinfall("X"), "X")
        self.assertEqual(_reconcile_bowling_pinfall("4/"), "4/")


class TestCandidateFusion(unittest.TestCase):
    """Verifies strict verbatim tie-breaking without string joining."""

    def test_never_concatenates(self):
        cand_a = ("15", 0.90, ["15"])
        cand_b = ("20", 0.85, ["20"])
        chosen, _ = fuse_candidates(cand_a, cand_b, is_pinfall=False)
        self.assertIn(chosen, ["15", "20"])
        self.assertNotEqual(chosen, "1520")
        self.assertNotEqual(chosen, "15 20")

    def test_symbolic_preference(self):
        cand_sym = ("4 /", 0.65, ["4", "/"])
        cand_bare = ("4 7", 0.85, ["4", "7"])
        chosen, _ = fuse_candidates(cand_sym, cand_bare, is_pinfall=True)
        self.assertEqual(chosen, "4 /")


if __name__ == "__main__":
    unittest.main()
