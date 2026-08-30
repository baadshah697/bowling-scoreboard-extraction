# BUGFIX BRIEF v3 — Scene-Gate Regression, Fabricated Bowler Names, Root-Caused OCR Misreads

**Status: PARTIAL PASS.** B.1 (frame-index off-by-one) and B.2 (concatenated-digit garbling)
from BUGFIX_BRIEF_v2 are confirmed fixed — verified below with fresh evidence. But this
pass surfaces three problems, reviewed directly against extracted frames from
`annotated_video.mp4` (not guessed from the JSON alone):

1. **CRITICAL — the scene gate is once again failing to suppress the overlay on CUTAWAY
   frames.** This is the same class of issue as BUGFIX_BRIEF_v1 Issue #1, which was
   reported fixed. It is not fixed. Confirmed on two different cutaway types.
2. `bowler_name` / `is_team_row` in the schema are **hardcoded fiction**, not OCR output,
   and at least one is demonstrably wrong.
3. Every remaining `rule_check: FAIL` in the current output traces back to exactly **two**
   pinfall-cell misreads — root-caused with pixel crops, not guessed.

---

## PART A — Confirmed fixed (do not re-touch)

- **Frame-index alignment (v2 B.1/B.4):** Extracted frame at t=0.5s shows real board
  frame 1 = `X`/15, frame 2 = `5-`/20, frame 3 = `-7`/27, frame 4 = `4-`/31 for row J.
  `scoreboard_state.json` keys `"1"`–`"4"` match these exactly, and `computed_cumulative`
  is keyed to the same frame as the OCR'd `cumulative` in every case checked. Good —
  `config.FRAME_COLUMN_INDEX` as single source of truth worked.
- **Concatenated-digit garbling (v2 B.2):** No `701`/`715`-style values anywhere in the
  fresh output. All FAIL values are physically plausible bowling scores (see Part C).
- **Occlusion masking (v1 Issue #6 / v2 B.5):** At t=20s and t=40s the pin-icon graphic
  visibly covers columns 6–10 of rows J and V, and the annotated video shows grey `OCC`
  tags in exactly those cells at exactly those timestamps, matching `"occluded": true`
  for the same row/frame/timestamp in the export. This is now verifiable end-to-end.
- **Live overlay (v1 Issue #2):** Cell values visibly progress between t=0.5s, t=20s,
  t=30s, t=57s (e.g. J's frame 5 goes from unpopulated to `X` once it comes on-screen).
  Not frozen.

---

## PART B — CRITICAL REGRESSION: scene gate not gating the annotator

**Evidence:** Frame grabbed at **t=40s** shows the full-screen cartoon cutaway (pink
character, no scoreboard pixels anywhere in frame) — and `annotate_video.py` is still
drawing the teal `SCOREBOARD` banner, the full calibrated grid, `OCC` tags, and live cell
values (`X`, `4/`, `61`, `25`, red FAIL boxes, etc.) directly on top of it.

Frame grabbed at **t=50s** shows the full-screen "Brunswick" logo splash — same result:
`SCOREBOARD` banner still shown, full grid and every cell's last-committed value still
drawn on top of the logo.

This is the *exact* defect from BUGFIX_BRIEF_v1 Issue #1, which was reported resolved.
Two out of eight timestamps I independently sampled (25%) landed on cutaway content that
was misclassified as SCOREBOARD — this is not a rare edge case.

**Why it's happening (root cause, not just symptom):** `scene_gate.classify_frame()`
requires *both* `diff <= SCENE_GATE_DIFF_THRESHOLD` (5.0) *and*
`blue_coverage >= SCENE_GATE_BLUE_COVERAGE_MIN` (0.10) to call a frame SCOREBOARD. This
was calibrated against **transition** frames (board → cutaway), where diff spikes hard.
But:

- The diff signal only detects *change between consecutive frames*. Several seconds into
  a steady cutaway (the cartoon isn't moving much frame-to-frame, or the Brunswick logo
  is fully static), diff drops back down and looks exactly as "stable" as the real board.
  Diff-magnitude alone cannot distinguish "the board is stable" from "something else
  stable is on screen."
- `compute_blue_coverage()`'s HSV range (`BOARD_BLUE_HSV_LOWER/UPPER`, hue 90–140) is wide
  enough that both cutaway types trip it too: the Brunswick splash is dominated by a deep
  blue background, and the cartoon scene's background props (lockers, monitors, floor)
  contain enough blue-hue pixels to clear a 10% coverage bar.

So for any cutaway frame that isn't a transition frame, both signals independently give a
false SCOREBOARD reading. The "2-signal, cleanly bimodal" finding in the architecture doc
was measured on a diff sample that evidently didn't include enough of the *sustained*
(non-transition) cutaway frames to catch this.

**Required fix:**
1. Add a third, structural signal that doesn't depend on motion or color at all — e.g.
   check for the presence of the fixed grid geometry itself: sample a handful of known
   pixel coordinates that should always sit exactly on grid divider lines / label glyphs
   on the real board (e.g. inside `LABEL_COL` where "J"/"V"/"P"/"T" letters always render
   at fixed positions) and check for expected high-contrast edge structure there. Cutaway
   content won't reproduce that structure regardless of its color or motion profile.
   Alternative: template-match a small fixed crop (e.g. the "TTL" label glyph's pixel
   region) against a stored reference — cheap, and immune to both failure modes above.
2. Re-run scene gate classification across the *whole* video (not a 5-frame sample) and
   specifically report counts for sustained (non-transition) cutaway frames — i.e., don't
   just check accuracy at the boundary, check the middle of each cutaway segment too.
3. Regenerate `annotated_video.mp4` and re-check t=40s and t=50s (and pick 3 more
   timestamps yourself) to confirm the CUTAWAY label now shows and no grid/text is drawn.
4. Do not report this fixed without pasting fresh frame grabs at cutaway timestamps,
   same as the original Issue #1 required.

---

## PART C — Root cause of every current `rule_check: FAIL`

I extracted the actual board pixels (not the annotator's overlay text) for every FAILed
cell and hand-verified the scoring chain. **All six current FAILs (P frames 2/3/4, T
frames 2/3/4) collapse to exactly two source misreads.** The rule engine's arithmetic
(`bowling_rules.py`) is correct in every case I checked by hand — do not touch it.

### C.1 — Row P: real `9-` (frame 3) misread as `3`

Real board, frame 3, row P: **`9-`** (large white text, clearly legible).
Committed pinfall in state/JSON: **`3`**.

The "9" glyph in the board's italic font and the dropped trailing dash together produced
a single-character `"3"` reading that survived temporal fusion (i.e. it was read as `3`
consistently, not a one-off flicker — this is a systematic recognition error, not
something K-frame consensus can fix).

Manually recomputing with the **real** value `9-`:
- Frame 1 (`X`, strike) needs next two balls = frame 2's two balls (`4/` → 4, 6):
  score = 10+4+6 = 20 → matches OCR'd cumulative 20 (PASS, unaffected).
- Frame 2 (`4/`, spare) needs next one ball = frame 3's first ball. Real frame 3 first
  ball = **9** (not 3). Score = 10+9 = 19 → running = 20+19 = **39** → matches the OCR'd
  cumulative (39) exactly. **This alone flips frame 2 from FAIL to PASS.**
- Frame 3 (open, `9-`) score = 9+0 = 9 → running = 39+9 = **48** → matches OCR'd
  cumulative (48) exactly. **Flips frame 3 from FAIL to PASS.**
- Frame 4 (`6-`) score = 6 → running = 48+6 = **54** → matches OCR'd cumulative (54)
  exactly (it already matched, since it's the value everything downstream inherits).

So a single misread digit is responsible for 3 of the 6 total FAILs, and the OCR'd
`cumulative` column was correct all along — it was the `pinfall` column that was wrong.

### C.2 — Row T: real `1/` (frame 2) misread as `1`

Real board, frame 2, row T: **`1/`** (spare — clearly a "1" then a "/" stroke).
Committed pinfall in state/JSON: **`1`** (the "/" was dropped entirely).

Recomputing with the real value `1/`:
- Frame 1 (`6 1`, open) score = 7 → running = 7 (already PASS, unaffected).
- Frame 2 (`1/`, spare) needs next one ball = frame 3's first ball. Real frame 3 = `8-` →
  first ball = 8. Score = 10+8 = 18 → running = 7+18 = **25** → matches OCR'd cumulative
  (25) exactly. **Flips frame 2 from FAIL to PASS.**
- Frame 3 (`8-`, open) score = 8 → running = 25+8 = **33** → matches OCR'd cumulative (33)
  exactly. **Flips frame 3 from FAIL to PASS.**
- Frame 4 (`3 4`, open — confirmed from pixels, not `34` as a typo, it's genuinely two
  separate digits `3` and `4`) score = 7 → running = 33+7 = **40** → matches OCR'd
  cumulative (40) exactly. **Flips frame 4 from FAIL to PASS.**

Same pattern: a dropped `/` on one cell cascades through three frames via the
delayed-scoring rule, and the OCR'd cumulative column was right the whole time.

### C.3 — Same failure mode, no scoring impact: row J frame 2

Real board: `5-`. Committed pinfall: `5` (dash dropped). This one happens to not change
the arithmetic (a trailing dash contributes 0 either way), so `rule_check` still shows
PASS — but the exported `pinfall` field is still factually incomplete. Same underlying
cause as C.1/C.2, just scored differently.

### What this means for `ocr_engine.py`

The dash (`-`) and spare-slash (`/`) are being dropped intermittently and inconsistently
(present in some cells, absent in others within the same frame at the same timestamp —
e.g. row V's `8-`/`3-` came through fine at the very same moment row J's `5-` didn't).
That inconsistency points to **detection**, not charset/allowlist: EasyOCR's CRAFT
detector is likely failing to box the thin trailing stroke as its own text region in some
crops, not misclassifying a detected box. Separately, the "9→3" case in C.1 is a genuine
**recognition** error on a stylized/italic glyph, a different failure mode from the
dropped strokes.

**Required fix (instrument before guessing):**
1. Log the raw EasyOCR `readtext()` output (all detected boxes + confidences, not just the
   joined string) for every pinfall cell for at least one full pass. This tells you
   whether the dash/slash is ever being detected-but-misclassified (recognition problem,
   fixable with charset/preprocessing tuning) vs. never detected at all (detection
   problem, needs `text_threshold`/`low_text` tuning or a wider crop margin).
2. For the digit-recognition case (9→3): crop and save the exact P-frame-3 pinfall cell
   across a few frames to `output/debug/`. Check whether upscaling more aggressively
   (higher `mag_ratio` specifically for pinfall cells, not just cumulative) or trying the
   adaptive-threshold fallback pass (already built in Phase 7, currently only triggered on
   low OCR confidence) helps — the fallback path might already fix this if its trigger
   condition were loosened, since a *confident* wrong answer never reaches it today.
3. Once source-fixed, re-run and confirm all 6 currently-FAILed cells flip to PASS with
   *no changes to `bowling_rules.py`* — that file is verified correct by hand above.

---

## PART D — `bowler_name` / `is_team_row` are fabricated, and at least one is wrong

`temporal_fusion.py`'s `ROW_META` hardcodes:
```python
ROW_META = {
    "J": {"bowler_name": "JAGDISH", "is_team_row": False},
    "V": {"bowler_name": "VIJAY",   "is_team_row": False},
    "P": {"bowler_name": "PAWAN",   "is_team_row": False},
    "T": {"bowler_name": "TEAM",    "is_team_row": True},
}
```
These names are never read from the video. The `HEADER_BAND` region (marquee name that
changes with the active bowler) is never OCR'd anywhere in the pipeline.

**Direct visual evidence from three timestamps:**
- **t=0.5s:** header marquee reads `TARUN`. The row highlighted active at that exact
  moment (bright yellow pinfall-row background, distinct from the other rows' plain blue)
  is **row T** — not one of J/V/P.
- **t=30s:** header marquee reads `JAGDISH`, and row **J** is the one highlighted active.
  This one happens to match the hardcoded guess — coincidence, not extraction.
- **t=57s:** header marquee reads `VISHAL`, and row **V** is the one highlighted active.
  This does *not* match the hardcoded `"VIJAY"`.

Two independent, timestamped observations (`TARUN`↔T-active, `VISHAL`↔V-active) point the
same direction: **row T is very likely a fourth individual bowler named Tarun, not a
"team" aggregate row**, and `is_team_row: true` for T is probably a wrong label carried
over from the architecture doc's initial (reasonable, but unverified) guess about why T is
drawn in red. The BOWLING_DOMAIN brief's Part A.4 finding — "T's pinfalls aren't the sum
of J/V/P, so score it independently" — is still operationally correct either way (a 4th
bowler is scored independently too), so no rule-engine change is needed there. But the
metadata fields describing *what T is* are asserting something that hasn't actually been
verified and now looks wrong.

**Required fix:**
1. OCR `config.HEADER_BAND` on every processed frame (or at least once per detected
   "active row changed" event, using the highlight-color change as a trigger — cheap,
   since it's already being computed for nothing right now) and populate `bowler_name`
   from the real marquee text, not a hardcoded dict.
2. Determine `is_team_row` from evidence, not assumption — e.g. check across enough of
   the video whether row T's header name is ever a plain human first name (settles it as
   a 4th bowler) or whether the marquee ever explicitly reads something like "TEAM" or
   "PAIR" (settles it as an aggregate row). Report whichever is actually observed; don't
   guess between them again.
3. Re-run and confirm `bowler_name` in the fresh JSON matches what's visible on-screen at
   the corresponding `source_timestamp_range_sec` for each row.

---

## Priority order

1. **Part B** (scene gate / annotator regression) — this was already flagged once as
   CRITICAL and reported fixed; it isn't. Fix and prove it with fresh cutaway-timestamp
   frame grabs, the same bar as BUGFIX_BRIEF_v1 required.
2. **Part C** (the two source pinfall misreads) — fixing OCR detection/recognition here
   should flip all 6 current FAILs to PASS with zero changes to the rule engine. Instrument
   first per C's "Required fix," don't just tune thresholds blindly.
3. **Part D** (fabricated bowler names / team-row assumption) — lower urgency than B/C
   since it doesn't corrupt scoring, but it's a locked-schema field currently returning
   fiction, and the "team row" assumption baked into the architecture doc's Part A.4 now
   looks empirically shaky.

## Definition of Done for this pass

- [ ] Fresh `annotated_video.mp4`, with frame grabs at t=40s and t=50s (or your own picks)
      showing the `CUTAWAY - no board detected` label and **no** grid/cell overlay drawn.
- [ ] A written explanation of the third signal added (or why diff+blue was tuned
      differently) plus fresh SCOREBOARD/CUTAWAY counts across the *full* video.
- [ ] Raw EasyOCR detection dump for the P-frame-3 and T-frame-2 pinfall cells across
      several frames, showing which failure mode (never-detected vs. misclassified) each is.
- [ ] A fresh `scoreboard_state.json` where P and T rows show 0 FAILs (or a specific,
      evidenced explanation for any that remain).
- [ ] `bowler_name` populated from real OCR for at least one full row-active cycle, with
      the corresponding timestamp cited, and `is_team_row` set from actual observed
      evidence rather than left as an unverified guess.
- [ ] A real, freshly recomputed mismatch rate with sample size, pulled directly from the
      fresh output file at write time (per the standing process rule from prior briefs).

Resubmit once all boxes are checked against a fresh full run.
