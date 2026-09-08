## [2026-09-08] — REBALANCE — IC OVERRIDE DOCUMENTATION

**Decision (Niko, 2026-09-08):** 4 exits, 3 initiations. Book 28 → 27 positions.

### SELLS (no rule conflicts — all consistent with the weak-links review)
| Ticker | Proceeds | Rationale |
|---|---|---|
| NVT  | $54,062 | Composite 5.67; P2 5.5 below the 6.0 management floor. |
| NOC  | $53,697 | Composite 6.12, LOW_QUALITY QGS, DOWNTREND; lowest-conviction defensive. |
| GWRE | $29,940 | Four consecutive weeks absent from the Fiscal screen; P2 5.5 breach; composite 6.12. |
| PODD | $25,046 | DISTRIBUTE (29.2), DOWNTREND, Q3; securities class-action news flow. |
| **Total** | **$162,745** | |

### BUYS — ALL THREE CARRY DOCUMENTED IC OVERRIDES

**KLAC — full 1/N, $51,919 (278.7908 sh @ $186.23)**
- **Rule overridden:** V12.1 L2 initiation trend filter. KLAC is in a confirmed
  DOWNTREND, which vetoes a NEW initiation (existing holdings are exempt).
- **Override rationale (Niko):** Composite 7.95 — the highest of the three buys and
  top-decile in the universe; Q1 quad with both axes accelerating; 56% ROIC;
  near-monopoly (~55% share) in semiconductor process control. Extension reading is
  OVERSOLD, so the downtrend is treated as an entry opportunity rather than a veto.
- **What would prove this wrong:** failure to reclaim the 200-DMA within two quarters
  alongside deteriorating WFE guidance.

**HALO — 2% starter, $28,035 (261.2768 sh @ $107.30)**
- **Rules overridden:** (1) Q3 quad — "no position in Q3 without explicit IC override
  documentation"; (2) strict equal weight — sized at 2%, roughly half of 1/N (3.70%).
- **Override rationale (Niko):** RARE_ELITE QGS, UPTREND intact, ACCUMULATE-range
  alignment. Royalty toll-road model (ENHANZE) collects on partner blockbusters
  without development risk. Q3 read reflects deceleration against prior-year comps,
  not deterioration. Half-weight sizing reflects starter-position status.
- **What would prove this wrong:** ENHANZE royalty step-downs or partner attrition
  reducing royalty revenue growth below high single digits.

**DAVE — 2% starter, $28,036 (75.0611 sh @ $373.51)**
- **Rules overridden:** (1) **P2 = 5.5, below the 6.0 hard floor** — "P2 Management
  Integrity score must be ≥ 6.0 before any initiation" (HARD RULE); (2) Q3 quad;
  (3) strict equal weight — 2% vs 1/N.
- **Override rationale (Niko):** RARE_ELITE QGS, ACCUMULATE alignment 80.4 (top of the
  non-held universe), 93% ROIC, 51% FCF margin, EPS_CONFIRMED earnings quality. The
  P2 score reflects regulatory/governance concerns around the tip-and-fee model, which
  are acknowledged and deliberately accepted; the 2% half-weight sizing is the explicit
  compensation for that risk.
- **What would prove this wrong:** adverse regulatory action on the tip/fee model, or
  credit losses rising materially through a consumer downturn.

**Net:** $162,745 proceeds vs $107,990 deployed → ~$54,755 residual cash (3.9%).
Book: 27 positions, 1/N = 3.70%. Sector mix unchanged on net IT exposure
(MU and Sandisk were considered and dropped from this round).

**Standing follow-up:** all three new positions need locked theses and formal
invalidation conditions written to `positions` — the whole book currently lacks them
(see the 2026-09-08 thesis review; 0 of 28 had documented theses).
