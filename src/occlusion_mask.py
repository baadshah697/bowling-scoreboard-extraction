"""
occlusion_mask.py -- Per-frame pin-icon occlusion detection.

Phase 5 of the ScoreVision pipeline.
Detects whether the bowling-pin animated graphic is present in the board's
right-column area by measuring white pixel fraction inside the known bounding box.
Returns a per-cell boolean mask (True = occluded, skip OCR for this frame).

Measured signal (2026-08-29, bowling_scoreboard.mp4):
  t=0s  (no icon): white_frac = 0.0223
  t=20s (icon):    white_frac = 0.1101
  t=57s (icon):    white_frac = 0.1162
Threshold = 0.05 (large margin above clean board, well below observed icon values).
"""

import cv2
import numpy as np
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def icon_present(frame: np.ndarray) -> bool:
    """
    Return True if the animated pin-icon graphic is visible in the detection area.
    Uses the white-pixel fraction of the known bounding box.
    """
    if frame is None or frame.size == 0:
        return False
    x1, y1, x2, y2 = config.PIN_ICON_DETECTION_AREA
    region = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    # White: low saturation, high value
    white_mask = cv2.inRange(hsv,
                             np.array([0,   0, 200]),
                             np.array([180, 30, 255]))
    total = region.shape[0] * region.shape[1]
    white_frac = np.count_nonzero(white_mask) / total
    return white_frac > config.PIN_ICON_WHITE_FRAC_THRESHOLD


def build_occlusion_mask(frame: np.ndarray) -> dict:
    """
    Returns a nested dict with the same shape as valid_cells:
      mask[row][subrow][col] = True  (occluded, skip OCR)
                             = False (clear, proceed)

    The pin-icon overlaps roughly columns 7-10 (indices 6-9) of rows J and V
    when present. We determine occlusion based on geometric intersection.
    """
    icon = icon_present(frame)

    mask = {}
    for row in ["J", "V", "P", "T"]:
        mask[row] = {"pinfall": [False] * config.NUM_FRAME_COLUMNS,
                     "cumulative": [False] * config.NUM_FRAME_COLUMNS}
        if not icon:
            continue  # no icon -> no occlusion anywhere this frame
        for subrow in ["pinfall", "cumulative"]:
            for col in range(config.NUM_FRAME_COLUMNS):
                x1, y1, x2, y2 = _cell_coords(row, subrow, col)
                if _intersects_icon(x1, y1, x2, y2):
                    mask[row][subrow][col] = True
    return mask


def _cell_coords(row: str, subrow: str, col: int):
    y1 = config.ROW_BANDS[row][subrow][1]
    y2 = config.ROW_BANDS[row][subrow][3]
    x1 = config.COL_X_BOUNDS[col]
    x2 = config.COL_X_BOUNDS[col + 1]
    return x1, y1, x2, y2


def _intersects_icon(x1, y1, x2, y2) -> bool:
    px1, py1, px2, py2 = config.PIN_ICON_DETECTION_AREA
    # Overlap if horizontal and vertical intervals intersect
    return (x1 < px2 and x2 > px1 and y1 < py2 and y2 > py1)


if __name__ == "__main__":
    cap = cv2.VideoCapture("data/bowling_scoreboard.mp4")
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0); ret, f0 = cap.read()
    cap.set(cv2.CAP_PROP_POS_FRAMES, 600); ret, f20 = cap.read()
    cap.release()

    print(f"t=0s (frame 0) icon present: {icon_present(f0)}")
    print(f"t=20s (frame 600) icon present: {icon_present(f20)}")
    mask_20 = build_occlusion_mask(f20)
    for r in ["J", "V", "P", "T"]:
        print(f"Row {r} pf occluded cols:", [i+1 for i, v in enumerate(mask_20[r]["pinfall"]) if v])
        print(f"Row {r} cum occluded cols:", [i+1 for i, v in enumerate(mask_20[r]["cumulative"]) if v])
