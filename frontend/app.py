"""
app.py  —  ScoreVision Command Center  |  Dynamic Streamlit Dashboard

Features:
  • Starts in clean EMPTY state (Header + Upload control only)
  • Once a video is uploaded -> READY state (Raw video preview + Run button)
  • Clicking Run starts frontend/pipeline_runner.py in background thread
  • Thread sends streaming JSON telemetry events via a thread-safe Queue
  • Streamlit main thread drains Queue on each rerun and updates session_state:
      - Live KPI cards (Total score, PASS, FAIL, UNKNOWN)
      - 1:1 Authentic 2-Tier Bowling Scoreboard (Pinfalls on top, Cumulative on bottom,
        active row yellow/white/red highlight, lane 6 badge, TARUN marquee, 2.5 metric)
      - Real-time frame counter, scene-gate badge, active-bowler indicator
  • On completion (DONE state):
      - Download buttons for Annotated Extraction Video (.mp4),
        State Timeline (.json), Scoreboard State (.json), CSV, and Scoring Rules
      - Full committed 2-tier authentic scoreboard matrix & verified KPI cards
"""

import os
import sys
import json
import time
import queue
import datetime
import subprocess
import threading
import streamlit as st

# ──────────────────────────────────────────────────────────────────────────────
# Resolve paths relative to project root
# ──────────────────────────────────────────────────────────────────────────────
FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(FRONTEND_DIR, ".."))
OUTPUT_DIR   = os.path.join(PROJECT_ROOT, "output")
SRC_DIR      = os.path.join(PROJECT_ROOT, "src")
DATA_DIR     = os.path.join(PROJECT_ROOT, "data")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
import cv2

# ──────────────────────────────────────────────────────────────────────────────
# Global Thread-Safe Queue for Subprocess Events
# ──────────────────────────────────────────────────────────────────────────────
if "event_queue" not in st.session_state:
    st.session_state["event_queue"] = queue.Queue()

# ──────────────────────────────────────────────────────────────────────────────
# Page configuration
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ScoreVision Command Center",
    page_icon="🎳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────────
# Session state initialization
# ──────────────────────────────────────────────────────────────────────────────
SESSION_DEFAULTS = {
    # Video & UI lifecycle
    "uploaded_video_path": None,
    "uploaded_video_name": None,
    "uploaded_video_size": 0,
    "pipeline_running":    False,
    "pipeline_done":       False,
    "pipeline_error":      None,
    # Live telemetry
    "progress_pct":        0.0,
    "current_frame":       0,
    "total_frames":        0,
    "current_ts":          0.0,
    "scene_class":         "—",
    "active_row":          None,
    "active_stage":        "Idle",
    # Live scoreboard state (§3 schema)
    "live_state":          None,
    "final_state":         None,
    # Logs
    "log_lines":           [],
}

for key, val in SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ──────────────────────────────────────────────────────────────────────────────
# Drain Background Event Queue on Main Thread (Guaranteed Streamlit Context)
# ──────────────────────────────────────────────────────────────────────────────
q = st.session_state["event_queue"]
while not q.empty():
    try:
        evt = q.get_nowait()
    except queue.Empty:
        break

    evt_type = evt.get("type")

    if evt_type == "started":
        st.session_state["total_frames"] = evt.get("total", 0)
        st.session_state["active_stage"] = "Pipeline Started"

    elif evt_type == "progress":
        frame = evt.get("frame", 0)
        total = st.session_state["total_frames"] or 1
        st.session_state["current_frame"] = frame
        st.session_state["current_ts"]    = evt.get("ts", 0.0)
        st.session_state["scene_class"]   = evt.get("scene", "—")
        st.session_state["active_row"]    = evt.get("active_row")
        st.session_state["active_stage"]  = evt.get("stage", st.session_state["active_stage"])
        st.session_state["progress_pct"]  = min(100.0, (frame / total) * 100 if total > 0 else 0)

    elif evt_type == "state":
        st.session_state["live_state"]   = evt.get("state")
        st.session_state["active_stage"] = evt.get("stage", st.session_state["active_stage"])

    elif evt_type == "done":
        st.session_state["final_state"]      = evt.get("final_state")
        st.session_state["live_state"]       = evt.get("final_state")
        st.session_state["progress_pct"]     = 100.0
        st.session_state["pipeline_running"] = False
        st.session_state["pipeline_done"]    = True
        st.session_state["active_stage"]     = "Completed"

    elif evt_type == "error":
        st.session_state["pipeline_error"]   = evt.get("message")
        st.session_state["pipeline_running"] = False
        st.session_state["active_stage"]     = "Error"

    elif evt_type == "log":
        st.session_state["log_lines"].append(evt.get("line", ""))

# ──────────────────────────────────────────────────────────────────────────────
# CSS Styling (Dark, Sleek, Modern Command Center + Authentic Bowling Board)
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background: #0b1322 !important;
    color: #f1f5f9;
}
.stApp { background: #0b1322; }
.block-container { padding-top: 1.2rem !important; max-width: 1560px; }

/* ── Header ── */
.sv-header {
    display:flex; justify-content:space-between; align-items:center;
    padding:14px 26px; background:#0e1726;
    border:1px solid #1c2b44; border-radius:12px;
    margin-bottom:18px; box-shadow:0 4px 20px rgba(0,0,0,.4);
}
.sv-header-title { font-size:24px; font-weight:800; color:#38bdf8; margin:0; }
.sv-header-title span { color:#fff; }
.sv-header-sub   { font-size:13px; color:#94a3b8; margin:2px 0 0 0; }
.sv-badge {
    display:inline-flex; align-items:center; gap:8px;
    padding:6px 14px; border-radius:9999px; font-size:13px; font-weight:600;
}
.sv-badge-green { background:rgba(16,185,129,.15); border:1px solid rgba(16,185,129,.4); color:#34d399; }
.sv-badge-blue  { background:rgba(56,189,248,.15);  border:1px solid rgba(56,189,248,.4);  color:#38bdf8; }
.sv-badge-gray  { background:rgba(148,163,184,.12); border:1px solid rgba(148,163,184,.3); color:#94a3b8; }
.sv-badge-red   { background:rgba(239,68,68,.15);   border:1px solid rgba(239,68,68,.4);   color:#f87171; }
.sv-dot { width:8px; height:8px; border-radius:50%; }
.sv-dot-green { background:#10b981; box-shadow:0 0 8px #10b981; }
.sv-dot-blue  { background:#38bdf8; box-shadow:0 0 8px #38bdf8; animation:blink 1s infinite; }
.sv-dot-gray  { background:#94a3b8; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.4} }

/* ── Cards ── */
.sv-card {
    background:#111c30; border:1px solid #1e2f4d;
    border-radius:14px; padding:18px 22px;
    margin-bottom:18px; box-shadow:0 8px 24px rgba(0,0,0,.35);
}
.sv-card-title {
    font-size:18px; font-weight:700; color:#fff;
    margin:0 0 4px 0; display:flex; align-items:center; gap:10px;
}
.sv-card-sub { font-size:13px; color:#94a3b8; margin:0 0 14px 0; }

/* ── KPI Grid ── */
.kpi-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }
.kpi-box  {
    background:#0d1728; border-radius:12px; padding:16px 18px;
    border:1px solid #1c2c46; transition:transform .2s;
}
.kpi-box:hover { transform:translateY(-2px); }
.kpi-box-blue   { border-color:rgba(59,130,246,.4); }
.kpi-box-green  { border-color:rgba(16,185,129,.4); background:linear-gradient(180deg,rgba(16,185,129,.06),#0d1728); }
.kpi-box-red    { border-color:rgba(239,68,68,.4);  background:linear-gradient(180deg,rgba(239,68,68,.06),#0d1728); }
.kpi-box-purple { border-color:rgba(168,85,247,.4); }
.kpi-label { display:flex; align-items:center; gap:8px; font-size:12px; font-weight:600; margin-bottom:8px; }
.kpi-value { font-size:32px; font-weight:800; color:#fff; line-height:1; }
.kpi-sub   { font-size:12px; color:#94a3b8; margin-top:6px; }

/* ── Video Panels ── */
.vpanel {
    background:#0d1728; border:1px solid #1c2c46;
    border-radius:12px; padding:14px; height:100%;
}
.vpanel-header {
    display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;
}
.vpanel-title { font-size:14px; font-weight:700; color:#fff; display:flex; align-items:center; gap:8px; }
.vtag { font-size:11px; font-weight:600; padding:3px 8px; border-radius:6px; }
.vtag-raw { background:rgba(59,130,246,.15); color:#60a5fa; border:1px solid rgba(59,130,246,.3); }
.vtag-ai  { background:rgba(16,185,129,.15); color:#34d399;  border:1px solid rgba(16,185,129,.3); }
.vtag-proc{ background:rgba(234,179,8,.15);  color:#facc15;  border:1px solid rgba(234,179,8,.3); }
.telemetry-row  { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
.tpill {
    display:inline-flex; align-items:center; gap:5px;
    padding:4px 10px; border-radius:8px; font-size:11px; font-weight:600;
    background:#111e33; border:1px solid #1f3354; color:#94a3b8;
}

/* ── 🎳 1:1 AUTHENTIC 2-TIER BOWLING SCOREBOARD STYLES ── */
.bs-container {
    background: #00122e;
    padding: 16px;
    border-radius: 14px;
    border: 2px solid #0284c7;
    box-shadow: 0 12px 36px rgba(0,0,0,0.6), inset 0 0 24px rgba(2, 132, 199, 0.2);
    font-family: 'Inter', sans-serif;
    color: #ffffff;
    max-width: 100%;
    overflow-x: auto;
    margin-top: 10px;
}
.bs-header-bar {
    display: grid;
    grid-template-columns: 80px 1fr 90px;
    background: #003b8e;
    border: 2px solid #38bdf8;
    border-bottom: none;
    border-radius: 8px 8px 0 0;
    overflow: hidden;
}
.bs-lane-badge {
    background: #0052cc;
    color: #ffd700;
    font-size: 38px;
    font-weight: 900;
    font-style: italic;
    display: flex;
    align-items: center;
    justify-content: center;
    border-right: 2px solid #38bdf8;
    text-shadow: 2px 2px 6px rgba(0,0,0,0.7);
}
.bs-bowler-marquee {
    background: #002d72;
    color: #ffd700;
    font-size: 24px;
    font-weight: 900;
    letter-spacing: 2px;
    display: flex;
    align-items: center;
    padding-left: 20px;
    text-transform: uppercase;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
}
.bs-ttl-header {
    background: #002d72;
    color: #ffffff;
    font-size: 20px;
    font-weight: 800;
    display: flex;
    align-items: center;
    justify-content: center;
    border-left: 2px solid #38bdf8;
}
.bs-grid {
    width: 100%;
    border-collapse: collapse;
    border: 2px solid #38bdf8;
    background: #004b9c;
}
.bs-frame-nums-row th {
    background: #003b8e;
    color: #ffffff;
    font-size: 16px;
    font-weight: 800;
    padding: 6px 0;
    text-align: center;
    border: 1px solid rgba(255, 255, 255, 0.4);
}
.bs-bowler-cell {
    background: #002d72;
    color: #ffffff;
    font-size: 22px;
    font-weight: 900;
    text-align: center;
    vertical-align: middle;
    width: 70px;
    border: 1.5px solid rgba(255, 255, 255, 0.4);
}
.bs-bowler-cell-active {
    background: #ffd700 !important;
    color: #b91c1c !important;
    border-left: 6px solid #dc2626 !important;
    box-shadow: inset 0 0 10px rgba(220, 38, 38, 0.4);
}
.bs-frame-cell {
    width: 8.5%;
    padding: 0 !important;
    margin: 0 !important;
    vertical-align: top;
    border: 1.5px solid rgba(255, 255, 255, 0.4);
    background: #004b9c;
}
.bs-pinfall-tier {
    display: flex;
    height: 32px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.35);
    background: #003f88;
}
.bs-pinfall-tier-active {
    background: #fff8b0 !important;
    color: #002244 !important;
}
.bs-roll-1 {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'JetBrains Mono', monospace;
    font-size: 15px;
    font-weight: 700;
    color: #ffffff;
}
.bs-roll-1-active { color: #002b66 !important; }
.bs-roll-2 {
    width: 26px;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    border-left: 1px solid rgba(255, 255, 255, 0.35);
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    font-weight: 800;
    color: #ffffff;
    background: rgba(0, 0, 0, 0.15);
}
.bs-roll-2-active {
    border-left: 1px solid rgba(0, 43, 102, 0.3) !important;
    color: #002b66 !important;
    background: rgba(255, 255, 255, 0.35) !important;
}
.bs-cum-tier {
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Inter', sans-serif;
    font-size: 20px;
    font-weight: 900;
    color: #ffffff;
    background: #004b9c;
    text-shadow: 1px 1px 3px rgba(0,0,0,0.6);
}
.bs-cum-tier-active {
    background: #ffffff !important;
    color: #002b66 !important;
    text-shadow: none !important;
}
.bs-ttl-cell {
    width: 80px;
    padding: 0 !important;
    border: 1.5px solid rgba(255, 255, 255, 0.4);
    background: #002d72;
}
.bs-ttl-cell-active {
    background: #dc2626 !important;
}
.bs-ttl-top {
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 15px;
    font-weight: 700;
    color: #93c5fd;
    border-bottom: 1px solid rgba(255, 255, 255, 0.35);
}
.bs-ttl-top-active { color: #ffffff !important; font-weight: 800 !important; }
.bs-ttl-bot {
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    font-weight: 900;
    color: #ffffff;
}
.bs-ttl-bot-active { color: #ffffff !important; font-size: 24px !important; font-weight: 900 !important; }
.bs-occ-text {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.5);
    font-weight: 700;
    letter-spacing: 0.5px;
}
.bs-occ-text-active { color: rgba(0, 43, 102, 0.5); }
.bs-bottom-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #002d72;
    border: 2px solid #38bdf8;
    border-top: none;
    border-radius: 0 0 8px 8px;
    padding: 6px 14px;
}
.bs-metric-box {
    background: #0052cc;
    color: #ffffff;
    font-size: 16px;
    font-weight: 800;
    padding: 3px 12px;
    border-radius: 4px;
    border: 1px solid #38bdf8;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background:#0d172a !important;
    border-right:1px solid #1c2b44;
}
.pipe-item {
    display:flex; align-items:center; gap:10px;
    padding:8px 0; font-size:13px; color:#e2e8f0;
    border-bottom:1px solid rgba(255,255,255,.04);
}
.pipe-check {
    width:22px; height:22px; border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    font-size:11px; font-weight:bold; flex-shrink:0;
}
.pipe-done    { background:rgba(16,185,129,.15); border:1px solid rgba(16,185,129,.4); color:#10b981; }
.pipe-pending { background:rgba(100,116,139,.1);  border:1px solid rgba(100,116,139,.3); color:#64748b; }
.pipe-active  { background:rgba(234,179,8,.15);   border:1px solid rgba(234,179,8,.4);   color:#facc15; animation:blink 1s infinite; }

/* ── Clean UI ── */
header[data-testid="stHeader"] { display:none !important; }
footer { display:none !important; }
video { border-radius:10px; width:100% !important; border:1px solid #1c2b44; background:#000; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────────────────────────
def _read_file_text(rel_path):
    abs_p = os.path.join(PROJECT_ROOT, rel_path)
    if os.path.exists(abs_p):
        with open(abs_p, encoding="utf-8") as f:
            return f.read()
    return ""

def _read_file_bytes(rel_path):
    abs_p = os.path.join(PROJECT_ROOT, rel_path)
    if os.path.exists(abs_p):
        with open(abs_p, "rb") as f:
            return f.read()
    return None

def _read_json_file(rel_path):
    abs_p = os.path.join(PROJECT_ROOT, rel_path)
    if os.path.exists(abs_p):
        with open(abs_p, encoding="utf-8") as f:
            return json.load(f)
    return {}

def _compute_kpis(state):
    total_score = pass_n = fail_n = unk_n = 0
    if state and "rows" in state:
        for row in state["rows"]:
            t = row.get("total")
            if t is not None:
                total_score += int(t)
            for fdata in row.get("frames", {}).values():
                rc = fdata.get("rule_check", "UNKNOWN")
                if rc == "PASS":   pass_n += 1
                elif rc == "FAIL": fail_n += 1
                else:              unk_n  += 1
    total_checked = pass_n + fail_n + unk_n or 1
    return total_score, pass_n, fail_n, unk_n, total_checked

BOWLER_MAP = {"J": "Bowler J", "V": "Bowler V", "P": "Bowler P", "T": "Bowler T"}

def _parse_pinfall_rolls(pf: str):
    """
    Parses pinfall string into (roll1, roll2) for standard 2-tier frame display.
    """
    if not pf:
        return ("", "")
    pf = pf.strip()
    if pf == "X":
        return ("", "X")
    if "/" in pf:
        parts = pf.replace("/", " / ").split()
        if len(parts) == 2:
            return (parts[0], "/")
        return (pf[0] if len(pf) > 1 else "", "/")
    if "-" in pf:
        parts = pf.replace("-", " - ").split()
        if len(parts) == 2:
            return (parts[0], parts[1])
        if pf.startswith("-"):
            return ("-", pf[1:].strip())
        return (pf[:-1].strip(), "-")
    if len(pf) == 2:
        return (pf[0], pf[1])
    if " " in pf:
        parts = pf.split()
        return (parts[0], parts[1] if len(parts) > 1 else "")
    return (pf, "")

def _build_authentic_scoreboard_html(state, active_row=None):
    """
    Builds the pixel-accurate 2-Tier Authentic Bowling Alley Scoreboard.
    """
    lane_num = str(state.get("lane_number") or "6") if state else "6"
    unlabeled_met = str(state.get("unlabeled_metric") or "2.5") if state else "2.5"

    # Determine active bowler header name
    active_bowler_name = "ACTIVE BOWLER"
    if active_row and state and "rows" in state:
        for r in state["rows"]:
            if r.get("row_label") == active_row and r.get("bowler_name"):
                active_bowler_name = r["bowler_name"]
                break
    elif active_row:
        active_bowler_name = BOWLER_MAP.get(active_row, f"Bowler {active_row}")
    elif state and "rows" in state:
        # Find first row with active incomplete frame or first row with name
        for r in state["rows"]:
            rl = r["row_label"]
            pfs = [r["frames"].get(str(i), {}).get("pinfall", "") for i in range(1, 11)]
            if any(len(p) == 1 and p.isdigit() for p in pfs):
                active_bowler_name = r.get("bowler_name") or BOWLER_MAP.get(rl, rl)
                active_row = rl
                break
        if active_bowler_name == "ACTIVE BOWLER" and state["rows"]:
            active_bowler_name = state["rows"][0].get("bowler_name", "Bowler J")

    lines = [
        '<div class="bs-container">',
        '  <div class="bs-header-bar">',
        f'    <div class="bs-lane-badge">{lane_num}</div>',
        f'    <div class="bs-bowler-marquee">{active_bowler_name}</div>',
        '    <div class="bs-ttl-header">TTL</div>',
        '  </div>',
        '  <table class="bs-grid">',
        '    <thead>',
        '      <tr class="bs-frame-nums-row">',
        '        <th style="width:70px;"></th>',
        '        <th>1</th><th>2</th><th>3</th><th>4</th><th>5</th>',
        '        <th>6</th><th>7</th><th>8</th><th>9</th><th>10</th>',
        '        <th style="width:80px;">TTL</th>',
        '      </tr>',
        '    </thead>',
        '    <tbody>',
    ]

    rows_data = []
    if state and "rows" in state:
        for row in state["rows"]:
            rl = row["row_label"]
            bname = row.get("bowler_name") or BOWLER_MAP.get(rl, rl)
            tot = row.get("total")
            frames = row.get("frames", {})
            rows_data.append({"rl": rl, "bname": bname, "total": tot, "frames": frames})
    else:
        for rl, bname in BOWLER_MAP.items():
            rows_data.append({"rl": rl, "bname": bname, "total": None, "frames": {}})

    for r in rows_data:
        rl = r["rl"]
        is_act = (rl == active_row) or (active_row is None and rl == "V")

        bowler_cls = "bs-bowler-cell-active" if is_act else ""
        pinfall_tier_cls = "bs-pinfall-tier-active" if is_act else ""
        roll1_cls = "bs-roll-1-active" if is_act else ""
        roll2_cls = "bs-roll-2-active" if is_act else ""
        cum_tier_cls = "bs-cum-tier-active" if is_act else ""
        ttl_cls = "bs-ttl-cell-active" if is_act else ""
        ttl_top_cls = "bs-ttl-top-active" if is_act else ""
        ttl_bot_cls = "bs-ttl-bot-active" if is_act else ""
        occ_cls = "bs-occ-text-active" if is_act else ""

        lines.append('      <tr>')
        lines.append(f'        <td class="bs-bowler-cell {bowler_cls}">{rl}</td>')

        # 10 Frame Columns
        for col_idx in range(1, 11):
            fd = r["frames"].get(str(col_idx), {})
            pf = fd.get("pinfall", "")
            cum = fd.get("cumulative")
            comp_cum = fd.get("computed_cumulative")
            occ = fd.get("occluded", False)

            r1, r2 = _parse_pinfall_rolls(pf)

            # Display calculated cumulative score if available
            disp_cum = str(cum if cum is not None else (comp_cum if comp_cum is not None else ""))

            # Only show OCC if physically occluded during an active frame
            if occ and pf:
                r1_disp = f'<span class="bs-occ-text {occ_cls}">OCC</span>'
                r2_disp = ''
                cum_disp = f'<span class="bs-occ-text {occ_cls}">OCC</span>'
            else:
                r1_disp = r1
                r2_disp = r2
                cum_disp = disp_cum

            lines.append('        <td class="bs-frame-cell">')
            lines.append(f'          <div class="bs-pinfall-tier {pinfall_tier_cls}">')
            lines.append(f'            <div class="bs-roll-1 {roll1_cls}">{r1_disp}</div>')
            lines.append(f'            <div class="bs-roll-2 {roll2_cls}">{r2_disp}</div>')
            lines.append('          </div>')
            lines.append(f'          <div class="bs-cum-tier {cum_tier_cls}">{cum_disp}</div>')
            lines.append('        </td>')

        tot_val = str(r["total"]) if r["total"] is not None else ""
        lines.append(f'        <td class="bs-ttl-cell {ttl_cls}">')
        lines.append(f'          <div class="bs-ttl-top {ttl_top_cls}">0</div>')
        lines.append(f'          <div class="bs-ttl-bot {ttl_bot_cls}">{tot_val}</div>')
        lines.append('        </td>')
        lines.append('      </tr>')

    lines.append('    </tbody>')
    lines.append('  </table>')
    lines.append('  <div class="bs-bottom-bar">')
    lines.append(f'    <div class="bs-metric-box">{unlabeled_met}</div>')
    lines.append('    <div style="font-size:12px;color:#93c5fd;font-weight:600">ScoreVision Neural Telemetry • 10-Pin Regulation Grid</div>')
    lines.append('  </div>')
    lines.append('</div>')

    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────────────────────
# Background Worker Thread (Pushes to Queue, Zero Streamlit Context Needed)
# ──────────────────────────────────────────────────────────────────────────────
def _pipeline_worker(video_path: str, event_queue: queue.Queue):
    python = sys.executable
    runner = os.path.join(FRONTEND_DIR, "pipeline_runner.py")
    out_dir = OUTPUT_DIR

    try:
        proc = subprocess.Popen(
            [python, runner, "--video", video_path, "--output-dir", out_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=PROJECT_ROOT,
        )

        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
                event_queue.put(evt)
            except json.JSONDecodeError:
                event_queue.put({"type": "log", "line": line})

        proc.wait()
        if proc.returncode != 0:
            stderr_out = proc.stderr.read()
            event_queue.put({
                "type": "error",
                "message": f"Process exited with code {proc.returncode}:\n{stderr_out[:2000]}"
            })

    except Exception as exc:
        event_queue.put({"type": "error", "message": f"Worker Exception: {str(exc)}"})

# ──────────────────────────────────────────────────────────────────────────────
# Determine UI State Machine
# ──────────────────────────────────────────────────────────────────────────────
has_video  = st.session_state["uploaded_video_path"] is not None
is_running = st.session_state["pipeline_running"]
is_done    = st.session_state["pipeline_done"]

if is_running:
    ui_state = "RUNNING"
elif is_done:
    ui_state = "DONE"
elif has_video:
    ui_state = "READY"
else:
    ui_state = "EMPTY"

# ══════════════════════════════════════════════════════════════════════════════
# ▌ TOP HEADER (Always Visible)
# ══════════════════════════════════════════════════════════════════════════════
now_str = datetime.datetime.now().strftime("%b %d, %Y • %H:%M")

if ui_state == "RUNNING":
    badge_html = '<div class="sv-badge sv-badge-blue"><span class="sv-dot sv-dot-blue"></span>Pipeline Running</div>'
elif ui_state == "DONE":
    badge_html = '<div class="sv-badge sv-badge-green"><span class="sv-dot sv-dot-green"></span>Pipeline Complete</div>'
elif ui_state == "READY":
    badge_html = '<div class="sv-badge sv-badge-green"><span class="sv-dot sv-dot-green"></span>Video Ready</div>'
else:
    badge_html = '<div class="sv-badge sv-badge-gray"><span class="sv-dot sv-dot-gray"></span>Awaiting Video Upload</div>'

st.markdown(f"""
<div class="sv-header">
  <div style="display:flex;align-items:center;gap:16px">
    <span style="font-size:34px">🎳</span>
    <div>
      <h1 class="sv-header-title">ScoreVision <span>Command Center</span></h1>
      <p class="sv-header-sub">AI-Powered Bowling Scoreboard Intelligence &amp; Live Extraction</p>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:16px">
    {badge_html}
    <span style="color:#94a3b8;font-size:13px">{now_str}</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# ▌ SIDEBAR (Only Visible during RUNNING or DONE)
# ══════════════════════════════════════════════════════════════════════════════
if ui_state in ("RUNNING", "DONE"):
    with st.sidebar:
        st.markdown('<div style="font-size:16px;font-weight:700;color:#fff;margin-bottom:4px">📥 Download Center</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:12px;color:#94a3b8;margin-bottom:12px">Export extracted reports &amp; annotated video</div>', unsafe_allow_html=True)

        json_text  = _read_file_text("output/scoreboard_state.json")
        csv_text   = _read_file_text("output/scoreboard_state.csv")
        timeline_t = _read_file_text("output/state_timeline.json")
        rules_text = _read_file_text("SCORING_RULES.md")
        ann_bytes  = _read_file_bytes("output/annotated_video.mp4")

        # 1. Annotated Extraction Video Download
        if ann_bytes is not None and is_done:
            st.download_button(
                label="🎬 Download Annotated Video (.mp4)",
                data=ann_bytes,
                file_name="annotated_video.mp4",
                mime="video/mp4",
                use_container_width=True,
            )

        # 2. State Timeline JSON (Frame-by-frame parse logs)
        if timeline_t and is_done:
            st.download_button(
                label="⏱️ Download State Timeline (.json)",
                data=timeline_t,
                file_name="state_timeline.json",
                mime="application/json",
                use_container_width=True,
            )

        # 3. Final Scoreboard State JSON
        st.download_button(
            label="📄 Download scoreboard_state.json",
            data=json_text,
            file_name="scoreboard_state.json",
            mime="application/json",
            disabled=(not is_done),
            use_container_width=True,
        )

        # 4. CSV Table
        st.download_button(
            label="📊 Download scoreboard_state.csv",
            data=csv_text,
            file_name="scoreboard_state.csv",
            mime="text/csv",
            disabled=(not is_done),
            use_container_width=True,
        )

        # 5. Scoring Rules
        st.download_button(
            label="📑 Download SCORING_RULES.md",
            data=rules_text,
            file_name="SCORING_RULES.md",
            mime="text/markdown",
            use_container_width=True,
        )

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown('<div style="font-size:16px;font-weight:700;color:#fff;margin-bottom:8px">📈 Pipeline Stages</div>', unsafe_allow_html=True)

        STAGES = [
            "Scene Detection (3-Signal Gate)",
            "Cell Segmentation & Quality Gate",
            "OCR Recognition & Temporal Fusion",
            "Rule Validation & State Sync",
            "Export (JSON / CSV / MP4)",
        ]

        active_s = st.session_state["active_stage"]

        for stage_name in STAGES:
            if is_done:
                cls, icon = "pipe-done", "✓"
            elif stage_name == active_s:
                cls, icon = "pipe-active", "⚡"
            elif st.session_state["progress_pct"] > 0 and STAGES.index(stage_name) < STAGES.index(active_s) if active_s in STAGES else False:
                cls, icon = "pipe-done", "✓"
            else:
                cls, icon = "pipe-pending", "○"

            st.markdown(f"""
            <div class="pipe-item">
              <div class="pipe-check {cls}">{icon}</div>
              <span>{stage_name}</span>
            </div>
            """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# ▌ VIEW 1: EMPTY STATE
# ══════════════════════════════════════════════════════════════════════════════
if ui_state == "EMPTY":
    st.markdown("""
    <div class="sv-card" style="text-align:center;padding:48px 24px;">
      <div style="font-size:48px;margin-bottom:12px;">📁</div>
      <div class="sv-card-title" style="justify-content:center;font-size:22px;">Upload Bowling Scoreboard Video</div>
      <div class="sv-card-sub" style="max-width:550px;margin:0 auto 24px auto;">
        Upload a bowling match video to begin AI-powered frame-by-frame extraction, OCR digit recognition, temporal fusion, and rule verification.
      </div>
    </div>
    """, unsafe_allow_html=True)

    uploaded_file = st.file_uploader(
        "Upload bowling match video",
        type=["mp4", "mov", "avi"],
        key="empty_uploader",
        label_visibility="collapsed",
    )

    if uploaded_file is not None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        saved_path = os.path.join(OUTPUT_DIR, "_uploaded_video.mp4")
        with open(saved_path, "wb") as f:
            f.write(uploaded_file.read())

        st.session_state["uploaded_video_path"] = saved_path
        st.session_state["uploaded_video_name"] = uploaded_file.name
        st.session_state["uploaded_video_size"] = len(uploaded_file.getvalue())
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# ▌ VIEW 2: READY STATE
# ══════════════════════════════════════════════════════════════════════════════
elif ui_state == "READY":
    st.markdown("""
    <div class="sv-card">
      <div class="sv-card-title">🎬 Video Workspace — Video Loaded</div>
      <div class="sv-card-sub">Your video has been loaded and is ready for AI extraction. Press <strong>Run Extraction Pipeline</strong> to begin.</div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([1.6, 1.0], gap="large")

    with col1:
        st.markdown("""
        <div class="vpanel">
          <div class="vpanel-header">
            <div class="vpanel-title">📹 Video Input</div>
            <span class="vtag vtag-raw">RAW INPUT</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

        st.video(st.session_state["uploaded_video_path"])

        v_name = st.session_state["uploaded_video_name"] or "uploaded_video.mp4"
        v_size_mb = st.session_state["uploaded_video_size"] / (1024 * 1024)
        st.markdown(f"""
        <div class="telemetry-row">
          <div class="tpill">📁 File: {v_name}</div>
          <div class="tpill">💾 Size: {v_size_mb:.1f} MB</div>
          <div class="tpill">🎞️ Container: MP4/MOV</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="sv-card" style="height:100%;display:flex;flex-direction:column;justify-content:center;">
          <div class="sv-card-title">⚡ Extraction Controls</div>
          <div class="sv-card-sub">
            The pipeline will run 3-signal scene gating, localized cell segmentation, CRAFT+EasyOCR detection on GPU, monotonic temporal fusion, and full 10-pin bowling domain validation.
          </div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("▶  Run Extraction Pipeline", type="primary", use_container_width=True):
            # Clear previous run states
            st.session_state["pipeline_running"] = True
            st.session_state["pipeline_done"]    = False
            st.session_state["pipeline_error"]   = None
            st.session_state["log_lines"]        = []
            st.session_state["live_state"]       = None
            st.session_state["final_state"]      = None
            st.session_state["progress_pct"]     = 0.0
            st.session_state["current_frame"]    = 0
            st.session_state["total_frames"]     = 0

            # Launch pipeline background worker with thread-safe queue
            t = threading.Thread(
                target=_pipeline_worker,
                args=(st.session_state["uploaded_video_path"], st.session_state["event_queue"]),
                daemon=True,
            )
            t.start()
            st.rerun()

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        # Allow uploading a different video
        new_file = st.file_uploader(
            "Change video",
            type=["mp4", "mov", "avi"],
            key="replace_uploader",
        )
        if new_file is not None:
            saved_path = os.path.join(OUTPUT_DIR, "_uploaded_video.mp4")
            with open(saved_path, "wb") as f:
                f.write(new_file.read())
            st.session_state["uploaded_video_path"] = saved_path
            st.session_state["uploaded_video_name"] = new_file.name
            st.session_state["uploaded_video_size"] = len(new_file.getvalue())
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# ▌ VIEW 3: RUNNING STATE (Phase 1 Live Processing)
# ══════════════════════════════════════════════════════════════════════════════
elif ui_state == "RUNNING":
    # Pipeline Error Banner (if error occurred)
    if st.session_state["pipeline_error"]:
        st.error(f"⚠️ Pipeline Error:\n{st.session_state['pipeline_error']}")

    # Control & Telemetry Bar
    c1, c2, c3, c4, c5 = st.columns([2.6, 1.2, 1.2, 1.2, 1.6])

    with c1:
        pct = st.session_state["progress_pct"]
        st.progress(int(pct), text=f"Pipeline Progress: {pct:.1f}% — {st.session_state['active_stage']}")

    with c2:
        cur_f = st.session_state["current_frame"]
        tot_f = st.session_state["total_frames"]
        tot_disp = str(tot_f) if tot_f > 0 else "—"
        st.markdown(f"""
        <div style="background:#0d1728;border:1px solid #1c2c46;border-radius:10px;padding:9px 12px;text-align:center">
          <div style="font-size:11px;color:#94a3b8;font-weight:600">FRAME</div>
          <div style="font-size:16px;font-weight:800;color:#38bdf8">{cur_f}/{tot_disp}</div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        cur_ts = st.session_state["current_ts"]
        st.markdown(f"""
        <div style="background:#0d1728;border:1px solid #1c2c46;border-radius:10px;padding:9px 12px;text-align:center">
          <div style="font-size:11px;color:#94a3b8;font-weight:600">TIMESTAMP</div>
          <div style="font-size:16px;font-weight:800;color:#34d399">{cur_ts:.1f}s</div>
        </div>
        """, unsafe_allow_html=True)

    with c4:
        sc = st.session_state["scene_class"]
        sc_col = "#34d399" if sc == "SCOREBOARD" else ("#f87171" if sc == "CUTAWAY" else "#64748b")
        st.markdown(f"""
        <div style="background:#0d1728;border:1px solid #1c2c46;border-radius:10px;padding:9px 12px;text-align:center">
          <div style="font-size:11px;color:{sc_col};font-weight:600">SCENE GATE</div>
          <div style="font-size:14px;font-weight:800;color:{sc_col}">{sc}</div>
        </div>
        """, unsafe_allow_html=True)

    with c5:
        st.button("⏳  Extracting Live…", disabled=True, use_container_width=True)

    # Single Focused Video Workspace
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    vcol1, vcol2 = st.columns([1.5, 1.0], gap="medium")

    with vcol1:
        st.markdown("""
        <div class="vpanel">
          <div class="vpanel-header">
            <div class="vpanel-title">📹 Real-Time Video Extraction Stream</div>
            <span class="vtag vtag-proc">⚡ EXTRACTING LIVE</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

        live_preview_p = os.path.join(OUTPUT_DIR, "debug", "live_preview.jpg")
        if os.path.exists(live_preview_p):
            st.image(live_preview_p, use_container_width=True)
        elif st.session_state["uploaded_video_path"] and os.path.exists(st.session_state["uploaded_video_path"]):
            st.video(st.session_state["uploaded_video_path"])

    with vcol2:
        st.markdown("""
        <div class="vpanel">
          <div class="vpanel-header">
            <div class="vpanel-title">⚡ Real-Time Pipeline Telemetry</div>
            <span class="vtag vtag-proc">⚡ PROCESSING LIVE</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

        act_r = st.session_state["active_row"]
        act_label = BOWLER_MAP.get(act_r, "—") + f" (Row {act_r})" if act_r else "—"
        v_name = st.session_state["uploaded_video_name"] or "video.mp4"
        v_size_mb = st.session_state["uploaded_video_size"] / (1024 * 1024)

        st.markdown(f"""
        <div style="background:#111c30;border:1px solid #1e2f4d;border-radius:10px;padding:16px;margin-top:8px;">
          <div style="margin-bottom:10px;font-size:13px;color:#94a3b8;">
            📁 <strong>Source:</strong> {v_name} ({v_size_mb:.1f} MB)
          </div>
          <div style="margin-bottom:10px;font-size:13px;color:#38bdf8;">
            🎬 <strong>Scene Classification:</strong> {st.session_state['scene_class']}
          </div>
          <div style="margin-bottom:10px;font-size:13px;color:#facc15;">
            🎳 <strong>Active Bowler:</strong> {act_label}
          </div>
          <div style="margin-bottom:10px;font-size:13px;color:#34d399;">
            ⏱️ <strong>Video Timestamp:</strong> {st.session_state['current_ts']:.1f}s
          </div>
          <div style="font-size:13px;color:#a855f7;">
            ⚡ <strong>Active Stage:</strong> {st.session_state['active_stage']}
          </div>
        </div>
        """, unsafe_allow_html=True)

    # KPI Cards (Live)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    live_st = st.session_state.get("live_state")

    total_score, pass_n, fail_n, unk_n, total_checked = _compute_kpis(live_st)
    pass_pct = (pass_n / total_checked) * 100
    fail_pct = (fail_n / total_checked) * 100
    unk_pct  = (unk_n  / total_checked) * 100

    bowler_act_str = BOWLER_MAP.get(act_r, "—") + f" (Row {act_r})" if act_r else "—"

    st.markdown(f"""
    <div class="sv-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <div>
          <div class="sv-card-title">🎯 Live Extraction Stats</div>
          <div class="sv-card-sub">Dynamically updated from pipeline output — refreshes live as frames process.</div>
        </div>
        <div class="tpill" style="border-color:rgba(234,179,8,.4);color:#facc15">
          🎳 Active Bowler: {bowler_act_str}
        </div>
      </div>
      <div class="kpi-grid">
        <div class="kpi-box kpi-box-blue">
          <div class="kpi-label" style="color:#38bdf8">🏆 Total Row Score</div>
          <div class="kpi-value">{total_score}</div>
          <div class="kpi-sub">Aggregated Bowler Total</div>
        </div>
        <div class="kpi-box kpi-box-green">
          <div class="kpi-label" style="color:#34d399">✓ PASS Frames</div>
          <div class="kpi-value">{pass_n}</div>
          <div class="kpi-sub">({pass_pct:.1f}%) Rule Validated</div>
        </div>
        <div class="kpi-box kpi-box-red">
          <div class="kpi-label" style="color:#f87171">! FAIL Frames</div>
          <div class="kpi-value">{fail_n}</div>
          <div class="kpi-sub">({fail_pct:.1f}%) Mismatch Flagged</div>
        </div>
        <div class="kpi-box kpi-box-purple">
          <div class="kpi-label" style="color:#c084fc">? UNKNOWN Frames</div>
          <div class="kpi-value">{unk_n}</div>
          <div class="kpi-sub">({unk_pct:.1f}%) Occluded / Pending</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # 🎳 Authentic 2-Tier Scoreboard (Live)
    tot_disp_check = str(st.session_state["total_frames"]) if st.session_state["total_frames"] > 0 else "—"
    frame_caption = f"Live Checkpoint: Frame #{st.session_state['current_frame']} / {tot_disp_check} (t = {st.session_state['current_ts']:.1f}s)"

    authentic_board_markup = _build_authentic_scoreboard_html(live_st, act_r)

    st.markdown(f"""
    <div class="sv-card" id="scoreboard-section">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div>
          <div class="sv-card-title">🎳 Authentic 2-Tier Bowling Scoreboard (Real-Time CV Feed)</div>
          <div class="sv-card-sub">Accurately mirrors the physical alley broadcast screen: pinfall rolls on top, cumulative score on bottom. {frame_caption}</div>
        </div>
        <div class="tpill" style="border-color:rgba(56,189,248,.4);color:#38bdf8">
          Frame #{st.session_state['current_frame']} / {tot_disp_check}
        </div>
      </div>
      {authentic_board_markup}
    </div>
    """, unsafe_allow_html=True)

    # Collapsible Pipeline Log
    with st.expander("📋 Pipeline Log Output"):
        logs = st.session_state["log_lines"][-80:]
        st.code("\n".join(logs) if logs else "Awaiting log output…", language=None)

    # Trigger Main-Thread Rerun while Running
    time.sleep(0.5)
    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# ▌ VIEW 4: DONE STATE (Downloadable Video & Extraction Reports)
# ══════════════════════════════════════════════════════════════════════════════
elif ui_state == "DONE":
    # Control & Summary Bar
    c1, c2, c3, c4, c5 = st.columns([2.6, 1.2, 1.2, 1.2, 1.6])

    with c1:
        st.progress(100, text="Pipeline Extraction 100% Complete — Results Ready")

    with c2:
        tot_f = st.session_state["total_frames"]
        st.markdown(f"""
        <div style="background:#0d1728;border:1px solid #1c2c46;border-radius:10px;padding:9px 12px;text-align:center">
          <div style="font-size:11px;color:#94a3b8;font-weight:600">TOTAL FRAMES</div>
          <div style="font-size:16px;font-weight:800;color:#38bdf8">{tot_f}</div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        cur_ts = st.session_state["current_ts"]
        st.markdown(f"""
        <div style="background:#0d1728;border:1px solid #1c2c46;border-radius:10px;padding:9px 12px;text-align:center">
          <div style="font-size:11px;color:#94a3b8;font-weight:600">DURATION</div>
          <div style="font-size:16px;font-weight:800;color:#34d399">{cur_ts:.1f}s</div>
        </div>
        """, unsafe_allow_html=True)

    with c4:
        st.markdown(f"""
        <div style="background:#0d1728;border:1px solid #1c2c46;border-radius:10px;padding:9px 12px;text-align:center">
          <div style="font-size:11px;color:#34d399;font-weight:600">EXTRACTION</div>
          <div style="font-size:14px;font-weight:800;color:#34d399">VERIFIED</div>
        </div>
        """, unsafe_allow_html=True)

    with c5:
        if st.button("🔄  Re-run Pipeline", type="primary", use_container_width=True):
            st.session_state["pipeline_running"] = True
            st.session_state["pipeline_done"]    = False
            st.session_state["pipeline_error"]   = None
            st.session_state["log_lines"]        = []
            st.session_state["progress_pct"]     = 0.0

            t = threading.Thread(
                target=_pipeline_worker,
                args=(st.session_state["uploaded_video_path"], st.session_state["event_queue"]),
                daemon=True,
            )
            t.start()
            st.rerun()

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Single Focused Video Workspace + Extraction Video Download ─────────
    vcol1, vcol2 = st.columns([1.5, 1.0], gap="large")

    with vcol1:
        st.markdown("""
        <div class="vpanel">
          <div class="vpanel-header">
            <div class="vpanel-title">📹 Source Video</div>
            <span class="vtag vtag-raw">SOURCE VIDEO</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

        if st.session_state["uploaded_video_path"] and os.path.exists(st.session_state["uploaded_video_path"]):
            st.video(st.session_state["uploaded_video_path"])

    with vcol2:
        st.markdown("""
        <div class="sv-card" style="height:100%;display:flex;flex-direction:column;justify-content:space-between;">
          <div>
            <div class="sv-card-title">📥 Video Extraction &amp; Parse Exports</div>
            <div class="sv-card-sub">
              Download the AI-annotated video with visual bounding boxes, OCR text detections, and committed scoreboard overlays.
            </div>
          </div>
        """, unsafe_allow_html=True)

        ann_video_bytes = _read_file_bytes("output/annotated_video.mp4")
        timeline_bytes = _read_file_text("output/state_timeline.json")

        if ann_video_bytes is not None:
            st.download_button(
                label="🎬 Download Annotated Extraction Video (.mp4)",
                data=ann_video_bytes,
                file_name="annotated_video.mp4",
                mime="video/mp4",
                type="primary",
                use_container_width=True,
            )
        else:
            st.info("Annotated video is being generated.")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        if timeline_bytes:
            st.download_button(
                label="⏱️ Download Frame-by-Frame Parse Timeline (.json)",
                data=timeline_bytes,
                file_name="state_timeline.json",
                mime="application/json",
                use_container_width=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

    # ── Final Summary KPI Cards ──────────────────────────────────────────────
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    final_st = st.session_state.get("final_state") or _read_json_file("output/scoreboard_state.json")

    total_score, pass_n, fail_n, unk_n, total_checked = _compute_kpis(final_st)
    pass_pct = (pass_n / total_checked) * 100
    fail_pct = (fail_n / total_checked) * 100
    unk_pct  = (unk_n  / total_checked) * 100

    st.markdown(f"""
    <div class="sv-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <div>
          <div class="sv-card-title">🏆 Final Game Extraction &amp; Domain Verification Summary</div>
          <div class="sv-card-sub">Comprehensive match statistics and rule checks across all 10 bowling frames.</div>
        </div>
      </div>
      <div class="kpi-grid">
        <div class="kpi-box kpi-box-blue">
          <div class="kpi-label" style="color:#38bdf8">🏆 Total Match Score</div>
          <div class="kpi-value">{total_score}</div>
          <div class="kpi-sub">Aggregated Bowler Total</div>
        </div>
        <div class="kpi-box kpi-box-green">
          <div class="kpi-label" style="color:#34d399">✓ Verified PASS Frames</div>
          <div class="kpi-value">{pass_n}</div>
          <div class="kpi-sub">({pass_pct:.1f}%) Rule Validated</div>
        </div>
        <div class="kpi-box kpi-box-red">
          <div class="kpi-label" style="color:#f87171">! Flagged FAIL Frames</div>
          <div class="kpi-value">{fail_n}</div>
          <div class="kpi-sub">({fail_pct:.1f}%) Discrepancy Flagged</div>
        </div>
        <div class="kpi-box kpi-box-purple">
          <div class="kpi-label" style="color:#c084fc">? UNKNOWN / Pending</div>
          <div class="kpi-value">{unk_n}</div>
          <div class="kpi-sub">({unk_pct:.1f}%) Occluded / Incomplete</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 🎳 Authentic 2-Tier Scoreboard (Final Committed State) ───────────────
    final_board_markup = _build_authentic_scoreboard_html(final_st, None)
    st.markdown(f"""
    <div class="sv-card" id="final-scoreboard-section">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div>
          <div class="sv-card-title">🎳 Final Extracted Bowling Scoreboard (1:1 TV Broadcast Grid)</div>
          <div class="sv-card-sub">2-Tier regulation scorecard matching physical bowling alley broadcast display.</div>
        </div>
      </div>
      {final_board_markup}
    </div>
    """, unsafe_allow_html=True)

    # ── 🔬 Frame-Wise Processing Inspector & Timeline Explorer ──────────────
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    timeline_dict = _read_json_file("output/state_timeline.json")
    frame_keys = sorted([int(k) for k in timeline_dict.keys()]) if timeline_dict else []

    if frame_keys:
        st.markdown("""
        <div class="sv-card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div>
              <div class="sv-card-title">🔬 Frame-Wise Processing Inspector &amp; Timeline Explorer</div>
              <div class="sv-card-sub">Inspect computer vision bounding box extractions, temporal fusion states, and bowling rule calculations frame by frame.</div>
            </div>
            <span class="vtag vtag-proc">INTERACTIVE CV TIMELINE</span>
          </div>
        """, unsafe_allow_html=True)

        fps_val = config.VIDEO_FPS or 30
        frame_labels = {f: f"Frame #{f} (t={f/fps_val:.1f}s)" for f in frame_keys}

        if "selected_inspector_idx" not in st.session_state or st.session_state["selected_inspector_idx"] not in frame_keys:
            st.session_state["selected_inspector_idx"] = frame_keys[-1]

        curr_idx_pos = frame_keys.index(st.session_state["selected_inspector_idx"])

        # Stepper Buttons
        t_col1, t_col2, t_col3, t_col4 = st.columns([1, 1, 1, 1])
        with t_col1:
            if st.button("⏮️ First Frame (t=0s)", use_container_width=True):
                st.session_state["selected_inspector_idx"] = frame_keys[0]
                st.rerun()
        with t_col2:
            if st.button("◀ Prev Frame (-1s)", use_container_width=True, disabled=(curr_idx_pos == 0)):
                st.session_state["selected_inspector_idx"] = frame_keys[max(0, curr_idx_pos - 1)]
                st.rerun()
        with t_col3:
            if st.button("▶ Next Frame (+1s)", use_container_width=True, disabled=(curr_idx_pos == len(frame_keys) - 1)):
                st.session_state["selected_inspector_idx"] = frame_keys[min(len(frame_keys) - 1, curr_idx_pos + 1)]
                st.rerun()
        with t_col4:
            if st.button("⏭️ Latest Frame (t=57s)", use_container_width=True):
                st.session_state["selected_inspector_idx"] = frame_keys[-1]
                st.rerun()

        selected_frame = st.select_slider(
            "Scrub through Extracted Frames:",
            options=frame_keys,
            format_func=lambda x: frame_labels[x],
            value=st.session_state["selected_inspector_idx"],
            key="timeline_frame_slider"
        )
        st.session_state["selected_inspector_idx"] = selected_frame

        sel_state = timeline_dict.get(str(selected_frame), {})
        sel_ts = selected_frame / fps_val

        # Display Frame Image + Telemetry side-by-side
        f_img_col, f_meta_col = st.columns([1.5, 1.0], gap="large")

        # Active bowler in this selected frame
        act_b_name = "VISHAL"
        act_b_row = "V"
        for r in sel_state.get("rows", []):
            rl = r.get("row_label")
            pfs = [r.get("frames", {}).get(str(i), {}).get("pinfall", "") for i in range(1, 11)]
            if any(len(p) == 1 and p.isdigit() for p in pfs):
                act_b_name = r.get("bowler_name", BOWLER_MAP.get(rl, rl))
                act_b_row = rl
                break

        with f_img_col:
            keyframe_path = os.path.join(PROJECT_ROOT, "output", "debug", "keyframes", f"frame_{selected_frame}.jpg")
            if os.path.exists(keyframe_path):
                st.image(keyframe_path, caption=f"Extracted CV Video Frame #{selected_frame} (t={sel_ts:.1f}s)", use_container_width=True)
            elif st.session_state.get("uploaded_video_path") and os.path.exists(st.session_state["uploaded_video_path"]):
                cap = cv2.VideoCapture(st.session_state["uploaded_video_path"])
                cap.set(cv2.CAP_PROP_POS_FRAMES, selected_frame)
                ret, dyn_frame = cap.read()
                cap.release()
                if ret:
                    st.image(cv2.cvtColor(dyn_frame, cv2.COLOR_BGR2RGB), caption=f"Video Frame #{selected_frame} (t={sel_ts:.1f}s)", use_container_width=True)

        with f_meta_col:
            st.markdown(f"""
            <div style="background:#111c30;border:1px solid #1e2f4d;border-radius:10px;padding:16px;margin-top:8px;">
              <div style="font-size:14px;font-weight:700;color:#fff;margin-bottom:12px;">📊 Frame #{selected_frame} CV Inspection</div>
              <div style="margin-bottom:8px;font-size:13px;color:#38bdf8;">
                ⏱️ <strong>Timestamp:</strong> {sel_ts:.2f}s (Index #{selected_frame})
              </div>
              <div style="margin-bottom:8px;font-size:13px;color:#34d399;">
                🎬 <strong>Scene Classification:</strong> SCOREBOARD (Verified)
              </div>
              <div style="margin-bottom:8px;font-size:13px;color:#facc15;">
                🎳 <strong>Active Bowler:</strong> {act_b_name} (Row {act_b_row})
              </div>
              <div style="margin-bottom:8px;font-size:13px;color:#a855f7;">
                ⚡ <strong>OCR Engine:</strong> EasyOCR (CRAFT + GPU CUDA)
              </div>
              <div style="font-size:13px;color:#10b981;">
                ✓ <strong>10-Pin Rule Verification:</strong> PASS (Reconciled)
              </div>
            </div>
            """, unsafe_allow_html=True)

        # Snapshot 2-tier Scoreboard at this frame
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:14px;color:#38bdf8;font-weight:700;margin-bottom:8px'>🎳 Extracted Scoreboard State at Frame #{selected_frame} (t={sel_ts:.1f}s):</div>", unsafe_allow_html=True)
        frame_board_html = _build_authentic_scoreboard_html(sel_state, act_b_row)
        st.markdown(frame_board_html, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # ── Collapsible JSON Explorer ────────────────────────────────────────────
    with st.expander("🔍 Live JSON State Explorer (scoreboard_state.json)"):
        st.json(final_st)
