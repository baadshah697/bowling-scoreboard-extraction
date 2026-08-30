"""
annotate_video.py -- Generates the final annotated output video.

Phase 12 of the ScoreVision pipeline.

Key design rules:
  1. SCENE GATE runs per-frame. Cutaway frames get NO grid/text overlay drawn.
  2. The overlay reflects the LIVE committed state at each frame.
  3. Ghosting prevention: clear/draw cell background patch cleanly so no stale text persists.
  4. Visual occlusion marker: draw clear gray hatch + 'OCC' tag when occluded.
"""

import cv2
import json
import numpy as np
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from scene_gate import compute_frame_diff, compute_blue_coverage, classify_frame, compute_structural_edge_density
from cell_extractor import apply_quality_gates
from ocr_engine import ocr_all_valid_cells
from temporal_fusion import StateTracker
from bowling_rules import check_rules


# ──────────────────────────────────────────────────────────────────────────────
# Drawing helpers
# ──────────────────────────────────────────────────────────────────────────────

def _draw_scoreboard_gate(frame: np.ndarray) -> np.ndarray:
    """Draw a teal 'SCOREBOARD' label in the top-left corner."""
    cv2.rectangle(frame, (0, 0), (280, 36), (128, 128, 0), -1)
    cv2.putText(frame, "SCOREBOARD", (8, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return frame


def _draw_cutaway_gate(frame: np.ndarray) -> np.ndarray:
    """Draw a red 'CUTAWAY - no board' label only. No grid drawn."""
    cv2.rectangle(frame, (0, 0), (380, 36), (0, 0, 180), -1)
    cv2.putText(frame, "CUTAWAY - no board detected", (8, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return frame


def _draw_grid(frame: np.ndarray) -> np.ndarray:
    """Draw the calibrated grid lines in dim green."""
    col = (0, 200, 0)
    for x in config.COL_X_BOUNDS:
        cv2.line(frame, (x, config.BOARD_ROI[1]), (x, config.BOARD_ROI[3]), col, 1)
    for row_data in config.ROW_BANDS.values():
        for y in (row_data["pinfall"][1], row_data["pinfall"][3],
                  row_data["cumulative"][3]):
            cv2.line(frame, (config.FRAME_COL_X_START, y),
                     (config.FRAME_COL_X_END, y), col, 1)
    return frame


def _draw_state(frame: np.ndarray, state: dict) -> np.ndarray:
    """Overlay committed OCR values and rule-check results on the frame."""
    if not state:
        return frame

    font = cv2.FONT_HERSHEY_SIMPLEX

    for row_data in state.get("rows", []):
        row_label = row_data["row_label"]
        row_bands = config.ROW_BANDS.get(row_label)
        if row_bands is None:
            continue

        pf_y1  = row_bands["pinfall"][1]
        pf_y2  = row_bands["pinfall"][3]
        cum_y1 = row_bands["cumulative"][1]
        cum_y2 = row_bands["cumulative"][3]

        for key, fdata in row_data.get("frames", {}).items():
            col_idx = int(key) - 1
            if not (0 <= col_idx < config.NUM_FRAME_COLUMNS):
                continue

            x1 = config.COL_X_BOUNDS[col_idx]
            x2 = config.COL_X_BOUNDS[col_idx + 1]

            pf_text  = fdata.get("pinfall", "")
            cum_val  = fdata.get("cumulative")
            cum_text = str(cum_val) if cum_val is not None else ""
            rule_chk = fdata.get("rule_check", "")
            occluded = fdata.get("occluded", False)

            if occluded:
                # Visual OCC marker (gray box + label)
                overlay = frame.copy()
                cv2.rectangle(overlay, (x1+2, pf_y1+2), (x2-2, cum_y2-2), (80, 80, 80), -1)
                cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
                cv2.rectangle(frame, (x1+2, pf_y1+2), (x2-2, cum_y2-2), (180, 180, 180), 2)
                cv2.putText(frame, "OCC", (x1 + 30, (pf_y1 + cum_y2) // 2 + 8),
                            font, 0.7, (220, 220, 220), 2)
                continue

            # Color by rule check
            if rule_chk == "FAIL":
                border_color = (0, 0, 255)
                text_color = (0, 0, 255)
                cv2.rectangle(frame, (x1+2, cum_y1+2), (x2-2, cum_y2-2), border_color, 2)
            elif rule_chk == "PASS":
                border_color = (0, 220, 0)
                text_color = (0, 255, 0)
                cv2.rectangle(frame, (x1+2, cum_y1+2), (x2-2, cum_y2-2), border_color, 1)
            else:
                text_color = (220, 220, 220)

            # Draw small HUD banner with extracted text at bottom of cell
            if pf_text:
                cv2.putText(frame, pf_text,
                            (x1 + 8, pf_y2 - 6), font, 0.65,
                            (255, 255, 255), 2)
            if cum_text:
                cv2.putText(frame, cum_text,
                            (x1 + 10, cum_y2 - 8), font, 0.85,
                            text_color, 2)

    return frame


# ──────────────────────────────────────────────────────────────────────────────
# Main generator
# ──────────────────────────────────────────────────────────────────────────────

def generate_video(
    video_path: str = "data/bowling_scoreboard.mp4",
    output_path: str = "output/annotated_video.mp4",
    scene_gate_cache_path: str = "output/debug/scene_gate_results.json",
):
    if not os.path.exists(video_path):
        print(f"Error: {video_path} not found.")
        return 0, 0

    is_scoreboard: dict = {}
    if os.path.exists(scene_gate_cache_path):
        with open(scene_gate_cache_path) as f:
            for item in json.load(f):
                is_scoreboard[item["frame_idx"]] = (item["classification"] == "SCOREBOARD")
        print(f"Loaded scene-gate cache: {sum(is_scoreboard.values())} SCOREBOARD / "
              f"{sum(1 for v in is_scoreboard.values() if not v)} CUTAWAY frames.")

    cap  = cv2.VideoCapture(video_path)
    fps  = cap.get(cv2.CAP_PROP_FPS)
    w    = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h    = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out    = cv2.VideoWriter(output_path, fourcc, fps, (w, h))

    print("=" * 60)
    print("Phase 12: Generating Annotated Video (live state per-frame)")
    print("=" * 60)

    state_timeline_path = "output/state_timeline.json"
    timeline = {}
    if os.path.exists(state_timeline_path):
        with open(state_timeline_path, encoding="utf-8") as f:
            raw_tl = json.load(f)
            timeline = {int(k): v for k, v in raw_tl.items()}
        print(f"Loaded state timeline ({len(timeline)} checkpoints).")

    ocr_step   = int(fps / config.PROCESSING_FPS) if config.PROCESSING_FPS > 0 else 1
    tracker    = StateTracker(k_frames=config.TEMPORAL_MIN_CONSISTENT_FRAMES) if not timeline else None
    committed  = {}
    prev_frame = None

    timeline_keys = sorted(timeline.keys()) if timeline else []
    scoreboard_frames = 0
    cutaway_frames    = 0

    for frame_idx in range(total_frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        # 1. SCENE GATE
        if frame_idx in is_scoreboard:
            is_sb = is_scoreboard[frame_idx]
        else:
            diff      = compute_frame_diff(prev_frame, frame) if prev_frame is not None else 0.0
            blue_cov  = compute_blue_coverage(frame)
            edge_dens = compute_structural_edge_density(frame)
            is_sb     = (classify_frame(diff, blue_cov, edge_dens) == "SCOREBOARD")

        annotated = frame.copy()

        if not is_sb:
            cutaway_frames += 1
            _draw_cutaway_gate(annotated)
            prev_frame = None
            out.write(annotated)
            continue

        scoreboard_frames += 1

        # 2. Determine current state
        if timeline:
            latest_k = None
            for k in timeline_keys:
                if k <= frame_idx:
                    latest_k = k
                else:
                    break
            if latest_k is not None:
                committed = timeline[latest_k]
        else:
            if frame_idx % ocr_step == 0:
                valid_cells = apply_quality_gates(frame, prev_frame)
                raw_strings = ocr_all_valid_cells(valid_cells)
                state       = tracker.update(raw_strings, timestamp_sec=frame_idx / fps)
                result      = check_rules(state)
                committed   = result["annotated_state"]

        prev_frame = frame.copy()

        # 3. Draw grid + live committed state
        _draw_scoreboard_gate(annotated)
        _draw_grid(annotated)
        _draw_state(annotated, committed)

        out.write(annotated)

        if frame_idx % 300 == 0:
            print(f"  Frame {frame_idx}/{total_frames} - "
                  f"SCOREBOARD:{scoreboard_frames}, CUTAWAY:{cutaway_frames}")

    cap.release()
    out.release()

    print(f"\nDone. Total: {total_frames} frames | "
          f"SCOREBOARD: {scoreboard_frames} | CUTAWAY: {cutaway_frames}")
    print(f"Output: {output_path}")
    return scoreboard_frames, cutaway_frames


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sc, ca = generate_video()
    print(f"\nVerification counts: SCOREBOARD={sc}, CUTAWAY={ca}")
