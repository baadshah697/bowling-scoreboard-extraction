"""
pipeline_runner.py  --  Streaming pipeline worker for ScoreVision.

Located in frontend/
Resolves backend modules from ../src relative to the project root.
Outputs to ../output relative to the project root.

Protocol (one JSON object per line on stdout):
  {"type": "started",   "total": 1735, "fps": 30.0}
  {"type": "progress",  "frame": 120, "total": 1735, "ts": 4.0, "scene": "SCOREBOARD", "active_row": "T", "stage": "Quality Gate & OCR"}
  {"type": "state",     "frame": 120, "ts": 4.0, "state": {...}}
  {"type": "done",      "scoreboard": 1198, "cutaway": 537, "final_state": {...}}
  {"type": "error",     "message": "..."}
"""

import os
import sys
import json
import time
import argparse
from collections import Counter
import cv2
import numpy as np
import torch

# ──────────────────────────────────────────────────────────────────────────────
# Resolve paths relative to project root
# ──────────────────────────────────────────────────────────────────────────────
FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(FRONTEND_DIR, ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config
from scene_gate import compute_frame_diff, compute_blue_coverage, classify_frame, compute_structural_edge_density
from cell_extractor import apply_quality_gates
from ocr_engine import ocr_all_valid_cells, get_reader
from temporal_fusion import StateTracker
from bowling_rules import check_rules
from annotate_video import _draw_scoreboard_gate, _draw_cutaway_gate, _draw_grid, _draw_state


def _read_lane_number(frame: np.ndarray) -> str:
    """OCR the top-left lane number (e.g. '6')."""
    # Crop top-left region containing the lane number
    crop = frame[10:95, 10:200]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    padded = cv2.copyMakeBorder(norm, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=int(np.median(norm)))
    res = get_reader().readtext(padded, allowlist='0123456789', detail=0, mag_ratio=1.5)
    return res[0].strip() if res else None


def _detect_active_row(frame, hsv=None):
    if hsv is None:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    max_sat, active_row = 0, None
    for row, (x1, y1, x2, y2) in config.ACTIVE_ROW_SAMPLE_PATCHES.items():
        patch = hsv[y1:y2, x1:x2]
        sat = float(np.mean(patch[:, :, 1]))
        if sat > max_sat:
            max_sat, active_row = sat, row
    return (active_row if max_sat >= config.ACTIVE_ROW_SAT_THRESHOLD else None), max_sat


def _read_header_name(frame):
    crop = frame[15:85, 266:1400]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    padded = cv2.copyMakeBorder(norm, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=int(np.median(norm)))
    res = get_reader().readtext(padded, allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ ', detail=0, mag_ratio=1.5)
    return " ".join(res).strip() if res else ""


def _read_unlabeled_metric(frame):
    x1, y1, x2, y2 = config.UNLABELED_METRIC_ROI
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    padded = cv2.copyMakeBorder(gray, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=int(gray.mean()))
    results = get_reader().readtext(padded, allowlist='0123456789.', detail=0, mag_ratio=2.0)
    return results[0].strip() if results else None


def emit(obj):
    """Write one JSON line to stdout, flush immediately."""
    print(json.dumps(obj), flush=True)


def _detect_hardware():
    """
    Auto-detect available compute hardware.
    Returns (use_gpu: bool, device_label: str, detail: str)
    """
    force_env = os.environ.get("SCOREVISION_FORCE_CPU", "0") == "1"
    gpu_available = torch.cuda.is_available() and not force_env
    if gpu_available:
        try:
            gpu_name = torch.cuda.get_device_name(0)
        except Exception:
            gpu_name = "NVIDIA GPU"
        num_cores = os.cpu_count() or 1
        label = f"GPU (CUDA) — {gpu_name}"
        detail = f"EasyOCR CRAFT running on {gpu_name} VRAM | {num_cores} CPU threads available"
    else:
        num_cores = os.cpu_count() or 4
        label = f"CPU (Multi-Core SIMD) — {num_cores} Threads"
        detail = f"EasyOCR CRAFT running on {num_cores} CPU threads with SIMD + Temporal Cell Cache"
    return gpu_available, label, detail


def run_pipeline(video_path: str, output_dir: str = None):
    if output_dir is None:
        output_dir = os.path.join(PROJECT_ROOT, "output")
    elif not os.path.isabs(output_dir):
        output_dir = os.path.join(PROJECT_ROOT, output_dir)

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "debug"), exist_ok=True)

    # Ensure video path is absolute
    if not os.path.isabs(video_path):
        video_path = os.path.join(PROJECT_ROOT, video_path)

    if not os.path.exists(video_path):
        emit({"type": "error", "message": f"Input video not found: {video_path}"})
        return

    from ocr_engine import reset_ocr_cache
    reset_ocr_cache()

    # ── Hardware Auto-Detection ──────────────────────────────────────────────
    use_gpu, hw_label, hw_detail = _detect_hardware()
    hw_mode = "GPU" if use_gpu else "CPU"

    # Print to terminal
    print(f"[ScoreVision] Hardware Detected: {hw_label}", flush=True)
    print(f"[ScoreVision] OCR Engine: {hw_detail}", flush=True)

    # Emit event for dashboard
    emit({
        "type": "hardware",
        "mode": hw_mode,
        "label": hw_label,
        "detail": hw_detail,
    })

    # Ensure clean keyframe and preview directory for the new video
    keyframe_dir = os.path.join(output_dir, "debug", "keyframes")
    if os.path.exists(keyframe_dir):
        import shutil
        try:
            shutil.rmtree(keyframe_dir)
        except Exception:
            pass
    os.makedirs(keyframe_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        emit({"type": "error", "message": f"Cannot open video with OpenCV: {video_path}"})
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(fps / config.PROCESSING_FPS))

    # Initialize annotated video writer
    video_out_path = os.path.join(output_dir, "annotated_video.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    video_writer = cv2.VideoWriter(video_out_path, fourcc, float(config.PROCESSING_FPS), (w, h))

    tracker = StateTracker(k_frames=config.TEMPORAL_MIN_CONSISTENT_FRAMES)
    state_timeline = {}
    name_votes = {r: [] for r in ["J", "V", "P", "T"]}
    prev_frame = None
    scoreboard_seen = cutaway_seen = 0
    unlabeled_metric = None
    lane_number = None

    print(f"[ScoreVision] Processing video: {os.path.basename(video_path)} ({total_frames} frames @ {fps:.1f} fps)", flush=True)
    emit({"type": "started", "total": total_frames, "fps": fps, "hw_mode": hw_mode, "hw_label": hw_label})

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step != 0:
            frame_idx += 1
            continue

        ts = frame_idx / fps

        # ── 1. Scene Gate ────────────────────────────────────────────────────
        diff = compute_frame_diff(prev_frame, frame) if prev_frame is not None else 0.0
        blue_cov = compute_blue_coverage(frame)
        edge_dens = compute_structural_edge_density(frame)
        scene_label = classify_frame(diff, blue_cov, edge_dens)
        is_sb = (scene_label == "SCOREBOARD")

        active_row, _ = _detect_active_row(frame) if is_sb else (None, 0)

        if not is_sb:
            cutaway_seen += 1
            cut_v_frame = frame.copy()
            cut_v_frame = _draw_cutaway_gate(cut_v_frame)
            if video_writer is not None:
                video_writer.write(cut_v_frame)
            
            # Save keyframe image for timeline explorer
            try:
                cv2.imwrite(os.path.join(keyframe_dir, f"frame_{frame_idx}.jpg"), cut_v_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            except Exception:
                pass
            
            # Carry over committed state in timeline
            current_state = tracker.committed
            state_timeline[str(frame_idx)] = check_rules(current_state)["annotated_state"]
            prev_frame = None
            frame_idx += 1
            continue

        scoreboard_seen += 1

        # ── 2. Lane Number & Bowler Name ────────────────────────────────────
        if lane_number is None:
            lane_number = _read_lane_number(frame)
            if lane_number:
                tracker.set_lane_number(lane_number)

        if active_row:
            header_name = _read_header_name(frame)
            if header_name:
                name_votes[active_row].append(header_name)
                v_counts = Counter(name_votes[active_row])
                top_name, top_cnt = v_counts.most_common(1)[0]
                if top_cnt >= 2:
                    tracker.set_bowler_name(active_row, top_name)

        # ── 3. Unlabeled Metric ─────────────────────────────────────────────
        if unlabeled_metric is None:
            metric_val = _read_unlabeled_metric(frame)
            if metric_val:
                unlabeled_metric = metric_val

        # ── 4. Cell Quality Gate & OCR ──────────────────────────────────────
        valid_cells = apply_quality_gates(frame, prev_frame)
        prev_frame = frame.copy()
        
        emit({
            "type": "progress",
            "frame": frame_idx,
            "total": total_frames,
            "ts": round(ts, 2),
            "scene": scene_label,
            "active_row": active_row,
            "stage": "OCR Recognition & Temporal Fusion",
            "hw_mode": hw_mode,
        })
        # Also print progress to terminal every 10 scoreboard frames
        if scoreboard_seen % 10 == 1:
            print(f"[ScoreVision] [{hw_mode}] Frame {frame_idx}/{total_frames} ({ts:.1f}s) | Scene: {scene_label} | Row: {active_row}", flush=True)

        raw_strings = ocr_all_valid_cells(valid_cells, timestamp_sec=ts)

        # ── 5. Temporal Fusion & Bowling Rules ──────────────────────────────
        state = tracker.update(raw_strings, timestamp_sec=ts)
        state_with_rules = check_rules(state)["annotated_state"]
        state_timeline[str(frame_idx)] = state_with_rules

        # Build fully annotated frame
        ann_v_frame = frame.copy()
        ann_v_frame = _draw_grid(ann_v_frame)
        ann_v_frame = _draw_state(ann_v_frame, state_with_rules)
        ann_v_frame = _draw_scoreboard_gate(ann_v_frame)

        # Save keyframe image for live preview and timeline explorer
        try:
            keyframe_p = os.path.join(keyframe_dir, f"frame_{frame_idx}.jpg")
            cv2.imwrite(keyframe_p, ann_v_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])

            # Atomic write: write to temp then rename so Streamlit never sees a half-written file
            preview_save_p = os.path.join(output_dir, "debug", "live_preview.jpg")
            preview_tmp_p  = preview_save_p + ".tmp"
            cv2.imwrite(preview_tmp_p, ann_v_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            os.replace(preview_tmp_p, preview_save_p)
        except Exception:
            pass

        # Write annotated video frame
        if video_writer is not None:
            try:
                ann_v_frame = frame.copy()
                ann_v_frame = _draw_grid(ann_v_frame)
                ann_v_frame = _draw_state(ann_v_frame, state_with_rules)
                ann_v_frame = _draw_scoreboard_gate(ann_v_frame)
                video_writer.write(ann_v_frame)
            except Exception:
                pass

        # Emit full state snapshot
        emit({
            "type": "state",
            "frame": frame_idx,
            "ts": round(ts, 2),
            "state": state_with_rules,
            "stage": "Rule Validation & State Sync",
        })

        frame_idx += 1

    cap.release()
    if video_writer is not None:
        video_writer.release()
        # Fast web H.264 encode for flawless browser playback without getting stuck
        try:
            import imageio_ffmpeg, subprocess
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            tmp_h264 = video_out_path + ".h264.mp4"
            cmd = [
                ffmpeg_exe, "-y", "-i", video_out_path,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-preset", "ultrafast",
                tmp_h264
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if os.path.exists(tmp_h264) and os.path.getsize(tmp_h264) > 1024:
                os.replace(tmp_h264, video_out_path)
        except Exception as e:
            pass

    # Finalize state
    final_state = tracker.committed
    final_state["unlabeled_metric"] = unlabeled_metric
    if lane_number:
        final_state["lane_number"] = lane_number
    final_annotated = check_rules(final_state)["annotated_state"]

    # Save outputs
    json_path = os.path.join(output_dir, "scoreboard_state.json")
    csv_path = os.path.join(output_dir, "scoreboard_state.csv")
    timeline_path = os.path.join(output_dir, "state_timeline.json")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(final_annotated, f, indent=2)
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(state_timeline, f, indent=2)

    # CSV Export
    import csv
    fieldnames = [
        "lane_number", "row_label", "bowler_name", "is_team_row", "frame",
        "pinfall", "cumulative", "computed_cumulative", "confidence",
        "occluded", "frame_rule_check", "row_total", "row_rule_check", "unlabeled_metric"
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row_data in final_annotated.get("rows", []):
            for frame_num in range(1, 11):
                key = str(frame_num)
                fdata = row_data.get("frames", {}).get(key, {})
                writer.writerow({
                    "lane_number": final_annotated.get("lane_number", "") or "",
                    "row_label": row_data["row_label"],
                    "bowler_name": row_data.get("bowler_name", ""),
                    "is_team_row": row_data.get("is_team_row", False),
                    "frame": frame_num,
                    "pinfall": fdata.get("pinfall", ""),
                    "cumulative": fdata.get("cumulative", ""),
                    "computed_cumulative": fdata.get("computed_cumulative", ""),
                    "confidence": fdata.get("confidence", ""),
                    "occluded": fdata.get("occluded", ""),
                    "frame_rule_check": fdata.get("rule_check", "UNKNOWN" if fdata else "NOT_REACHED"),
                    "row_total": row_data.get("total", ""),
                    "row_rule_check": row_data.get("rule_check", ""),
                    "unlabeled_metric": unlabeled_metric or "",
                })

    print(f"[ScoreVision] [{hw_mode}] Extraction complete — {scoreboard_seen} scoreboard frames | {cutaway_seen} cutaways", flush=True)
    emit({
        "type": "done",
        "scoreboard": scoreboard_seen,
        "cutaway": cutaway_seen,
        "final_state": final_annotated,
        "stage": "Export (JSON / CSV / MP4)",
        "hw_mode": hw_mode,
        "hw_label": hw_label,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    run_pipeline(args.video, args.output_dir)
