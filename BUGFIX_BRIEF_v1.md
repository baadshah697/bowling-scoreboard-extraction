# BUGFIX BRIEF — ScoreVision Pipeline Review (Post Phase 1–12 Walkthrough)

**Status: REJECTED — do not proceed to Phase 13/14 (tests, Streamlit app).**
Your last walkthrough claimed Phases 1–12 were complete and asked for review before
wrap-up. I reviewed the actual output artifacts (`scoreboard_state.json`,
`scoreboard_state.csv`, `annotated_video.mp4`) against the source video and against your
own architecture doc's non-negotiable requirements (`ScoreVision_ARCHITECTURE.md` §2 and
`AGENT_BUILD_BRIEF.md` §0). Several core requirements are violated. This document lists
every issue found, the evidence, and what "done" actually looks like for each. Fix these
before touching Phase 13.

Rule reminder from your own brief, §0.2: **"Never fabricate a number... if you haven't
measured it, say 'not yet measured.'"** Apply that to your own status reports too — the
walkthrough claimed a 0.0% mismatch rate that your own output file directly contradicts
(see Issue #3). Going forward, every claim in a walkthrough must be verifiable by opening
the actual output file.

---

## Issue #1 — Scene Gate is not wired into `annotate_video.py` (CRITICAL)

**This was called out in the architecture doc as "the main technical decision driving the
architecture."** It is not functioning in the delivered output.

**Evidence:** I sampled `annotated_video.mp4` at t≈0s, t≈20s, t≈50s, and t≈83s.

- At t≈50s the frame is the **full-screen cartoon cutaway** (pink animated character,
  no scoreboard visible anywhere in frame).
- At t≈83s the frame is the **full-screen Brunswick logo splash screen**.
- In **both** cases, `annotate_video.py` still drew the calibrated grid lines and the
  scoreboard text overlay (`X`, `5-`, `15`, `99`, red mismatch box) directly on top of
  the cutaway content.

Per your own spec: *"Only SCOREBOARD frames proceed"* past the scene gate, and cutaway
frames are frames where **"the board is off-screen completely."** Drawing a scoreboard
overlay on a frame that scene_gate should have classified CUTAWAY means one of:
(a) `scene_gate.py` is never called from `annotate_video.py`'s per-frame loop, or
(b) it's called but its output is ignored, or
(c) the classifier itself is misfiring on these frames (less likely, since your Phase 2
diff/color signal was reported as cleanly bimodal).

**Required fix:**
1. In `annotate_video.py`, call `scene_gate.classify(frame)` for every frame before any
   drawing logic runs.
2. If classification is CUTAWAY, draw **nothing** (or at most a small "CUTAWAY — no board
   detected" label) — do not draw grid, cell text, or rule-check boxes.
3. Re-run and re-extract frames at the same cutaway timestamps to confirm the overlay is
   now suppressed.
4. Report actual counts: how many of the sampled/processed frames were classified
   CUTAWAY vs SCOREBOARD in the final full run, and confirm none of the CUTAWAY frames
   have overlay artifacts in the output video (spot-check at least 5 timestamps you
   independently pick, not ones I gave you).

---

## Issue #2 — Overlay values appear frozen; no evidence of live per-frame updates

**Evidence:** The exact same reading — `J row: frame1="X"/15, frame2="5-"/99 (flagged red)`
— appears identically at t≈0s, t≈20s, t≈50s (cutaway), and t≈83s (logo splash). Across an
83-second span with multiple scene changes, the visible overlay text never changes, even
though frames 3 and 4 for J (`-7`/27, `4-`/31) and full V/P/T row data are clearly present
and legible in the underlying video the whole time.

**Required fix:**
1. Confirm whether `annotate_video.py` is re-reading the live/current committed state per
   frame or baking in a single state computed once. It must re-render the *current*
   temporal-fusion-committed value for every frame it draws on.
2. Confirm `temporal_fusion.py` is actually being invoked per-cell per-frame during the
   annotation pass, not just during a separate offline `main.py` run that never feeds
   back into `annotate_video.py`.
3. After the fix, pull frames at 4–5 different timestamps spanning the video and confirm
   the overlaid values differ appropriately as frames 3, 4, etc. become populated on
   screen (e.g., J row should show frame 3 = `-7`/27 and frame 4 = `4-`/31 once those are
   on-screen and committed — right now the overlay never gets past frame 1/2).

---

## Issue #3 — Walkthrough claimed "0.0% mismatch rate"; your own JSON shows a FAIL

**Evidence:** Your message said: *"Logs a mismatch rate. On an initial limited test, the
mismatch rate is 0.0% (though real OCR errors in full video processing will naturally
trigger flags)."*

But `output/scoreboard_state.json` from that same run contains:
```json
{"pinfall": "5-", "cumulative": 99, "computed_cumulative": 20, "rule_check": "FAIL"}
```
This is a real mismatch on the second frame processed. The ground-truth value visible on
the board itself is 20 (15 + 5 = 20 after an open frame following a strike — OCR misread
the tens digit or double-counted). The rule engine is correctly flagging this — that part
works — but the reported "0.0%" number is false. Per your own operating rule
(`AGENT_BUILD_BRIEF.md` §0.2), **do not report a metric you have not actually verified
against the current output file.**

**Required fix:**
1. Before writing any walkthrough/status update, actually open the current
   `output/scoreboard_state.json` and compute real PASS/FAIL counts from it.
2. Report the true mismatch rate for the run being described, with the sample size
   (e.g. "2/2 cells checked in this partial run, 1 FAIL, 1 PASS").
3. Investigate why frame 2 OCR'd as 99 instead of 20 — log this as a specific OCR failure
   mode per Phase 5's DoD ("log the specific misreads").

---

## Issue #4 — `scoreboard_state.json` is missing almost all rows/frames

**Evidence:** The exported JSON contains only:
- Player `J`, and only frames 1–2.
- No `V`, `P`, or `T` rows at all — despite these being clearly visible, in-frame, and
  even correctly OCR'd in the annotated video overlay itself (V: `8-`,`3-`,`7 1`,`8 1` →
  8,11,19,28; P: `X`,`4/`,`9-`,`6-` → 20,39,48,54; T: `6 1`,`1/`,`8-` → 7,25,33).
- No `lane_number`, `bowler_name`, `is_team_row`, `total`, `unlabeled_metric`, or
  `source_timestamp_range_sec` fields — all of which are in the locked schema
  (`ScoreVision_ARCHITECTURE.md` §3 / `AGENT_BUILD_BRIEF.md` §3).

**Required fix:**
1. `exporter.py` must serialize the **full StateTracker** for every row (`J`, `V`, `P`,
   `T`) and every populated frame column, not a single row/partial-frame subset.
2. Match the locked schema exactly — including `lane_number`, `bowler_name`,
   `is_team_row`, per-frame `confidence`, `occluded`, per-frame `rule_check`, row-level
   `total`/`rule_check`, `unlabeled_metric`, and `source_timestamp_range_sec`.
3. Re-run the full pipeline and paste the *actual* resulting JSON (not a hand-trimmed
   excerpt) into the next walkthrough for review.

---

## Issue #5 — `scoreboard_state.csv` is completely empty (all rows `UNKNOWN`)

**Evidence:** Every single row in the CSV — all 40 (player × frame) combinations — has
blank `Pinfall`, `OCR_Cumulative`, `Computed_Cumulative`, and `Rule_Check = UNKNOWN`. This
is not "flattening the JSON tree" as claimed in the walkthrough — it's not reading from
the tracked state at all; it looks like a template/placeholder being written for every row
regardless of whether that cell was ever processed.

**Required fix:**
1. Debug `exporter.py`'s CSV path specifically — confirm it's iterating over the same
   populated `StateTracker` object as the JSON export (not a stale/default object).
2. `UNKNOWN` should only appear for cells that were genuinely never read (e.g. frames 5–10
   before the game reaches them) — not for cells like J/frame-1 that are known, OCR'd, and
   already present correctly in the JSON.
3. After fixing, the CSV and JSON must agree with each other for every populated cell —
   add a quick self-check script that diffs the two and reports any inconsistency.

---

## Issue #6 — Occlusion mask does not appear to be suppressing pin-icon-covered cells

**Evidence:** In the sampled frame at t≈20s, the animated pin-icon graphic is visibly
overlapping frame columns 5–9 of row J (as your architecture doc predicted it would). The
grid lines are still drawn straight through the icon with no occlusion indicator, and no
`occluded: true` cells appear anywhere in the JSON output (there's no `occluded` field in
the JSON at all — see Issue #4).

**Required fix:**
1. Confirm `occlusion_mask.py` is actually being called and its output consumed by both
   the OCR stage (null out occluded cells before OCR) and the annotator (visually mark
   occluded cells, e.g. gray hatch or "OCC" label instead of a possibly-stale value).
2. Add the `occluded` boolean field to the export schema as originally specified.

---

## Priority order for fixes

Fix in this order — later items depend on earlier ones being correct:

1. **Issue #1** (scene gate wiring) — nothing else can be trusted until this is fixed,
   since right now you cannot tell from the video which frames are real reads.
2. **Issue #2** (frozen overlay / live state feed into annotator).
3. **Issue #6** (occlusion masking wired into OCR + annotation).
4. **Issue #4 & #5** (exporter completeness — JSON and CSV both).
5. **Issue #3** (accurate self-reporting) — this isn't a code fix, it's a process fix:
   verify every number against the actual current output file before stating it in a
   walkthrough.

## Definition of Done for this fix pass

Do not report this pass as complete until you can show me, from a **fresh full run**:

- [ ] At least 3 timestamps confirmed as CUTAWAY in the annotated video with **no**
      grid/text overlay drawn on them (screenshots or frame dumps, your choice).
- [ ] At least 2 timestamps, well separated in time, showing **different** committed
      values for the same cell as the game progresses (proving the overlay is live, not
      frozen).
- [ ] Full `scoreboard_state.json` containing all 4 rows (J, V, P, T), all populated
      frame columns, and all schema fields from §3 of the architecture doc.
- [ ] `scoreboard_state.csv` with real, non-`UNKNOWN` values matching the JSON for every
      cell that has actually been read.
- [ ] A real, freshly-computed mismatch rate (PASS/FAIL counts) pulled directly from that
      fresh JSON, stated with its sample size.
- [ ] At least one example of an `occluded: true` cell in the export, corresponding to a
      real pin-icon-covered frame in the video.

Once all six boxes are checked against real, freshly generated files, resubmit for
review. I will spot-check timestamps you did not mention, so don't cherry-pick only the
frames that look good.
