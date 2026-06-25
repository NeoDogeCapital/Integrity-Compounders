-- ============================================================================
-- Migration 011 — Integrity Compounders Alpha System V12 Upgrade
-- ----------------------------------------------------------------------------
-- Adds all V12 columns. Additive and idempotent: V11 columns
-- (alignment_score, gate_*, pod, etc.) are left intact so the pipeline keeps
-- running during cutover. New V12 values land in *_v2 / new-named columns.
-- POD columns are deprecated (commented) but not dropped, to preserve history.
-- ============================================================================

-- ── Stage 2: Quad contamination detector ──────────────────────────────────
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS eps_cagr_1y           numeric;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS gp_cagr_1y            numeric;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS gp_cagr_3y            numeric;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS eps_acceleration      numeric;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS gp_acceleration       numeric;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS earnings_quality_flag varchar(20);

-- ── Stage 3: Quality Indicators (diagnostic) ──────────────────────────────
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS gate_capital_efficiency     boolean;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS gate_pricing_power          boolean;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS gate_operational_efficiency boolean;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS gate_cash_conversion        boolean;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS gate_growth_durability      boolean;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS indicators_pass             integer;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS quality_profile             varchar(20);
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS fcf_margin_source           varchar(20);

-- ── Stage 4: Signals + self-computed Alignment ────────────────────────────
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS fcf_ev_rank        numeric;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS fv_rank_v2         numeric;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS mc_rank_v2         numeric;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS esv_rank_v2        numeric;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS alignment_score_v2 numeric;
ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS alignment_bucket_v2 varchar(20);

-- ── Stage 5: Pillar sub-scores (P1 three anchors) ─────────────────────────
ALTER TABLE company_scores ADD COLUMN IF NOT EXISTS p1_moat_score         numeric;
ALTER TABLE company_scores ADD COLUMN IF NOT EXISTS p1_economics_score    numeric;
ALTER TABLE company_scores ADD COLUMN IF NOT EXISTS p1_reinvestment_score numeric;
ALTER TABLE company_scores ADD COLUMN IF NOT EXISTS earnings_quality_flag varchar(20);

-- ── Stage 2 mirror on companies (quad-level cache) ────────────────────────
ALTER TABLE companies ADD COLUMN IF NOT EXISTS earnings_quality_flag varchar(20);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS quality_profile       varchar(20);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS alignment_score_v2    numeric;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS alignment_bucket_v2   varchar(20);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS fcf_ev_rank           numeric;

-- ── POD retirement (Issue 9) — deprecate, do not drop ─────────────────────
COMMENT ON COLUMN company_market_data.pod       IS 'DEPRECATED v12 — retired, replaced by quality_profile + factor model';
COMMENT ON COLUMN company_market_data.pod_count IS 'DEPRECATED v12';
COMMENT ON COLUMN companies.pod                 IS 'DEPRECATED v12';
COMMENT ON COLUMN companies.pod_assignment      IS 'DEPRECATED v12';
COMMENT ON COLUMN companies.pod_count           IS 'DEPRECATED v12';

-- ── Raw EV rank retirement (Issue 10) — replaced by fcf_ev_rank ────────────
COMMENT ON COLUMN company_market_data.ev_rank IS 'DEPRECATED v12 — size measure, replaced by fcf_ev_rank (FCF/EV percentile)';
