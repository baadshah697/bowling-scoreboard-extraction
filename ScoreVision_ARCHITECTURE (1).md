# ScoreVision — Robust Bowling Scoreboard Intelligence
**Final Locked Architecture & Build Specification (v2) — FOG Computer Vision Engineer Assignment**

This is the locked spec, merging the original architecture with the accepted revisions
below. It is grounded in what the actual video contains, measured directly rather than
assumed. Where something is *not yet confirmed*, it's marked as such — no invented
metrics, no invented bowling fields.

### Revision log (v1 → v2)
| Change | Accepted? | Reasoning |
|---|---|---|
| Split Scene Gate / Quality Gate into two stages | ✅ Accepted | Cleaner separation of concerns, both lightweight |
| Multi-signal scene classifier (diff + color + edge + structure) | ⚠️ Partially accepted | Measured diff data shows 30–100x clean separation between steady-state (0.6–1.3) and cutaway (20–140+) frames with zero overlap in-sample. A 3–4 signal fusion model is unjustified complexity for an already-bimodal signal. **Using diff (primary) + HSV color-coverage (corroborating check) — 2 signals, not 4** — and will only add more if Phase 2 testing proves it's needed. |
| Multi-hypothesis preprocessing, fallback-only | ✅ Accepted | Already scoped this way in v1; confirmed |
| Confidence-weighted temporal state machine over plain majority vote | ✅ Accepted | Genuinely more robust, still lightweight (no HMM) |
| Verify bowling notation empirically before coding the rule engine | ✅ Accepted, and flagged as an open item | All sampled frames so far only show frames 1–4 filled. 10th-frame bonus layout and a full completed row have not yet been observed. Rule engine can't be finalized until Phase 6 confirms this from real frames later in the clip. |
| Tests directory, evidence-based confidence + reasons, VLM scoped as fallback-only | ✅ Accepted | Cheap, credible, already broadly consistent with v1 |

---

## 1. Ground truth about the actual video (measured, not assumed)

| Property | Value |
|---|---|
| Resolution | 1920×1080, 30fps, 57.83s, 1735 frames |
| Board position | Fixed, static camera. Top-left origin ~(35,10) to ~(1830,780) in 1920×1080 space |
| Structure | Lane number (top-left, large), active bowler's name (top, marquee), 4 scoring rows |
| Rows | `J`, `V`, `P` = individual bowler initials (one active at a time, row highlighted yellow/red); `T` = team/pair running total row, always highlighted red |
| Columns | Frames 1–10, each frame showing pinfall symbols (`X`, `/`, `-`, digits, split combos like `8 1`) above a cumulative running total |
| Right column | `TTL` — final/current cumulative total per row |
| Unlabeled field | Bottom-left number (`2.5`, `2.4`, `2.3`...) changes across frames — **meaning not confirmed from visuals alone; will be reported as `unlabeled_metric` in output, not guessed at** |

### Critical finding neither draft plan accounted for
Frame-diff sampled at 1fps across the full video shows two distinct behaviors:

- **Steady-state scoreboard frames:** mean pixel diff ≈ 0.6–1.3 (tiny — just the pin-overlay
  graphic flickering in the corner).
- **Cutaway frames:** mean diff spikes to **20–140** — because the feed periodically cuts
  **away from the scoreboard entirely** to (a) a full-screen cartoon pin-fall animation and
  (b) a full-screen "Brunswick" logo/pin splash screen. These aren't occlusions on top of the
  board — the board is off-screen completely for several seconds at a time.

This means the Gatekeeper can't just be "is the board stable," it has to first answer
**"is the board on screen at all,"** then "is it clean enough to read." That single measured
fact is why this design differs from both draft prompts and is the main technical decision
driving the architecture below.

---

## 2. Pipeline (v2)

```
video
  │
  ▼
[1] SCENE GATE          — diff magnitude (primary) + HSV board-color coverage (corroborating)
  │                        → SCOREBOARD | CUTAWAY. Only SCOREBOARD frames proceed.
  ▼
[2] QUALITY GATE         — separate question: is THIS scoreboard frame OCR-suitable?
  │                        Laplacian blur variance + neighbor-frame diff (mid-transition
  │                        check). clean → OCR ; blurred/transitional → reject ; skip to
  │                        next sampled frame.
  ▼
[3] GRID CALIBRATION    — one-time: locate board + row/column grid lines (contour/line
  │                        detection with fixed-ROI fallback), stored in config.py.
  │                        Re-verified every N frames (alignment check) in case of drift —
  │                        cheap, since camera is static and this should rarely trigger.
  ▼
[4] CELL SEGMENTATION   — slice grid into (row × frame-column) cells using calibrated
  │                        geometry — never one OCR pass over the whole board.
  ▼
[5] OCCLUSION MASK      — detect the pin-icon graphic's bounding box per frame (color-blob),
  │                        null out any cell it overlaps for THAT frame only. Recovery comes
  │                        from temporal evidence in clean frames, not from guessing.
  ▼
[6] CELL OCR            — EasyOCR per cell, constrained charset per cell type (pinfall:
  │                        digits/X/-//space ; total: digits only). Primary pass = single
  │                        preprocessing (grayscale+threshold). Cells with low OCR confidence
  │                        escalate to [6b].
  ▼
[6b] MULTI-HYPOTHESIS   — fallback only: re-run OCR on 2–3 alternate preprocessings
  │    (adaptive threshold / upscale / denoise), fuse candidates by agreement.
  ▼
[7] TEMPORAL STATE      — confidence-weighted state machine per cell: hold current committed
  │  MACHINE               value; a new differing reading only overwrites it after it repeats
  │                        across ≥K independent frames (not a single-frame majority vote).
  │                        Absorbs one-off misreads without needing the VLM.
  ▼
[8] BOWLING RULE ENGINE — independently recompute each row's cumulative total from its own
  │                        pinfall symbols, USING NOTATION VERIFIED FROM REAL FRAMES (see
  │                        open item below — not finalized from assumed examples).
  │                        Compare computed total to the OCR'd running-total cell.
  │                        MATCH → high confidence, keep as-is. MISMATCH → flag cell.
  ▼
[9] VLM FALLBACK (opt.) — ONLY for cells still flagged after [7]+[8] disagree: crop that one
  │                        cell, ask a vision LLM for a strict-JSON reading. Off by default,
  │                        project must run fully without an API key.
  ▼
[10] CONFIDENCE +        — confidence = f(OCR agreement, temporal consistency, occlusion
  │   EXPLAINABILITY        state, rule validation) — computed, not fabricated. Each cell
  │                        carries a short human-readable reason list (see §10).
  ▼
[11] STRUCTURED EXPORT  — JSON + CSV, schema below
  ▼
[12] ANNOTATED VIDEO    — overlay grid box, scene status, active player, live-read cells,
  │                        confidence, rule-check status
  ▼
[13] TESTS              — tests/test_parser.py, test_rules.py, test_temporal.py — small
                           deterministic cases, run before calling any phase "done"
```

### Open validation item (do not skip)
Every frame sampled so far only shows bowling frames 1–4 populated. The 10th-frame
bonus-throw notation and a fully completed row have **not been observed yet**. Phase 6 of
the build order must pull frames from later in the clip (or confirm the clip never reaches
a completed game) before `bowling_rules.py` is finalized — the rule engine will be built
against verified real notation, not the illustrative example from the first draft.

### Why this beats "OCR the whole frame":
1. **Cell-level OCR** is far more accurate than whole-board OCR because each cell has a known,
   constrained alphabet — the parser never has to disambiguate "is this a name or a score."
2. **Scene gate** stops the pipeline from wasting time (and introducing garbage) on the ~15s of
   the clip that isn't the scoreboard at all.
3. **The bowling rule engine is a self-checking arithmetic layer that's specific to this
   domain** — it doesn't just detect an error, it tells you *which* cell is wrong, because the
   running-total column is a checksum over the pinfall columns. That's the one piece of real
   "engineering thinking" a naive OCR script structurally cannot produce.
4. **VLM fallback is scoped to single flagged cells**, not "call GPT-4o on every frame" — cheap,
   fast, and honestly describable as a small correction layer rather than the whole system.

---

## 3. Output schema (reflects the actual board, not a guessed one)

```json
{
  "lane_number": "6",
  "rows": [
    {
      "row_label": "J",
      "bowler_name": "JAGDISH",
      "is_team_row": false,
      "frames": {
        "1": {"pinfall": "X",   "cumulative": 15, "confidence": 0.97},
        "2": {"pinfall": "5-",  "cumulative": 20, "confidence": 0.95},
        "3": {"pinfall": "-7",  "cumulative": 27, "confidence": 0.93},
        "4": {"pinfall": "4-",  "cumulative": 31, "confidence": 0.96}
      },
      "total": 31,
      "rule_check": "PASS"
    }
  ],
  "unlabeled_metric": "2.5",
  "source_timestamp_range_sec": [0, 12]
}
```
CSV is a flattened row-per-(bowler, frame) view of the same data for spreadsheet review.

---

## 4. Repo structure (v2)

```
bowling-scoreboard-extraction/
├── data/bowling_scoreboard.mp4
├── src/
│   ├── config.py              # calibrated ROI, grid geometry, HSV thresholds — isolated, named
│   ├── video_reader.py
│   ├── scene_gate.py          # [1] diff + HSV color-coverage → SCOREBOARD | CUTAWAY
│   ├── quality_gate.py        # [2] blur / transition rejection
│   ├── board_calibrator.py    # [3] grid calibration + periodic re-verify
│   ├── cell_segmenter.py      # [4]
│   ├── occlusion_mask.py      # [5]
│   ├── preprocessing.py       # grayscale/threshold/adaptive/upscale variants
│   ├── ocr_engine.py          # [6][6b] EasyOCR wrapper, constrained charset, fallback multi-hypothesis
│   ├── temporal_fusion.py     # [7] confidence-weighted state machine
│   ├── bowling_rules.py       # [8] scoring engine + validator (built AFTER notation confirmed)
│   ├── confidence.py          # [10] evidence-based confidence + reasons
│   ├── exporter.py            # [11]
│   ├── annotate_video.py      # [12]
│   └── main.py                # orchestrator
├── optional/
│   └── vlm_fallback.py        # [9] pluggable, off by default, no API key required to run
├── app/streamlit_app.py       # thin wrapper, built only after CLI pipeline works
├── tests/
│   ├── test_parser.py
│   ├── test_rules.py
│   └── test_temporal.py
├── output/{extracted.json, extracted.csv, annotated_video.mp4}
├── output/debug/               # intermediate crops/overlays for the doc PDF
├── screenshots/
├── requirements.txt
├── README.md
└── .gitignore
```

## 5. Build order (locked, matches Phases 1–15 from the reviewed spec)

1. **Video analysis** (done — §1 above) + `config.py` with measured ROI.
2. `scene_gate.py` — run against the full 1735 frames, report actual SCOREBOARD/CUTAWAY
   counts and the diff+color values observed (not the 5-frame sample alone).
3. `quality_gate.py` — verify against sampled frames, tune blur threshold empirically.
4. `board_calibrator.py` + `cell_segmenter.py` — draw the calibrated grid over a frame,
   visually confirm cell boxes align to the real columns/rows before trusting any OCR on them.
5. `ocr_engine.py` baseline (single preprocessing) — hand-label a small sample of cells,
   measure raw accuracy, log common failure modes (which characters get confused).
6. **Confirm bowling notation** from real frames spanning more of the game (10th frame,
   completed row) — only then write `bowling_rules.py`.
7. `preprocessing.py` multi-hypothesis fallback — compare accuracy baseline vs. fallback-assisted,
   only keep it if it measurably helps.
8. `temporal_fusion.py` — compare raw OCR vs. temporally-fused accuracy on the same labeled sample.
9. `bowling_rules.py` — run rule_check across all rows once implemented, report real mismatch rate.
10. `confidence.py` — evidence-based scoring + reason strings.
11. `optional/vlm_fallback.py` — stub/interface first; wire a real API only if time allows.
12. `exporter.py`, `annotate_video.py` — structured output + visual proof for the demo video.
13. `tests/` — lock in the deterministic cases before calling any phase done.
14. `app/streamlit_app.py` — only after the CLI pipeline runs standalone end-to-end.

## 6. Honesty constraints (carried into README and docs)
- Any accuracy/confidence number reported must come from an actual run against
  `bowling_scoreboard.mp4`, with the sample size stated.
- The bottom-left number is reported verbatim, unlabeled — not guessed at.
- Grid calibration is a fixed ROI **because the camera is static in this video** — stated as a
  design decision, not hidden as if it were general-purpose auto-detection.
- The scene gate is 2-signal (diff + color coverage) because that's what the measured data
  justified — not artificially expanded to look more sophisticated.
- Bowling scoring rules are implemented only after being confirmed against real frames
  showing the relevant notation — not derived from the illustrative example in early drafts.
- VLM fallback is optional, off by default, and clearly scoped — not presented as core CV work.
