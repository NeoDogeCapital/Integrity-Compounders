"""
daily_signals.py — daily universe-wide technical signal changes

The V12.1 momentum engine computes trend / 200-DMA extension / reversal for
every active name, but only when the weekly pipeline runs — so a 200-DMA break
on Tuesday surfaced Friday. This job runs DAILY (launchd, post-close):

  1. incremental price refresh (1wk window, Fiscal fallback armed)
  2. recompute momentum signals universe-wide
  3. snapshot each name's categorical state into ic_signal_state_daily
  4. diff vs the prior snapshot -> ic_signal_changes (holdings flagged)
  5. print the day's changes; trigger_monitor §7c shows the last 3 days

This is the in-house answer to "signals firing automatically across the
screened universe" — model-native definitions, no vendor. TrendSpider remains
the intraday/holdings alert layer and the chart-structure view.

    python scripts/daily_signals.py            # normal daily run
    python scripts/daily_signals.py --no-fetch # recompute+diff only
"""
import sys
import argparse
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import psycopg2
from config.settings import settings

FIELDS = ["trend_status", "extension_flag", "reversal_setup", "quadrant"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    today = date.today()

    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS ic_signal_state_daily (
        state_date DATE NOT NULL, ticker VARCHAR(12) NOT NULL,
        trend_status VARCHAR(16), extension_flag VARCHAR(16),
        reversal_setup BOOLEAN, quadrant VARCHAR(4),
        PRIMARY KEY (state_date, ticker))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS ic_signal_changes (
        id BIGSERIAL PRIMARY KEY, change_date DATE NOT NULL,
        ticker VARCHAR(12) NOT NULL, field VARCHAR(24) NOT NULL,
        old_value TEXT, new_value TEXT, is_holding BOOLEAN DEFAULT FALSE,
        UNIQUE (change_date, ticker, field))""")

    if not a.no_fetch:
        from backfill_price_history import backfill as refresh
        print("[daily-signals] price refresh (1wk incremental)...")
        refresh(period="5d")
    from momentum_engine import compute_momentum
    mconn = psycopg2.connect(settings.DATABASE_URL)
    compute_momentum(mconn)
    mconn.commit(); mconn.close()

    # quadrant comes from the weekly screener stage; carried for context only.
    cur.execute("""SELECT c.ticker, cmd.trend_status, cmd.extension_flag,
            cmd.reversal_setup, cmd.quadrant, COALESCE(c.in_portfolio, FALSE)
        FROM companies c JOIN company_market_data cmd ON cmd.ticker = c.ticker
         AND cmd.data_date = (SELECT MAX(data_date) FROM company_market_data
                              WHERE ticker = c.ticker)
        WHERE c.active = TRUE""")
    rows = cur.fetchall()
    held = {r[0] for r in rows if r[5]}

    cur.execute("SELECT MAX(state_date) FROM ic_signal_state_daily WHERE state_date < %s", (today,))
    prev_date = cur.fetchone()[0]
    prev = {}
    if prev_date:
        cur.execute("""SELECT ticker, trend_status, extension_flag, reversal_setup, quadrant
                       FROM ic_signal_state_daily WHERE state_date = %s""", (prev_date,))
        prev = {r[0]: dict(zip(FIELDS, r[1:])) for r in cur.fetchall()}

    changes = []
    for tk, trend, ext, rev, quad, _h in rows:
        cur.execute("""INSERT INTO ic_signal_state_daily
            (state_date, ticker, trend_status, extension_flag, reversal_setup, quadrant)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (state_date, ticker) DO UPDATE SET
              trend_status=EXCLUDED.trend_status, extension_flag=EXCLUDED.extension_flag,
              reversal_setup=EXCLUDED.reversal_setup, quadrant=EXCLUDED.quadrant""",
            (today, tk, trend, ext, rev, quad))
        if tk in prev:
            now = dict(zip(FIELDS, (trend, ext, rev, quad)))
            for f in FIELDS:
                if str(prev[tk].get(f)) != str(now.get(f)) and now.get(f) is not None:
                    cur.execute("""INSERT INTO ic_signal_changes
                        (change_date, ticker, field, old_value, new_value, is_holding)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (change_date, ticker, field) DO UPDATE SET
                          old_value=EXCLUDED.old_value, new_value=EXCLUDED.new_value""",
                        (today, tk, f, str(prev[tk].get(f)), str(now.get(f)), tk in held))
                    changes.append((tk, f, prev[tk].get(f), now.get(f), tk in held))

    print(f"\n[daily-signals] {today} · {len(rows)} names · baseline {prev_date or 'NONE (first run)'}")
    if not prev_date:
        print("  first run — baseline recorded, diffs start tomorrow")
    elif not changes:
        print("  no signal changes vs prior snapshot")
    else:
        changes.sort(key=lambda c: (not c[4], c[0]))
        print(f"  {len(changes)} signal change(s):")
        for tk, f, o, n, h in changes:
            print(f"   {'★' if h else ' '} {tk:<6} {f:<16} {o} → {n}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
