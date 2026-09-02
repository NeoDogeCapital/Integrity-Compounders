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


# Explicit overrides take priority; otherwise class-share dots → yfinance dashes
# (DB "MOG.A"/"BRK.B" → yfinance "MOG-A"/"BRK-B"). Rows are always stored under the
# canonical DB ticker, only the yfinance *request* symbol is mapped.
YF_SYMBOL_OVERRIDES = {}

def _yf_symbol(ticker: str) -> str:
    return YF_SYMBOL_OVERRIDES.get(ticker, ticker.replace(".", "-"))


# Benchmarks + factor ETFs. These are NOT in `companies`, so without this list they
# never get refreshed and silently go stale — which strands the return series and the
# factor-exposure regressions at whatever date they last loaded.
BENCH_ETFS = ["SPY", "QQQ", "VLUE", "MTUM", "QUAL", "USMV", "IWM", "IWF"]


def backfill(period=PERIOD, only_missing=False, limit=None, only_ticker=None):
    conn = psycopg2.connect(settings.DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT ticker FROM companies WHERE active = TRUE ORDER BY ticker")
    tickers = [r[0] for r in cur.fetchall()]
    tickers += [t for t in BENCH_ETFS if t not in tickers]

    if only_ticker:
        want = {t.strip().upper() for t in ([only_ticker] if isinstance(only_ticker, str) else only_ticker)}
        # explicit tickers are honored even when not in the active core universe
        # (the micro sleeve backfills inactive, micro-tagged names)
        tickers += sorted(want - set(tickers))
        tickers = [t for t in tickers if t.upper() in want]
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
            df = yf.Ticker(_yf_symbol(tk)).history(period=period, auto_adjust=False)
            if df is None or df.empty:
                # Fiscal.ai REST fallback (needs FISCAL_API_KEY in .env; no-op without it).
                # Covers delisted/class-share names yfinance can't serve (CSGS, MOG.A).
                # Fiscal closes are split- but not dividend-adjusted — acceptable for
                # gap-fill on otherwise-empty names.
                try:
                    from fiscal_api import fetch_prices_fallback
                    fb = fetch_prices_fallback(tk)
                except Exception:
                    fb = None
                if fb:
                    recs = [(tk, d, None, None, None, None, px, vol, None) for d, px, vol in fb]
                    pgx.execute_values(cur, UPSERT, recs, page_size=500)
                    conn.commit()
                    ok += 1; rows_total += len(recs)
                    print(f"  {i:>3}/{len(tickers)}  {tk:<6} ok via Fiscal fallback ({len(recs)} bars)")
                    continue
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
            # The Supabase pooler drops long-lived connections mid-run
            # ("server closed the connection unexpectedly"); a rollback on the
            # dead handle then raised InterfaceError and killed the whole job
            # (daily-signals failed 08-19..08-21 this way). Reconnect and move on.
            try:
                conn.rollback()
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = psycopg2.connect(settings.DATABASE_URL)
                cur = conn.cursor()
                print(f"  {i:>3}/{len(tickers)}  {tk:<6} reconnected after dropped connection")
            fail += 1; failed.append(tk)
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
    ap.add_argument("--ticker", default=None, help="Backfill a single ticker (e.g. MOG.A)")
    a = ap.parse_args()
    backfill(a.period, a.only_missing, a.limit, a.ticker)
