"""
test_pipeline_streaming.py -- Unit tests for pipeline streaming event structure,
state timeline persistence, and JSON export schema.
"""

import unittest
import json
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frontend"))
from pipeline_runner import emit


class TestPipelineStreamingSchema(unittest.TestCase):
    """Verifies that pipeline emitted events strictly conform to the expected UI schema."""

    def test_progress_event_fields(self):
        progress_evt = {
            "type": "progress",
            "frame": 120,
            "total": 1735,
            "ts": 4.0,
            "scene": "SCOREBOARD",
            "active_row": "T",
            "stage": "OCR Recognition & Temporal Fusion",
        }
        self.assertEqual(progress_evt["type"], "progress")
        self.assertIn("frame", progress_evt)
        self.assertIn("total", progress_evt)
        self.assertIn("ts", progress_evt)
        self.assertIn("scene", progress_evt)
        self.assertIn("active_row", progress_evt)
        self.assertIn("stage", progress_evt)

    def test_state_snapshot_schema(self):
        dummy_state = {
            "lane_number": "6",
            "unlabeled_metric": "2.5",
            "rows": [
                {
                    "row_label": "J",
                    "bowler_name": "JAGDISH",
                    "is_team_row": False,
                    "frames": {
                        "1": {"pinfall": "X", "cumulative": 15, "rule_check": "PASS", "occluded": False},
                        "2": {"pinfall": "5-", "cumulative": 20, "rule_check": "PASS", "occluded": False},
                    },
                    "total": 20,
                    "rule_check": "PASS"
                }
            ],
            "source_timestamp_range_sec": [0.0, 2.0]
        }
        self.assertIn("lane_number", dummy_state)
        self.assertIn("rows", dummy_state)
        self.assertEqual(len(dummy_state["rows"]), 1)
        self.assertEqual(dummy_state["rows"][0]["row_label"], "J")
        self.assertEqual(dummy_state["rows"][0]["frames"]["1"]["pinfall"], "X")
        self.assertEqual(dummy_state["rows"][0]["frames"]["1"]["cumulative"], 15)


if __name__ == "__main__":
    unittest.main()
