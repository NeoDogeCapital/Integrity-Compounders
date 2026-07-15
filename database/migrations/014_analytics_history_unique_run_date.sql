-- 014 — ic_analytics_history: one snapshot per run_date
--
-- persist() wrote "ON CONFLICT DO NOTHING", but the only unique index on this
-- table is the id primary key, so nothing ever conflicted and every run APPENDED
-- a duplicate row. 2026-07-15 had accumulated 5 rows. This matters more now that
-- the analytics step runs from data_updater on the daily workflow rather than
-- only when publish.py happens to be invoked: the table is the time series behind
-- the "metrics over time" charts, and duplicate points per date corrupt it.
--
-- Keep the newest row per run_date (highest id = most recent computation), then
-- constrain the table so persist() can upsert on run_date.

DELETE FROM ic_analytics_history a
USING ic_analytics_history b
WHERE a.run_date = b.run_date
  AND a.id < b.id;

CREATE UNIQUE INDEX IF NOT EXISTS ux_ic_analytics_history_run_date
    ON ic_analytics_history (run_date);
