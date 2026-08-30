"""
scene_gate.py -- Classifies each frame as SCOREBOARD or CUTAWAY.

Uses a 3-signal approach:
1. Primary: Frame-diff magnitude (mean absolute pixel difference between consecutive
   frames, computed on a 320x180 downscale).
2. Corroborating: HSV blue color coverage in the board ROI.
3. Structural (3rd signal, immune to color/motion failures):
   Canny edge density inside COLUMN_HEADER_BAND (x=266-1656, y=95-140).
   The real board always has high-density white text edges there (frame numbers
   1-10, TTL). Cutaway content cannot reproduce that fixed typographic structure
   at those exact pixel coordinates regardless of its own color or motion.

A frame is classified as SCOREBOARD if:
- Its diff to the previous frame is below SCENE_GATE_DIFF_THRESHOLD
  AND its blue coverage meets SCENE_GATE_BLUE_COVERAGE_MIN
  AND its structural edge density meets SCENE_GATE_EDGE_DENSITY_MIN

Signal calibration (measured from full video, reported in walkthrough):
  SCOREBOARD col_hdr edge density: 0.038–0.061
  Confirmed CUTAWAY (t=40s cartoon, t=43s, t=50s Brunswick): 0.007–0.030
  Threshold: 0.035 (comfortable margin above CUTAWAY max, below SCOREBOARD min)
"""

import cv2
import numpy as np
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# Downscale dimensions for diff computation
DOWNSCALE_W = 320
DOWNSCALE_H = 180


def compute_frame_diff(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
    """
    Compute mean absolute pixel difference between two frames.
    Both frames are downscaled to 320x180 grayscale before comparison.
    Returns mean absolute difference (0-255 range).
    """
    small_a = cv2.resize(frame_a, (DOWNSCALE_W, DOWNSCALE_H))
    small_b = cv2.resize(frame_b, (DOWNSCALE_W, DOWNSCALE_H))
    gray_a = cv2.cvtColor(small_a, cv2.COLOR_BGR2GRAY) if len(small_a.shape) == 3 else small_a
    gray_b = cv2.cvtColor(small_b, cv2.COLOR_BGR2GRAY) if len(small_b.shape) == 3 else small_b
    diff = cv2.absdiff(gray_a, gray_b)
    return float(np.mean(diff))


def compute_blue_coverage(frame: np.ndarray, roi: tuple = None) -> float:
    """
    Compute the fraction of pixels within the ROI that fall in the
    board's blue HSV range.

    Args:
        frame: BGR frame (full resolution)
        roi: (x1, y1, x2, y2) region to analyze. Defaults to BOARD_ROI.

    Returns:
        float: fraction of ROI pixels that are blue (0.0 to 1.0)
    """
    if roi is None:
        roi = config.BOARD_ROI
    x1, y1, x2, y2 = roi
    region = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(hsv,
                            np.array(config.BOARD_BLUE_HSV_LOWER),
                            np.array(config.BOARD_BLUE_HSV_UPPER))
    total_pixels = blue_mask.shape[0] * blue_mask.shape[1]
    blue_pixels = np.count_nonzero(blue_mask)
    return blue_pixels / total_pixels if total_pixels > 0 else 0.0


def compute_structural_edge_density(frame: np.ndarray) -> float:
    """
    Compute Canny edge density inside SCENE_GATE_EDGE_DENSITY_REGIONS.

    The real board's column header band (frame numbers 1-10, TTL) always
    produces high-density white text edges. Cutaway content (cartoon, logo)
    does not reproduce that fixed structure at those exact pixel coordinates.

    Returns:
        float: mean Canny edge pixel fraction across all configured regions
    """
    densities = []
    for (x1, y1, x2, y2) in config.SCENE_GATE_EDGE_DENSITY_REGIONS:
        region = frame[y1:y2, x1:x2]
        if region.size == 0:
            continue
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) if len(region.shape) == 3 else region
        edges = cv2.Canny(gray, 50, 150)
        density = np.count_nonzero(edges) / edges.size
        densities.append(density)
    return float(np.mean(densities)) if densities else 0.0


def classify_frame(diff_value: float, blue_coverage: float,
                   edge_density: float = None,
                   diff_threshold: float = None,
                   blue_threshold: float = None,
                   edge_threshold: float = None) -> str:
    """
    Classify a frame as SCOREBOARD or CUTAWAY.

    All three signals must agree for SCOREBOARD. This prevents any single
    signal's failure mode from causing a misclassification.

    Args:
        diff_value: frame-to-frame diff (0 = identical frames)
        blue_coverage: fraction of BOARD_ROI pixels that are HSV-blue
        edge_density: Canny edge density in structural regions (3rd signal)
                      If None, the structural check is skipped (backward compat).
        diff_threshold: override config.SCENE_GATE_DIFF_THRESHOLD
        blue_threshold: override config.SCENE_GATE_BLUE_COVERAGE_MIN
        edge_threshold: override config.SCENE_GATE_EDGE_DENSITY_MIN
    """
    if diff_threshold is None:
        diff_threshold = config.SCENE_GATE_DIFF_THRESHOLD
    if blue_threshold is None:
        blue_threshold = config.SCENE_GATE_BLUE_COVERAGE_MIN
    if edge_threshold is None:
        edge_threshold = config.SCENE_GATE_EDGE_DENSITY_MIN

    is_stable = diff_value <= diff_threshold
    has_blue = blue_coverage >= blue_threshold
    has_structure = (edge_density is None) or (edge_density >= edge_threshold)

    if is_stable and has_blue and has_structure:
        return "SCOREBOARD"
    else:
        return "CUTAWAY"


def run_scene_gate(video_path: str, sample_every_n: int = 1,
                   verbose: bool = False, max_frames: int = None) -> list:
    """
    Run the scene gate on the entire video.
    Includes the 3rd structural (edge density) signal per frame.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError("Cannot open video: %s" % video_path)

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if max_frames is not None:
        total_frames = min(total_frames, max_frames)

    results = []
    prev_frame = None
    scoreboard_count = 0
    cutaway_count = 0

    frame_idx = 0
    while frame_idx < total_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        timestamp = frame_idx / fps

        # Signal 1: frame diff
        diff = compute_frame_diff(prev_frame, frame) if prev_frame is not None else 0.0

        # Signal 2: blue coverage
        blue_cov = compute_blue_coverage(frame)

        # Signal 3: structural edge density (immune to color/motion failures)
        edge_dens = compute_structural_edge_density(frame)

        # Classify using all 3 signals
        classification = classify_frame(diff, blue_cov, edge_dens)

        if classification == "SCOREBOARD":
            scoreboard_count += 1
        else:
            cutaway_count += 1

        result = {
            "frame_idx": frame_idx,
            "timestamp": round(timestamp, 3),
            "diff": round(diff, 3),
            "blue_coverage": round(blue_cov, 4),
            "edge_density": round(edge_dens, 4),
            "classification": classification,
        }
        results.append(result)

        if verbose and (frame_idx % 100 == 0 or classification == "CUTAWAY"):
            print("  Frame %4d (t=%.1fs): diff=%.2f blue=%.3f edge=%.3f -> %s" % (
                frame_idx, timestamp, diff, blue_cov, edge_dens, classification), flush=True)

        prev_frame = frame.copy()
        frame_idx += sample_every_n

    cap.release()

    print("\n=== Scene Gate Summary ===")
    print("Total frames processed: %d" % len(results))
    print("SCOREBOARD: %d (%.1f%%)" % (scoreboard_count, 100*scoreboard_count/max(1, len(results))))
    print("CUTAWAY: %d (%.1f%%)" % (cutaway_count, 100*cutaway_count/max(1, len(results))))

    return results


def save_scene_gate_results(results: list, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print("Saved scene gate results to: %s" % output_path)


if __name__ == "__main__":
    video_path = os.path.join(os.path.dirname(__file__), "..", "data", "bowling_scoreboard.mp4")
    output_path = os.path.join(os.path.dirname(__file__), "..", "output", "debug", "scene_gate_results.json")

    print("=" * 60)
    print("Phase 2: Scene Gate (SCOREBOARD vs CUTAWAY classification)")
    print("=" * 60)

    results = run_scene_gate(video_path, sample_every_n=1, verbose=True)
    save_scene_gate_results(results, output_path)

    print("\n" + "=" * 60)
    print("Phase 2 COMPLETE")
    print("=" * 60)
