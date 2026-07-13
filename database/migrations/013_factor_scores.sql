-- ═══════════════════════════════════════════════════════════
-- MIGRATION 013 — per-name characteristic factor scores
-- Six factors (Value, Momentum, Quality, Low Vol, Size, Growth)
-- as winsorized cross-sectional z-scores of fundamental descriptors,
-- for every active name. MSCI/Barra-style descriptor standardization.
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS factor_scores (
  id             UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  ticker         VARCHAR(20) NOT NULL,
  data_date      DATE NOT NULL,
  value_z        NUMERIC, value_pct    NUMERIC,
  momentum_z     NUMERIC, momentum_pct NUMERIC,
  quality_z      NUMERIC, quality_pct  NUMERIC,
  lowvol_z       NUMERIC, lowvol_pct   NUMERIC,
  size_z         NUMERIC, size_pct     NUMERIC,
  growth_z       NUMERIC, growth_pct   NUMERIC,
  factor_profile TEXT,                              -- top loadings, e.g. "Momentum / Growth"
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(ticker, data_date)
);
CREATE INDEX IF NOT EXISTS idx_factor_scores_ticker_date
  ON factor_scores(ticker, data_date DESC);
