"""
main.py -- End-to-end ScoreVision pipeline orchestrator.

Run from the repo root:
  python src/main.py

Outputs:
  output/scoreboard_state.json   (full §3 schema)
  output/scoreboard_state.csv    (flattened, one row per bowler×frame)
  output/state_timeline.json     (per-frame state history)
  output/debug/ocr_raw_candidates.json (raw OCR detections)
"""

import cv2
import numpy as np
import os, sys, time, json
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from scene_gate import compute_frame_diff, compute_blue_coverage, classify_frame, compute_structural_edge_density
from cell_extractor import apply_quality_gates
from ocr_engine import ocr_all_valid_cells, save_raw_candidates_log, get_reader
from temporal_fusion import StateTracker
from bowling_rules import check_rules
from exporter import export_to_json, export_to_csv, self_check


def _read_unlabeled_metric(frame: np.ndarray) -> str:
    """
    OCR the bottom-left 'unlabeled metric' (e.g. '2.5') using EasyOCR.
    Only called once per run (value changes slowly).
    """
    x1, y1, x2, y2 = config.UNLABELED_METRIC_ROI
    crop   = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    gray   = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    padded = cv2.copyMakeBorder(gray, 20, 20, 20, 20,
                                cv2.BORDER_CONSTANT, value=int(gray.mean()))
    results = get_reader().readtext(padded, allowlist='0123456789.', detail=0,
                                    mag_ratio=2.0)
    return results[0].strip() if results else None


def _detect_active_row(frame: np.ndarray) -> tuple:
    """
    Detect which bowler row is currently active from pinfall left-edge saturation.
    Returns (row_label or None, saturation_value).
    """
    max_sat = 0
    active_row = None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    
    for row, (x1, y1, x2, y2) in config.ACTIVE_ROW_SAMPLE_PATCHES.items():
        patch = hsv[y1:y2, x1:x2]
        sat = float(np.mean(patch[:, :, 1]))
        if sat > max_sat:
            max_sat = sat
            active_row = row
            
    if max_sat >= config.ACTIVE_ROW_SAT_THRESHOLD:
        return active_row, max_sat
    return None, max_sat


def _read_header_name(frame: np.ndarray) -> str:
    """OCR the header marquee region for the active bowler name."""
    crop = frame[15:85, 266:1400]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    padded = cv2.copyMakeBorder(norm, 20, 20, 20, 20, cv2.BORDER_CONSTANT,
                                value=int(np.median(norm)))
    res = get_reader().readtext(padded, allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ ',
                                detail=0, mag_ratio=1.5)
    return " ".join(res).strip() if res else ""


def main():
    video_path  = os.path.join("data", "bowling_scoreboard.mp4")
    output_json = os.path.join("output", "scoreboard_state.json")
    output_csv  = os.path.join("output", "scoreboard_state.csv")
    cache_path  = os.path.join("output", "debug", "scene_gate_results.json")

    if not os.path.exists(video_path):
        print(f"Error: {video_path} not found.")
        return

    print("=" * 60)
    print("ScoreVision  —  End-to-End Extraction Pipeline")
    print("=" * 60)

    # ── Load scene-gate cache (built in Phase 2 with 3-signal gate) ───────────
    is_scoreboard: dict = {}
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            for item in json.load(f):
                is_scoreboard[item["frame_idx"]] = (item["classification"] == "SCOREBOARD")
        sb_count = sum(is_scoreboard.values())
        ca_count = len(is_scoreboard) - sb_count
        print(f"Scene-gate cache loaded: {sb_count} SCOREBOARD / {ca_count} CUTAWAY frames.")
    else:
        print("Warning: no scene-gate cache found; will classify statelessly per frame.")

    cap = cv2.VideoCapture(video_path)
    fps          = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    step    = int(fps / config.PROCESSING_FPS) if config.PROCESSING_FPS > 0 else 1
    tracker = StateTracker(k_frames=config.TEMPORAL_MIN_CONSISTENT_FRAMES)
    state_timeline = {}

    prev_frame       = None
    scoreboard_seen  = 0
    cutaway_seen     = 0
    unlabeled_metric = None
    name_votes       = {r: [] for r in ["J", "V", "P", "T"]}
    start            = time.time()

    frame_idx = 0
    while frame_idx < total_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        ts = frame_idx / fps

        # ── 1. Scene Gate ────────────────────────────────────────────────────
        if frame_idx in is_scoreboard:
            is_sb = is_scoreboard[frame_idx]
        else:
            diff      = compute_frame_diff(prev_frame, frame) if prev_frame is not None else 0.0
            blue_cov  = compute_blue_coverage(frame)
            edge_dens = compute_structural_edge_density(frame)
            is_sb     = (classify_frame(diff, blue_cov, edge_dens) == "SCOREBOARD")

        if not is_sb:
            cutaway_seen += 1
            if cutaway_seen <= 5:
                print(f"  [{ts:.1f}s] Frame {frame_idx}: CUTAWAY")
            prev_frame = None
            frame_idx += step
            continue

        scoreboard_seen += 1

        # ── 2. Bowler Name & Active Row Extraction ───────────────────────────
        active_row, sat = _detect_active_row(frame)
        if active_row:
            header_name = _read_header_name(frame)
            if header_name:
                name_votes[active_row].append(header_name)
                # If we have consistent reads, update tracker bowler name
                v_counts = Counter(name_votes[active_row])
                top_name, top_cnt = v_counts.most_common(1)[0]
                if top_cnt >= 2:
                    tracker.set_bowler_name(active_row, top_name)

        # ── 3. Unlabeled metric (grab once from first clean frame) ────────────
        if unlabeled_metric is None:
            unlabeled_metric = _read_unlabeled_metric(frame)
            if unlabeled_metric:
                print(f"  [{ts:.1f}s] Unlabeled metric OCR'd: '{unlabeled_metric}'")

        # ── 4. Quality Gate + Occlusion Mask ─────────────────────────────────
        valid_cells = apply_quality_gates(frame, prev_frame)
        prev_frame  = frame.copy()

        cells_clear = sum(
            1 for r in valid_cells.values()
            for sub in r.values()
            for c in sub
            if c is not None and not c["occluded"]
        )
        cells_occ = sum(
            1 for r in valid_cells.values()
            for sub in r.values()
            for c in sub
            if c is not None and c["occluded"]
        )

        if cells_clear == 0 and cells_occ == 0:
            print(f"  [{ts:.1f}s] Frame {frame_idx}: all cells rejected by quality gate — skip")
            frame_idx += step
            continue

        # ── 5. OCR ───────────────────────────────────────────────────────────
        print(f"  [{ts:.1f}s] Frame {frame_idx}: "
              f"{cells_clear} clear + {cells_occ} occluded cells — running OCR...")
        raw_strings = ocr_all_valid_cells(valid_cells, timestamp_sec=ts)

        # ── 6. Temporal Fusion ───────────────────────────────────────────────
        state = tracker.update(raw_strings, timestamp_sec=ts)
        state_with_rules = check_rules(state)["annotated_state"]
        state_timeline[str(frame_idx)] = state_with_rules

        frame_idx += step

    cap.release()

    # Save state timeline
    timeline_path = os.path.join("output", "state_timeline.json")
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(state_timeline, f, indent=2)
    print(f"Saved state timeline ({len(state_timeline)} steps) -> {timeline_path}")

    # Save raw candidate OCR detections for debugging/traceability
    save_raw_candidates_log("output/debug/ocr_raw_candidates.json")

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"Pipeline complete: {scoreboard_seen} SCOREBOARD / {cutaway_seen} CUTAWAY frames")
    print(f"Processing time: {elapsed:.1f}s")
    print(f"{'='*60}")

    # ── 7. Inject unlabeled metric & finalize names ───────────────────────────
    final_state = tracker.committed
    final_state["unlabeled_metric"] = unlabeled_metric

    # ── 8. Domain Rule Check ─────────────────────────────────────────────────
    result = check_rules(final_state)
    ann    = result["annotated_state"]
    nc     = result["total_checks"]
    nm     = result["mismatches"]
    rate   = result["mismatch_rate"]

    if rate is not None:
        print(f"Rule check: {nc} cells checked | {nm} FAIL | {nc-nm} PASS | "
              f"mismatch rate = {rate:.1%}  (sample size = {nc})")
    else:
        print("Rule check: 0 cells were verifiable (game may not have started).")

    # ── 9. Export ─────────────────────────────────────────────────────────────
    os.makedirs("output", exist_ok=True)
    export_to_json(ann, output_json)
    export_to_csv(ann,  output_csv)

    print("\nRunning JSON/CSV consistency self-check...")
    self_check(output_json, output_csv)

    # ── 10. Log specific misreads ────────────────────────────────────────────
    print("\nMismatch details:")
    found_any = False
    for row_data in ann.get("rows", []):
        rl = row_data["row_label"]
        for fn, fdata in row_data.get("frames", {}).items():
            if fdata.get("rule_check") == "FAIL":
                print(f"  Row {rl} Frame {fn}: "
                       f"pinfall='{fdata['pinfall']}'  "
                       f"OCR cumulative={fdata['cumulative']}  "
                       f"computed={fdata.get('computed_cumulative')}")
                found_any = True
    if not found_any:
        print("  (none)")

    print("\nDone.")


if __name__ == "__main__":
    main()
