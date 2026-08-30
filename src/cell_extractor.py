"""
cell_extractor.py -- Extracts individual grid cells and applies quality + occlusion gates.

Phases 4+5 of the ScoreVision pipeline.
Responsibilities:
  1. Crop individual cells for pinfall and cumulative totals using inset margins.
     - Pinfall sub-row uses PINFALL_CELL_INSET_RIGHT (2px) so trailing `-` and `/`
       strokes are not clipped at the right column boundary.
     - Cumulative sub-row uses CELL_INSET_RIGHT (6px).
  2. Transition quality gate: skip cells that are mid-roll-over
     (local frame-to-frame diff exceeds threshold).
  3. Occlusion gate: if the pin-icon graphic covers a cell THIS frame, 
     mark it occluded=True so OCR is skipped; recovery comes from temporal
     fusion using clean neighbouring frames.

Returns:
  valid_cells[row][subrow][col] = {'img': np.ndarray | None, 'occluded': bool}
  None img means transition-rejected; occluded=True means icon-covered.
"""

import cv2
import numpy as np
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from occlusion_mask import build_occlusion_mask


def get_cell_coordinates(row_label: str, subrow_type: str, col_idx: int, apply_inset: bool = True):
    """
    Get bounding box coordinates (x1, y1, x2, y2) for a cell.
    apply_inset trims horizontal margins to prevent adjacent divider line/character bleed.
    """
    y1 = config.ROW_BANDS[row_label][subrow_type][1]
    y2 = config.ROW_BANDS[row_label][subrow_type][3]
    x1 = config.COL_X_BOUNDS[col_idx]
    x2 = config.COL_X_BOUNDS[col_idx + 1]
    
    if apply_inset:
        x1 += config.CELL_INSET_LEFT
        inset_r = config.PINFALL_CELL_INSET_RIGHT if subrow_type == "pinfall" else config.CELL_INSET_RIGHT
        x2 -= inset_r
        
    return x1, y1, x2, y2


def check_transition(cell_img: np.ndarray, prev_cell_img: np.ndarray,
                     threshold: float = None) -> bool:
    """Return True if the cell appears to be mid-transition (rolling number)."""
    if prev_cell_img is None:
        return False
    if threshold is None:
        threshold = config.QUALITY_GATE_TRANSITION_THRESHOLD
    gray_curr = cv2.cvtColor(cell_img,  cv2.COLOR_BGR2GRAY)
    gray_prev = cv2.cvtColor(prev_cell_img, cv2.COLOR_BGR2GRAY)
    return float(np.mean(cv2.absdiff(gray_curr, gray_prev))) > threshold


def apply_quality_gates(frame: np.ndarray, prev_frame: np.ndarray) -> dict:
    """
    Extract all 80 cells and apply quality + occlusion gates.

    Returns:
      valid_cells[row][subrow][col] = {
          'img':      np.ndarray crop  or  None  (transition-rejected),
          'occluded': bool              (True = pin icon covers this cell)
      }
    """
    occ_mask = build_occlusion_mask(frame)

    valid_cells = {}
    for row in ["J", "V", "P", "T"]:
        valid_cells[row] = {"pinfall": [None] * config.NUM_FRAME_COLUMNS,
                            "cumulative": [None] * config.NUM_FRAME_COLUMNS}
        for subrow in ["pinfall", "cumulative"]:
            for col in range(config.NUM_FRAME_COLUMNS):
                x1, y1, x2, y2 = get_cell_coordinates(row, subrow, col, apply_inset=True)
                cell_img = frame[y1:y2, x1:x2]
                occluded = occ_mask[row][subrow][col]

                # Transition check (only on non-occluded cells)
                if not occluded and prev_frame is not None:
                    prev_cell = prev_frame[y1:y2, x1:x2]
                    if check_transition(cell_img, prev_cell):
                        # Leave as None (transition-rejected)
                        continue

                valid_cells[row][subrow][col] = {
                    "img":      cell_img if not occluded else None,
                    "occluded": occluded,
                }
    return valid_cells
