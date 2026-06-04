"""
earnings_tracker.py
-------------------
Tracks earnings calendar for all holdings and watchlist.

Usage:
    python scripts/earnings_tracker.py
    python scripts/earnings_tracker.py --pre AAPL
    python scripts/earnings_tracker.py --post AAPL Q2-2026
    python scripts/earnings_tracker.py --calendar
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, date, timedelta

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
import anthropic
from config.settings import settings

MODEL = "claude-sonnet-4-5"

def get_conn():
    return psycopg2.connect(settings.DATABASE_URL)


def get_upcoming_earnings(days: int, cur) -> list[dict]:
    end = date.today() + timedelta(days=days)
    cur.execute("""
        SELECT c.ticker, c.company_name, cmd.next_earnings_date,
               c.in_portfolio, c.on_watchlist
        FROM company_market_data cmd
        JOIN companies c ON c.id = cmd.company_id
        WHERE cmd.next_earnings_date BETWEEN CURRENT_DATE AND %s
          AND (c.in_portfolio=TRUE OR c.on_watchlist=TRUE)
          AND cmd.data_date = (
              SELECT MAX(data_date) FROM company_market_data WHERE company_id=cmd.company_id
          )
        ORDER BY cmd.next_earnings_date
    """, (end,))
    return [dict(zip(["ticker","name","date","in_portfolio","on_watchlist"], r))
            for r in cur.fetchall()]


def has_pre_memo(ticker: str, quarter: str, cur) -> bool:
    cur.execute("""
        SELECT pre_completed FROM earnings_memos
        WHERE ticker=%s AND quarter=%s ORDER BY created_at DESC LIMIT 1
    """, (ticker.upper(), quarter))
    row = cur.fetchone()
    return bool(row and row[0])


def current_quarter() -> str:
    today = date.today()
    q = (today.month - 1) // 3 + 1
    return f"Q{q}-{today.year}"


def show_calendar(days: int = 30, cur = None):
    earnings = get_upcoming_earnings(days, cur)
    no_earnings = []

    cur.execute("""
        SELECT c.ticker FROM companies c
        LEFT JOIN company_market_data cmd ON cmd.company_id=c.id
          AND cmd.data_date=(SELECT MAX(data_date) FROM company_market_data WHERE company_id=c.id)
        WHERE c.in_portfolio=TRUE AND c.active=TRUE
          AND (cmd.next_earnings_date IS NULL OR cmd.next_earnings_date > CURRENT_DATE + %s)
        ORDER BY c.ticker
    """, (timedelta(days=days),))
    no_earnings = [r[0] for r in cur.fetchall()]

    print(f"\n  EARNINGS CALENDAR — Next {days} Days")
    print(f"  {'='*56}")

    if not earnings:
        print(f"  No earnings in next {days} days for holdings/watchlist.")
    else:
        last_label = None
        for e in earnings:
            days_away = (e["date"] - date.today()).days
            quarter = current_quarter()
            has_pre = has_pre_memo(e["ticker"], quarter, cur)
            pre_tag = "✅ EXISTS" if has_pre else "⚠️  MISSING — run --pre now"

            if days_away == 0:
                label = "TODAY"
            elif days_away == 1:
                label = "TOMORROW"
            else:
                label = f"IN {days_away} DAYS ({e['date'].strftime('%b %d')})"

            if label != last_label:
                print(f"\n  {label}")
                last_label = label

            icon = "⚡" if days_away == 0 else "📅"
            portfolio_flag = " [HELD]" if e["in_portfolio"] else " [watchlist]"
            print(f"    {icon} {e['ticker']:<6} {e['name'][:30]:<30}{portfolio_flag}")
            print(f"         Pre-earnings note: {pre_tag}")

    if no_earnings:
        print(f"\n  No earnings next {days} days:")
        print(f"    {', '.join(no_earnings)}")
    print(f"\n  {'='*56}")


def run_pre_earnings(ticker: str, conn):
    cur = conn.cursor()
    ticker = ticker.upper()
    quarter = current_quarter()

    cur.execute("SELECT id, company_name FROM companies WHERE ticker=%s", (ticker,))
    row = cur.fetchone()
    if not row:
        print(f"  ❌ {ticker} not found"); cur.close(); return
    company_id, name = row

    # Check if already exists
    if has_pre_memo(ticker, quarter, cur):
        print(f"  ℹ️  Pre-earnings memo for {ticker} {quarter} already exists.")
        overwrite = input("  Overwrite? (y/n): ").strip().lower()
        if overwrite != "y":
            cur.close(); return

    # Fetch context
    cur.execute("""
        SELECT thesis_locked FROM positions WHERE ticker=%s AND status='ACTIVE'
        ORDER BY created_at DESC LIMIT 1
    """, (ticker,))
    pos = cur.fetchone()
    thesis = pos[0] if pos else "No active position thesis"

    cur.execute("""
        SELECT quarter, beat_miss_meet, guidance_change, thesis_status_post, full_notes
        FROM earnings_memos WHERE ticker=%s AND post_completed=TRUE
        ORDER BY earnings_date DESC LIMIT 2
    """, (ticker,))
    prior_earnings = cur.fetchall()

    # Ask Claude for what to watch
    prior_block = "\n".join(
        f"  {r[0]}: {r[1]} guidance:{r[2]} thesis:{r[3]}"
        for r in prior_earnings
    ) or "  No prior earnings memos"

    print(f"  Generating pre-earnings setup for {ticker} {quarter}...")
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=MODEL, max_tokens=600,
        system="You are an equity analyst preparing for an earnings call.",
        messages=[{"role":"user","content":
            f"For {name} ({ticker}) Q earnings:\nThesis: {thesis}\nPrior earnings:\n{prior_block}\n\n"
            f"List 5 specific things to watch for that would STRENGTHEN or WEAKEN the thesis. "
            f"Be specific to this company. Format as a simple numbered list."}]
    )
    suggestions = resp.content[0].text.strip()

    print(f"\n  SUGGESTED THINGS TO WATCH ({ticker} {quarter}):\n{suggestions}\n")

    rev_est  = input("  Revenue estimate ($M): ").strip()
    eps_est  = input("  EPS estimate ($): ").strip()

    try:
        rev_f = float(rev_est) if rev_est else None
        eps_f = float(eps_est) if eps_est else None
    except ValueError:
        rev_f = eps_f = None

    watch_items = []
    print("  Add items to watch (blank line to finish):")
    while True:
        item = input("  > ").strip()
        if not item: break
        watch_items.append(item)

    # Write to earnings_memos
    cur.execute("""
        INSERT INTO earnings_memos (company_id, ticker, quarter, earnings_date,
            revenue_estimate, eps_estimate, key_things_watching, pre_completed, pre_completed_at)
        VALUES (%s,%s,%s,NULL,%s,%s,%s,TRUE,NOW())
        ON CONFLICT DO NOTHING
    """, (company_id, ticker, quarter, rev_f, eps_f, watch_items or None))
    conn.commit()

    # Obsidian note
    today = date.today().strftime("%Y-%m-%d")
    note_dir = ROOT / "Earnings"
    note_dir.mkdir(exist_ok=True)
    note_path = note_dir / f"{today}_{ticker}_{quarter}_pre_earnings.md"
    with open(note_path, "w", encoding="utf-8") as f:
        f.write(f"""---
ticker: "{ticker}"
company: "{name}"
source_id: "earnings_transcripts"
content_type: "earnings_call"
quarter: "{quarter}"
date: {today}
thesis_impact: "neutral"
signal_strength: "high"
tags: [earnings, pre-earnings]
---

## Pre-Earnings Setup — {quarter}

**Revenue Estimate:** {rev_est or '—'}
**EPS Estimate:** {eps_est or '—'}

## Key Things Watching
{chr(10).join(f'- {w}' for w in watch_items) if watch_items else '- '}

## AI Suggested Watch Items
{suggestions}

## What would STRENGTHEN the thesis
<!-- Fill in before the call -->

## What would WEAKEN the thesis
<!-- Fill in before the call -->

---
## Post-Earnings Results
<!-- Fill in after the call -->
""")

    cur.close()
    print(f"  ✅ Pre-earnings memo saved: {note_path.name}")


def run_post_earnings(ticker: str, quarter: str, conn):
    cur = conn.cursor()
    ticker = ticker.upper()

    cur.execute("SELECT id, company_name FROM companies WHERE ticker=%s", (ticker,))
    row = cur.fetchone()
    if not row:
        print(f"  ❌ {ticker} not found"); cur.close(); return
    company_id, name = row

    cur.execute("""
        SELECT id, revenue_estimate, eps_estimate, key_things_watching
        FROM earnings_memos WHERE ticker=%s AND quarter=%s
        ORDER BY created_at DESC LIMIT 1
    """, (ticker, quarter))
    pre = cur.fetchone()

    print(f"\n  POST-EARNINGS ASSESSMENT — {ticker} {quarter}")
    if pre:
        print(f"  Pre-note: rev est ${pre[1]}M  EPS est ${pre[2]}")
        print(f"  Watching: {pre[3]}")
    else:
        print(f"  ⚠️  No pre-earnings note found")

    try:
        rev_actual = float(input("  Revenue actual ($M): ").strip())
        eps_actual = float(input("  EPS actual ($): ").strip())
    except ValueError:
        rev_actual = eps_actual = None

    beat_miss = input("  Beat/Miss/Meet (BEAT/MISS/MEET): ").strip().upper()
    if beat_miss not in ("BEAT","MISS","MEET"): beat_miss = "MEET"

    guidance = input("  Guidance change (RAISED/MAINTAINED/LOWERED/WITHDRAWN/NONE): ").strip().upper()
    if guidance not in ("RAISED","MAINTAINED","LOWERED","WITHDRAWN","NONE"): guidance = "MAINTAINED"

    demand = input("  Demand commentary (POSITIVE/NEUTRAL/CAUTIOUS): ").strip().upper()
    if demand not in ("POSITIVE","NEUTRAL","CAUTIOUS"): demand = "NEUTRAL"

    margins = input("  Margin trajectory (EXPANDING/STABLE/COMPRESSING): ").strip().upper()
    if margins not in ("EXPANDING","STABLE","COMPRESSING"): margins = "STABLE"

    capex = input("  Capex signal (INCREASING/STABLE/DECREASING): ").strip().upper()
    if capex not in ("INCREASING","STABLE","DECREASING"): capex = "STABLE"

    tone = input("  Management tone vs prior (IMPROVED/UNCHANGED/DETERIORATED): ").strip().upper()
    if tone not in ("IMPROVED","UNCHANGED","DETERIORATED"): tone = "UNCHANGED"

    notes = input("  Full notes (optional): ").strip()

    # Claude thesis assessment
    print("  Assessing thesis impact...")
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    pre_context = f"Pre-expectations: rev ${pre[1]}M, EPS ${pre[2]}, watching: {pre[3]}" if pre else "No pre-note"
    resp = client.messages.create(
        model=MODEL, max_tokens=500,
        system="You are an equity analyst doing post-earnings assessment.",
        messages=[{"role":"user","content":
            f"{name} ({ticker}) {quarter} results:\n{pre_context}\n"
            f"Actual: rev ${rev_actual}M EPS ${eps_actual} — {beat_miss}\n"
            f"Guidance:{guidance} Demand:{demand} Margins:{margins} Capex:{capex} Tone:{tone}\n\n"
            f"Assess thesis status as INTACT/WATCH/WEAKENED/BROKEN and suggest action ADD/HOLD/TRIM/REVIEW/EXIT. "
            f"Format: STATUS: [status]\nACTION: [action]\nRATIONALE: [2 sentences]"}]
    )
    assessment = resp.content[0].text.strip()
    print(f"\n  Claude assessment:\n  {assessment}\n")

    thesis_status = "INTACT"
    action = "HOLD"
    for line in assessment.split("\n"):
        if line.startswith("STATUS:"):
            s = line.split(":",1)[1].strip().upper()
            if s in ("INTACT","WATCH","WEAKENED","BROKEN"): thesis_status = s
        if line.startswith("ACTION:"):
            a = line.split(":",1)[1].strip().upper()
            if a in ("ADD","HOLD","TRIM","REVIEW","EXIT"): action = a

    confirm = input(f"  Accept assessment? thesis:{thesis_status} action:{action} (y/n): ").strip().lower()
    if confirm == "n":
        thesis_status = input("  Thesis status: ").strip().upper()
        action        = input("  Action: ").strip().upper()

    # Write post-earnings
    memo_id = pre[0] if pre else None
    if memo_id:
        cur.execute("""
            UPDATE earnings_memos SET
                revenue_actual=%s, eps_actual=%s, beat_miss_meet=%s,
                guidance_change=%s, demand_commentary=%s, margin_trajectory=%s,
                capex_signal=%s, management_tone_vs_prior=%s,
                thesis_status_post=%s, action_implication=%s,
                full_notes=%s, post_completed=TRUE, post_completed_at=NOW()
            WHERE id=%s
        """, (rev_actual, eps_actual, beat_miss, guidance, demand, margins,
              capex, tone, thesis_status, action, notes or assessment, memo_id))
    else:
        cur.execute("""
            INSERT INTO earnings_memos (company_id, ticker, quarter,
                revenue_actual, eps_actual, beat_miss_meet, guidance_change,
                demand_commentary, margin_trajectory, capex_signal,
                management_tone_vs_prior, thesis_status_post, action_implication,
                full_notes, post_completed, post_completed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,NOW())
        """, (company_id, ticker, quarter, rev_actual, eps_actual, beat_miss,
              guidance, demand, margins, capex, tone, thesis_status, action,
              notes or assessment))

    if thesis_status in ("WATCH","WEAKENED","BROKEN"):
        cur.execute("""
            INSERT INTO triggers (ticker, company_id, trigger_type, trigger_action, trigger_condition)
            VALUES (%s,%s,'invalidation','REVIEW',%s)
        """, (ticker, company_id, f"Post-earnings: thesis {thesis_status} — run thesis_monitor.py"))
        print(f"  ⚠️  Thesis alert trigger created — consider running: python scripts/thesis_monitor.py --ticker {ticker}")

    conn.commit()
    cur.close()
    print(f"  ✅ Post-earnings assessment saved for {ticker} {quarter}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pre",      type=str)
    parser.add_argument("--post",     nargs=2, metavar=("TICKER","QUARTER"))
    parser.add_argument("--calendar", action="store_true")
    parser.add_argument("--days",     type=int, default=30)
    args = parser.parse_args()

    conn = get_conn()
    conn.autocommit = False
    cur  = conn.cursor()

    try:
        if args.pre:
            run_pre_earnings(args.pre.upper(), conn)
        elif args.post:
            run_post_earnings(args.post[0].upper(), args.post[1], conn)
        else:
            show_calendar(args.days, cur)
    except Exception as e:
        conn.rollback()
        print(f"  ❌ Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
