# AGENT BUILD BRIEF — ScoreVision (Bowling Scoreboard Extraction)

You are an autonomous coding agent building this project end-to-end in Python. This
document is fully self-contained — do not assume any other context exists. Read it
completely before writing any code.

## 0. Non-negotiable operating rules

1. **Work in phases, in order (§6).** Do not skip ahead. After each phase, run the code
   against the real input video, print/log the actual measured result, and only then move
   to the next phase.
2. **Never fabricate a number.** Any accuracy %, confidence score, timing, or count you
   report must come from actually running the code against `data/bowling_scoreboard.mp4`.
   If you haven't measured it, say "not yet measured," don't invent a plausible-looking value.
3. **Never hardcode magic numbers inline.** All calibration values (ROI, thresholds, column
   boundaries) live in `src/config.py`, named and commented.
4. **Do not over-engineer.** No custom-trained neural networks, no YOLO, no cloud
   infrastructure, no Kubernetes, no unnecessary abstraction layers. This problem is solved
   with OpenCV + OCR + lightweight state logic + a domain rule-checker. If you're tempted to
   add a heavier tool, first prove the lightweight approach fails on real data.
5. **The bowling rule engine (`bowling_rules.py`) must not be written until Phase 6 confirms
   real notation from frames later in the video** — specifically frame-10 bonus-throw format
   and at least one fully completed row. Until then, treat exact 10th-frame notation as
   UNKNOWN, not as ChatGPT-style illustrative examples.
6. **The unlabeled bottom-left number** (observed values: `2.5`, `2.4`, `2.3`) must be
   extracted and reported as `unlabeled_metric` in the output schema. Do not guess what it
   means (lane oil pattern %, average, etc.) unless you find independent evidence in the
   video itself.
7. **The project must run end-to-end from the CLI with zero API keys.** The VLM fallback
   module is optional, isolated, and off by default.

---

## 1. Ground truth about the input video (already measured — do not re-derive from scratch)

- File: `data/bowling_scoreboard.mp4`
- 1920×1080, 30fps, 57.83s duration, 1735 total frames.
- Static camera, fixed board position, no camera movement.
- The feed **periodically cuts away from the scoreboard entirely** to (a) a full-screen
  cartoon pin-fall animation and (b) a full-screen "Brunswick" logo/pin splash screen —
  these are NOT occlusions on top of the board, the board is fully off-screen.
- Measured at 1fps frame-diff (mean abs pixel diff on a 320×180 downscale, consecutive
  frames): steady-state scoreboard frames measure **0.6–1.3**; cutaway frames measure
  **20–140+**. Clean separation, no overlap observed in sample. This is the primary scene
  gate signal — use it, don't discard it in favor of something more complex.
- A small pin-icon graphic also appears/disappears **within** the scoreboard view,
  overlapping the top-right frame columns (roughly frame columns 8–10 of one row at a
  time) — this is a real occlusion event to mask, separate from the full cutaway.
- Board layout (single active lane, "6", shown top-left):
  - Header row: lane number (large, top-left) + active bowler's name (marquee text)
  - Column header row: frame numbers `1`–`10`, then a `TTL` column
  - 4 scoring rows, each with a pinfall sub-row and a cumulative-total sub-row:
    - `J`, `V`, `P` — individual bowler initials (one row highlighted yellow/red = active
      bowler; header name above changes to match)
    - `T` — team/pair row, always highlighted red
  - Pinfall notation observed so far: `X` (strike), digit-dash pairs (`5-`, `4-`), dash-digit
    (`-7`), split combos (`8 1`, `7 1`), and `/` (spare, e.g. `4/`, `1/`)
  - **Not yet observed:** frames 5–10 populated, 10th-frame bonus notation, a fully
    completed row/game. Confirm from real frames before finalizing rule logic.
  - Bottom-left: a decimal number that changes (`2.5`→`2.4`→`2.3` observed) — meaning
    unconfirmed, extract only, do not interpret.

### Calibration seed values (measured from frame `t=0.1s` on the 1920×1080 source — use as
### a STARTING POINT for `config.py`, then refine/verify with an actual grid-overlay debug
### image before trusting them; do not skip the visual verification step)

```python
# src/config.py — seed values, VERIFY VISUALLY before use, refine as needed

FRAME_W, FRAME_H = 1920, 1080

# Outer board bounding box (x1, y1, x2, y2)
BOARD_ROI = (30, 10, 1430, 790)

# Header band: lane number + active bowler name
HEADER_BAND = (30, 10, 1430, 65)

# Column header band: frame numbers 1-10 + "TTL" label
COLUMN_HEADER_BAND = (30, 65, 1430, 105)

# Row bands — each has a pinfall sub-row and a cumulative-total sub-row
ROW_BANDS = {
    "J": {"pinfall": (30, 105, 1430, 160), "cumulative": (30, 160, 1430, 215)},
    "V": {"pinfall": (30, 215, 1430, 270), "cumulative": (30, 270, 1430, 325)},
    "P": {"pinfall": (30, 325, 1430, 380), "cumulative": (30, 380, 1430, 435)},
    "T": {"pinfall": (30, 460, 1430, 520), "cumulative": (30, 520, 1430, 590)},
}

# Row-label column (single letter J/V/P/T) vs. frame-grid columns
LABEL_COL = (30, 105, 200, 590)

# 10 frame columns span x=200 to x=1310, TTL column spans x=1310 to x=1430
FRAME_COL_X_START = 200
FRAME_COL_X_END = 1310
NUM_FRAME_COLUMNS = 10
TTL_COL = (1310, 200, 1430, 590)  # (x1, y_top_placeholder, x2, y_bottom_placeholder) — use ROW_BANDS y-range per row

# Bottom-left unlabeled metric
UNLABELED_METRIC_ROI = (30, 745, 200, 790)

# HSV range for the board's blue background (used for scene-gate color-coverage check
# and for pin-icon occlusion-graphic color-blob detection — verify/tune both separately)
BOARD_BLUE_HSV_LOWER = (90, 60, 40)
BOARD_BLUE_HSV_UPPER = (140, 255, 255)
```

Per-frame-column x boundary formula (10 equal columns between `FRAME_COL_X_START` and
`FRAME_COL_X_END`):
```python
col_width = (FRAME_COL_X_END - FRAME_COL_X_START) / NUM_FRAME_COLUMNS  # ≈110.5
col_x_bounds = [FRAME_COL_X_START + i * col_width for i in range(NUM_FRAME_COLUMNS + 1)]
```

---

## 2. Pipeline (build in this order, one module per stage)

```
video
 → [1] scene_gate.py        diff-magnitude (primary) + HSV color-coverage (corroborating)
                             → SCOREBOARD | CUTAWAY. Only SCOREBOARD frames proceed.
 → [2] quality_gate.py      Laplacian blur variance + neighbor-diff transition check
                             → OCR-suitable or reject/skip.
 → [3] board_calibrator.py  One-time grid calibration from config.py seed + contour/line
                             verification; periodic re-check every N frames (cheap, static cam).
 → [4] cell_segmenter.py    Slice into (row × frame-column) cells using calibrated geometry.
                             Never OCR the whole board as one block.
 → [5] occlusion_mask.py    Detect pin-icon graphic bounding box (color-blob), null out any
                             cell it overlaps for that frame only.
 → [6] ocr_engine.py        EasyOCR per cell, constrained charset per cell type. Primary pass
                             = grayscale+threshold. Low-confidence cells escalate to [6b].
 → [6b] preprocessing.py    Fallback-only multi-hypothesis (adaptive threshold / upscale /
                             denoise), fuse by agreement. Only kept if it measurably improves
                             accuracy over baseline — prove this, don't assume it.
 → [7] temporal_fusion.py   Confidence-weighted state machine per cell: hold committed value,
                             only overwrite after ≥K consistent differing readings.
 → [8] bowling_rules.py     BUILD ONLY AFTER NOTATION CONFIRMED (see §0.5). Recompute each
                             row's cumulative total from its own pinfall symbols, compare to
                             OCR'd running-total cell. MATCH/MISMATCH per cell.
 → [9] optional/vlm_fallback.py   Only for cells still flagged after [7]+[8]. Crop single
                             cell, strict-JSON vision-LLM read. Isolated, off by default.
 → [10] confidence.py       confidence = f(OCR agreement, temporal consistency, occlusion
                             state, rule validation) — computed, not fabricated. Attach a
                             short reason list per cell.
 → [11] exporter.py         JSON + CSV, schema in §3.
 → [12] annotate_video.py   Overlay grid box, scene status, active player, live-read cells,
                             confidence, rule-check status onto the source video.
```

---

## 3. Output schema

```json
{
  "lane_number": "6",
  "rows": [
    {
      "row_label": "J",
      "bowler_name": "JAGDISH",
      "is_team_row": false,
      "frames": {
        "1": {"pinfall": "X",  "cumulative": 15, "confidence": 0.0, "occluded": false, "rule_check": "PASS"}
      },
      "total": 0,
      "rule_check": "PASS"
    }
  ],
  "unlabeled_metric": "2.5",
  "source_timestamp_range_sec": [0, 0]
}
```
CSV = flattened row-per-(bowler, frame) view of the same data.

---

## 4. Repo structure

```
bowling-scoreboard-extraction/
├── data/bowling_scoreboard.mp4
├── src/
│   ├── config.py
│   ├── video_reader.py
│   ├── scene_gate.py
│   ├── quality_gate.py
│   ├── board_calibrator.py
│   ├── cell_segmenter.py
│   ├── occlusion_mask.py
│   ├── preprocessing.py
│   ├── ocr_engine.py
│   ├── temporal_fusion.py
│   ├── bowling_rules.py
│   ├── confidence.py
│   ├── exporter.py
│   ├── annotate_video.py
│   └── main.py
├── optional/vlm_fallback.py
├── app/streamlit_app.py
├── tests/
│   ├── test_parser.py
│   ├── test_rules.py
│   └── test_temporal.py
├── output/
│   ├── extracted_scoreboard.json
│   ├── extracted_scoreboard.csv
│   ├── annotated_video.mp4
│   └── debug/                 # grid overlays, cell crops, scene-gate visualizations
├── screenshots/
├── requirements.txt
├── README.md
└── .gitignore
```

---

## 5. Definition of Done, per phase (do not proceed until each is satisfied)

**Phase 1 — `video_reader.py` + `config.py`**
DoD: script opens the video, dumps the ROI crop from §1's seed values as a PNG. Agent
visually confirms (or self-checks via saved image) the crop actually bounds the board
before proceeding.

**Phase 2 — `scene_gate.py`**
DoD: run against all 1735 frames (or a representative dense sample, e.g. every 5th frame).
Print counts of SCOREBOARD vs CUTAWAY frames and the diff/color values at the transition
boundaries. Report these as real numbers in a short log/markdown, not estimated.

**Phase 3 — `quality_gate.py`**
DoD: run on all SCOREBOARD-classified frames from Phase 2, report how many pass/reject,
save 2-3 example rejected frames to `output/debug/` with the reason logged.

**Phase 4 — `board_calibrator.py` + `cell_segmenter.py`**
DoD: save a debug image with the calibrated grid drawn over a real frame
(`output/debug/grid_overlay.png`). Visually confirm cell boundaries align to actual
columns/rows before any OCR runs on them.

**Phase 5 — `ocr_engine.py` baseline**
DoD: hand-label ~20-30 real cells (value you can read yourself from the video), run OCR,
compute and report actual raw accuracy on that labeled set. Log the specific misreads
(e.g. "X" read as "×", "8" read as "B").

**Phase 6 — confirm bowling notation**
DoD: pull frames from later in the clip. Explicitly report whether frame 10 / a completed
row was observed, and what its notation looks like. This determines whether
`bowling_rules.py` needs 10th-frame bonus-throw handling or can be scoped to frames 1-9
with that limitation stated plainly in the README.

**Phase 7 — `preprocessing.py` fallback**
DoD: re-run the Phase 5 labeled set with fallback preprocessing enabled for low-confidence
cells only. Report accuracy before vs. after. Keep the feature only if it measurably helps.

**Phase 8 — `temporal_fusion.py`**
DoD: same labeled set (or an extended one across time), report raw-OCR vs. temporally-fused
accuracy.

**Phase 9 — `bowling_rules.py`**
DoD: run rule_check across all extracted rows, report the real match/mismatch count.

**Phase 10 — `confidence.py`**
DoD: sample 5 cells, print their full evidence breakdown and computed confidence to verify
the calculation is doing what it claims.

**Phase 11 — `optional/vlm_fallback.py`**
DoD: stub interface + prompt template exists and is callable; pipeline runs fully with it
disabled (no API key set) without error.

**Phase 12 — `exporter.py`, `annotate_video.py`**
DoD: `output/extracted_scoreboard.json`, `.csv`, and `annotated_video.mp4` all generated
from a real full run.

**Phase 13 — `tests/`**
DoD: `pytest tests/` passes, covering at minimum: (a) parser converts raw OCR-like strings
to structured values correctly, (b) a known verified pinfall sequence produces the correct
cumulative score, (c) a single noisy reading does not overwrite an established temporal state.

**Phase 14 — `app/streamlit_app.py`**
DoD: only start this after Phase 13 passes. Thin wrapper over `src/main.py` — upload video,
show input preview, detection, extracted table, confidence, download buttons for JSON/CSV/
annotated video.

---

## 6. README must include (write this last, from real results)
Overview • Architecture diagram (text) • Tech stack + why each choice was made • Install/run
instructions • Output format explanation • Pipeline explanation per stage • Real measured
challenges and how they were solved • Design decisions (e.g. "fixed ROI because camera is
static," "2-signal scene gate because diff+color already gave clean separation in testing")
• Honest limitations (e.g. 10th-frame handling scope, unlabeled_metric meaning unknown) •
Future improvements.

Do not claim a feature exists in the README unless it is actually implemented and tested.

---

Start at Phase 1. Report the measured crop result before moving to Phase 2.
