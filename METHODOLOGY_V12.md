# Integrity Compounders Alpha System — Methodology V12

**Version 12 | Internal Use Only**

## Philosophy

Integrity Compounders owns a concentrated set of exceptional businesses, holds
them while the thesis is intact, and lets compounding do the work. The system is
fully quantitative at the screening and monitoring layer and judgment-assisted at
the thesis and scoring layer. Nothing enters the portfolio on intuition alone.
Every signal answers one specific question about whether a business is a durable
compounder and whether now is the right time to own it.

Portfolio construction: equal weight (1/N) across all holdings including
discretionary names. Maximum 25 holdings. Sector cap 28%. Adding a name requires
removing one.

## The Pipeline — Nine Stages

### Stage 1 — Data Ingestion
Sources: Fiscal AI screener CSV (primary fundamentals) + yfinance enrichment
(prices, momentum, beta, short interest). Single source of truth: Supabase
PostgreSQL. Local SQLite is a cache only — decision data is never authored there.

### Stage 2 — Quad Classification
**Question: Is this business accelerating or decelerating right now, and is that
acceleration real?**

Axes (forward vs trailing — captures consensus revision direction):
- X = fwd_rev_cagr − rev_3y_cagr (revenue acceleration)
- Y = fwd_eps_cagr − eps_3y_cagr (earnings acceleration)

Quadrants:
- Q1 Full Compounder: X>0, Y>0 — revenue and earnings both accelerating
- Q2 Earnings Resilience: X>0, Y≤0 — revenue accelerating, earnings compressing
- Q3 Margin Compression: X≤0, Y≤0 — both decelerating (watchlist)
- Q4 Reset/Avoid: X≤0, Y>0 — revenue decelerating, EPS expanding (cost-cutting)

**Earnings Quality Contamination Detector** (new in V12):
Because EPS is vulnerable to buybacks, tax, SBC, and D&A manipulation, we verify
earnings acceleration against gross profit acceleration on a trailing basis:
- eps_acceleration = eps_cagr_1y − eps_cagr_3y
- gp_acceleration = gp_cagr_1y − gp_cagr_3y

Flags:
- EPS_CONFIRMED: both accelerating — earnings growth backed by real unit economics
- EPS_ENGINEERED: EPS accelerating, gross profit NOT — financial engineering, scrutinize
- GP_LEADING: gross profit accelerating ahead of EPS — early positive inflection
- NEUTRAL: neither accelerating

The flag feeds the pillar scorer. A Q1 name flagged EPS_ENGINEERED is a momentum
trade, not a confirmed compounder.

Two-consecutive-month confirmation: a quad change requires two consecutive months
in the new quadrant before it triggers portfolio action.

### Stage 3 — Quality Indicators (Diagnostic)
**Question: Does this business clear minimum quality standards on each independent
dimension?**

Six indicators, each PASS/FAIL. These are DIAGNOSTIC, not eliminatory — they
describe the quality profile but do not by themselves exclude a name. Missing data
produces DATA_INCOMPLETE, never a false FAIL.

| Indicator | Threshold | Question |
|---|---|---|
| Capital Efficiency | ROIC ≥ 10% | Returns above cost of capital? |
| Pricing Power | Gross Margin ≥ 30% | Structural pricing advantage? |
| Operational Efficiency | Operating Margin ≥ 15% | Disciplined cost structure? |
| Cash Conversion | FCF Margin ≥ 7% | Earnings converting to cash? |
| Growth Durability | Revenue 3Y CAGR ≥ 5% | Real growth, not a bond substitute? |
| Balance Sheet | Net Debt/EBITDA ≤ 3.0× | Survives a downturn? |

Quality Profile: 5-6 pass = FULL_COMPOUNDER, 3-4 = QUALITY_WATCH,
1-2 = DEVELOPING, 0 = QUALITY_CONCERN.

FCF Margin source priority: Fiscal AI CSV → yfinance backup → DATA_INCOMPLETE.

### Stage 4 — Signal Synthesis
**Question: Across quality, growth, valuation, efficiency, and momentum, how
attractive is this name and what should we do with it?**

This stage consolidates V11's separate signal and alignment stages.

**Quality Growth Score (QGS)** — *How much quality and growth am I getting for the
price I'm paying?*
QGS = (fwd_rev_cagr + fwd_eps_cagr) × fcf_ev_yield × roic × fcf_margin
Multiplicative — a weakness in any dimension collapses the score.
Tiers: RARE_ELITE >0.0028, EXCEPTIONAL >0.0016, GOOD_COMPOUNDER >0.0006,
AVERAGE >0.0002, LOW_QUALITY otherwise.

**Growth Efficiency Ratio (GER)** — *Is this growth real or purchased with dilution?*
GER = (fwd_rev_cagr + fwd_eps_cagr) / max(sbc_pct + shares_out_growth, 0.01)
Flags: NORMAL, FLOORED (denominator capped at 1%), NET_RETURNER (buybacks exceed
issuance — a positive signal).

**FCF/EV Rank** — *How cheap is this on a cash basis relative to total capital?*
Percentile rank of FCF/EV yield. Replaces V11's raw EV rank (which measured size).
100 = cheapest on cash yield, 1 = most expensive.

**Alignment Score** — *What action does this name warrant right now?*
Fully self-computed (V12 replaces Fiscal AI black-box ranks):
- FV Rank (40%): QGS percentile within universe — quality-growth-valuation
- MC Rank (25%): weighted momentum percentile (1M×15% + 3M×25% + 6M×30% + 12M×30%)
  — momentum confirmation; is price behavior confirming the fundamental thesis?
- ESV Rank (35%): earnings surprise composite — beat rate (35%) + rev surprise (25%)
  + eps surprise (25%) + PEAD drift proxy (15%); is the business beating and is the
  beat sustaining?

Alignment = FV×0.40 + MC×0.25 + ESV×0.35
Buckets: ACCUMULATE ≥65, HOLD 35-64, DISTRIBUTE <35

**Flip Score** — *Is this a value trap or reversal risk?* (standalone risk overlay)
0-1 composite of FCF yield rank + yield decline rank + reverse momentum rank.
>0.50 alongside ACCUMULATE flags a potential value trap.

### Stage 5 — Three-Pillar AI Underwriting
**Question: Is this a structurally excellent business (P1), run by capable aligned
management (P2), with financial resilience to survive adversity (P3)?**

Valuation appears in NONE of the pillars — it lives only in QGS and FCF/EV.
Scored 1.0-10.0 by Claude from research, transcripts, filings.

**P1 Business Quality (40%)** — three anchors, averaged:
- Moat Durability: what keeps competitors out, how structural
- Economics Sustainability: will margins/returns hold 5 years; uses ROIC LEVEL
- Reinvestment Quality: organic runway to deploy capital at high returns

**P2 Management & Capital Allocation (35%) — HARD FLOOR 6.0:**
- Capital Allocation Effectiveness (40%): ROIC TRAJECTORY (rising/stable/eroding),
  M&A discipline, buyback discipline, SBC as % revenue
- Alignment & Integrity (35%): founder-led, insider ownership, compensation structure
- Communication Quality (25%): honesty, guidance accuracy, strategy consistency

**P3 Financial Strength (25%) — HARD FLOOR 6.0:**
- Balance Sheet Resilience (35%): leverage, interest coverage
- Earnings & Cash Quality (35%): FCF conversion, revenue consistency, FCF track record
- Self-Funding Ability (30%): can growth be funded internally

Composite = P1×0.40 + P2×0.35 + P3×0.25
Tiers: TIER_1 ≥8.0, TIER_2 6.5-7.9, WATCHLIST 5.0-6.4, DNQ <5.0
Hard floors: P2<6.0 or P3<6.0 blocks eligibility regardless of composite.

ROIC appears in both P1 and P2 by design: P1 uses the LEVEL (structural quality),
P2 uses the TRAJECTORY (management skill). The earnings_quality_flag from Stage 2
feeds this layer — EPS_ENGINEERED names get extra scrutiny on P1 economics and P2
capital allocation.

### Stage 6 — Portfolio Construction
Initiation requires: Q1 or Q2, Alignment ACCUMULATE, pillar composite ≥6.5,
P2≥6.0, P3≥6.0, sector cap intact, thesis documented with invalidation conditions.
Equal weight. Q3/Q4 names not added without explicit documented override.

### Stage 7 — Exit & Thesis Monitoring
Exit review triggered by: two consecutive months Q3/Q4, Alignment DISTRIBUTE,
pillar composite below 6.5, P2 or P3 hard floor breach, thesis monitor BROKEN.

### Stage 8 — Factor Risk (monthly, portfolio level)
Six-factor exposure model: Quality, Value, Momentum, Volatility, Sentiment,
Reversal. Bps per 2σ within ±200 bps tolerance. Does not drive individual stock
decisions — informs portfolio-level rebalancing.

### Stage 9 — Decision Hierarchy
Priority order when signals conflict:
1. Pillar hard floors (P2/P3 < 6.0) — blocks unconditionally
2. Pillar composite tier — conviction ceiling
3. Quad — Q1/Q2 actionable, Q3/Q4 require override
4. Alignment Score — ACCUMULATE enables deployment
5. Flip Score — value trap check
6. Quality Profile — diagnostic context
7. QGS/GER/earnings_quality_flag — supporting signals

## Retired in V12
- POD (Point of Differentiation) — replaced by quality profile + factor model
- Raw EV Rank — replaced by FCF/EV percentile
- Standalone PEAD flag — absorbed into ESV Rank
- "Gate" eliminatory language — now diagnostic Quality Indicators
- Valuation inside pillars — moved to QGS/FCF-EV only
