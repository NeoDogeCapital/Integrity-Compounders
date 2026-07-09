# Integrity Compounders — METHODOLOGY V12.1
### Momentum & Universe-Rank Redesign · July 2026
> Focused follow-on to V12. V12 governs the pillars, quad, quality indicators, and
> QGS/GER signals; **V12.1 rebuilds momentum into four distinct signals and demotes
> universe-relative ranking** in favor of absolute grades and each company's own
> history. In any conflict, `CLAUDE.md` governs computation; this doc governs intent.

---

## 1. Why V12.1 exists

Two structural weaknesses in V12, both pushing the same direction — away from pure
universe-relative percentiles, toward absolute and historical measures.

1. **Momentum was one blurry blend doing several jobs badly.** The old MC Rank was a
   raw multi-period price-return blend (1M/3M/6M/12M), universe-percentile-ranked.
   Problems: raw return (not risk-adjusted); included the mean-reverting 1-month
   return with positive weight; purely relative ("high momentum" = "falling less
   than peers"); no trend-quality or exhaustion detection.
2. **Universe rank was the backbone of the Alignment Score, and it shouldn't be.**
   The whole Alignment Score was built on universe-relative percentiles while the
   pillars, quad, and quality indicators are absolute. Universe rank moves when the
   company doesn't, hides absolute deterioration in a weak field, and misses the most
   intuitive frame: how a company compares to **its own history**.

**Guiding principle for momentum: it is for TIMING and CONFIRMATION, never thesis.**
Momentum never drives an exit on its own. A compounder with intact fundamentals and a
broken 200-DMA is a hold or an add, not a sell.

---

## 2. The four momentum signals (`scripts/momentum_engine.py`)

Computed from `ic_price_history` (adjusted close). Each does exactly one job.

| # | Signal | Column | Definition | Job |
|---|--------|--------|------------|-----|
| 1 | **Selection** | `mom_12_1_risk_adj` | (12M return − 1M return) / trailing-12M annualized vol | The real momentum anomaly — skips the mean-reverting recent month, risk-adjusted |
| 2 | **Trend filter** | `trend_status` | UPTREND (px>200DMA & 50>200) · DOWNTREND (px<200DMA & 50<200) · else NEUTRAL | Absolute initiation veto |
| 3 | **Extension** | `extension_flag` / `dist_200dma_z` | z-score of distance from 200-DMA vs its own trailing-year distribution → OVEREXTENDED (>2σ) / HEALTHY / OVERSOLD (<−2σ) | Entry timing / exhaustion |
| 4 | **Reversal setup** | `reversal_setup` | risk-adj 12-1 > 0 **and** 1M return < 0 **and** price > 200-DMA | Buy-the-dip in an uptrend |

Requires ≥ 252 + 5 trading days of price history; names with less are skipped (no
momentum that refresh). **Data note:** momentum is only as broad as `ic_price_history`
— a name needs ~12 months of daily prices to score.

---

## 3. Three-lens Alignment Score v3 (`scripts/alignment_scorer_v3.py`)

Each component blends three lenses. Absolute grade leads; historical self-comparison is
meaningful; **universe percentile is demoted to a tiebreaker.**

```
FV  (Fundamental Velocity) = QGS tier 55%  + QGS vs own history 30% + universe pctile 15%
MC  (Market Conviction)    = trend status 45% + risk-adj 12-1 vs own history 40% + universe pctile 15%
VAL (Valuation)            = FCF/EV vs own range 65% + universe pctile 35%   (no absolute grade)

alignment_score_v3 = FV × 0.40 + MC × 0.25 + VAL × 0.35
```

The 0.40 / 0.25 / 0.35 top-level weights are unchanged from v2 — **what changed is how
each of the three components is built.** Valuation is inherently comparative, so it keeps
more universe weight (35%) than FV/MC (15%).

**Absolute grades:**
- QGS tier → `RARE_ELITE 95 · EXCEPTIONAL 80 · GOOD_COMPOUNDER 62 · AVERAGE 42 · LOW_QUALITY 20`
- Trend → `UPTREND 85 · NEUTRAL 50 · DOWNTREND 20`

Buckets: **ACCUMULATE ≥ 65 · HOLD 35–64 · DISTRIBUTE < 35** (`alignment_bucket_v3`).

### Cold-start behavior (`history_maturity`)
The historical lens needs accumulated snapshots. `signal_history` is written every run.
- `< 3` snapshots → **COLD_START**: historical lens defaults to the absolute grade (or,
  for valuation which has no absolute grade, to the universe percentile).
- `3–5` → **BUILDING** · `≥ 6` → **MATURE**.

No backfill: on the first run everything is COLD_START and historical lenses equal the
absolute grades — this is correct, not a bug. Signal accrues each refresh; ~6 refreshes →
BUILDING, ~12 → MATURE self-comparison.

---

## 4. L2 trend filter — initiation veto (`passes_initiation_trend_filter`)
A **new** initiation is vetoed if the name is in a confirmed DOWNTREND. **Existing
positions are exempt** — momentum is timing, not thesis. A vetoed name stays in the
candidate pool; it is simply not actionable for a new buy until the trend turns.
Surface with `python run.py initiation`.

---

## 5. Pipeline order (`scripts/data_updater.py`)
```
market data (yfinance) → Fiscal AI signals (QGS/GER) →
compute_momentum → compute_alignment_v3
```
`alignment_score_v3` supersedes v2. v2 remains in the codebase but is no longer the
headline score.

---

## 6. Schema (`database/migrations/012_v121_momentum_rank.sql`)
- `company_market_data`: momentum columns (`mom_12_1_risk_adj`, `trend_status`,
  `extension_flag`, `dist_200dma_z`, `reversal_setup`, `mom_1m_return`, `mom_12m_return`, …)
  and three-lens outputs (`fv_/mc_/val_composite`, `alignment_score_v3`,
  `alignment_bucket_v3`, `history_maturity`).
- `signal_history` (ticker, snapshot_date, QGS, fcf_ev_yield, mom_12_1_risk_adj, roic,
  fcf_margin, …) — the accumulating dependency that makes the historical lens work.
  **Workspace note:** the snapshot pulls `roic_trailing` / `fcf_margin_trailing` from
  `company_market_data` (it has no `roic` / `fcf_margin` columns).

---

## 7. Known follow-ups
- **`ic_price_history` coverage:** momentum computes only for names with ≥12mo of daily
  prices. A one-time historical price backfill (1–2yr) would extend momentum to the full
  active universe; until then, non-covered names get neutral-default MC and are not
  trend-vetoed.
- **HTML dashboards:** the CLI factor card (`who is`) shows the momentum + three-lens
  block; styling the published GitHub Pages dashboards with the same detail is a
  pending visual task.

*Integrity Compounders · Integrity Wealth Partners · LPL Financial Affiliate*
