-- 015 — null the one fossilised win_loss_ratio value
--
-- Until the fix in this batch, persist() wrote win_loss_ratio and slugging_pct
-- from the same expression, t['all']['slug'] — agg() had no win/loss key at all.
-- The 2026-06-15 snapshot therefore stored slugging in both columns:
--
--     run_date    win_loss_ratio   slugging_pct    batting_average
--     2026-06-15  2.070484         2.070484        0.555556
--
-- Bit-for-bit identical, which is what makes this an artifact rather than a
-- coincidence. It cannot be recomputed: trade_stats() marks positions to CURRENT
-- prices, so re-running it today yields today's ratio, not June's.
--
-- Nulling rather than leaving it: win_loss_ratio is a time series, and a wrong
-- number plots as a real one. Left in place it would draw a 2.07 -> 0.91 collapse
-- in win/loss that never happened — the metric simply wasn't being measured.
-- NULL is honest about that; the original value is preserved in this comment and
-- in git so nothing is unrecoverable.
--
-- slugging_pct and batting_average for 2026-06-15 are unaffected and correct.

UPDATE ic_analytics_history
SET win_loss_ratio = NULL
WHERE run_date = '2026-06-15'
  AND win_loss_ratio = slugging_pct;
