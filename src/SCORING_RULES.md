# 🎳 Official Regulation 10-Pin Bowling Scoring Rules & Mathematical Engine

This document outlines the international standard 10-pin bowling regulation rules, scoring formulas, and the bidirectional computer vision verification engine used by **ScoreVision**.

---

## 1. Scoreboard Grid Architecture (2-Tier Display)

A standard ten-pin bowling match consists of **10 Frames** played across sequential player rows:

```
+---------------------------------------------------------------------------------------+
|  BOWLER   |   1   |   2   |   3   |   4   |   5   | ... |   9   |    10     |   TTL   |
+-----------+-------+-------+-------+-------+-------+-----+-------+-----------+---------+
|  PLAYER   | r1|r2 | r1|r2 | r1|r2 | r1|r2 | r1|r2 | ... | r1|r2 | r1|r2|r3  |  MATCH  |
|           |  C_1  |  C_2  |  C_3  |  C_4  |  C_5  | ... |  C_9  |   C_10    |  TOTAL  |
+---------------------------------------------------------------------------------------+
```

Each frame column contains two distinct tiers:
1. **Upper Tier (Pinfall Rolls)**: Small boxes indicating the individual pin counts knocked down on Roll 1 and Roll 2 (and Roll 3 in Frame 10).
2. **Lower Tier (Cumulative Score $C_i$)**: The running match cumulative score accrued through Frame $i$.
3. **TTL Column**: The overall bowler match total.

---

## 2. Standard Frame Scoring Rules (Frames 1 to 9)

In each frame from 1 to 9, a bowler delivers up to two balls to knock down 10 pins.

### A. Open Frame
- **Definition**: The bowler fails to knock down all 10 pins in 2 rolls ($r_1 + r_2 < 10$).
- **Pinfall Notation**: `r1 r2` (e.g. `8 1`, `6 2`, `7 -`, `9 -`). A zero is marked as a hyphen `-`.
- **Frame Score**: $S_i = r_1 + r_2$
- **Cumulative Score**:
  $$C_i = C_{i-1} + r_1 + r_2$$

---

### B. Spare (`/`)
- **Definition**: The bowler knocks down all remaining pins on the **second roll** ($r_1 + r_2 = 10$).
- **Pinfall Notation**: `r1 /` (e.g. `9 /`, `7 /`, `4 /`, `- /`).
- **Bonus**: The pinfall of the **next single roll** ($b_1 = \text{Roll 1 of Frame } i+1$).
- **Frame Score**:
  $$S_i = 10 + b_1$$
- **Cumulative Score (Resolved)**:
  $$C_i = C_{i-1} + 10 + b_1$$
- **In-Progress Base (Live Display)**:
  $$C_i^{\text{live}} = C_{i-1} + 10$$

---

### C. Strike (`X`)
- **Definition**: The bowler knocks down all 10 pins on the **first roll** ($r_1 = 10$). No second ball is rolled.
- **Pinfall Notation**: `X` (placed in the right box of the upper tier).
- **Bonus**: The pinfalls of the **next two consecutive rolls** ($b_1 + b_2$).
- **Frame Score**:
  $$S_i = 10 + b_1 + b_2$$
- **Cumulative Score (Resolved)**:
  - If followed by an Open Frame or Spare:
    $$C_i = C_{i-1} + 10 + r_{i+1,1} + r_{i+1,2}$$
  - If followed by a Double Strike ($X, X$):
    $$C_i = C_{i-1} + 20 + r_{i+2,1}$$
  - If followed by a Turkey ($X, X, X$):
    $$C_i = C_{i-1} + 30$$
- **In-Progress Base (Live Display)**:
  $$C_i^{\text{live}} = C_{i-1} + 10$$

---

## 3. The 10th Frame (Final Frame Special Rules)

The 10th frame determines the final match outcome and can contain up to **3 rolls**:
- If the bowler rolls a **Strike on Roll 1 (`X`)**: They receive two bonus balls in the 10th frame (`X X X` max score = 30).
- If the bowler rolls a **Spare on Roll 2 (`/`)**: They receive one bonus ball in the 10th frame (`9 / X` or `9 / 8`).
- If the bowler bowls an **Open Frame**: The frame ends after 2 rolls ($r_1 + r_2 < 10$).
- **Frame 10 Score**:
  $$S_{10} = r_1 + r_2 + r_3$$
- **Final Game Score**:
  $$\text{Final Total} = C_9 + S_{10} \quad (\text{Max Possible: } 300)$$

---

## 4. Mathematical Invariants & Validation Constraints

ScoreVision enforces the following mathematical invariants during temporal fusion and OCR validation:

| Invariant | Formal Rule | Error Handling / Imputation |
|:---|:---|:---|
| **Monotonicity** | $0 \le C_1 \le C_2 \le C_3 \dots \le C_{10} \le 300$ | Any candidate reading $C_i < C_{i-1}$ is rejected as visual noise. |
| **Max Frame Delta** | $\Delta C_i = C_i - C_{i-1} \le 30$ | Deliberate upper bound prevention ($>30$ per frame is mathematically impossible). |
| **Open Frame Balance** | $\Delta C_i = r_{i,1} + r_{i,2} < 10$ | If delta $\Delta C_i$ and roll 2 are known, roll 1 is locked to $\Delta C_i - r_{i,2}$. |
| **Spare Rule** | $10 \le \Delta C_i \le 20$ | Requires roll 2 to be marked as `/`. |
| **Strike Rule** | $10 \le \Delta C_i \le 30$ | Requires roll 1 to be marked as `X`. |
| **Total Alignment** | $\text{TTL} = \max(C_1, C_2, \dots, C_{10})$ | Match total must exactly equal the latest resolved frame cumulative score. |

---

## 5. Bidirectional Computer Vision Self-Healing Pipeline

When visual occlusions (such as pop-up bowler graphics or pinset animations) obscure cells, ScoreVision's rule engine reconstructs the missing data bidirectionally:

```
[Forward Projection]   C_i = C_{i-1} + Pinfall(i)
                             ▲
                             │ (Cross-Validation)
                             ▼
[Backward Inference]   Pinfall(i) = C_i - C_{i-1}
```

1. **Forward Chain**: Missing cumulative numbers in early/middle frames are automatically calculated from observed open frame pinfalls.
2. **Backward Repair**: If an OCR reading misidentifies a character with low confidence (e.g. reading `12` instead of `72`), the verified cumulative delta $\Delta C_i = 34 - 25 = 9$ instantly self-heals the first roll to $9 - 2 = 7 \implies \mathbf{72}$.
