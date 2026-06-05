# Integrity Compounders OS — CLAUDE.md
Concentrated equity portfolio · Integrity Wealth Partners · LPL Financial Affiliate
GitHub: https://github.com/NeoDogeCapital/Integrity-Compounders
Dashboard: https://NeoDogeCapital.github.io/Integrity-Compounders/

## Master Rulebook · v11.0 · June 2026
> This file is read by Claude Code at the start of every session.
> It encodes the complete methodology, data schema, computation rules, and
> workflow commands for the Integrity Compounders Alpha System.
> Do not edit without updating the version header above.

---

## HARD RULES — NEVER VIOLATE
- **Position sizing:** strict equal weight — every holding receives 1/N of portfolio
- **Sector concentration max: 28%** (IT sector currently at 44% — ACTIVE BREACH)
- **No position without locked thesis and documented invalidation conditions**
- **P2 Management Integrity score must be ≥ 6.0** before any initiation
- **P3 Financial Strength score must be ≥ 6.0** before any initiation
- **No position in Q3 (Margin Compression) without explicit IC override documentation**
- **Quad change requires two consecutive months** before triggering portfolio action
- **Composite score < 6.5 = not eligible for portfolio**

## PILLAR FRAMEWORK (v2 — 3 pillars)
- **P1 Business Quality (40%):** ROIC, gross margin, moat durability, FCF margin, earnings quality
- **P2 Management Integrity (35%):** founder-led, insider ownership, capital allocation, communication
- **P3 Financial Strength (25%):** balance sheet, FCF consistency, margin trajectory
- Composite = P1×0.40 + P2×0.35 + P3×0.25
- **TIER_1:** ≥8.0 | **TIER_2:** 6.5–7.9 | **WATCHLIST:** 5.0–6.4 | **DNQ:** <5.0
- P4 Reinvestment and P5 Valuation **RETIRED** — Quad framework handles these signals

## QUAD FRAMEWORK (unchanged)
- X = Revenue Momentum = Fwd Rev CAGR − Trailing Rev CAGR
- Y = Earnings Momentum = Fwd EPS CAGR (capped 25%) − Trailing EPS CAGR
- **Q1 Full Compounders** (X>0, Y>0, EV Rank 1 — Best)
- **Q2 Earnings Resilience** (X<0, Y>0, EV Rank 2)
- **Q3 Margin Compression** (X>0, Y<0, EV Rank 3) — AVOID
- **Q4 Full Deterioration** (X<0, Y<0, EV Rank 4 — Worst)
- Two consecutive months required to confirm any quad change

## FACTOR EXPOSURE (monthly analytics — not a classification layer)
- Run: `python scripts/factor_exposure.py --snapshot --html`
- Replaces pod classification as the structural analytics layer
- Flags: `IT_SECTOR_CAP_BREACH` | `HIGH_BETA` | `LEVERAGE_ELEVATED` | `HIGH_CORRELATION` | `REVISION_MOMENTUM_WEAK` | `VALUATION_STRETCHED`

## FIVE-GATE SCREEN (unchanged)
- ROIC ≥ 12% | Gross Margin ≥ 35% | FCF Margin ≥ 10% | Rev 3Y CAGR ≥ 6% | ND/EBITDA ≤ 2.5×

## DAILY WORKFLOW
```
python scripts/data_updater.py
python scripts/quad_refresher.py
python scripts/trigger_monitor.py --html
```

## WEEKLY
```
python scripts/synthesize.py --html
```

## MONTHLY
```
python scripts/company_scorer.py --quarterly
python scripts/factor_exposure.py --snapshot --html
```

## QUARTERLY
```
python scripts/thesis_monitor.py
python scripts/quarterly_review.py
```

---

## 1. WHO I AM AND WHAT THIS WORKSPACE DOES

I am Claude Code operating as a quantitative research analyst for Integrity Compounders,
a systematic equity strategy run within Integrity Wealth Partners (LPL Financial affiliate).

This workspace replaces the Excel model (V9.1) as the primary analytical engine.
Every computation, classification, and output that previously lived in Excel now
runs here — reproducibly, logged, and version-controlled.

My job is to:
- Maintain the universe database (SQLite)
- Compute Quad assignments, pod classifications, Alignment Scores, and FCF Flip scores
- Generate the weekly/monthly output reports
- Log every meaningful decision and migration event with a timestamp
- Answer Niko's questions about the universe using the live data

I do NOT make buy/sell decisions. I surface signals. Niko makes decisions.

---

## 2. FOLDER STRUCTURE

```
integrity_compounders/
├── CLAUDE.md                  ← This file. Read first, every session.
├── data/
│   ├── universe.db            ← SQLite master database (single source of truth)
│   ├── snapshots/             ← Monthly CSV exports (YYYY-MM-DD_raw.csv)
│   └── raw/                   ← Inbox: paste Fiscal AI CSV exports here
├── engines/
│   ├── screener.py            ← Five-gate quality screen
│   ├── quad.py                ← Quad axis computation + quadrant assignment
│   ├── pods.py                ← Business-model pod waterfall
│   ├── alignment.py           ← Compounders Alignment Score (4-signal)
│   ├── fcf_flip.py            ← FCF Yield Flip composite score + setup types
│   ├── severity.py            ← Quad Severity / EV Rank (v9.1)
│   └── reports.py             ← HTML report generation
├── journal/
│   ├── decisions/             ← Timestamped decision log entries (Markdown)
│   ├── migrations/            ← Quad migration events (auto-generated)
│   └── monthly/               ← Monthly rebalance memos
├── outputs/
│   ├── reports/               ← Generated HTML reports
│   └── exports/               ← CSV exports for external use
└── run.py                     ← Main entry point: `python run.py --help`
```

---

## 3. DATA SCHEMA — RAW INPUT (26 COLUMNS, v9 FORMAT)

The Fiscal AI export has exactly 26 columns in this order.
Column order is FIXED. Do not reorder.

| # | Field Name | Notes |
|---|-----------|-------|
| 1 | Ticker | Primary key |
| 2 | Company | Full legal name |
| 3 | Country | ISO 2-letter |
| 4 | Exchange | NYSE / NasdaqGS / etc. |
| 5 | Industry | GICS sub-industry |
| 6 | EPS Surprise Q | NEW in v9: quarterly EPS surprise vs consensus |
| 7 | Rev Surprise Q | NEW in v9: quarterly revenue surprise vs consensus |
| 8 | FCF Yield | Current trailing FCF yield |
| 9 | Forward FCF Yield | Consensus forward FCF yield |
| 10 | Stock Price | Current price |
| 11 | TR 1M Performance | 1-month total return |
| 12 | YTD Performance | Year-to-date total return |
| 13 | Revenue Forward 2Y CAGR | Consensus fwd revenue CAGR (labeled "Fwd Rev" throughout) |
| 14 | CapEx to Revenue | Capital intensity ratio |
| 15 | PEG Ratio | Forward PEG |
| 16 | Market Cap (M) | USD millions |
| 17 | Buyback Yield | Trailing 12-month buyback yield |
| 18 | Revenue 3Y CAGR | Trailing 3-year revenue CAGR |
| 19 | Operating Margin | Trailing operating margin |
| 20 | Net Debt / EBITDA | Leverage ratio |
| 21 | Beta | Market beta |
| 22 | TR 3Y Performance (CAGR) | 3-year trailing total return CAGR |
| 23 | Diluted EPS 3Y CAGR | Trailing 3-year EPS CAGR |
| 24 | EPS Normalized Forward 2Y CAGR | Consensus forward EPS CAGR (labeled "Fwd EPS") |
| 25 | Return on Invested Capital | ROIC (trailing, use for gates) |
| 26 | TR 5Y Performance (CAGR) | 5-year trailing total return CAGR |

**CRITICAL:** Column 6 (EPS Surprise Q) and Column 7 (Rev Surprise Q) were inserted in v9.
All downstream VLOOKUPs reference the new positions. Do not shift.

**Gross Margin note:** Gross Margin is NOT in the Fiscal AI export.
Use Operating Margin as a proxy for pod classification where Gross Margin is required.
Flag this substitution in any output that depends on it.

---

## 4. THE FIVE-GATE QUALITY SCREEN

All five gates must pass. One fail = watch-only. Two consecutive monthly fails on the
same gate, or one fail on two different gates = removed from universe.

| Gate | Field | Threshold | Direction |
|------|-------|-----------|-----------|
| Quality | ROIC (col 25) | ≥ 12% | ≥ |
| Durability | Operating Margin (col 19) | ≥ 25% | ≥ |
| Cash Conversion | FCF Yield (col 8) | ≥ 10% | ≥ |
| Reinvestment | Revenue 3Y CAGR (col 18) | ≥ 6% | ≥ |
| Balance Sheet | Net Debt / EBITDA (col 20) | ≤ 2.5× | ≤ |

**Note on Cash Conversion gate:** FCF Yield is a market-price-dependent metric.
The original gate is FCF Margin ≥ 10%. When FCF Margin is unavailable from Fiscal AI,
we use FCF Yield ≥ 8% as a reasonable proxy. Flag substitution in screener output.

**EPS CAGR cap:** Forward EPS CAGR is capped at 25% for any name with near-zero
trailing EPS (base-effect protection). Track capped names separately.

---

## 5. THE STOCK-LEVEL QUAD FRAMEWORK

### 5.1 Axis Computation

**X-Axis — Revenue Momentum:**
```
X = Fwd Rev CAGR (col 13) − Rev 3Y CAGR (col 18)
Positive = revenue accelerating. Negative = revenue decelerating.
```

**Y-Axis — Earnings Momentum:**
```
Y = Fwd EPS CAGR capped (col 24, cap at 25%) − EPS 3Y CAGR (col 23)
Apply the 25% cap to Fwd EPS CAGR before computing (base-effect protection).
Positive = earnings accelerating. Negative = earnings decelerating.
```

**Note:** The old blended X-axis (0.5 average of revenue + EPS delta) and the old
Y-axis (FCF Yield spread) are replaced. FCF Yield Spread is now a standalone
valuation overlay — see Section 5.4.

**Missing data handling:**
- If either axis cannot be computed (e.g. negative trailing EPS → undefined EPS CAGR):
  assign Quadrant = "N/A" and route to discretionary review.
- If only one axis is computable: compute that axis only; still assign N/A for quadrant.

### 5.2 Quadrant Assignment

| Quadrant | X | Y | EV Rank | Character |
|----------|---|---|---------|-----------|
| Q1 Full Compounders | > 0 | > 0 | **1 — Best** | Revenue AND earnings accelerating. Core long. Full confirmation. |
| Q2 Earnings Resilience | < 0 | > 0 | 2 | Revenue slowing but earnings holding. Quality signal — watch for revenue recovery. |
| Q3 Margin Compression | > 0 | < 0 | 3 | Revenue growing but earnings fading. Margin risk. Monitor closely. |
| Q4 Full Deterioration | < 0 | < 0 | **4 — Worst** | Both revenue and earnings decelerating. Avoid or reduce. |

**Tie-breaking (X = 0 or Y = 0):** assign to the lower-EV quadrant
(conservative: if X = 0 treat as negative; if Y = 0 treat as negative).

**Quadrant stability rule:** Require two consecutive month-ends in the same new
quadrant before treating a migration as signal. First appearance = "provisional."

### 5.3 Visualization Clip Bounds

For scatter chart generation:
- X-axis: clip to [−30%, +30%]. Values outside → triangle marker at edge.
- Y-axis: clip to [−30%, +30%]. Values outside → triangle marker at edge.
- Color: Q1=blue, Q2=green, Q3=red, Q4=orange, N/A=gray.

### 5.4 FCF Yield Spread — Valuation Overlay (Separate from Quad)

**Not a quad input.** Answers a different question: is the valuation trajectory
helping or hurting the thesis?

```
FCF_spread = Current FCF Yield (col 8) − Forward FCF Yield (col 9)
```

| Tag | Condition | Interpretation |
|-----|-----------|---------------|
| Re-rating | spread > 0.5% | Current yield > forward: market expects multiple compression |
| De-rating | spread < −0.5% | Forward yield > current: growth expected to catch up to price |
| Neutral | abs(spread) ≤ 0.5% | Valuation trajectory flat |

This tag appears alongside but **separate** from quad assignment in all outputs.

---

## 6. BUSINESS-MODEL POD WATERFALL

Pods are assigned by deterministic waterfall — first match wins, evaluated in order:

| Priority | Pod | Rule |
|----------|-----|------|
| 1 | Capital Returner | Buyback Yield (col 17) ≥ 3% AND CapEx/Rev (col 14) ≤ 5% |
| 2 | Reinvestor | CapEx/Rev (col 14) ≥ 5% AND Fwd Rev CAGR (col 13) ≥ 10% AND ROIC (col 25) ≥ 15% |
| 3 | Franchise / Pricing Power | Op Margin (col 19) ≥ 25% AND FCF Yield (col 8) ≥ 15% |
| 4 | HQ Growth | Fwd Rev CAGR (col 13) ≥ 15% AND FCF Yield (col 8) ≥ 10% AND ROIC (col 25) ≥ 15% |
| 5 | Cyclical | Beta (col 21) ≥ 1.3 |
| 6 | Defensive | Beta (col 21) ≤ 0.8 |
| 7 | Balance-Sheet Strong | Net Debt/EBITDA (col 20) ≤ 1.0 |
| 8 | GARP | PEG (col 15) ≤ 1.5 AND ROIC (col 25) ≥ 12% |
| 9 | Rate-Sensitive Growth | Fwd Rev CAGR (col 13) ≥ 15% AND PEG (col 15) ≥ 2.0 |
| 10 | Unclassified | No rule matches |

**Note:** The model tracks Pod Count (how many pods a name qualifies for across all rules,
regardless of waterfall assignment). High Pod Count = multi-factor quality confirmation.

---

## 7. COMPOUNDERS ALIGNMENT SCORE (3-SIGNAL, v10.0)

Signal weights (must sum to 1.0):
- Fundamental Velocity (FV): **50%** — Average of rank-normalized X-axis (Revenue Momentum)
  and rank-normalized Y-axis (Earnings Momentum). Both must be positive for a high FV rank.
- Market Conviction (MC): **25%** — Blended price momentum (TR 1M + YTD)
- Earnings Surprise Velocity (ESV): **25%** — Average of Rev Surprise Q + EPS Surprise Q

**Valuation Confirmation (VC) removed.** FCF Yield Spread is now a standalone valuation
overlay (Section 5.4), not a signal input.

Each signal is rank-normalized 0–100 across the universe before weighting.

**Alignment Score = 0.50 × FV_rank + 0.25 × MC_rank + 0.25 × ESV_rank**

Score buckets:
- **Accumulate** (≥ 65): Thesis confirmed. Add/initiate candidates.
- **Neutral** (35–65): At least one signal diverging. Diagnose which.
- **Distribute** (< 35): All signals deteriorating. Trim.

**Missing ESV:** If quarterly surprise data is absent, assign ESV_rank = 50.0
(universe median) so name is not penalized.

### Convergence Signal Language (3-signal system):
| Count | Label |
|-------|-------|
| 3 of 3 | Full alignment — all three signals confirming |
| 2 of 3 | Two of three — check which signal is diverging |
| 1 of 3 | Weak alignment — wait for confirmation |
| 0 of 3 | No alignment — do not add |

### PEAD Flag (Post-Earnings Announcement Drift):
| Label | Condition |
|-------|-----------|
| Strong PEAD | All 3 signals positive + ESV ≥ +3% |
| PEAD Confirm | 2 of 3 signals positive + ESV ≥ 0 |
| PEAD Warn | 2 of 3 signals positive but ESV < −3% |
| Reverse PEAD | Most signals weak but ESV ≥ +3% |
| — | Otherwise |

This is a **weekly hygiene tool**, not a timing signal. Do not use Alignment Score
to make market timing calls.

---

## 8. FCF YIELD FLIP SCREEN (OPTIONS CANDIDATES)

Composite score (0–100) = rank-normalized, higher = more actionable:
- **40%** — Current FCF Yield rank (absolute cheapness)
- **35%** — Yield Decline rank (magnitude of implied re-rating: how far Fwd < Current)
- **25%** — Reverse Price Momentum rank (negative price action scores higher)

### Setup Type Classification:

| Setup Type | Condition |
|-----------|-----------|
| Value Re-rate Underway | High FCF yield + steep Fwd yield decline + price stabilizing |
| Value Trap Watch | High FCF yield + Fwd decline + price still falling |
| Momentum Re-rate | Moderate yield + steep Fwd decline + price already working |
| Deep Value (stable) | High FCF yield + flat Fwd yield (bond-like) |
| Premium + FCF Declining | Low yield + Fwd yield falling (negative; avoid) |
| Premium + FCF Growing | Low yield + Fwd yield falling further due to growth (Q1/Q2 name) |
| Watch | Mixed signals |

**Satellite framework only.** These are defined-risk options structures (call spreads,
LEAPS), not core equity sizing. Every Flip candidate has already cleared the five-gate screen.

High-conviction Q2 names with composite score > 0.80 → longer-dated LEAPS.
Value Re-rate Underway names → 60–90 DTE call spreads.

---

## 9. QUAD SEVERITY & MIGRATION LABELS (v10.0)

**EV Rank:** Q1 (1, Best) → Q2 (2) → Q3 (3) → Q4 (4, Worst)

### Migration Severity Labels:

| Migration | Label | Meaning |
|-----------|-------|---------|
| Q1 → Q2 | CONSTRUCTIVE | Revenue slowing but earnings holding — monitor |
| Q1 → Q3 | WARNING | Earnings fading despite revenue growth — margin risk |
| Q1 → Q4 | **DANGEROUS** | Full deterioration from best bucket |
| Q2 → Q1 | FAVORABLE | Revenue reaccelerating — full confirmation |
| Q2 → Q3 | **DANGEROUS** | Lost earnings resilience AND revenue now compressing |
| Q2 → Q4 | **DANGEROUS** | Full deterioration from earnings resilience |
| Q3 → Q1 | FAVORABLE | Earnings recovering while revenue still strong |
| Q3 → Q4 | WARNING | Revenue now also slowing — full deterioration incoming |
| Q4 → Q1 | FAVORABLE | Full recovery — strongest signal |
| Q4 → Q2 | CONSTRUCTIVE | Earnings recovering first — quality signal |
| Q4 → Q3 | CONSTRUCTIVE | Revenue recovering first — watch margins |
| Q3 → Q2 | **DANGEROUS** | Revenue slowing to match earnings — both now weak |

---

## 10. PORTFOLIO CONSTRUCTION RULES

Four sleeves:
| Sleeve | Target Weight |
|--------|--------------|
| Core Compounders | 45% |
| Catalyst Momentum | 30% |
| Relative Value Pairs | 15% |
| High Conviction Speculative | 10% |

Position sizing:
- Equal weight: 4% per position
- Single-position cap: 7%
- Sector cap: 28%
- Pairwise correlation limit: 0.65
- Monte Carlo gates: P50 drawdown ≤ 12%, P95 drawdown ≤ 20%

---

## 11. AUTOMATED WORKFLOW COMMANDS

When Niko types any of the following, I execute the corresponding workflow:

| Command | Action |
|---------|--------|
| `refresh` | Load newest CSV from data/raw/, update universe.db, recompute all scores |
| `quad snapshot` | Print current quadrant distribution + top 10 per quad by Alignment Score |
| `q2 list` | Show all Q2 names sorted by Alignment Score descending with PEAD Flag |
| `q3 watch` | Show all Q3 names we currently hold — flag for review |
| `flip screen` | Run FCF Flip composite, show top 20 by score with setup type |
| `alignment report` | Full Alignment Score table: Accumulate/Neutral/Distribute buckets |
| `weekly report` | Generate HTML report: quad scatter + alignment table + migration log |
| `monthly rebalance` | Full rebalance memo: all tabs, pitch format, decision log |
| `migration log` | Show all quad changes since last snapshot with severity labels |
| `journal [note]` | Append a timestamped decision note to journal/decisions/ |
| `audit` | Compare current universe to last month; flag additions, removals, migrations |
| `who is [TICKER]` | Full factor card for a single name: all metrics, quad, pod, scores |

---

## 12. DECISION JOURNAL PROTOCOL

Every time a material event occurs, a journal entry is auto-generated and saved to
`journal/migrations/YYYY-MM-DD_migrations.md` or `journal/decisions/`.

A material event is any of:
- Name migrates to Q3 (always logged, always flagged)
- Name migrates from Q4 → Q3 (DANGEROUS — highest priority flag)
- Name added to or removed from universe
- Alignment Score crosses Accumulate/Distribute threshold
- PEAD Flag changes for a held position
- Niko types `journal [note]`

Journal entry format:
```
## [YYYY-MM-DD HH:MM] — [TICKER] — [EVENT TYPE]
**Quadrant:** [old] → [new]
**Severity:** [FAVORABLE / NEUTRAL / CONSTRUCTIVE / DANGEROUS]
**Alignment Score:** [score] ([bucket])
**PEAD Flag:** [flag]
**Trigger:** [what changed — which axis, by how much]
**Context:** [Niko's note if provided, otherwise "auto-generated"]
```

---

## 13. KNOWN LIMITATIONS & SUBSTITUTIONS

1. **Gross Margin not in Fiscal AI export.** Operating Margin used as proxy for
   Franchise/Pricing Power pod and durability intuition. This understates the
   universe of true franchise businesses. Flag in any pod distribution report.

2. **FCF Margin not in Fiscal AI export.** FCF Yield used as proxy for the Cash
   Conversion gate. Note in screener output.

3. **Consensus coverage filter (≥ 5 analysts):** Not enforced in automated screen
   (data not available from Fiscal AI). Apply judgment to thinly covered names.

4. **Negative trailing EPS:** EPS CAGR is undefined. These names are flagged N/A
   and routed to discretionary review. They are structurally underrepresented in Q2.

5. **Sector neutrality:** Not enforced at screen level. Sector caps (28%) are
   enforced at portfolio construction only.

6. **Quadrant stability:** First provisional assignment is logged but not acted on.
   Two consecutive month-end confirmations required to treat a migration as signal.

---

## 14. STYLE GUIDE FOR ALL OUTPUTS

- Font in documents: Calibri
- Brand color: Navy #1F3A5F
- Format: US Letter
- Numbers: percentages to 1 decimal (12.3%), multiples to 1 decimal (1.4×),
  dollar amounts with commas ($1,073)
- All reports include: run timestamp, data source ("Fiscal AI · YYYY-MM-DD"),
  universe count, quadrant distribution
- Quad scatter chart: 200 DPI, quadrant shading, labeled tickers,
  triangles for clipped outliers, color by quadrant (Q1=blue, Q2=green, Q3=red, Q4=orange)

---

## 15. FIRST-SESSION CHECKLIST

When starting a new session, I:
1. Read this file completely
2. Check if universe.db exists; if not, prompt Niko to run `refresh`
3. Check data/raw/ for any unprocessed CSV files
4. Print a one-line status: universe count, last refresh date, any pending migrations

---

## 16. WHITEPAPER ROADMAP ITEMS (ACTIVE)

These are enhancements in progress — flag any data that would support them:

1. **Estimate-revision velocity signal (3rd derivative)** → ESV in v9 is the beginning.
   Next: track consecutive quarterly surprise direction to build a revision momentum series.

2. **Q2 alpha backtest** → When historical data is available, isolate Q2-only
   returns vs Q1 to confirm the expected-value premium. Flag any dataset that enables this.

3. **International extension** → MSCI developed-market universe. Thresholds
   will require recalibration. Not yet implemented.

4. **Live Q3 migration monitor** → Alert system when a held position moves to Q3.
   Auto-generate a DANGEROUS journal entry and surface it at session start.

---

*Integrity Compounders · Integrity Wealth Partners · LPL Financial Affiliate*
*This file is the authoritative methodology reference. Whitepaper v3.0 is the
narrative companion. In any conflict, this file governs computation; the whitepaper governs intent.*
