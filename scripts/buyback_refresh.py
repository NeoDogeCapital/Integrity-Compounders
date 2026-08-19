"""
buyback_refresh.py — universe-wide buyback yield from Fiscal.ai (monthly)

For every active name with a latest company_market_data row: pull the LTM
standardized cash-flow statement via the Fiscal REST API, take
`cash_flow_statement_repurchases_of_common_shares`, and write
buyback_yield = |LTM repurchases| / market cap (%, market_cap stored in raw
dollars) onto the latest cmd row.

Replaces the never-delivered FMP dependency. Holdings were first computed via
the MCP on 2026-08-18; this script generalizes it to the whole universe using
FISCAL_API_KEY. Names without Fiscal coverage or without a market cap are
skipped and reported, never zero-filled.

    python scripts/buyback_refresh.py [--limit N]
"""
import sys
import time
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import psycopg2
from config.settings import settings
from fiscal_api import FiscalAPI, FiscalKeyMissing

METRIC = "cash_flow_statement_repurchases_of_common_shares"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.25, help="politeness delay between calls")
    a = ap.parse_args()

    try:
        api = FiscalAPI()
        api.profile(ticker="AAPL")  # connectivity gate
    except FiscalKeyMissing as e:
        print(f"  ⚠️  {e}"); return 1

    conn = psycopg2.connect(settings.DATABASE_URL); conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""SELECT c.ticker, cmd.market_cap FROM companies c
        JOIN company_market_data cmd ON cmd.ticker = c.ticker
         AND cmd.data_date = (SELECT MAX(data_date) FROM company_market_data WHERE ticker = c.ticker)
        WHERE c.active = TRUE AND cmd.market_cap IS NOT NULL ORDER BY c.ticker""")
    rows = cur.fetchall()
    if a.limit:
        rows = rows[:a.limit]
    print(f"  buyback refresh: {len(rows)} names via Fiscal REST\n")

    ok = skip = err = 0
    for i, (tk, mcap) in enumerate(rows, 1):
        try:
            fin = api.financials_standardized("cash-flow-statement", ticker=tk, periodType="ltm")
            data = (fin or {}).get("data") or []
            if not data:
                skip += 1; continue
            latest = max(data, key=lambda d: d.get("reportDate") or "")
            v = (latest.get("metricsValues") or {}).get(METRIC) or {}
            bb = v.get("value")
            if bb is None:
                bb = 0.0  # no repurchase line in an otherwise-present LTM statement = no buybacks
            y = abs(float(bb)) / float(mcap) * 100
            cur.execute("""UPDATE company_market_data SET buyback_yield=%s WHERE ticker=%s
                AND data_date=(SELECT MAX(data_date) FROM company_market_data WHERE ticker=%s)""",
                        (y, tk, tk))
            ok += 1
        except Exception as e:
            err += 1
            if err <= 5:
                print(f"   {tk}: {str(e)[:70]}")
        if i % 50 == 0:
            print(f"   {i}/{len(rows)} · ok {ok} · no-data {skip} · err {err}")
        time.sleep(a.sleep)

    cur.execute("""SELECT COUNT(buyback_yield) FROM company_market_data cmd
        WHERE data_date=(SELECT MAX(data_date) FROM company_market_data WHERE ticker=cmd.ticker)""")
    print(f"\n  DONE: {ok} updated · {skip} no Fiscal LTM data · {err} errors")
    print(f"  buyback_yield populated on latest rows: {cur.fetchone()[0]}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
