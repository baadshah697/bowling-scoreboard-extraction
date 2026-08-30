"""
test_authentic_scoreboard.py -- Unit tests for 2-tier Authentic Bowling Scoreboard rendering,
pinfall roll splitting, active bowler highlights, and lane badges.
"""

import unittest
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frontend"))
from app import _parse_pinfall_rolls, _build_authentic_scoreboard_html


class TestPinfallRollParsing(unittest.TestCase):
    """Verifies that pinfall strings are accurately parsed into (roll1, roll2)."""

    def test_strike(self):
        r1, r2 = _parse_pinfall_rolls("X")
        self.assertEqual(r1, "")
        self.assertEqual(r2, "X")

    def test_spare(self):
        r1, r2 = _parse_pinfall_rolls("4/")
        self.assertEqual(r1, "4")
        self.assertEqual(r2, "/")

        r1_s, r2_s = _parse_pinfall_rolls("1 /")
        self.assertEqual(r1_s, "1")
        self.assertEqual(r2_s, "/")

    def test_dash_open_frame(self):
        r1, r2 = _parse_pinfall_rolls("5-")
        self.assertEqual(r1, "5")
        self.assertEqual(r2, "-")

        r1_l, r2_l = _parse_pinfall_rolls("-7")
        self.assertEqual(r1_l, "-")
        self.assertEqual(r2_l, "7")

    def test_two_digit_rolls(self):
        r1, r2 = _parse_pinfall_rolls("71")
        self.assertEqual(r1, "7")
        self.assertEqual(r2, "1")

        r1_sp, r2_sp = _parse_pinfall_rolls("6 1")
        self.assertEqual(r1_sp, "6")
        self.assertEqual(r2_sp, "1")

    def test_empty(self):
        self.assertEqual(_parse_pinfall_rolls(""), ("", ""))
        self.assertEqual(_parse_pinfall_rolls(None), ("", ""))


class TestAuthenticBoardHTML(unittest.TestCase):
    """Verifies authentic 2-tier bowling grid HTML markup generation."""

    def test_board_contains_lane_and_marquee(self):
        dummy_state = {
            "lane_number": "6",
            "unlabeled_metric": "2.5",
            "rows": [
                {"row_label": "J", "bowler_name": "JAGDISH", "total": 31, "frames": {}},
                {"row_label": "V", "bowler_name": "VISHAL", "total": 28, "frames": {}},
                {"row_label": "P", "bowler_name": "PAWAN", "total": 54, "frames": {}},
                {"row_label": "T", "bowler_name": "TARUN", "total": 33, "frames": {}},
            ]
        }
        html = _build_authentic_scoreboard_html(dummy_state, active_row="T")
        
        self.assertIn('<div class="bs-lane-badge">6</div>', html)
        self.assertIn('<div class="bs-bowler-marquee">TARUN</div>', html)
        self.assertIn('<div class="bs-metric-box">2.5</div>', html)
        self.assertIn('bs-bowler-cell-active', html)
        self.assertIn('bs-cum-tier-active', html)
        self.assertIn('bs-ttl-cell-active', html)


if __name__ == "__main__":
    unittest.main()
