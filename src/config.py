"""
config.py -- Calibration values for the bowling scoreboard extraction pipeline.

All ROI coordinates are in (x1, y1, x2, y2) format relative to the 1920x1080 source.

GRID CALIBRATION & DOMAIN MAPPING:
- 10 bowling frame columns (Frames 1 through 10) starting at x=266 to x=1656
- Column width = 139px per frame
- Col index 0 maps to Frame 1 (x=266 to x=405)
- Col index 9 maps to Frame 10 (x=1517 to x=1656)
- TTL column spans x=1656 to x=1900
- Label column on far left spans x=4 to x=266
"""

# === Source video properties ===
FRAME_W = 1920
FRAME_H = 1080
VIDEO_FPS = 30
VIDEO_DURATION_SEC = 57.83
VIDEO_TOTAL_FRAMES = 1735

# === Outer board bounding box (x1, y1, x2, y2) ===
BOARD_ROI = (4, 10, 1900, 810)

# === Header band: lane number + active bowler name ===
HEADER_BAND = (4, 10, 1900, 95)

# === Column header band: frame numbers 1-10 + "TTL" label ===
COLUMN_HEADER_BAND = (266, 95, 1656, 140)

# === Frame columns: 10 equal columns of 139px each starting at x=266 ===
FRAME_COL_X_START = 266
FRAME_COL_WIDTH = 139
NUM_FRAME_COLUMNS = 10
FRAME_COL_X_END = FRAME_COL_X_START + FRAME_COL_WIDTH * NUM_FRAME_COLUMNS  # = 1656

# Single source of truth for column-index to 1-based frame number
FRAME_COLUMN_INDEX = {i: i + 1 for i in range(NUM_FRAME_COLUMNS)}

# Per-column x-boundaries (computed): [266, 405, 544, 683, 822, 961, 1100, 1239, 1378, 1517, 1656]
COL_X_BOUNDS = [FRAME_COL_X_START + i * FRAME_COL_WIDTH for i in range(NUM_FRAME_COLUMNS + 1)]

# Horizontal crop margin inset (in pixels) to avoid edge/divider line bleed into OCR
CELL_INSET_LEFT = 8
CELL_INSET_RIGHT = 6

# === Row bands -- each has a pinfall sub-row and a cumulative-total sub-row ===
# Measured and verified against high-variance text profiles and visual ruler.
ROW_BANDS = {
    "J": {"pinfall": (FRAME_COL_X_START, 145, FRAME_COL_X_END, 210), "cumulative": (FRAME_COL_X_START, 215, FRAME_COL_X_END, 295)},
    "V": {"pinfall": (FRAME_COL_X_START, 305, FRAME_COL_X_END, 370), "cumulative": (FRAME_COL_X_START, 375, FRAME_COL_X_END, 455)},
    "P": {"pinfall": (FRAME_COL_X_START, 465, FRAME_COL_X_END, 535), "cumulative": (FRAME_COL_X_START, 540, FRAME_COL_X_END, 620)},
    "T": {"pinfall": (FRAME_COL_X_START, 630, FRAME_COL_X_END, 700), "cumulative": (FRAME_COL_X_START, 705, FRAME_COL_X_END, 785)},
}

# === Row-label column (single letter J/V/P/T) ===
LABEL_COL = (4, 140, 266, 780)

# === TTL (total) column ===
TTL_COL_X = (FRAME_COL_X_END, 1900)

# === Bottom-left unlabeled metric ===
UNLABELED_METRIC_ROI = (30, 1010, 250, 1065)

# === HSV range for the board's blue background ===
BOARD_BLUE_HSV_LOWER = (90, 60, 40)
BOARD_BLUE_HSV_UPPER = (140, 255, 255)

# === Scene gate thresholds ===
SCENE_GATE_DIFF_THRESHOLD = 5.0  # frames above this diff are CUTAWAY candidates
SCENE_GATE_BLUE_COVERAGE_MIN = 0.10  # minimum fraction of BOARD_ROI pixels that are blue

# Structural scene gate (3rd signal, immune to color and motion):
# Compute Canny edge density inside COLUMN_HEADER_BAND (x=266-1656, y=95-140).
# The real board always has high-density white text edges there (frame numbers + TTL).
# Cutaway content drops below this threshold because it doesn't reproduce the
# board's fixed typographic structure at those exact pixel coordinates.
# Calibrated from full-video measurements: SCOREBOARD col_hdr ~0.050-0.060,
# confirmed CUTAWAY frames (t=40s, t=43s, t=50s) col_hdr = 0.007-0.030.
# Threshold set at 0.035 to leave a comfortable margin above the highest confirmed
# CUTAWAY reading (0.030) and well below the lowest SCOREBOARD reading (0.040+).
SCENE_GATE_EDGE_DENSITY_REGIONS = [
    # (x1, y1, x2, y2): fixed-structure regions sampled for edge density
    (266, 95, 1656, 140),   # column header band: frame numbers 1-10, TTL label
]
SCENE_GATE_EDGE_DENSITY_MIN = 0.035  # Canny edge fraction; below this => CUTAWAY

# === Quality gate thresholds ===
QUALITY_GATE_TRANSITION_THRESHOLD = 3.0  # if diff to neighbor exceeds this, likely mid-transition

# === Temporal fusion parameters ===
TEMPORAL_MIN_CONSISTENT_FRAMES = 3  # >=K consistent readings before overwriting committed value

# === Sampling rate for processing ===
PROCESSING_FPS = 1  # sample 1 frame per second for OCR processing

# === Occlusion detection ===
# Pin-icon graphic appears in top-right area (frames 7-10, rows J/V)
PIN_ICON_DETECTION_AREA = (1040, 80, 1620, 430)
PIN_ICON_WHITE_FRAC_THRESHOLD = 0.05

# === Active-row highlight detection ===
# The currently active bowler's row pinfall band has a visibly brighter/more
# saturated background (yellow highlight vs. plain dark blue for idle rows).
# We sample a small patch from the LEFT side of each row's pinfall band
# (where the label-column bleeds into the first frame column) and compare
# HSV saturation. The row with the highest saturation above this threshold
# is classified as active. Calibration: idle rows ~sat 60-90, active ~sat 180+.
ACTIVE_ROW_SAMPLE_PATCHES = {
    "J": (270, 155, 320, 200),   # small patch in row J pinfall band left-edge
    "V": (270, 315, 320, 360),
    "P": (270, 475, 320, 525),
    "T": (270, 640, 320, 685),
}
ACTIVE_ROW_SAT_THRESHOLD = 120   # HSV saturation: active row max_sat > this

# === Pinfall-cell OCR parameters (tuned for thin trailing marks) ===
# Wider right margin so trailing `-` and `/` strokes aren't clipped at crop edge.
PINFALL_CELL_INSET_RIGHT = 2   # pixels from right column boundary (vs. CELL_INSET_RIGHT=6)
# Lower EasyOCR text detection threshold to box thin/short strokes like `-` and `/`.
PINFALL_LOW_TEXT_THRESHOLD = 0.30  # default EasyOCR low_text is 0.4
# Primary mag_ratio for pinfall cells (higher resolution helps italic digit recognition).
PINFALL_MAG_RATIO_PRIMARY = 2.5

# === Debug output paths ===
OUTPUT_DIR = "output"
DEBUG_DIR = "output/debug"
SCREENSHOTS_DIR = "screenshots"
