"""
video_reader.py — Video access utilities for the bowling scoreboard extraction pipeline.

Provides functions to:
- Open the video and iterate frames
- Seek to specific timestamps or frame indices
- Crop a frame to a given ROI
- Dump ROI crops for visual verification
"""

import cv2
import os
import sys
import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def open_video(video_path: str) -> cv2.VideoCapture:
    """Open a video file and return the VideoCapture object."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")
    return cap


def get_video_info(cap: cv2.VideoCapture) -> dict:
    """Return basic video properties."""
    return {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "duration_sec": cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS),
    }


def read_frame_at_index(cap: cv2.VideoCapture, frame_idx: int) -> np.ndarray:
    """Read a specific frame by index. Returns the BGR frame or raises on failure."""
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    if not ret:
        raise RuntimeError(f"Failed to read frame at index {frame_idx}")
    return frame


def read_frame_at_time(cap: cv2.VideoCapture, time_sec: float) -> np.ndarray:
    """Read the frame closest to a given timestamp (seconds)."""
    cap.set(cv2.CAP_PROP_POS_MSEC, time_sec * 1000)
    ret, frame = cap.read()
    if not ret:
        raise RuntimeError(f"Failed to read frame at time {time_sec:.2f}s")
    return frame


def crop_roi(frame: np.ndarray, roi: tuple) -> np.ndarray:
    """Crop a frame to an ROI given as (x1, y1, x2, y2)."""
    x1, y1, x2, y2 = roi
    return frame[y1:y2, x1:x2]


def iter_frames(cap: cv2.VideoCapture, sample_fps: float = None, start_frame: int = 0):
    """
    Iterate over frames from the video.

    Args:
        cap: VideoCapture object
        sample_fps: If given, yield frames at this rate (e.g. 1 = one per second).
                    If None, yield every frame.
        start_frame: Starting frame index.

    Yields:
        (frame_index, timestamp_sec, frame_bgr)
    """
    video_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if sample_fps is not None:
        step = max(1, int(round(video_fps / sample_fps)))
    else:
        step = 1

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    frame_idx = start_frame
    while frame_idx < total_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break
        timestamp = frame_idx / video_fps
        yield frame_idx, timestamp, frame
        frame_idx += step


def dump_roi_crop(video_path: str, output_path: str, roi: tuple = None,
                  time_sec: float = 0.1):
    """
    Open the video, read a frame at the given timestamp, crop to ROI,
    and save as PNG for visual verification.

    Args:
        video_path: Path to the video file.
        output_path: Path to save the cropped PNG.
        roi: (x1, y1, x2, y2) tuple. Defaults to config.BOARD_ROI.
        time_sec: Timestamp in seconds to grab the frame from.

    Returns:
        dict with info about the saved crop.
    """
    if roi is None:
        roi = config.BOARD_ROI

    cap = open_video(video_path)
    info = get_video_info(cap)
    print(f"Video info: {info}")

    frame = read_frame_at_time(cap, time_sec)
    print(f"Read frame at t={time_sec}s, shape={frame.shape}")

    cropped = crop_roi(frame, roi)
    print(f"Cropped ROI {roi} -> shape={cropped.shape}")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cv2.imwrite(output_path, cropped)
    print(f"Saved ROI crop to: {output_path}")

    # Also save the full frame with ROI rectangle drawn for context
    debug_frame = frame.copy()
    x1, y1, x2, y2 = roi
    cv2.rectangle(debug_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
    # Add ROI text
    cv2.putText(debug_frame, f"BOARD_ROI: {roi}", (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    full_debug_path = output_path.replace(".png", "_full_annotated.png")
    cv2.imwrite(full_debug_path, debug_frame)
    print(f"Saved full frame with ROI overlay to: {full_debug_path}")

    cap.release()

    return {
        "video_info": info,
        "roi": roi,
        "crop_shape": cropped.shape,
        "crop_path": output_path,
        "annotated_path": full_debug_path,
    }


if __name__ == "__main__":
    video_path = os.path.join(os.path.dirname(__file__), "..", "data", "bowling_scoreboard.mp4")
    output_path = os.path.join(os.path.dirname(__file__), "..", "output", "debug", "board_roi_crop.png")

    print("=" * 60)
    print("Phase 1: Video Reader + ROI Crop Verification")
    print("=" * 60)

    result = dump_roi_crop(video_path, output_path)

    print("\n" + "=" * 60)
    print("Phase 1 Result Summary:")
    print(f"  Video: {result['video_info']}")
    print(f"  ROI: {result['roi']}")
    print(f"  Crop shape (HxWxC): {result['crop_shape']}")
    print(f"  Crop saved to: {result['crop_path']}")
    print(f"  Annotated frame saved to: {result['annotated_path']}")
    print("=" * 60)
    print("\n-> NEXT STEP: Visually inspect the crop to confirm it bounds the scoreboard.")
