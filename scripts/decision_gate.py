"""
decision_gate.py
----------------
Pre-trade checklist enforcement for all position decisions.

Usage:
    python scripts/decision_gate.py --initiate AAPL
    python scripts/decision_gate.py --trim AAPL
    python scripts/decision_gate.py --exit AAPL
    python scripts/decision_gate.py --review AAPL
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
from config.settings import settings

def get_conn():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    return conn

SECTOR_CAP = 28.0

def get_company(ticker: str, cur) -> dict | None:
    cur.execute("""
        SELECT c.id, c.ticker, c.company_name, c.sector, c.is_discretionary,
               c.quad_current, c.in_portfolio,
               COALESCE(cs.composite_score_v2, cs.composite_score) AS composite,
               COALESCE(cs.p2_management,         cs.pillar_2_management)         AS p2,
               COALESCE(cs.p3_financial_strength, cs.pillar_3_financial_strength) AS p3,
               cs.tier_classification, cs.score_date
        FROM companies c
        LEFT JOIN LATERAL (
            SELECT composite_score_v2, composite_score,
                   p2_management, pillar_2_management,
                   p3_financial_strength, pillar_3_financial_strength,
                   tier_classification, score_date
            FROM company_scores WHERE company_id = c.id
            ORDER BY score_date DESC LIMIT 1
        ) cs ON TRUE
        WHERE c.ticker = %s
    """, (ticker.upper(),))
    row = cur.fetchone()
    if not row:
        return None
    return dict(zip(["id","ticker","name","sector","is_discretionary","quad",
                      "in_portfolio","composite","p2","p3","tier","score_date"], row))

def get_sector_pct(sector: str, cur) -> float:
    cur.execute("""
        SELECT ROUND(COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (), 0), 1)
        FROM companies WHERE in_portfolio=TRUE AND active=TRUE AND sector = %s
        GROUP BY sector
    """, (sector,))
    row = cur.fetchone()
    return float(row[0]) if row else 0.0

def get_active_positions_count(cur) -> int:
    cur.execute("SELECT COUNT(*) FROM positions WHERE status='ACTIVE'")
    return cur.fetchone()[0]

def get_sma_status(ticker: str, cur) -> str:
    cur.execute("""
        SELECT current_price, sma_200 FROM company_market_data
        WHERE ticker=%s ORDER BY data_date DESC LIMIT 1
    """, (ticker,))
    row = cur.fetchone()
    if not row or not row[1]:
        return "UNKNOWN (no SMA data)"
    price, sma200 = float(row[0] or 0), float(row[1])
    return "ABOVE" if price > sma200 else "BELOW"

def get_active_position(ticker: str, cur) -> dict | None:
    cur.execute("""
        SELECT id, trade_id, thesis_locked, why_it_compounds, invalidation_conditions,
               entry_price, entry_date, status, target_allocation_pct, is_discretionary
        FROM positions WHERE ticker=%s AND status='ACTIVE'
        ORDER BY created_at DESC LIMIT 1
    """, (ticker.upper(),))
    row = cur.fetchone()
    if not row:
        return None
    return dict(zip(["id","trade_id","thesis","why","invalidation","entry_price",
                      "entry_date","status","target_pct","is_disc"], row))

def next_trade_id(cur) -> str:
    cur.execute("SELECT COUNT(*) FROM positions")
    n = cur.fetchone()[0] + 1
    return f"TRD-IC-{date.today().year}-{n:04d}"

def run_initiate_gate(ticker: str, conn):
    cur = conn.cursor()
    co  = get_company(ticker, cur)
    if not co:
        print(f"  ❌ {ticker} not found in companies table")
        cur.close(); return

    n_holdings  = get_active_positions_count(cur)
    new_target  = round(1.0 / (n_holdings + 1), 4)
    sector_pct  = get_sector_pct(co.get("sector",""), cur) if co.get("sector") else 0
    sma_status  = get_sma_status(ticker, cur)

    print(f"\n  DECISION GATE — INITIATE — {ticker}")
    print(f"  {'='*50}")

    # Hard rules
    composite   = float(co.get("composite") or 0)
    p2          = float(co.get("p2") or 0)
    p3          = float(co.get("p3") or 0)
    score_date  = co.get("score_date")

    score_ok    = composite >= 6.5
    p2_ok       = p2 >= 6.0
    p3_ok       = p3 >= 6.0
    sector_ok   = sector_pct <= SECTOR_CAP
    has_score   = composite > 0

    # 3-pillar hard rules
    quad    = co.get("quad") or "NA"
    quad_ok_init = quad not in ("Q3",)

    print(f"\n  HARD RULES (v2 — 3-pillar) — any fail = blocked:")
    print(f"    {'✅' if score_ok  else '❌'} Composite ≥ 6.5 (v2):           "
          f"{composite:.2f} — {'PASS' if score_ok else 'FAIL'}" + (" — NO SCORE YET" if not has_score else ""))
    print(f"    {'✅' if p2_ok    else '❌'} P2 Management ≥ 6.0:             {p2:.1f} — {'PASS' if p2_ok else 'FAIL'}")
    print(f"    {'✅' if p3_ok    else '❌'} P3 Financial Strength ≥ 6.0:     {p3:.1f} — {'PASS' if p3_ok else 'FAIL'}")
    print(f"    {'✅' if sector_ok else '❌'} {co.get('sector','?')} Sector ≤ {SECTOR_CAP}%:  "
          f"{sector_pct:.1f}% — {'PASS' if sector_ok else 'FAIL — BLOCKED'}")
    print(f"    {'✅' if quad_ok_init else '⚠️ '} Quad not Q3:                     {quad} — {'PASS' if quad_ok_init else 'WARN (override req.)'}")

    print(f"\n  POSITION SIZING:")
    print(f"    Current holdings:   {n_holdings}")
    print(f"    New target weight:  1/{n_holdings+1} = {new_target*100:.2f}%")
    print(f"    All existing positions rebalance to {new_target*100:.2f}%")

    print(f"\n  QUAD CHECK:")
    quad = co.get("quad") or "NA"
    quad_ok = quad in ("Q1","Q2")
    print(f"    Current quad: {quad}  {'✅ (Q1/Q2 preferred)' if quad_ok else '⚠️  (Q3/Q4 — elevated risk)'}")
    print(f"    L2 trend filter: Price vs 200d SMA — {sma_status}")

    print(f"\n  THESIS REQUIREMENTS:")
    print(f"    Thesis locked:              ⚠️  Required before approval")
    print(f"    Invalidation conditions:    ⚠️  Required before approval")
    print(f"    Why it compounds:           ⚠️  Required before approval")

    # Discretionary override required
    if co.get("is_discretionary"):
        print(f"\n  ⚠️  DISCRETIONARY POSITION — override documentation required")

    hard_pass = score_ok and p2_ok and p3_ok and sector_ok and quad_ok_init
    if not hard_pass:
        print(f"\n  HARD RULE VIOLATION — initiation blocked.")
        override = input("  Type OVERRIDE to document an exception, or Enter to abort: ").strip()
        if override.upper() != "OVERRIDE":
            print("  Aborted.")
            cur.close(); return
        override_reason = input("  Override rationale (required): ").strip()
        if not override_reason:
            print("  No rationale provided. Aborted.")
            cur.close(); return
    else:
        override_reason = None

    print(f"\n  All hard rules {'passed' if hard_pass else 'overridden'}. Enter position details:")
    thesis    = input("  Thesis statement: ").strip()
    why       = input("  Why it compounds: ").strip()
    print("  Invalidation conditions (one per line, blank to finish):")
    inv_conditions = []
    while True:
        line = input("    > ").strip()
        if not line:
            break
        inv_conditions.append(line)

    try:
        entry_price = float(input("  Entry price ($): ").strip())
    except ValueError:
        entry_price = None

    trade_id = next_trade_id(cur)
    company_id = co["id"]

    print(f"\n  Creating position {trade_id}...")

    # Write positions
    cur.execute("""
        INSERT INTO positions (
            trade_id, company_id, ticker,
            target_allocation_pct, n_holdings_at_entry,
            is_discretionary, composite_score_at_entry,
            quad_at_entry, thesis_locked, thesis_locked_at,
            why_it_compounds, invalidation_conditions,
            entry_price, entry_date, status,
            override_applied, override_reason,
            mandatory_review_date
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s,%s,%s,%s,'ACTIVE',%s,%s,
                  CURRENT_DATE + INTERVAL '90 days')
    """, (
        trade_id, company_id, ticker.upper(),
        new_target, n_holdings + 1,
        bool(co.get("is_discretionary")),
        co.get("composite"), co.get("quad"),
        thesis, why, inv_conditions,
        entry_price, date.today(),
        bool(override_reason), override_reason,
    ))

    # Decision log
    cur.execute("""
        INSERT INTO decision_log (ticker, company_id, decision_type, decision_rationale,
            composite_score_at_decision, quad_at_decision, allocation_after_pct,
            n_holdings_at_decision, override_applied, override_reason, override_rule)
        VALUES (%s,%s,'INITIATE',%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        ticker.upper(), company_id, thesis,
        co.get("composite"), co.get("quad"),
        new_target, n_holdings + 1,
        bool(override_reason), override_reason,
        "SECTOR_CAP" if not sector_ok else None,
    ))

    # Rebalance log for all existing positions
    cur.execute("SELECT id, ticker FROM positions WHERE status='ACTIVE' AND ticker != %s",
                (ticker.upper(),))
    existing = cur.fetchall()
    for pos_id, pos_ticker in existing:
        cur.execute("""
            INSERT INTO position_rebalance_log
                (position_id, ticker, event_date, event_type, n_holdings_at_event,
                 target_allocation_pct, notes)
            VALUES (%s,%s,%s,'REBALANCE',%s,%s,'New position initiated — all weights reset to 1/N')
        """, (pos_id, pos_ticker, date.today(), n_holdings + 1, new_target))

    # Standard triggers
    for ttype, taction, cond in [
        ("score_floor_breach", "REVIEW", f"Composite score falls below 6.5"),
        ("quad_migration_confirmed", "REVIEW", f"Confirmed migration to Q3 or Q4"),
        ("time_based", "REVIEW", f"Mandatory 90-day thesis review"),
    ]:
        cur.execute("""
            INSERT INTO triggers (ticker, company_id, trigger_type, trigger_action,
                trigger_condition, expires_at)
            SELECT %s, %s, %s, %s, %s, CURRENT_DATE + INTERVAL '90 days'
        """, (ticker.upper(), company_id, ttype, taction, cond))

    conn.commit()
    cur.close()
    print(f"  ✅ Position {trade_id} created. {n_holdings+1} total holdings, target weight {new_target*100:.2f}%")


def run_trim_gate(ticker: str, conn):
    cur = conn.cursor()
    pos = get_active_position(ticker, cur)
    if not pos:
        print(f"  ❌ No active position found for {ticker}")
        cur.close(); return

    co = get_company(ticker, cur)
    print(f"\n  DECISION GATE — TRIM — {ticker}")
    print(f"  Active position: {pos['trade_id']}  entry ${pos.get('entry_price','?')} on {pos.get('entry_date','?')}")

    if co and co.get("is_discretionary"):
        print("  ⚠️  DISCRETIONARY — override documentation required")
        ovr = input("  Override rationale: ").strip()
    else:
        ovr = None

    rationale = input("  Trim rationale: ").strip()
    new_target_pct = None
    try:
        new_target_pct = float(input("  New target weight % (or Enter to skip): ").strip() or "0") / 100 or None
    except ValueError:
        pass

    cur.execute("""
        INSERT INTO decision_log (ticker, decision_type, decision_rationale,
            quad_at_decision, override_applied, override_reason)
        VALUES (%s,'TRIM',%s,%s,%s,%s)
    """, (ticker.upper(), rationale, co.get("quad") if co else None, bool(ovr), ovr))

    if new_target_pct:
        cur.execute("UPDATE positions SET target_allocation_pct=%s WHERE id=%s",
                    (new_target_pct, pos["id"]))

    conn.commit()
    cur.close()
    print(f"  ✅ TRIM logged for {ticker}")


def run_exit_gate(ticker: str, conn):
    cur = conn.cursor()
    pos = get_active_position(ticker, cur)
    if not pos:
        print(f"  ❌ No active position found for {ticker}")
        cur.close(); return

    co = get_company(ticker, cur)
    print(f"\n  DECISION GATE — EXIT — {ticker}")
    print(f"  Active position: {pos['trade_id']}")

    rationale  = input("  Exit rationale: ").strip()
    try:
        exit_price = float(input("  Exit price ($): ").strip())
    except ValueError:
        exit_price = None

    entry  = float(pos.get("entry_price") or 0)
    pnl    = ((exit_price - entry) / entry) if (exit_price and entry) else None

    thesis_integrity = input("  Thesis integrity at exit (INTACT/PARTIALLY_BROKEN/BROKEN): ").strip().upper()
    if thesis_integrity not in ("INTACT","PARTIALLY_BROKEN","BROKEN"):
        thesis_integrity = "INTACT"

    went_right = input("  What went right: ").strip()
    went_wrong = input("  What went wrong: ").strip()
    lesson     = input("  Key lesson: ").strip()

    holding_days = (date.today() - pos["entry_date"]).days if pos.get("entry_date") else None

    cur.execute("""
        UPDATE positions SET status='CLOSED', exit_date=%s, exit_price=%s,
               exit_reason=%s, pnl_pct=%s, thesis_integrity_at_exit=%s,
               holding_days=%s WHERE id=%s
    """, (date.today(), exit_price, rationale, pnl, thesis_integrity, holding_days, pos["id"]))

    cur.execute("""
        INSERT INTO exit_journal (position_id, ticker, exit_date, holding_days,
            pnl_pct, thesis_integrity_at_exit, what_went_right, what_went_wrong, key_lesson)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (pos["id"], ticker.upper(), date.today(), holding_days,
          pnl, thesis_integrity, went_right, went_wrong, lesson))

    cur.execute("""
        INSERT INTO decision_log (ticker, decision_type, decision_rationale,
            quad_at_decision, allocation_before_pct, allocation_after_pct)
        VALUES (%s,'EXIT',%s,%s,%s,0)
    """, (ticker.upper(), rationale, co.get("quad") if co else None,
          float(pos.get("target_pct") or 0)))

    conn.commit()
    cur.close()
    print(f"  ✅ EXIT logged for {ticker}  P&L: {f'{pnl*100:+.1f}%' if pnl else 'N/A'}  "
          f"Thesis: {thesis_integrity}")


def run_review_gate(ticker: str, conn):
    cur = conn.cursor()
    co = get_company(ticker, cur)
    if not co:
        print(f"  ❌ {ticker} not found")
        cur.close(); return

    composite   = float(co.get("composite") or 0)
    p2          = float(co.get("p2") or 0)
    p3          = float(co.get("p3") or 0)
    sector_pct  = get_sector_pct(co.get("sector",""), cur)
    n_holdings  = get_active_positions_count(cur)
    new_target  = round(1.0 / (n_holdings + 1), 4)
    sma_status  = get_sma_status(ticker, cur)

    print(f"\n  WATCHLIST → PORTFOLIO REVIEW — {ticker} — {co.get('name')}")
    print(f"  {'='*50}")
    print(f"\n  Composite score:   {composite:.1f} / 10")
    print(f"  P2 Management:     {p2:.1f}  {'✅' if p2>=6 else '❌'}")
    print(f"  P3 Financial:      {p3:.1f}  {'✅' if p3>=6 else '❌'}")
    print(f"  Sector weight:     {sector_pct:.1f}%  {'✅' if sector_pct<=28 else '⚠️ '}")
    print(f"  Quad:              {co.get('quad','NA')}")
    print(f"  200d SMA:          {sma_status}")
    print(f"  If initiated:      {n_holdings+1} holdings @ {new_target*100:.2f}% each")

    ready = composite >= 6.5 and p2 >= 6.0 and p3 >= 6.0
    print(f"\n  {'✅ ELIGIBLE for initiation' if ready else '⚠️  NOT YET ELIGIBLE — gaps above'}")
    if ready:
        go = input("  Proceed to initiate? (y/n): ").strip().lower()
        if go == "y":
            cur.close()
            run_initiate_gate(ticker, conn)
            return

    cur.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--initiate", type=str)
    parser.add_argument("--trim",     type=str)
    parser.add_argument("--exit",     type=str)
    parser.add_argument("--review",   type=str)
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.initiate:
            run_initiate_gate(args.initiate.upper(), conn)
        elif args.trim:
            run_trim_gate(args.trim.upper(), conn)
        elif args.exit:
            run_exit_gate(args.exit.upper(), conn)
        elif args.review:
            run_review_gate(args.review.upper(), conn)
        else:
            parser.print_help()
    except Exception as e:
        conn.rollback()
        print(f"  ❌ Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
