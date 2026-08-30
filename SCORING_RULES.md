# Ten-Pin Bowling Scoring Rules & Verification Engine

## 1. Ten-Pin Bowling Scoring Specifications
A standard game of ten-pin bowling consists of 10 frames per bowler.

### Frame Types & Symbols
- **Strike (`X`):** 10 pins knocked down on the first roll of the frame.
  - *Score:* $10 + \text{pins from the next two rolls}$.
- **Spare (`/`):** All remaining pins knocked down on the second roll.
  - *Score:* $10 + \text{pins from the next single roll}$.
- **Open Frame (`D1 D2`, `D-`, `-D`):** Less than 10 pins knocked down across two rolls.
  - *Score:* $\text{Sum of pins in that frame}$.
- **Miss / Zero (`-`):** 0 pins knocked down on that roll.
- **Tenth Frame (`10`):** May include up to 3 rolls if a strike or spare is rolled.

---

## 2. Mathematical Cumulative Boundaries
For each frame $i \in [1, 10]$:
$$0 \le \text{Cumulative}[i] \le i \times 30$$
$$\text{Cumulative}[i-1] \le \text{Cumulative}[i] \le \text{Cumulative}[i-1] + 30$$

Maximum theoretical score: $300$ (12 consecutive strikes).

---

## 3. ScoreVision Rule Validation Engine
The ScoreVision rule engine recomputes each bowler's running cumulative score from their extracted pinfall symbols and compares against the OCR'd running-total cell:
- **`PASS`**: Computed score exactly equals OCR'd cumulative score.
- **`FAIL`**: Discrepancy detected between computed and OCR'd score.
- **`UNKNOWN`**: Frame is occluded, unrolled, or awaiting future bonus balls (e.g., strikes/spares in live frames).
