# BUGFIX BRIEF v2 — Bowling Domain Grounding + Grid/Index Alignment Root-Cause

**Status: REJECTED again.** The Phase-fix pass resolved the *structural* issues from
BUGFIX_BRIEF_v1 (scene gate is now wired in, schema is complete, exporter runs) but
introduced/exposed a deeper, more serious problem: **the actual numbers being extracted
are now wrong on almost every cell** (mismatch rate went from 1/2 to 15/15 = 100%). This
is not "the rule-checker is working as designed, flagging real OCR noise" — the errors
follow a pattern that points to a specific, fixable geometry/indexing bug, not random OCR
noise. This document first grounds you in the actual domain (how a bowling scoresheet is
laid out and scored on paper/CRT boards), then walks through the evidence, then gives the
fix plan.

Read this fully before changing code. Do not just re-tune OCR confidence thresholds —
that will not fix what's actually wrong here.

---

## PART A — Domain knowledge: how a ten-pin bowling scoresheet actually works

You need this model in your head before touching `cell_segmenter.py`, `ocr_engine.py`, or
`bowling_rules.py` again. Two real scoreboard photos are provided alongside this brief
(different bowling centers/leagues, same universal format) — use them as ground truth for
layout, independent of our specific clip.

### A.1 — Frame anatomy (per bowler, per frame column)

Each of the 10 frame columns for a bowler is visually split into **two stacked regions**:

1. **Top region — pinfall notation for that frame's individual ball(s).** This is
   *small* text, and for frames 1–9 shows the result of up to two throws using shorthand:
   - A digit `0`–`9` = pins knocked down by that ball.
   - `-` = a miss on that ball (0 pins). Often paired with a digit, e.g. `5-` (ball 1 = 5,
     ball 2 = miss) or `-7` (ball 1 = miss, ball 2 = 7).
   - `/` = **spare** — placed as the *second* symbol, meaning ball 1 + ball 2 = 10 (e.g.
     `4/`, `1/`).
   - `X` = **strike** — all 10 pins on the *first* ball. Because the frame ends
     immediately, only one symbol is shown for the whole frame (not two little boxes),
     often rendered large/bold and sometimes visually spanning the space of both throws.
   - Split combinations like `8 1`, `7 1` are just two open-frame digits shown
     side-by-side (space-separated in this feed's font) — not a special symbol.
2. **Bottom region — the cumulative running score after that frame**, shown *larger*.
   This is a running total across the whole game so far, **not** a per-frame score.

Reference Image 1 (4-lane league sheet) shows this exact structure repeatedly: e.g. row
"H", frame 3 = `X` (top) / `46` (bottom, cumulative). Reference Image 2 (end-of-league
recap) shows the same two-tier layout across multiple rows with fully completed games.

### A.2 — Critical scoring rule: cumulative totals are DELAYED, not immediate

A strike or spare's frame score depends on **future** throws (bonus balls), so the
cumulative total for a frame **cannot be finalized until those bonus balls have actually
been bowled**:
- Strike (`X`): frame score = 10 + the next **two balls** thrown (which may span into the
  next frame, or even the frame after that if frame N+1 is also a strike).
- Spare (`/`): frame score = 10 + the next **one ball** thrown.
- Open frame (two throws, no strike/spare): frame score = sum of the two throws, known
  immediately.

**This means it is completely normal and correct for the cumulative-total box of a recent
frame to be blank/not-yet-shown on the real board** if the bonus ball(s) needed to resolve
it haven't happened yet. Do not treat a blank cumulative cell as a pipeline failure by
itself — check whether the real board has actually posted a number there yet before
flagging it as a bug. (Your `UNKNOWN` rule_check for not-yet-resolved cells is the
*correct* behavior here — keep that.)

### A.3 — 10th frame is structurally different

Frame 10 gets **up to three** ball slots (because a strike or spare in frame 10 earns
bonus ball(s) *within the same frame*, not carried into a nonexistent frame 11). Do not
assume every frame column has the same 2-symbol layout — frame 10's top region needs its
own parsing path once you observe it (per the original architecture doc's still-open
validation item — confirm this from real frames before hardcoding 10th-frame logic).

### A.4 — The "T" (team) row scores independently, don't assume it's derived

Looking at the actual pinfalls on the `T` row in our clip (`6 1`, `1/`, `8-`, ...) — these
are **not** the arithmetic sum of J/V/P's pinfalls for the same frame. Treat `T` as its
own independently-scored row using the exact same rule engine as any bowler row (this
already appears to be your assumption — just confirm it explicitly in a code comment so a
future you doesn't "optimize" it into a derived sum by mistake).

---

## PART B — What's actually wrong in the current output (evidence-based)

### B.1 — Off-by-one frame-index shift between the real board and your JSON keys

Compare the real board (visible in `annotated_video.mp4` at t=0s) to your exported JSON
for row `J`:

| Real board column | Real pinfall | Real cumulative | Your JSON key | Your JSON pinfall | Your JSON cumulative |
|---|---|---|---|---|---|
| Frame 1 | `X` | 15 | `"2"` | `X` | 15 |
| Frame 2 | `5-` | 20 | `"3"` | `5` | 701 |
| Frame 3 | `-7` | 27 | `"4"` | `7` | 77 |
| Frame 4 | `4-` | 31 | `"5"` | `43` | 7 |

**Every real frame N is being written to JSON key N+1.** Frame 1's data is stored under
`"2"`, frame 2's under `"3"`, etc. This is a straightforward off-by-one somewhere in your
column indexing — most likely in `cell_segmenter.py`'s column-to-frame-number mapping
(e.g. a loop starting at column index 1 instead of 0, or a frame-number variable
initialized to 1 then incremented *before* first use instead of after). This is
independent of the OCR garbling in B.2 below — fix this first, since it makes every other
number in the export mislabeled even where OCR itself is correct (see frame 1→"2": the
values `X`/15 are read *correctly*, just filed under the wrong frame number).

**Required fix:** Add an explicit, tested mapping from pixel column → frame number in
`config.py` or `board_calibrator.py` (e.g. `FRAME_COLUMN_INDEX = {0: 1, 1: 2, ..., 9: 10}`
or equivalent zero/one-indexing made explicit), and add a unit test in
`tests/test_parser.py` that asserts frame 1's real on-screen values land under JSON key
`"1"`, not `"2"`.

### B.2 — Garbled/concatenated digits in cumulative cells, not simple misreads

Look at the pattern of wrong cumulative values: `701`, `77`, `715`, `70`, `43`. These
aren't the kind of error a clean digit-vs-digit OCR confusion produces (like reading `8`
as `B` — the failure mode you correctly logged in Phase 5). They look like **multiple
separate readings glommed together into one string** — e.g. `701` and `715` are 3 digits
where a real cumulative total in this game is at most 2 digits at this point in the video.
Two ranked hypotheses to test — don't just pick one and assume, instrument and check:

1. **Temporal fusion is concatenating disagreeing candidate strings instead of choosing
   one by consensus.** If `temporal_fusion.py`'s state machine ever does something like
   `state += new_reading` instead of `state = new_reading` when candidates disagree, or
   merges multiple OCR hypotheses (from the Phase 7 multi-preprocessing fallback) by
   string-joining instead of voting, you'd see exactly this symptom — 3-digit strings
   built from three different 1-digit candidate reads.
2. **Vertical row-band bleed**: if the "cumulative" sub-row crop boundary in
   `ROW_BANDS[row]["cumulative"]` starts a few pixels too high, the crop could include the
   bottom sliver of the "pinfall" text sitting above it, and EasyOCR could read that
   partial glyph as an extra leading/trailing digit, then concatenate it with the real
   cumulative number.

**Required fix:**
1. Add a debug log/dump of the **raw, pre-fusion OCR candidate list** for every flagged
   cell (all candidates from the primary pass + any Phase 7 fallback passes), not just the
   final fused value. This will make it immediately obvious which hypothesis above is
   correct.
2. Save cropped cell images for the specific failing cells (J frame 2 cumulative, T frame
   2 cumulative, etc.) to `output/debug/` so we can visually confirm whether the crop
   itself contains bleed from a neighboring row/column, or whether the crop is clean and
   the bug is purely in `temporal_fusion.py`'s merge logic.
3. Fix whichever is confirmed. If it's temporal fusion, the fix is: on disagreement,
   pick the single most-frequent full-string candidate (majority vote on the *whole
   string*, not per-character), never concatenate.

### B.3 — Annotator is drawing new text on top of old text without clearing (ghosting)

Visually, `annotated_video.mp4` shows overlapping/smeared numbers stacked on each other
inside the same cell (e.g. a faded `701` sitting next to/behind the real `20`, a `43`
overlapping the real `48`). This is very likely the **same root bug as B.2** manifesting
visually: if the annotator is drawing every historical committed value it has ever seen
for a cell instead of only the current one, that's consistent with a state object that
accumulates instead of overwrites.

**Required fix:** In `annotate_video.py`, explicitly clear/redraw the cell's background
patch before writing the current text (or only draw text once, computed from a
single source of truth per cell per frame) — confirm no stale text can persist across
draw calls. This should get resolved as a side effect of fixing B.2, but verify it
separately with a fresh frame dump.

### B.4 — `computed_cumulative` is shifted differently than the OCR fields, in the same rows

Notice for row `J`, JSON key `"3"`: `pinfall: "5"`, `cumulative (OCR'd): 701`, but
`computed_cumulative: 27` — 27 is the **real board's frame-3** total, not frame-2's (which
would be 20). So the rule engine's `computed_cumulative` appears to be indexed *one frame
further ahead* than the OCR'd `pinfall`/`cumulative` fields in the very same dict entry.
This means the off-by-one in B.1 is not a single consistent shift applied uniformly — the
OCR-extraction path and the rule-engine path are indexing frames differently from each
other. Don't fix B.1 by nudging one number until the table above "looks right" — trace
both code paths (`cell_segmenter.py` → `ocr_engine.py` → export, and separately
`bowling_rules.py`'s internal frame loop → export) and make sure they consume the *same*
frame-number source of truth.

**Required fix:** Both paths must read frame number from one shared, single place
(`config.py`'s column mapping from B.1) — not have their own independent counters.

### B.5 — Occlusion masking still not visually verifiable

Your report claims 20 cells were masked `occluded: true` at t≈20s, but the frame at that
timestamp (pin-icon animation covering the top-right of the board) shows no visual `OCC`
marker anywhere, and no `occluded: true` entries appear for the frames actually under the
icon in the exported JSON. Don't report this as done until you can point to a specific
frame + cell where the JSON says `occluded: true` **and** the annotated video shows that
same cell marked, at the same timestamp, side by side.

### B.6 — Self-reported numbers don't match the delivered file (recurring issue)

Your fix-pass report's embedded JSON excerpt shows row `T`, `"total": 40`, but the actual
`scoreboard_state.json` file you delivered shows row `T`, `"total": 4`. This is the same
class of problem flagged in BUGFIX_BRIEF_v1 Issue #3: **the walkthrough text and the
actual output file disagree.** Going forward, generate any pasted JSON/CSV excerpt in a
walkthrough by reading it back from the actual file on disk at report time (e.g. `cat` it
or load-and-print it), never by hand-copying/editing an earlier draft.

### B.7 — `total` field uses the last dict key's value blindly

Row totals (`"total": 7` for J, using the mis-shifted, garbled frame-"5" value) are being
set from whatever the last populated frame key happens to contain, even when that cell is
flagged `FAIL`. Once B.1/B.2 are fixed this may resolve itself, but as a safeguard: derive
`total` from the highest-confidence, rule-`PASS`ed frame available, and if the true latest
frame is `FAIL`/`UNKNOWN`, say so explicitly (e.g. `"total": null, "total_status":
"latest frame unresolved or flagged"`) rather than presenting a number you don't trust.

---

## Priority order

1. **B.1** (frame index off-by-one) — fix and unit-test this first; it's the cheapest fix
   and it's corrupting every downstream number's label.
2. **B.4** (align rule-engine indexing with the same source of truth as B.1) — do this in
   the same pass as B.1, since they're the same class of bug in two places.
3. **B.2 / B.3** (diagnose real vs. concatenated OCR values, fix temporal fusion or crop
   bounds, fix annotator ghosting) — instrument first (raw candidate dump + cell crops),
   don't guess.
4. **B.5** (prove occlusion masking with a matched frame+cell+JSON example).
5. **B.7** (don't report a total derived from a FAIL/UNKNOWN cell as if it were trustworthy).
6. **B.6** (process fix: always regenerate report excerpts from the real output file).

## Definition of Done for this pass

- [ ] A debug table (like the one in B.1) for at least 2 full rows, showing real board
      column → JSON key now match 1:1, generated from a fresh run.
- [ ] Raw pre-fusion OCR candidates logged for at least 5 previously-flagged cells,
      attached or referenced, showing which hypothesis (B.2.1 vs B.2.2) was confirmed.
- [ ] A fresh `output/debug/` crop image for at least 2 of those cells so the crop
      boundaries can be visually checked against the real column/row lines.
- [ ] A fresh frame dump showing no ghosting/overlapping stale text in any cell.
- [ ] `computed_cumulative` and OCR'd `cumulative` referring to the *same* real frame in
      every JSON entry (they don't have to match in value — that's what rule_check is
      for — but they must be about the same frame).
- [ ] One matched example (frame + cell + timestamp) proving occlusion masking works,
      shown in both the JSON (`occluded: true`) and the annotated video (visual OCC mark).
- [ ] A real, freshly recomputed mismatch rate, with the report's pasted JSON generated
      by reading the actual output file at write time — not hand-assembled.

Resubmit once all boxes are checked against a fresh full run. As before, I'll spot-check
timestamps and cells you didn't specifically call out.
