# Integrity Compounders — Institutional Process Review
**August 2026 · written against Alpha System v12.1, post Fiscal.ai MCP connection**

Scope: the full weekly pipeline (screener → quads/QGS → momentum/alignment →
portfolio → analytics → dashboards) reviewed from an institutional-fund lens,
plus concrete capability proposals enabled by the Fiscal.ai direct connection.
Companion to CLAUDE.md §16 (roadmap); this document is the reasoning, §16 is
the active list.

---

## 1. What already meets an institutional bar

- **Systematic, versioned methodology** (V12/V12.1 docs), hard rules with floors,
  a two-consecutive-month confirmation state machine, and a decision journal
  with documented overrides (STX eligibility, CEG hold). Most shops never write
  the overrides down.
- **Reproducible pipeline** with health assertions (20 checks) covering the
  failure modes that actually occurred — freshness, engine coverage, book sync,
  key uniqueness. The "every defect was silent" lesson is now encoded.
- **Honest analytics**: geometric capture, episode-based batting/slugging from
  corrected inception, CAPM alpha reported even when it is ~0.
- **Earnings-quality contamination detector** — genuinely differentiated, and now
  **verified against primary data** (FCX: LTM EPS +53.8% vs gross profit −8.0%
  from filed statements — the EPS_ENGINEERED flag reproduced independently).

## 2. Gaps, institutional lens

### Data layer
1. **Single-source fragility.** The weekly manual CSV is the sole driver of
   quads/QGS; yfinance is the sole price/fundamental feed (42-partial weeks,
   chronic symbol failures). *Partially fixed:* CSGS and MOG.A price history now
   filled from Fiscal (CSGS's failure explained — delisted 2026-05); a scripted
   Fiscal fallback needs a REST API key (MCP is session-bound to Claude's OAuth).
2. **Cadence risk.** A company reporting Tuesday isn't re-screened until Friday's
   CSV. Shifts are caught up to 5 trading days late. Fiscal's `events_calendar`
   + transcripts enable **event-driven review on report day**.
3. **No volume stored.** `ic_price_history` has closes only — no ADV, so no
   liquidity screen despite 2nd–7th-percentile Size-factor holdings (AGX, MLI,
   LEU). Fiscal supplies volume; store it.
4. **Point-in-time discipline is partial.** `company_market_data` keeps dated
   rows (good) but the signal loader UPDATEs the latest row in place; restated
   history isn't distinguishable. Institutional backtests require PIT integrity.

### Signal layer
5. **Quad axes are fragile at the tails.** Consensus fwd CAGRs blow up on
   near-zero bases (Y observed at −667% and +4672%); the 25% cap exists in the
   axis math but not the stored `fwd_eps_3y_cagr`. Names ranked by these tails
   are noise-ranked. Consider winsorized or dollar-based acceleration for V13.
6. **Revision velocity (roadmap #1) remains blocked** — the MCP exposes actuals,
   not consensus estimates (`company_earnings_summary` confirmed). Options:
   screener-export deltas week-over-week (already computable), or an estimates
   vendor. Do not fake it from news.
7. **Unused signal layers now one call away:** insider transactions,
   institutional/13F holders, fund-letter sentiment, segment/KPI-level trends,
   and the **adjusted-vs-GAAP wedge** (`company_adjusted_metrics`) — a natural
   contamination-detector v2: persistent widening of company-adjusted vs GAAP
   EPS is the institutional red flag the current detector approximates.

### Risk layer
8. **Theme concentration is measured by GICS, which understates it.** IT reads
   ~32% (cap 28%, chronically breached) but the true AI-infrastructure theme —
   compute, memory, storage, networking, cooling, power, EPC — spans IT,
   Industrials, Utilities and Energy holdings and is the real bet (~70% of the
   book). Institutional practice: tag holdings by theme and report theme
   exposure beside sector exposure.
9. **Return decomposition says beta, not selection.** Beta 1.72, alpha ~0,
   up-capture 2.38/down 1.47: returns are regime + convexity. That is a valid
   strategy — but it should be *stated* (in dashboards and client language) so
   a Quad-3/4 macro regime turn is understood as the primary risk.
10. **No liquidity/capacity policy.** Several holdings could not absorb
    institutional-size flows; there is no ADV-based position limit.

### Process & governance
11. **Pillar scores are AI-assisted point-in-time judgments** with notes but no
    rubric versioning or scheduled re-score; WDC/STX were scored on demand.
    Institutional standard: quarterly re-score of all holdings, rubric version
    stamped, human sign-off recorded (the journal already supports this).
12. **Fiscal terminal portfolios are stale** ("IC 7/1/2026", 25 names) — either
    maintain them as the client-facing mirror (reconciled by the health check
    via `terminal_get_portfolio`) or retire them; a stale second book is worse
    than none.

## 3. Fiscal-enabled capability proposals

**P0 — immediate, high value (runbook-level, no new infra):**
- **Earnings-day watch.** Weekly: pull `events_calendar` for the 28 holdings;
  any name reporting that week is flagged in the morning monitor. On report
  day: transcript pull + guidance-language check (the AEM workflow — where the
  transcript showed guidance *maintained* within range vs the consensus cut).
- **Primary-source contamination audit** each quarter: recompute EPS vs GP
  acceleration from Fiscal filed statements for every EPS_ENGINEERED name and
  every held Q1 name (FCX pattern, done 2026-08-18).
- **Buyback yield** from standardized cash flow — DONE for all 28 holdings
  (top: NEM 3.6%, PODD 3.5%, MA 3.2%, V 3.2%); closes the "pending FMP" gap.
  Extend universe-wide when scripted access exists.

**P1 — build next (small scripts + MCP runbooks):**
- Provision a **Fiscal REST API key** (`FISCAL_API_KEY` in .env) → scripted
  price/volume/fundamental fallback in `data_updater`; retire yfinance
  single-dependency. Store volume; add ADV liquidity screen.
- **Adjusted-vs-GAAP wedge** metric for holdings via `company_adjusted_metrics`
  → second contamination signal.
- **Insider-activity monitor** for holdings (net insider buying/selling per
  quarter) → journal-worthy event when a held name shows clustered selling.
- **Theme tags** on holdings + theme-exposure line on the factor dashboard.
- **Segment-level deceleration** for the top 10 positions (consolidated revenue
  can hide a decelerating core segment — the earliest catchable shift).

**P2 — larger projects:**
- **Screener parity rebuild.** The MCP does not expose saved Fiscal screens
  (account scope = portfolios only), so replacing the Friday CSV means
  rebuilding the screen from raw data (`companies_list` + batched financials/
  ratios) — feasible with a REST key, requires parity validation vs live CSVs
  for several weeks before the CSV is retired. Until then the CSV stays
  canonical for quads/QGS.
- Consensus-estimates source for true revision velocity.
- Formal PIT store (append-only signal snapshots already accumulate in
  `signal_history`; extend to fundamentals).

## 4. Known limits of the connection (honest constraints)
- The MCP is **session-bound** (Claude's OAuth): Python pipeline scripts cannot
  call it. Anything scheduled/scripted needs the REST API key.
- 30-second sandbox; ~6 concurrent helpers; full-universe pulls need batching.
- `company_earnings_summary` returns **actuals only** — no estimates.
- Fiscal closes are split- but not dividend-adjusted; mixing with yfinance
  adj_close is acceptable for gap-fill (done for CSGS/MOG.A, both previously
  empty) but a full source migration must pick one convention.

*Prepared 2026-08-18 · Integrity Compounders · internal.*
