"""
temporal_fusion.py -- Confidence-weighted state machine per cell.

Phase 7 of the ScoreVision pipeline.
Holds the committed value for each cell; a differing reading only overwrites
it after it repeats across >= K independent frames. Absorbs one-off misreads.

Key design choices:
  - None raw strings (occluded cells) are IGNORED by the state machine:
    they don't count as a vote, and they don't reset the vote buffer.
  - Empty string '' means OCR ran but found nothing.
  - On candidate disagreement: majority vote on the WHOLE STRING candidate,
    NEVER concatenate.
  - Cumulative values: validated with bowling domain bounds
    (monotonic non-decreasing, max 30 per frame: prev_cum <= cum <= prev_cum + 30, and cum <= (col+1)*30).
  - Bowler names: populated dynamically from OCR'd marquee text, with all rows
    classified as individual bowlers (is_team_row: false) per video evidence.
"""

import re
from collections import Counter
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


# ──────────────────────────────────────────────────────────────────────────────
# Text cleaning & validation helpers
# ──────────────────────────────────────────────────────────────────────────────

def clean_pinfall(raw: str) -> str:
    if raw is None or raw == "":
        return ""
    cleaned = raw.replace(" ", "").upper()
    cleaned = re.sub(r'[^0-9X/\-]', '', cleaned)
    return cleaned


def clean_cumulative(raw) -> int:
    """Return int or None. Accepts str or int."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, int):
        return raw if 0 <= raw <= 300 else None
    digits = re.sub(r'[^0-9]', '', str(raw))
    try:
        val = int(digits) if digits else None
        if val is not None and 0 <= val <= 300:
            return val
        return None
    except ValueError:
        return None


def is_valid_cumulative_transition(candidate: int, prev_col_cum: int, col_idx: int) -> bool:
    """
    Validates candidate cumulative score using ten-pin bowling domain rules:
    1. Maximum possible score for frame (col_idx+1) is (col_idx+1) * 30.
    2. If previous frame has a cumulative score V_prev, candidate must satisfy:
       V_prev <= candidate <= V_prev + 30.
    """
    if candidate is None:
        return False
    max_for_col = (col_idx + 1) * 30
    if candidate > max_for_col:
        return False
    if prev_col_cum is not None:
        if candidate < prev_col_cum:
            return False
        if candidate > prev_col_cum + 30:
            return False
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Per-cell vote buffer
# ──────────────────────────────────────────────────────────────────────────────

class _CellState:
    """State machine for a single (row, subrow, col) cell."""

    def __init__(self, k: int):
        self.k = k
        self.committed_value = None   # str for pinfall, int|None for cumulative
        self.committed_conf  = 0.0
        self.vote_buffer     = []     # rolling window of non-None reads
        self.occluded_this_frame = False

    def update(self, raw_value, is_pinfall: bool, prev_col_cum: int = None, col_idx: int = 0) -> tuple:
        """
        Feed a new raw reading.
        raw_value = None  -> occluded (skip)
        raw_value = ''    -> OCR ran, nothing found
        raw_value = str   -> OCR result

        Returns (committed_value, confidence, occluded).
        """
        self.occluded_this_frame = (raw_value is None)
        if raw_value is None:
            return self.committed_value, self.committed_conf, True

        cleaned = clean_pinfall(raw_value) if is_pinfall else clean_cumulative(raw_value)

        # For cumulative, filter out physically impossible candidates immediately
        if not is_pinfall and cleaned is not None:
            if not is_valid_cumulative_transition(cleaned, prev_col_cum, col_idx):
                cleaned = None

        if cleaned not in ("", None):
            self.vote_buffer.append(cleaned)
            if len(self.vote_buffer) > self.k:
                self.vote_buffer.pop(0)

            # Require K consistent non-empty reads
            if len(self.vote_buffer) == self.k:
                counter = Counter(self.vote_buffer)
                top_val, top_cnt = counter.most_common(1)[0]
                if top_cnt == self.k:
                    if is_pinfall and self.committed_value:
                        curr_is_complete = (self.committed_value == 'X' or len(self.committed_value) >= 2)
                        new_is_incomplete = (len(str(top_val)) < 2 and top_val != 'X')
                        # Do not let incomplete 1-character reads (e.g. '4', '7') overwrite complete frames (e.g. '4/', '-7')
                        if curr_is_complete and new_is_incomplete:
                            pass
                        # Do not let misrecognized open frame overwrite established spare
                        elif '/' in self.committed_value and '/' not in str(top_val):
                            pass
                        else:
                            self.committed_value = top_val
                            self.committed_conf  = 1.0
                    elif not is_pinfall and self.committed_value is not None:
                        # Bowling Rule: Cumulative score for a frame cannot decrease once committed
                        if isinstance(top_val, int) and top_val < self.committed_value:
                            pass
                        else:
                            self.committed_value = top_val
                            self.committed_conf  = 1.0
                    else:
                        self.committed_value = top_val
                        self.committed_conf  = 1.0

        return self.committed_value, self.committed_conf, False


# ──────────────────────────────────────────────────────────────────────────────
# Public StateTracker
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_ROW_META = {
    "J": {"bowler_name": "Bowler J",  "is_team_row": False},
    "V": {"bowler_name": "Bowler V",  "is_team_row": False},
    "P": {"bowler_name": "Bowler P",  "is_team_row": False},
    "T": {"bowler_name": "Bowler T",  "is_team_row": False},
}


class StateTracker:
    """
    Maintains temporal-fusion state for all 4 rows x 10 columns.
    Produces the committed scoreboard state in the §3 locked schema format.
    """

    def __init__(self, k_frames: int = None, lane_number: str = None):
        self.k           = k_frames or config.TEMPORAL_MIN_CONSISTENT_FRAMES
        self.lane_number = lane_number
        self.bowler_names = {r: meta["bowler_name"] for r, meta in DEFAULT_ROW_META.items()}
        self._cells: dict = {}          # (row, subrow, col) -> _CellState
        self._source_ts: list = []      # timestamps of processed frames

        for row in ["J", "V", "P", "T"]:
            for subrow in ["pinfall", "cumulative"]:
                for col in range(config.NUM_FRAME_COLUMNS):
                    self._cells[(row, subrow, col)] = _CellState(self.k)

    def set_bowler_name(self, row: str, name: str):
        if row in self.bowler_names and name:
            self.bowler_names[row] = name

    def set_lane_number(self, lane: str):
        if lane:
            self.lane_number = lane

    def update(self, raw_strings: dict, timestamp_sec: float = None) -> dict:
        """
        Process one frame's raw OCR strings.
        Returns the full committed state dict in §3 schema format.
        """
        if timestamp_sec is not None:
            self._source_ts.append(timestamp_sec)

        for row in ["J", "V", "P", "T"]:
            # Update pinfalls first
            for col in range(config.NUM_FRAME_COLUMNS):
                raw_pf = raw_strings[row]["pinfall"][col]
                self._cells[(row, "pinfall", col)].update(raw_pf, is_pinfall=True, col_idx=col)

            # Update cumulatives with monotonic domain validation
            prev_cum = None
            for col in range(config.NUM_FRAME_COLUMNS):
                raw_cum = raw_strings[row]["cumulative"][col]
                val, conf, occ = self._cells[(row, "cumulative", col)].update(
                    raw_cum, is_pinfall=False, prev_col_cum=prev_cum, col_idx=col
                )
                if val is not None:
                    prev_cum = val

        return self._build_schema()

    @property
    def committed(self) -> dict:
        """Current committed state without feeding new data."""
        return self._build_schema()

    def _build_schema(self) -> dict:
        """Produce a dict matching §3 of ScoreVision_ARCHITECTURE.md."""
        ts_range = (
            [round(self._source_ts[0], 2), round(self._source_ts[-1], 2)]
            if self._source_ts else [0, 0]
        )

        rows_out = []
        for row in ["J", "V", "P", "T"]:
            frames_out = {}
            max_cum = None

            for col in range(config.NUM_FRAME_COLUMNS):
                frame_key = str(config.FRAME_COLUMN_INDEX[col])
                pf_state  = self._cells[(row, "pinfall",    col)]
                cum_state = self._cells[(row, "cumulative", col)]

                pf_val  = pf_state.committed_value
                cum_val = cum_state.committed_value
                conf = round((pf_state.committed_conf + cum_state.committed_conf) / 2, 4)
                occ  = pf_state.occluded_this_frame or cum_state.occluded_this_frame

                if pf_val or cum_val is not None or occ:
                    frames_out[frame_key] = {
                        "pinfall":    pf_val  if pf_val  is not None else "",
                        "cumulative": cum_val,
                        "confidence": conf,
                        "occluded":   occ,
                    }
                    if cum_val is not None:
                        if max_cum is None or cum_val > max_cum:
                            max_cum = cum_val

            rows_out.append({
                "row_label":    row,
                "bowler_name":  self.bowler_names.get(row, DEFAULT_ROW_META[row]["bowler_name"]),
                "is_team_row":  False,  # Verified: all 4 rows are individual bowlers (Tarun, Vishal, Jagdish, Pawan)
                "frames":       frames_out,
                "total":        max_cum,
                "rule_check":   "UNKNOWN",   # overwritten by bowling_rules
            })

        return {
            "lane_number":              self.lane_number,
            "rows":                     rows_out,
            "unlabeled_metric":         None,   # filled by main.py
            "source_timestamp_range_sec": ts_range,
        }
