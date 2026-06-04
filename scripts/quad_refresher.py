"""
quad_refresher.py
-----------------
Computes Stock-Level Quad assignments from company_market_data.
Enforces two-consecutive-month confirmation before treating a quad
change as a confirmed signal.

Quad axes (Integrity Compounders v10.0):
  X = Revenue Momentum = Fwd Rev CAGR - Trailing Rev CAGR
  Y = Earnings Momentum = Fwd EPS CAGR - Trailing EPS CAGR

Quadrants:
  Q1 Full Compounders:    X > 0, Y > 0  (EV Rank 1 — Best)
  Q2 Earnings Resilience: X < 0, Y > 0  (EV Rank 2)
  Q3 Margin Compression:  X > 0, Y < 0  (EV Rank 3)
  Q4 Full Deterioration:  X < 0, Y < 0  (EV Rank 4 — Worst)
  NA: either axis is NULL

Usage:
    python scripts/quad_refresher.py            # all active companies
    python scripts/quad_refresher.py --ticker NVDA
"""

import sys
import argparse
from pathlib import Path
from datetime import date

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
from config.settings import settings


QUAD_NAMES = {
    "Q1": "Full Compounders",
    "Q2": "Earnings Resilience",
    "Q3": "Margin Compression",
    "Q4": "Full Deterioration",
    "NA": "Axis Incomplete",
}


def get_conn():
    return psycopg2.connect(settings.DATABASE_URL)


def assign_quad(x: float | None, y: float | None) -> str:
    if x is None or y is None:
        return "NA"
    if x >= 0 and y >= 0:
        return "Q1"
    if x < 0  and y >= 0:
        return "Q2"
    if x >= 0 and y < 0:
        return "Q3"
    return "Q4"   # x < 0 and y < 0


def process_ticker(company_id: str, ticker: str, quad_current: str | None,
                   quad_consec: int, conn) -> dict:
    """
    Pull latest market data, compute quad, handle migration logic.
    Returns result dict for printing.
    """
    cur = conn.cursor()

    # Latest market data row
    cur.execute("""
        SELECT fwd_revenue_3y_cagr, revenue_3y_cagr_trailing,
               fwd_eps_3y_cagr,     earnings_momentum_roc,
               multiple_roc,        fcf_yield_current, fcf_yield_forward,
               data_date
        FROM company_market_data
        WHERE company_id = %s
        ORDER BY data_date DESC
        LIMIT 1
    """, (company_id,))
    row = cur.fetchone()

    if not row:
        cur.close()
        return {"ticker": ticker, "status": "no_data", "new_quad": "NA",
                "x": None, "y": None, "message": "no market data"}

    (fwd_rev, trail_rev, fwd_eps_growth, earn_mom_roc,
     mult_roc, fcf_curr, fcf_fwd, data_date) = row

    # Compute axes
    # X = Revenue Momentum: Fwd Rev CAGR - Trailing Rev CAGR
    x = (float(fwd_rev) - float(trail_rev)) if (fwd_rev is not None and trail_rev is not None) else None

    # Y = Earnings Momentum: Fwd EPS CAGR - Trailing EPS CAGR
    # Use pre-computed earnings_momentum_roc if available (most accurate)
    # Fall back to multiple_roc (FCF yield spread) as secondary signal
    if earn_mom_roc is not None:
        y = float(earn_mom_roc)
    elif fwd_eps_growth is not None and trail_rev is not None:
        # Use fwd EPS growth vs zero as a simple proxy
        y = float(fwd_eps_growth)
    else:
        y = float(mult_roc) if mult_roc is not None else None

    new_quad = assign_quad(x, y)

    result = {
        "ticker":    ticker,
        "x":         x,
        "y":         y,
        "new_quad":  new_quad,
        "old_quad":  quad_current,
        "status":    None,
        "message":   "",
        "confirmed": False,
    }

    if new_quad == quad_current:
        # No change
        result["status"] = "no_change"
        cur.close()
        return result

    # Quad changed — check migration log for an existing provisional entry
    cur.execute("""
        SELECT id, consecutive_months
        FROM quad_migration_log
        WHERE company_id = %s
          AND to_quad = %s
          AND confirmed = FALSE
        ORDER BY created_at DESC
        LIMIT 1
    """, (company_id, new_quad))
    prior = cur.fetchone()

    today = date.today()

    if prior:
        # Provisional entry exists for this quad — confirm it
        prior_id, consec = prior
        cur.execute("""
            UPDATE quad_migration_log
            SET consecutive_months = 2,
                confirmed = TRUE,
                pm_decision = 'PENDING'
            WHERE id = %s
        """, (prior_id,))
        # Update companies table
        cur.execute("""
            UPDATE companies
            SET quad_current = %s,
                quad_prior = %s,
                quad_changed_at = NOW(),
                quad_consecutive_months = 2
            WHERE id = %s
        """, (new_quad, quad_current, company_id))
        conn.commit()
        result["status"]    = "confirmed"
        result["confirmed"] = True
        result["message"]   = f"CONFIRMED (month 2) — was {quad_current} — PM REVIEW REQUIRED"
    else:
        # New migration — insert provisional entry, do NOT update quad_current yet
        cur.execute("""
            INSERT INTO quad_migration_log
                (company_id, ticker, from_quad, to_quad, migration_date,
                 trigger_type, earnings_momentum_roc, multiple_roc,
                 consecutive_months, confirmed, pm_decision)
            VALUES (%s, %s, %s, %s, %s, 'estimate_revision', %s, %s, 1, FALSE, 'PENDING')
        """, (company_id, ticker, quad_current or "NA", new_quad, today,
              x, y))
        cur.execute("""
            UPDATE companies
            SET quad_consecutive_months = 1
            WHERE id = %s
        """, (company_id,))
        conn.commit()
        result["status"]  = "provisional"
        result["message"] = f"MIGRATION month 1/2 (was {quad_current or 'None'}) — not yet confirmed"

    cur.close()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, default=None)
    args = parser.parse_args()

    conn = get_conn()
    cur  = conn.cursor()

    if args.ticker:
        cur.execute("""
            SELECT id, ticker, quad_current, quad_consecutive_months
            FROM companies WHERE ticker = %s AND active = TRUE
        """, (args.ticker.upper(),))
    else:
        cur.execute("""
            SELECT id, ticker, quad_current, quad_consecutive_months
            FROM companies WHERE active = TRUE ORDER BY ticker
        """)

    companies = cur.fetchall()
    cur.close()

    print(f"\n  QUAD REFRESHER — {date.today()} — {len(companies)} ticker(s)\n")
    print(f"  {'Ticker':<7} {'X':>8}  {'Y':>8}  {'Quad':<5}  Status")
    print("  " + "-" * 65)

    results = []
    for company_id, ticker, quad_current, quad_consec in companies:
        r = process_ticker(str(company_id), ticker, quad_current,
                           quad_consec or 0, conn)
        results.append(r)

        x_str = f"{r['x']*100:+.1f}%" if r.get("x") is not None else "   N/A "
        y_str = f"{r['y']*100:+.1f}%" if r.get("y") is not None else "   N/A "
        quad_str = r["new_quad"]

        if r["status"] == "no_data":
            print(f"  {ticker:<7} {'—':>8}  {'—':>8}  {'NA':<5}  ⚪ no market data")
        elif r["status"] == "no_change":
            print(f"  {ticker:<7} {x_str:>8}  {y_str:>8}  {quad_str:<5}  (no change)")
        elif r["status"] == "provisional":
            print(f"  {ticker:<7} {x_str:>8}  {y_str:>8}  {quad_str:<5}  ⚠️  {r['message']}")
        elif r["status"] == "confirmed":
            print(f"  {ticker:<7} {x_str:>8}  {y_str:>8}  {quad_str:<5}  🚨 {r['message']}")

    # Portfolio quad distribution
    cur = conn.cursor()
    cur.execute("""
        SELECT quad_current, COUNT(*) as n
        FROM companies
        WHERE in_portfolio = TRUE AND active = TRUE
        GROUP BY quad_current
        ORDER BY quad_current
    """)
    dist = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("SELECT COUNT(*) FROM companies WHERE in_portfolio=TRUE AND active=TRUE")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()

    print(f"\n  PORTFOLIO QUAD DISTRIBUTION ({total} holdings, equal weight)")
    print(f"  {'Quad':<5}  {'Name':<26}  {'Count':>5}  {'Weight':>7}  Alert")
    print("  " + "-" * 60)
    for q, name in QUAD_NAMES.items():
        n   = dist.get(q, 0)
        pct = n / total * 100 if total else 0
        flag = "  ⚠️  REVIEW" if q in ("Q3","Q4") and n > 0 else ""
        print(f"  {q:<5}  {name:<26}  {n:>5}  {pct:>6.1f}%{flag}")

    # Summary
    migrations  = [r for r in results if r["status"] == "provisional"]
    confirmed   = [r for r in results if r["status"] == "confirmed"]
    no_data     = [r for r in results if r["status"] == "no_data"]

    print(f"\n  SUMMARY: {len(confirmed)} confirmed migration(s)  "
          f"{len(migrations)} provisional  {len(no_data)} no data")
    if confirmed:
        print("  🚨 Confirmed — PM decision required:")
        for r in confirmed:
            print(f"     {r['ticker']}: {r['old_quad']} → {r['new_quad']}")


if __name__ == "__main__":
    main()
