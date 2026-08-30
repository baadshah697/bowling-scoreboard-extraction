# FINAL FIX BRIEF — ScoreVision: Close Out Remaining 3 Issues, Zero Regressions

You are resuming work on an already-mostly-working pipeline. Three prior review rounds
(`BUGFIX_BRIEF_v1.md`, `BOWLING_DOMAIN_AND_ALIGNMENT_FIX_BRIEF.md` (v2),
`BUGFIX_BRIEF_v3.md`) have already fixed real bugs. **Your job in this pass is narrow:
fix exactly the 3 open issues below, and prove — with fresh evidence — that you did not
break anything that was already working.** Every previous round introduced a regression
while fixing something else. Do not repeat that pattern.

Read this entire document before writing any code. Read the 3 prior brief files in full —
they contain the evidence trail and reasoning you need; don't re-derive it from scratch.

---

## 0. Non-negotiable operating rules

1. **Regression check before you start.** Before changing anything, run the current
   pipeline end-to-end and save its outputs (`scoreboard_state.json`, `.csv`,
   `annotated_video.mp4`) to `output/baseline_before_fix/`. You will diff against this.
2. **Never fabricate a number, a "fixed" claim, or a screenshot.** Every claim in your
   final report must be backed by something you actually generated in this run — a real
   frame grab, a real log line, a real diff. If you didn't measure it, say so.
3. **Fix only the 3 issues in §2.** Do not refactor, rename, "clean up," or restructure
   code outside what's needed for these fixes. Every prior regression was introduced by an
   agent touching more than the brief asked for. `bowling_rules.py`'s scoring math is
   independently verified correct by hand in `BUGFIX_BRIEF_v3.md` Part C — do not modify
   it. If you believe you've found a reason it needs to change, stop and flag it in your
   report instead of changing it.
4. **After each of the 3 fixes, immediately re-run the full §3 regression checklist** for
   that fix before moving to the next one. Do not batch all 3 fixes and test once at the
   end — if something breaks, you need to know which fix broke it.
5. **The final report must include a fresh run's actual output files and actual frame
   grabs, generated at report-writing time** — not copy-pasted from an earlier draft, not
   hand-assembled. This exact process failure happened before (see v2 Issue B.6).

---

## 1. What is already correct — DO NOT change these, and your regression pass must
   re-confirm each one still holds after every fix

| # | Behavior | How to re-verify it still holds |
|---|---|---|
| 1 | Frame-index alignment: real board frame N ↔ JSON key `"N"`, 1:1, for both the OCR path and `bowling_rules.py`'s `computed_cumulative` path. | Pull a frame, read frame 1's real pinfall/cumulative off the pixels, confirm it lands under JSON key `"1"` (not `"2"`). Repeat for at least 2 rows. |
| 2 | No concatenated/garbled multi-digit values (e.g. `701`, `715`) anywhere in cumulative cells. | Scan the fresh JSON for any cumulative value that's a 3+ digit number implausibly early in the game (frame ≤ 5); there should be none. |
| 3 | Occlusion masking: `OCC` tag in the annotated video and `"occluded": true` in the JSON agree, at the same row/frame/timestamp, when the pin-icon graphic is on screen. | Grab a frame at a timestamp where the pin icon is visible over columns 6–10 of rows J/V; confirm both the video and JSON show occlusion for the same cells. |
| 4 | Live overlay: committed values visibly progress over time, not frozen at frame 1/2 forever. | Grab frames at 3 well-separated timestamps; confirm at least one cell's displayed value differs across them as the game progresses. |
| 5 | `bowling_rules.py`'s scoring arithmetic is correct given correct pinfall input (verified by hand in `BUGFIX_BRIEF_v3.md` Part C for both a strike-chain and a spare-chain). | Do not re-derive this from scratch — re-use the worked examples in that brief as your regression cases in `tests/test_rules.py` if they aren't already there. |
| 6 | CSV and JSON agree on every populated cell (`exporter.self_check`). | Run `self_check()` on the fresh output; 0 mismatches expected. |

If any of these regress after your changes, that is a failed pass — fix it before
reporting completion, and say explicitly in your report that it regressed and how you
fixed it. Do not silently patch it and omit it from the report.

---

## 2. The 3 issues to fix, in required order

### Issue 1 (fix first — everything else is unverifiable until this works): Scene gate
### does not suppress the overlay on sustained (non-transition) CUTAWAY frames

**Root cause (already diagnosed in `BUGFIX_BRIEF_v3.md` Part B — do not re-diagnose,
implement the fix):** `scene_gate.classify_frame()` uses frame-to-frame diff (which only
detects *change*, not *content*) plus HSV blue-coverage (which both cutaway types —
the cartoon animation and the Brunswick logo splash — satisfy anyway, since both contain
substantial blue-hued pixels). A few seconds into either cutaway, diff drops low and the
frame gets misclassified as SCOREBOARD.

**Fix:** Add a third signal that checks for the fixed board *structure*, not motion or
color, since cutaway content cannot reproduce the board's structure regardless of its own
motion/color profile. Two acceptable approaches — pick one, implement it, do not
half-implement both:

- **(A) Template/edge match at fixed anchor points.** Pick 2–3 small fixed pixel regions
  from `config.py` that always contain high-contrast board structure on the real board
  (e.g. inside `LABEL_COL` where the "J"/"V"/"P"/"T" glyphs always render, or the "TTL"
  header text region). At startup, cache a reference crop of each from a known-good
  SCOREBOARD frame (e.g. frame 0). Per frame, compute normalized cross-correlation
  (`cv2.matchTemplate`) or simple structural similarity between the live crop and the
  reference. Require a minimum match score for SCOREBOARD classification. This is cheap
  (a handful of small crops, not the whole frame) and immune to both failure modes in
  Part B since it doesn't care about color or inter-frame motion at all.
- **(B) Edge-density / text-structure check.** Compute edge density (e.g. Canny edge
  count) inside `COLUMN_HEADER_BAND` or `LABEL_COL`. The real board has consistent,
  high-density crisp text edges in these fixed locations; cutaway content (cartoon,
  logo) will not reliably reproduce that density at those exact fixed coordinates.

Whichever you pick, add its threshold(s) to `config.py` as named, commented constants —
same rule as everything else in this codebase. Do not hardcode magic numbers inline.

**Required verification (do this before touching Issues 2 or 3):**
1. Re-run scene gate classification across the **full** video, not a sample. Report real
   SCOREBOARD/CUTAWAY counts.
2. Specifically re-check the two timestamps already proven broken in `BUGFIX_BRIEF_v3.md`
   Part B (~t=40s cartoon, ~t=50s Brunswick splash) plus 3 more timestamps you pick
   yourself from elsewhere in the video's cutaway segments (not just the transition edges
   — pick timestamps from the *middle* of a cutaway segment, since that's exactly where
   the old signal failed).
3. Regenerate `annotated_video.mp4` and grab frames at all 5 of those timestamps. Confirm
   each shows the `CUTAWAY - no board detected` label with no grid, no cell text, no OCC
   tags drawn on top.
4. Re-run the Item 3 and Item 4 regression checks from §1 (occlusion + live overlay) to
   confirm the new gate hasn't started rejecting real SCOREBOARD frames as CUTAWAY
   (a false-negative regression is just as bad as the false-positive you're fixing).

### Issue 2: Pinfall OCR drops thin trailing marks (`-`, `/`) and misreads at least one
### stylized digit, causing every current `rule_check: FAIL`

**Root cause (already diagnosed in `BUGFIX_BRIEF_v3.md` Part C — two distinct failure
modes, do not conflate them):**
- **Detection failure:** the dash/slash stroke is sometimes never boxed by EasyOCR's
  CRAFT detector at all (inconsistent even within the same frame/timestamp — row V's
  dashes came through fine while row J's didn't at the same moment). This is a detection
  problem, not a charset problem.
- **Recognition failure:** row P frame 3's real `9` was read as `3` — a genuine
  character-classification error on this font, not a missing detection.

**Fix — instrument first, then fix, in this order:**
1. In `ocr_engine.extract_text_from_cell()`, add a debug-only path that logs/saves the
   **raw `readtext()` output** (every detected box, its text, and its confidence — not
   just the final joined string) for every pinfall cell, for at least one full processing
   pass. Write this to `output/debug/ocr_raw_candidates.json` keyed by
   `(row, frame, timestamp)`.
2. From that dump, confirm for the two known cells (row P frame 3, row T frame 2):
   was the dash/slash **ever detected as a box** (even with wrong/low-confidence text), or
   **never boxed at all**? This tells you which of the two fixes below actually applies —
   don't apply both blindly.
   - If never boxed: widen the cell crop's right-hand margin (`CELL_INSET_RIGHT` may be
     trimming the trailing stroke) and/or lower EasyOCR's `text_threshold`/`low_text`
     parameters (currently using defaults) specifically for pinfall cells, since short
     thin strokes are exactly what those parameters govern.
   - If boxed but misread: this is a recognition/preprocessing issue. Try the adaptive-
     threshold fallback pass (already built in Phase 7 / `preprocessing.py`) — but note
     it currently only triggers on **low confidence**, and a wrong-but-confident read
     (like `9`→`3`) never reaches it. Either loosen the trigger condition (e.g. always
     run the fallback for pinfall cells and fuse by agreement, not just on low
     confidence) or add a targeted preprocessing step (e.g. slight de-skew, since the
     board font is italic) and prove it helps before keeping it.
3. **Do not touch `bowling_rules.py`.** Its arithmetic is verified correct by hand for
   both affected chains in `BUGFIX_BRIEF_v3.md` Part C.1/C.2. If the FAILs don't clear
   after fixing the OCR, the bug is still upstream — keep debugging OCR, don't start
   "fixing" the rule engine to compensate for bad input.

**Required verification:**
1. Re-run the full pipeline. Confirm row P frame 3 now reads `9-` (or at minimum `9`) and
   row T frame 2 now reads `1/` (or at minimum contains a detected `/`).
2. Confirm all 6 previously-FAILed cells (P frames 2/3/4, T frames 2/3/4) now show
   `rule_check: PASS`, with `computed_cumulative` exactly matching the OCR'd `cumulative`
   in each — paste the actual fresh JSON fragment for these two rows in your report,
   read from the real output file at report time.
3. If any of the 6 still fail, report the actual current OCR read for that cell and the
   actual current computed vs. OCR'd values — do not claim "fixed" if it isn't.
4. Re-check row J frame 2 (`5-`, currently read as `5`) — this one doesn't affect
   `rule_check` (PASS either way) but is still an accuracy bug in the `pinfall` field
   itself. Confirm whether your Issue 2 fix also corrects it; report either way.

### Issue 3: `bowler_name` / `is_team_row` are hardcoded, not OCR'd, and at least one
### hardcoded value is wrong

**Root cause (already diagnosed in `BUGFIX_BRIEF_v3.md` Part D):**
`temporal_fusion.ROW_META` hardcodes `{"J": "JAGDISH", "V": "VIJAY", "P": "PAWAN",
"T": "TEAM", is_team_row: T only}`. The real marquee header (`config.HEADER_BAND`) is
never OCR'd. Confirmed visual evidence: header reads `TARUN` while row T is highlighted
active, `JAGDISH` while row J is active (matches by coincidence), and `VISHAL` while row V
is active (does **not** match the hardcoded `"VIJAY"`).

**Fix:**
1. OCR `config.HEADER_BAND` per processed frame using the existing `ocr_engine` machinery
   (same pattern as `main._read_unlabeled_metric`, adapted for a text/allowlist
   appropriate to names — likely `A-Z ` only, no digits needed).
2. Determine which row is "active" at a given frame from the highlight-color signal that
   already exists visually on the board (the active row's pinfall sub-row background is a
   distinctly brighter/more saturated color than the other rows — this is the same visual
   cue used by a human reading the board, and by you in verifying Part D). Add this as a
   small helper (e.g. `detect_active_row(frame) -> str | None`), with its color thresholds
   as named constants in `config.py`.
3. When the active row changes (or on a fixed interval — pick whichever is simpler and
   say which you picked and why), OCR the header and assign that text as `bowler_name` for
   whichever row was active at that moment. Use temporal fusion (same K-consistent-reads
   pattern already used elsewhere) so a single bad OCR frame doesn't relabel a row.
4. For `is_team_row`: do not guess. Determine it from what's actually observed — if every
   row's header name across the whole video is a plausible individual human first name
   (including whatever name appears while T is active), report `is_team_row: false` for
   all four rows and say so explicitly, noting this contradicts the original architecture
   doc's assumption. If the marquee ever explicitly shows something like "TEAM" or "PAIR"
   while a row is active, report `is_team_row: true` for that row instead. Either way,
   state in your report which evidence you're basing the decision on — cite the timestamp
   and the actual OCR'd text, the same way `BUGFIX_BRIEF_v3.md` Part D did.

**Required verification:**
1. Re-run the full pipeline. Paste the fresh `bowler_name` values for all 4 rows,
   read from the actual output file.
2. For each row, cite at least one timestamp where that name is visibly on-screen in the
   header while that row is highlighted active, so the mapping is independently checkable.
3. Confirm `is_team_row` in the output reflects what you actually observed, not the
   original architecture doc's assumption, unless your observation happens to confirm it.

---

## 3. Full regression checklist (run this once after all 3 fixes are in)

This re-states §1's table as a literal checklist plus the 3 new fixes, so a fresh full run
can be graded against all of it in one pass:

- [ ] Frame-index alignment still 1:1 (real frame N = JSON key `"N"`) for at least 2 rows.
- [ ] No garbled/concatenated multi-digit cumulative values anywhere in the fresh JSON.
- [ ] Occlusion: JSON `occluded: true` and video `OCC` tag agree, same cell, same
      timestamp, for at least one example.
- [ ] Live overlay still updates over time (not frozen) — confirm at 3+ timestamps.
- [ ] `bowling_rules.py` untouched; its worked examples (strike-chain, spare-chain) still
      pass in `tests/test_rules.py`.
- [ ] `exporter.self_check()` reports 0 CSV/JSON mismatches on the fresh output.
- [ ] **New:** CUTAWAY frames (5 timestamps, including 2 previously-broken ones) show the
      CUTAWAY label with zero grid/text/OCC drawn on top — with fresh frame grabs.
- [ ] **New:** SCOREBOARD frames are still correctly classified as SCOREBOARD after the
      new gate signal is added (no false-negative regression) — confirm counts are
      consistent with a real full-video run, not just the previously-broken timestamps.
- [ ] **New:** Rows P and T show 0 `rule_check: FAIL` (or a specific, evidenced
      explanation for any that remain, with the actual current OCR read quoted).
- [ ] **New:** `bowler_name` for all 4 rows is populated from real OCR, with a cited
      timestamp per row proving the mapping, and `is_team_row` reflects actual observed
      evidence rather than the original unverified assumption.

Every box must be checked against a **fresh, full run** completed after all 3 fixes are
in — not checked incrementally against different partial runs. If a box that was
previously passing (§1's items) fails after your changes, that is not acceptable to
report as "done" — go back and fix it before submitting.

## 4. What your final report must contain

1. The regression checklist above, fully checked, with evidence for each line (a quoted
   JSON fragment, a cited timestamp, a described frame grab — generated fresh, at report
   time, from the actual output files).
2. For Issue 1: the signal you added, its threshold(s) and where they live in `config.py`,
   and the fresh SCOREBOARD/CUTAWAY counts across the full video.
3. For Issue 2: which failure mode (detection vs. recognition) was confirmed for each of
   the two cells, what you changed, and the fresh rule-check result for all 6 previously-
   failed cells.
4. For Issue 3: the fresh `bowler_name` values for all 4 rows, the timestamp evidence for
   each, and your `is_team_row` determination with its basis stated.
5. Anything from §1's "already correct" list that regressed during this pass, and how you
   fixed it before reporting completion — do not omit a regression just because you caught
   and fixed it yourself; say so, so the pattern of "each fix breaks something else" is
   visible and can be watched for going forward.
