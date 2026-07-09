-- ═══════════════════════════════════════════════════════════
-- V12.1 MIGRATION — momentum revamp + three-lens framework
-- ═══════════════════════════════════════════════════════════

-- ── New momentum signals ─────────────────────────────────────
ALTER TABLE company_market_data
  ADD COLUMN IF NOT EXISTS mom_12_1              DECIMAL(10,6),   -- 12M minus 1M return
  ADD COLUMN IF NOT EXISTS vol_12m               DECIMAL(10,6),   -- trailing 12M volatility
  ADD COLUMN IF NOT EXISTS mom_12_1_risk_adj     DECIMAL(10,6),   -- (12M-1M)/vol
  ADD COLUMN IF NOT EXISTS trend_status          VARCHAR(12),     -- UPTREND/NEUTRAL/DOWNTREND
  ADD COLUMN IF NOT EXISTS dist_200dma           DECIMAL(10,6),   -- (price-200dma)/200dma
  ADD COLUMN IF NOT EXISTS dist_200dma_z         DECIMAL(10,6),   -- z-score of that distance
  ADD COLUMN IF NOT EXISTS extension_flag        VARCHAR(14),     -- OVEREXTENDED/HEALTHY/OVERSOLD
  ADD COLUMN IF NOT EXISTS reversal_setup        BOOLEAN,         -- buy-the-dip flag
  ADD COLUMN IF NOT EXISTS mom_1m_return         DECIMAL(10,6),   -- explicit 1M for reversal logic
  ADD COLUMN IF NOT EXISTS mom_12m_return        DECIMAL(10,6);   -- explicit 12M

-- ── Three-lens composite outputs ─────────────────────────────
ALTER TABLE company_market_data
  ADD COLUMN IF NOT EXISTS fv_absolute           DECIMAL(6,2),    -- QGS tier score 0-100
  ADD COLUMN IF NOT EXISTS fv_historical         DECIMAL(6,2),    -- QGS vs own 12M history
  ADD COLUMN IF NOT EXISTS fv_universe           DECIMAL(6,2),    -- QGS percentile (demoted)
  ADD COLUMN IF NOT EXISTS fv_composite          DECIMAL(6,2),
  ADD COLUMN IF NOT EXISTS mc_absolute           DECIMAL(6,2),    -- trend status score
  ADD COLUMN IF NOT EXISTS mc_historical         DECIMAL(6,2),    -- risk-adj 12-1 vs own history
  ADD COLUMN IF NOT EXISTS mc_universe           DECIMAL(6,2),    -- momentum percentile (demoted)
  ADD COLUMN IF NOT EXISTS mc_composite          DECIMAL(6,2),
  ADD COLUMN IF NOT EXISTS val_historical        DECIMAL(6,2),    -- FCF/EV vs own range
  ADD COLUMN IF NOT EXISTS val_universe          DECIMAL(6,2),    -- FCF/EV percentile
  ADD COLUMN IF NOT EXISTS val_composite         DECIMAL(6,2),
  ADD COLUMN IF NOT EXISTS alignment_score_v3    DECIMAL(6,2),
  ADD COLUMN IF NOT EXISTS alignment_bucket_v3   VARCHAR(20),
  ADD COLUMN IF NOT EXISTS history_maturity      VARCHAR(20);     -- COLD_START/BUILDING/MATURE

-- ── Signal history table (the dependency that makes this work) ──
CREATE TABLE IF NOT EXISTS signal_history (
  id                    UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  ticker                VARCHAR(20) NOT NULL,
  snapshot_date         DATE NOT NULL,
  quality_growth_score  DECIMAL(12,6),
  fcf_ev_yield          DECIMAL(8,4),
  mom_12_1_risk_adj     DECIMAL(10,6),
  roic                  DECIMAL(8,4),
  fcf_margin            DECIMAL(8,4),
  alignment_score_v3    DECIMAL(6,2),
  created_at            TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(ticker, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_signal_history_ticker_date
  ON signal_history(ticker, snapshot_date DESC);
