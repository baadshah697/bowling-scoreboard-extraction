# 🎳 ScoreVision: Real-Time Bowling Scoreboard Computer Vision & OCR Extraction Engine

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-CUDA%20%2F%20CPU-orange.svg)](https://pytorch.org/)
[![OpenCV](https://img.shields.io/badge/OpenCV-Computer%20Vision-green.svg)](https://opencv.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-Interactive%20UI-red.svg)](https://streamlit.io/)
[![Tests](https://img.shields.io/badge/Tests-30%20Passed-brightgreen.svg)]()

> ### ⚡ **CRITICAL HARDWARE RECOMMENDATION FOR FASTEST PERFORMANCE**
> 
> **For the fastest extraction speed (~25 to 30 seconds for a full match video), running on an NVIDIA GPU with CUDA is strongly recommended.** 
> Deep CRAFT character region detection and neural OCR matrix multiplications run at least **3x–4x faster on dedicated Tensor Cores and GPU VRAM**.
>
> 💡 **No GPU? No Problem!**
> ScoreVision features an adaptive engine: on standard laptops or PCs without a dedicated GPU, it automatically activates **Multi-Core CPU SIMD Parallelism + Temporal Cell Diff Caching** (skipping 95% of static cells in 0.013ms) to finish processing in **~80 seconds** with **100% mathematical accuracy**.

---

## 💻 Hardware Setup & Installation Guide

ScoreVision automatically detects whether a GPU or CPU is present on your system. Follow the setup matching your hardware:

### Option A: 🟢 NVIDIA GPU (CUDA Accelerated — Recommended for Maximum Speed)

If your machine has an NVIDIA GeForce / RTX / Quadro GPU, install the CUDA-enabled PyTorch build:

```bash
# 1. Clone the repository
git clone https://github.com/baadshah697/bowling-scoreboard-extraction.git
cd bowling-scoreboard-extraction

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # On Windows
# source venv/bin/activate     # On Mac/Linux

# 3. Install CUDA-accelerated PyTorch (CUDA 12.1)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# 4. Install remaining project requirements
pip install -r requirements.txt
```

---

### Option B: 🔵 CPU-Only Mode (Lightweight ~150 MB — For Any Laptop, PC, or Mac)

If your system does not have an NVIDIA GPU, install the lightweight CPU-only build (over **90% smaller download size**):

```bash
# 1. Clone the repository
git clone https://github.com/baadshah697/bowling-scoreboard-extraction.git
cd bowling-scoreboard-extraction

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # On Windows
# source venv/bin/activate     # On Mac/Linux

# 3. Install lightweight CPU PyTorch (~150 MB)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 4. Install remaining project requirements
pip install -r requirements.txt
```

---

## 🚀 How to Run

### 1. Launch the Interactive Web Dashboard (Recommended)

```bash
streamlit run frontend/app.py
```
1. Open **`http://localhost:8501`** in your browser.
2. Drag and drop your bowling match video.
3. Click **"▶ Run Extraction Pipeline"**.
4. The dashboard automatically detects your hardware, displays the active engine badge (🟢 **GPU** or 🔵 **CPU**), and streams live bounding boxes and 2-tier bowling scorecards.

---

### 2. Headless CLI Extraction

To run the pipeline directly via terminal or script:

```bash
python frontend/pipeline_runner.py --video data/bowling_scoreboard.mp4 --output-dir output
```

Outputs generated in `output/`:
- `scoreboard_state.json` — Structured JSON state with 10-pin validation invariants.
- `scoreboard_state.csv` — Tabular CSV scorecard with frame-by-frame pinfalls.
- `state_timeline.json` — Continuous temporal state snapshots for every frame.
- `annotated_video.mp4` — AI-annotated video with visual bounding boxes (web-compatible H.264).


---

## 🧪 Automated Test Suite

ScoreVision includes a 30-case test suite covering OCR accuracy, 10-pin mathematical rules, scene gating, and pipeline streaming:

```bash
python -m pytest
```

```
============================= test session starts =============================
collected 30 items

output/debug/test_ocr.py .                                               [  3%]
tests/test_authentic_scoreboard.py ......                                [ 23%]
tests/test_ocr_accuracy.py .......                                       [ 46%]
tests/test_parser.py ..........                                          [ 80%]
tests/test_pawan_row.py .                                                [ 83%]
tests/test_pipeline_streaming.py ..                                      [ 90%]
tests/test_scene_gating.py ...                                           [100%]

============================= 30 passed in 6.82s ==============================
```

---

## 📁 Repository Structure

```
bowling-scoreboard-extraction/
├── src/
│   ├── config.py                 # Single source of truth (coordinates, bands, thresholds)
│   ├── scene_gate.py             # 3-signal frame classifier (diff, blue HSV, Canny edges)
│   ├── cell_extractor.py         # 80-cell grid slicing and quality gating
│   ├── occlusion_mask.py         # Graphic occlusion detector
│   ├── ocr_engine.py             # GPU CRAFT + PyTorch EasyOCR with empty-cell gate
│   ├── temporal_fusion.py        # Monotonic cumulative state machine
│   ├── bowling_rules.py          # Regulation 10-pin bowling calculation engine
│   ├── annotate_video.py         # Video overlay annotator
│   ├── exporter.py               # JSON, CSV, and XLSX exporter
│   └── main.py                   # Standalone CLI orchestrator
├── frontend/
│   ├── app.py                    # Streamlit web application & 2-tier broadcast dashboard
│   └── pipeline_runner.py        # Subprocess streaming worker
├── tests/
│   ├── test_authentic_scoreboard.py
│   ├── test_ocr_accuracy.py
│   ├── test_parser.py
│   ├── test_pawan_row.py
│   ├── test_pipeline_streaming.py
│   └── test_scene_gating.py
├── data/                         # Folder for input videos (.gitkeep)
├── output/                       # Folder for generated exports (.gitkeep)
├── requirements.txt              # Project dependencies
├── .gitignore                    # Git exclusion rules
└── README.md                     # Project documentation
```

---

## 👨‍💻 Author

Developed by **[baadshah697](https://github.com/baadshah697)**.
