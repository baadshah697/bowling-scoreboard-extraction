"""
ocr_engine.py -- High-Precision GPU EasyOCR Engine for ScoreVision.

Key Optimizations:
  1. Automatic CUDA GPU Acceleration on NVIDIA RTX 4060 (with CPU fallback).
  2. Pre-OCR Empty/Uniform Cell Quality Gate:
     - Detects uniform/empty background cells (std < 12.0 or dynamic range < 30)
     - Immediately returns empty string with 0ms compute, eliminating OCR noise/hallucinations on blank frames.
  3. Multi-Pass Accurate Character Extraction:
     - CRAFT-guided localized text detection with contrast normalization.
     - Dual-pass candidate fusion (preferring symbolic bowling characters 'X', '/', '-').
     - Domain reconciliation for OCR confusion (e.g. impossible sum 4+7=11 -> '4/').
  4. Saves transparent detection logs to output/debug/ocr_raw_candidates.json.
"""

import cv2
import numpy as np
import easyocr
import torch
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

_reader = None
_raw_candidates_log = []


def get_reader(force_cpu: bool = False):
    global _reader
    if _reader is None:
        force_env = os.environ.get("SCOREVISION_FORCE_CPU", "0") == "1"
        use_gpu = torch.cuda.is_available() and not force_cpu and not force_env
        if not use_gpu:
            num_cores = os.cpu_count() or 4
            os.environ["OMP_NUM_THREADS"] = str(num_cores)
            torch.set_num_threads(num_cores)
        _reader = easyocr.Reader(['en'], gpu=use_gpu, verbose=False)
    return _reader


def _preprocess_cell(cell_img: np.ndarray, pad: int = 25) -> np.ndarray:
    """
    Contrast normalization (min-max) and solid background padding.
    """
    gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY) if len(cell_img.shape) == 3 else cell_img
    norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    edges = np.concatenate([norm[0, :], norm[-1, :], norm[:, 0], norm[:, -1]])
    bg = int(np.median(edges))
    return cv2.copyMakeBorder(norm, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=bg)


def _reconcile_bowling_pinfall(text: str) -> str:
    """
    Fix common OCR character confusions based on 10-pin bowling physics.
    Example: '47' -> 4 + 7 = 11 (> 10 impossible pins in single frame) -> '4/' (spare).
    """
    if not text:
        return ""
    clean = text.replace(" ", "").strip()
    if clean == "X" or clean == "/" or clean == "-":
        return clean
    if len(clean) == 2 and clean[0].isdigit() and clean[1].isdigit():
        d1, d2 = int(clean[0]), int(clean[1])
        if d1 + d2 > 10:
            # Physically impossible sum in standard 10-pin frame -> second digit is a spare '/'
            return f"{d1}/"
    return text


def fuse_candidates(candidate_a: tuple, candidate_b: tuple, is_pinfall: bool = True) -> tuple:
    """
    Fuse two OCR candidate passes for a single cell (Amendment 2).
    Tie-breaking policy (NEVER CONCATENATES):
    1. If one candidate contains symbolic bowling characters ('X', '/', '-'), prefer it.
    2. Otherwise, pick candidate with higher confidence.
    """
    text_a, conf_a, boxes_a = candidate_a
    text_b, conf_b, boxes_b = candidate_b

    if not text_a and not text_b:
        return "", []
    if not text_a:
        return text_b, boxes_b
    if not text_b:
        return text_a, boxes_a
    if text_a == text_b:
        return text_a, boxes_a

    if is_pinfall:
        symbols = set("X/-")
        has_sym_a = any(c in symbols for c in text_a)
        has_sym_b = any(c in symbols for c in text_b)
        if has_sym_a and not has_sym_b:
            return text_a, boxes_a
        elif has_sym_b and not has_sym_a:
            return text_b, boxes_b

    if conf_a >= conf_b:
        return text_a, boxes_a
    else:
        return text_b, boxes_b


def extract_text_from_cell(cell_img: np.ndarray,
                           allowlist: str = '0123456789X/- ',
                           is_pinfall: bool = True,
                           debug_context: tuple = None) -> tuple:
    """
    OCR a single pre-cropped cell image with empty-cell gate and dual-pass fusion.
    Returns (cleaned_text, raw_candidates_list).
    """
    if cell_img is None or cell_img.size == 0:
        return "", []

    gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY) if len(cell_img.shape) == 3 else cell_img

    # 1. Empty / Uniform Cell Quality Gate
    # Uniform background cells have near-zero variance; skip OCR immediately
    diff = int(np.max(gray)) - int(np.min(gray))
    std = float(gray.std())
    if std < 12.0 or diff < 28:
        return "", []

    reader = get_reader()
    padded = _preprocess_cell(cell_img, pad=25)

    # Primary pass
    primary_mag = config.PINFALL_MAG_RATIO_PRIMARY if is_pinfall else 1.5
    low_text = 0.20 if is_pinfall else 0.40
    results_primary = reader.readtext(padded, allowlist=allowlist, detail=1,
                                      mag_ratio=primary_mag, low_text=low_text, contrast_ths=0.05)
    boxes_primary = [r[1] for r in results_primary] if results_primary else []
    conf_primary = float(np.mean([r[2] for r in results_primary])) if results_primary else 0.0
    text_primary = " ".join(boxes_primary).strip()
    if is_pinfall:
        text_primary = _reconcile_bowling_pinfall(text_primary)
    cand_primary = (text_primary, conf_primary, boxes_primary)

    # Fallback pass (only if primary is empty or low confidence)
    if not text_primary or conf_primary < 0.60:
        fallback_mag = 1.8 if is_pinfall else 2.0
        results_fallback = reader.readtext(padded, allowlist=allowlist, detail=1,
                                           mag_ratio=fallback_mag, low_text=0.35)
        boxes_fallback = [r[1] for r in results_fallback] if results_fallback else []
        conf_fallback = float(np.mean([r[2] for r in results_fallback])) if results_fallback else 0.0
        text_fallback = " ".join(boxes_fallback).strip()
        if is_pinfall:
            text_fallback = _reconcile_bowling_pinfall(text_fallback)
        cand_fallback = (text_fallback, conf_fallback, boxes_fallback)

        chosen_text, chosen_boxes = fuse_candidates(cand_primary, cand_fallback, is_pinfall=is_pinfall)
    else:
        chosen_text, chosen_boxes = text_primary, boxes_primary
        cand_fallback = ("", 0.0, [])

    if debug_context is not None:
        _raw_candidates_log.append({
            "context": debug_context,
            "primary": {"text": text_primary, "conf": conf_primary, "boxes": boxes_primary},
            "fallback": {"text": cand_fallback[0], "conf": cand_fallback[1], "boxes": cand_fallback[2]},
            "chosen": chosen_text,
        })

    return chosen_text, chosen_boxes


_cell_cache = {}


def reset_ocr_cache():
    """Reset temporal cell cache between video runs."""
    global _cell_cache, _raw_candidates_log
    _cell_cache.clear()
    _raw_candidates_log.clear()


def ocr_all_valid_cells(valid_cells: dict, timestamp_sec: float = 0.0) -> dict:
    """
    Run OCR on every clear (non-occluded) cell with temporal diff caching.
    If a cell has not changed from previous keyframes, reuses cached OCR output in 0.01ms.

    Args:
        valid_cells: output of cell_extractor.apply_quality_gates()
        timestamp_sec: timestamp of the frame being processed

    Returns:
        raw_strings[row][subrow][col] = str | None
    """
    global _cell_cache
    raw_strings = {}

    for row in ["J", "V", "P", "T"]:
        raw_strings[row] = {"pinfall": [None] * config.NUM_FRAME_COLUMNS,
                            "cumulative": [None] * config.NUM_FRAME_COLUMNS}
        for subrow in ["pinfall", "cumulative"]:
            is_pf = (subrow == "pinfall")
            allowlist = '0123456789X/- ' if is_pf else '0123456789'
            for col in range(config.NUM_FRAME_COLUMNS):
                cell = valid_cells[row][subrow][col]
                if cell is None:
                    raw_strings[row][subrow][col] = ""
                elif cell["occluded"]:
                    raw_strings[row][subrow][col] = None
                else:
                    cell_img = cell["img"]
                    cell_key = (row, subrow, col)

                    # Quick grayscale for temporal diff comparison
                    gray_thumb = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY) if len(cell_img.shape) == 3 else cell_img

                    # Check if cell has changed from previous observation
                    if cell_key in _cell_cache:
                        last_gray, cached_text, cached_boxes = _cell_cache[cell_key]
                        if gray_thumb.shape == last_gray.shape:
                            diff_val = float(np.mean(cv2.absdiff(gray_thumb, last_gray)))
                            if diff_val < 3.5:
                                # Cell has not changed -- reuse in 0.01ms!
                                raw_strings[row][subrow][col] = cached_text
                                continue

                    # Cell has changed or is seen for the first time -- run full OCR
                    ctx = (row, subrow, col + 1, round(timestamp_sec, 2))
                    text, candidates = extract_text_from_cell(
                        cell_img, allowlist=allowlist, is_pinfall=is_pf, debug_context=ctx
                    )
                    _cell_cache[cell_key] = (gray_thumb.copy(), text, candidates)
                    raw_strings[row][subrow][col] = text

    return raw_strings


def save_raw_candidates_log(output_path: str = "output/debug/ocr_raw_candidates.json"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(_raw_candidates_log, f, indent=2)
