"""
backfill_price_history.py — populate ic_price_history for the full active universe
so V12.1 momentum (risk-adj 12-1, trend, 200-DMA extension) computes for every name.

Pulls ~2y of daily OHLCV + adjusted close from yfinance and upserts on
(ticker, price_date). Re-runnable: refreshes recent bars, fills gaps.

    python scripts/backfill_price_history.py                # all active tickers
    python scripts/backfill_price_history.py --only-missing # skip names already >=257 bars
    python scripts/backfill_price_history.py --period 3y
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import argparse
import psycopg2
import psycopg2.extras as pgx
import pandas as pd
import yfinance as yf
from config.settings import settings

PERIOD = "2y"
UPSERT = """
    INSERT INTO ic_price_history
      (ticker, price_date, open_price, high_price, low_price,
       close_price, adj_close, volume, daily_return)
    VALUES %s
    ON CONFLICT (ticker, price_date) DO UPDATE SET
      open_price=EXCLUDED.open_price, high_price=EXCLUDED.high_price,
      low_price=EXCLUDED.low_price, close_price=EXCLUDED.close_price,
      adj_close=EXCLUDED.adj_close, volume=EXCLUDED.volume,
      daily_return=EXCLUDED.daily_return
"""


def _f(v):
    return None if pd.isna(v) else float(v)


def backfill(period=PERIOD, only_missing=False, limit=None):
    conn = psycopg2.connect(settings.DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT ticker FROM companies WHERE active = TRUE ORDER BY ticker")
    tickers = [r[0] for r in cur.fetchall()]

    if only_missing:
        cur.execute("SELECT ticker FROM ic_price_history GROUP BY ticker HAVING COUNT(*) >= 257")
        have = {r[0] for r in cur.fetchall()}
        tickers = [t for t in tickers if t not in have]
    if limit:
        tickers = tickers[:limit]

    print(f"Backfilling {len(tickers)} active tickers (period={period})...\n")
    ok = fail = rows_total = 0
    failed = []

    for i, tk in enumerate(tickers, 1):
        try:
            df = yf.Ticker(tk).history(period=period, auto_adjust=False)
            if df is None or df.empty:
                fail += 1; failed.append(tk); continue
            df = df.reset_index()
            adj_col = "Adj Close" if "Adj Close" in df.columns else "Close"
            df["daily_return"] = df[adj_col].pct_change()

            recs = []
            for _, r in df.iterrows():
                d = r["Date"]
                d = d.date() if hasattr(d, "date") else d
                vol = r.get("Volume")
                recs.append((
                    tk, d, _f(r.get("Open")), _f(r.get("High")), _f(r.get("Low")),
                    _f(r.get("Close")), _f(r.get(adj_col)),
                    None if pd.isna(vol) else int(vol), _f(r.get("daily_return")),
                ))
            pgx.execute_values(cur, UPSERT, recs, page_size=500)
            conn.commit()
            ok += 1; rows_total += len(recs)
            if i % 25 == 0 or i == len(tickers):
                print(f"  {i:>3}/{len(tickers)}  {tk:<6} ok ({len(recs)} bars)")
        except Exception as e:
            conn.rollback(); fail += 1; failed.append(tk)
            if i % 25 == 0:
                print(f"  {i:>3}/{len(tickers)}  {tk:<6} FAIL {str(e)[:50]}")

    conn.close()
    print(f"\nDONE: {ok} ok · {fail} failed · {rows_total:,} bars upserted")
    if failed:
        print("failed:", ", ".join(failed[:50]) + (" ..." if len(failed) > 50 else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default=PERIOD)
    ap.add_argument("--only-missing", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    backfill(a.period, a.only_missing, a.limit)
