"""
quad_refresher.py
-----------------
Applies the two-consecutive-month confirmation rule to the stock-level Quad and
reports the portfolio's quad distribution.

It does NOT compute the quad. The canonical V12 quad is produced by
data_updater's compute_quad (engines/quad.py::_assign_quadrant) from the Fiscal
AI screener and stored in company_market_data.quadrant — the same value every
dashboard reads. This script READS that value and layers the migration state
machine (§5.2 / §12: two consecutive month-ends before a quad change counts as
signal) on top of it.

  X = Revenue Momentum  = Fwd Rev CAGR − Trailing Rev 3Y CAGR   (company_market_data.x_rev_mom)
  Y = Earnings Momentum = Fwd EPS CAGR (capped 25%) − Trailing   (company_market_data.x_eps_mom)

  Q1 Full Compounders   X > 0, Y > 0   (EV 1 — best)
  Q2 Margin Compression X > 0, Y ≤ 0   (EV 2 — actionable)
  Q3 Full Deterioration X ≤ 0, Y ≤ 0   (EV 3 — watchlist)
  Q4 Reset/Avoid        X ≤ 0, Y > 0   (EV 4 — WORST, cost-driven EPS)

Until 2026-07-27 this script computed its OWN quad from earnings_momentum_roc
(a legacy v9.1 price/estimate rate-of-change, values like +1046%) under the
retired v9/v10 rules. That quad disagreed with the V12 canonical on ~90% of the
universe, so every run flagged nearly the whole book as migrating and flooded
quad_migration_log with hundreds of bogus rows. Reading cmd.quadrant makes this
script agree with the dashboards by construction.

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
from engines.quad import QUAD_NAME, EV_RANK

# Local display map keyed on "NA" (companies.quad_current / this script's null
# convention); engines.quad uses "N/A" for the same state.
QUAD_NAMES = {q: QUAD_NAME[q] for q in ("Q1", "Q2", "Q3", "Q4")}
QUAD_NAMES["NA"] = "Axis Incomplete"


def get_conn():
    return psycopg2.connect(settings.DATABASE_URL)


def process_ticker(company_id: str, ticker: str, quad_current: str | None,
                   quad_consec: int, conn) -> dict:
    """
    Read the canonical V12 quad from the latest company_market_data row and run
    the two-month migration state machine. Returns a result dict for printing.
    """
    cur = conn.cursor()

    # Latest market-data row that actually carries a quad. A name absent from the
    # current screener still gets a priced company_market_data row each run, but
    # with quadrant=NULL — reading the absolute-latest row would see "NA" and log a
    # spurious "migration to NA" every week. A screen exit is not a quad change
    # (§4.1: tracked, just not screened this week); the last real quad stands.
    cur.execute("""
        SELECT quadrant, x_rev_mom, x_eps_mom, data_date
        FROM company_market_data
        WHERE company_id = %s AND quadrant IS NOT NULL
        ORDER BY data_date DESC
        LIMIT 1
    """, (company_id,))
    row = cur.fetchone()

    if not row:
        cur.close()
        return {"ticker": ticker, "status": "no_data", "new_quad": "NA",
                "x": None, "y": None, "message": "never quadded (not in any screen)"}

    quadrant, x_rev, x_eps, data_date = row
    new_quad = quadrant  # guaranteed Q1–Q4 by the WHERE clause
    x = float(x_rev) if x_rev is not None else None
    y = float(x_eps) if x_eps is not None else None

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

    if new_quad == quad_current or new_quad == "NA":
        # Same quad, or no computable quad — never treat a screen exit as a change.
        result["status"] = "no_change"
        cur.close()
        return result

    # Quad changed vs the last CONFIRMED quad — run the two-month state machine.
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
        # Provisional entry from a prior run persisted a second period — confirm it.
        prior_id, consec = prior
        cur.execute("""
            UPDATE quad_migration_log
            SET consecutive_months = 2, confirmed = TRUE, pm_decision = 'PENDING'
            WHERE id = %s
        """, (prior_id,))
        cur.execute("""
            UPDATE companies
            SET quad_current = %s, quad_prior = %s,
                quad_changed_at = NOW(), quad_consecutive_months = 2
            WHERE id = %s
        """, (new_quad, quad_current, company_id))
        conn.commit()
        result["status"]    = "confirmed"
        result["confirmed"] = True
        result["message"]   = f"CONFIRMED (month 2) — was {quad_current} — PM REVIEW REQUIRED"
    else:
        # First period in the new quad — provisional, do NOT move quad_current yet.
        # earnings_momentum_roc / multiple_roc are legacy v9.1 ROC columns that no
        # longer describe the V12 axes; the axes live in company_market_data
        # (x_rev_mom, x_eps_mom) for this data_date, so leave them NULL here.
        cur.execute("""
            INSERT INTO quad_migration_log
                (company_id, ticker, from_quad, to_quad, migration_date,
                 trigger_type, consecutive_months, confirmed, pm_decision)
            VALUES (%s, %s, %s, %s, %s, 'estimate_revision', 1, FALSE, 'PENDING')
        """, (company_id, ticker, quad_current or "NA", new_quad, today))
        cur.execute("""
            UPDATE companies SET quad_consecutive_months = 1 WHERE id = %s
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

    print(f"\n  QUAD REFRESHER — {date.today()} — {len(companies)} ticker(s)")
    print("  (reads V12 quad from company_market_data; applies 2-month confirmation)\n")
    print(f"  {'Ticker':<7} {'X rev':>8}  {'Y eps':>8}  {'Quad':<5}  Status")
    print("  " + "-" * 65)

    results = []
    for company_id, ticker, quad_current, quad_consec in companies:
        r = process_ticker(str(company_id), ticker, quad_current,
                           quad_consec or 0, conn)
        results.append(r)

        # x_rev_mom / x_eps_mom are stored in percentage-point units already.
        x_str = f"{r['x']:+.1f}%" if r.get("x") is not None else "   N/A "
        y_str = f"{r['y']:+.1f}%" if r.get("y") is not None else "   N/A "
        quad_str = r["new_quad"]

        if r["status"] == "no_data":
            print(f"  {ticker:<7} {'—':>8}  {'—':>8}  {'NA':<5}  ⚪ no market data")
        elif r["status"] == "no_change":
            print(f"  {ticker:<7} {x_str:>8}  {y_str:>8}  {quad_str:<5}  (no change)")
        elif r["status"] == "provisional":
            print(f"  {ticker:<7} {x_str:>8}  {y_str:>8}  {quad_str:<5}  ⚠️  {r['message']}")
        elif r["status"] == "confirmed":
            print(f"  {ticker:<7} {x_str:>8}  {y_str:>8}  {quad_str:<5}  🚨 {r['message']}")

    # Portfolio quad distribution (from the confirmed quad_current).
    cur = conn.cursor()
    cur.execute("""
        SELECT quad_current, COUNT(*) FROM companies
        WHERE in_portfolio = TRUE AND active = TRUE
        GROUP BY quad_current
    """)
    dist = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("SELECT COUNT(*) FROM companies WHERE in_portfolio=TRUE AND active=TRUE")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()

    print(f"\n  PORTFOLIO QUAD DISTRIBUTION ({total} holdings, equal weight)")
    print(f"  {'Quad':<5}  {'Name':<24}  {'EV':>2}  {'Count':>5}  {'Weight':>7}  Alert")
    print("  " + "-" * 62)
    for q in ("Q1", "Q2", "Q3", "Q4", "NA"):
        n   = dist.get(q, 0)
        pct = n / total * 100 if total else 0
        # V12: Q3 (deterioration) and Q4 (reset/avoid) are the override buckets.
        flag = "  ⚠️  REVIEW" if q in ("Q3", "Q4") and n > 0 else ""
        ev = EV_RANK.get(q if q != "NA" else "N/A", "")
        print(f"  {q:<5}  {QUAD_NAMES[q]:<24}  {str(ev):>2}  {n:>5}  {pct:>6.1f}%{flag}")

    migrations = [r for r in results if r["status"] == "provisional"]
    confirmed  = [r for r in results if r["status"] == "confirmed"]
    no_data    = [r for r in results if r["status"] == "no_data"]

    print(f"\n  SUMMARY: {len(confirmed)} confirmed migration(s)  "
          f"{len(migrations)} provisional  {len(no_data)} no data")
    if confirmed:
        print("  🚨 Confirmed — PM decision required:")
        for r in confirmed:
            print(f"     {r['ticker']}: {r['old_quad']} → {r['new_quad']} ({QUAD_NAMES.get(r['new_quad'],'')})")


if __name__ == "__main__":
    main()
