"""
thesis_monitor.py
-----------------
Quarterly thesis integrity check for all active holdings.

Usage:
    python scripts/thesis_monitor.py
    python scripts/thesis_monitor.py --ticker AAPL
    python scripts/thesis_monitor.py --force
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

STATUS_LEVELS = ["INTACT","WATCH","REVIEW","BROKEN"]

def fetch_context(ticker: str, cur, force: bool = False) -> dict | None:
    ticker = ticker.upper()
    cur.execute("""
        SELECT c.id, c.ticker, c.company_name, c.sector, c.quad_current
        FROM companies c WHERE c.ticker = %s AND c.active = TRUE
    """, (ticker,))
    row = cur.fetchone()
    if not row:
        return None
    co = dict(zip(["id","ticker","name","sector","quad"], row))

    # Last review
    cur.execute("""
        SELECT review_date, thesis_status, what_has_changed
        FROM company_reviews WHERE company_id = %s
        ORDER BY review_date DESC LIMIT 1
    """, (co["id"],))
    last_rev = cur.fetchone()
    last_date = last_rev[0] if last_rev else (date.today() - timedelta(days=90))
    days_since = (date.today() - last_date).days if last_rev else 90

    if not force and days_since < 30:
        return {"skip": True, "ticker": ticker, "days_since": days_since}

    # Research since last review
    cur.execute("""
        SELECT source_id, content_type, research_date, ai_summary,
               thesis_impact, signal_strength, red_flags, green_flags
        FROM research_inputs
        WHERE company_id = %s AND research_date >= %s
        ORDER BY research_date DESC
    """, (co["id"], last_date))
    cols = ["source","type","date","summary","impact","strength","red","green"]
    co["research"] = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Earnings since last review
    cur.execute("""
        SELECT quarter, beat_miss_meet, guidance_change, thesis_status_post, full_notes
        FROM earnings_memos
        WHERE company_id = %s AND (earnings_date >= %s OR earnings_date IS NULL)
        ORDER BY earnings_date DESC LIMIT 4
    """, (co["id"], last_date))
    co["earnings"] = [dict(zip(["quarter","beat","guidance","thesis","notes"], r))
                       for r in cur.fetchall()]

    # Latest scores
    cur.execute("""
        SELECT
            COALESCE(p1_business_quality,   pillar_1_business_quality)   AS p1,
            COALESCE(p2_management,         pillar_2_management)         AS p2,
            COALESCE(p3_financial_strength, pillar_3_financial_strength) AS p3,
            COALESCE(composite_score_v2,    composite_score)             AS composite
        FROM company_scores WHERE company_id = %s ORDER BY score_date DESC LIMIT 1
    """, (co["id"],))
    scores_row = cur.fetchone()
    co["scores"] = dict(zip(["p1","p2","p3","composite"], scores_row)) if scores_row else {}

    # Active position
    cur.execute("""
        SELECT thesis_locked, invalidation_conditions, entry_price, entry_date
        FROM positions WHERE ticker = %s AND status = 'ACTIVE'
        ORDER BY created_at DESC LIMIT 1
    """, (ticker,))
    pos_row = cur.fetchone()
    co["position"] = dict(zip(["thesis","invalidation","entry_price","entry_date"], pos_row)) if pos_row else {}

    # Quad migrations since last review
    cur.execute("""
        SELECT from_quad, to_quad, migration_date, confirmed
        FROM quad_migration_log
        WHERE ticker = %s AND migration_date >= %s
        ORDER BY migration_date DESC
    """, (ticker, last_date))
    co["migrations"] = [dict(zip(["from","to","date","confirmed"], r)) for r in cur.fetchall()]

    co["last_review_date"] = last_date
    co["days_since"] = days_since
    return co


def build_thesis_prompt(ctx: dict) -> str:
    pos = ctx.get("position", {}) or {}
    scores = ctx.get("scores", {}) or {}

    research_block = "\n".join(
        f"  [{r['date']} {r['type']} {r['impact']}] {(r.get('summary') or '')[:200]}"
        for r in ctx.get("research", [])
    ) or "  None since last review"

    earnings_block = "\n".join(
        f"  {e['quarter']}: {e['beat']} guidance:{e['guidance']} thesis:{e['thesis']}"
        for e in ctx.get("earnings", [])
    ) or "  None since last review"

    migrations_block = "\n".join(
        f"  {m['from']}→{m['to']} on {m['date']} {'(CONFIRMED)' if m['confirmed'] else '(provisional)'}"
        for m in ctx.get("migrations", [])
    ) or "  None"

    inv = pos.get("invalidation") or []
    inv_block = "\n".join(f"  - {c}" for c in (inv if isinstance(inv, list) else [inv])) or "  None set"

    return f"""Assess thesis integrity for {ctx.get('name')} ({ctx.get('ticker')}).

THESIS: {pos.get('thesis','Not set')}
3-PILLAR SCORES: P1 Business Quality:{scores.get('p1','?')} | P2 Management:{scores.get('p2','?')} | P3 Financial Strength:{scores.get('p3','?')} | Composite:{scores.get('composite','?')}
CURRENT QUAD: {ctx.get('quad','NA')}

INVALIDATION CONDITIONS:
{inv_block}

RESEARCH SINCE LAST REVIEW ({ctx.get('days_since',90)} days):
{research_block}

EARNINGS SINCE LAST REVIEW:
{earnings_block}

QUAD MIGRATIONS:
{migrations_block}

Assess each of the 3 pillars as INTACT, WATCH, REVIEW, or BROKEN.

PILLAR ASSESSMENT CRITERIA:
- P1 Business Quality: Has moat, pricing power, gross margin, ROIC, or FCF margin deteriorated?
- P2 Management: Any concerning signals in communication, capital allocation, or insider activity?
- P3 Financial Strength: Balance sheet stress, FCF compression, margin trajectory reversal?
Also assess each invalidation condition.
Respond with ONLY this JSON (3 pillars, no P4/P5):
{{
  "p1_status":"INTACT","p1_note":"...",
  "p2_status":"INTACT","p2_note":"...",
  "p3_status":"INTACT","p3_note":"...",
  "invalidation_notes":"...",
  "quad_note":"...",
  "overall_status":"INTACT",
  "overall_reasoning":"...",
  "recommended_action":"..."
}}"""


def call_claude(prompt: str) -> dict | None:
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=1000,
            system="You are a systematic equity analyst. Return only valid JSON.",
            messages=[{"role":"user","content":prompt}]
        )
        import json
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        return json.loads(text)
    except Exception as e:
        print(f"  [Claude] Error: {e}")
        return None


def display_and_save(ctx: dict, assessment: dict, conn) -> None:
    cur = conn.cursor()
    ticker = ctx["ticker"]
    status = assessment.get("overall_status","INTACT")
    inv_note = assessment.get("invalidation_notes","No conditions triggered")

    status_icons = {"INTACT":"✅","WATCH":"⚠️ ","REVIEW":"🔴","BROKEN":"🚨"}
    pillar_labels = [("P1 Business Quality","p1"),("P2 Management","p2"),
                     ("P3 Financial Strength","p3")]

    print(f"\n  THESIS MONITOR — {ticker} — {ctx.get('name')}")
    print(f"  {'='*50}")
    print(f"  Last review: {ctx.get('days_since',0)} days ago")
    print(f"  Research inputs since: {len(ctx.get('research',[]))}")
    print(f"  Earnings memos since:  {len(ctx.get('earnings',[]))}")
    print(f"\n  PILLAR ASSESSMENT:")
    for label, key in pillar_labels:
        s = assessment.get(f"{key}_status","INTACT")
        note = assessment.get(f"{key}_note","")[:60]
        print(f"    {status_icons.get(s,'?')} {label:<25} {s:<8} — {note}")

    print(f"\n  INVALIDATION CONDITIONS CHECK:")
    print(f"    {inv_note[:120]}")

    migrations = ctx.get("migrations",[])
    if migrations:
        print(f"\n  QUAD MIGRATIONS: {assessment.get('quad_note','')}")
    else:
        print(f"\n  QUAD: {ctx.get('quad','NA')} — no migration in review period")

    overall_icon = status_icons.get(status,"?")
    print(f"\n  OVERALL STATUS: {overall_icon} {status}")
    print(f"  ACTION: {assessment.get('recommended_action','')}")

    # Write to company_reviews
    cur.execute("""
        SELECT id FROM companies WHERE ticker=%s
    """, (ticker,))
    co_row = cur.fetchone()
    if co_row:
        cur.execute("""
            INSERT INTO company_reviews (
                company_id, ticker, review_date, review_type,
                thesis_status, what_has_changed, action_taken, next_review_date
            ) VALUES (%s,%s,%s,'QUARTERLY',%s,%s,'NO_CHANGE',
                      CURRENT_DATE + INTERVAL '30 days')
        """, (co_row[0], ticker, date.today(), status,
              assessment.get("overall_reasoning","")[:500]))

        # Fire trigger if REVIEW or BROKEN
        if status in ("REVIEW","BROKEN"):
            cur.execute("""
                INSERT INTO triggers (ticker, company_id, trigger_type, trigger_action,
                    trigger_condition)
                VALUES (%s,%s,'invalidation','REVIEW',%s)
            """, (ticker, co_row[0], f"Thesis monitor: {status} — {assessment.get('recommended_action','')}"))

    # Obsidian note
    today = date.today().strftime("%Y-%m-%d")
    note_dir = ROOT / "Quarterly-Reviews"
    note_dir.mkdir(exist_ok=True)
    note_path = note_dir / f"{today}_{ticker}_thesis_review.md"
    with open(note_path, "w", encoding="utf-8") as f:
        f.write(f"""---
ticker: "{ticker}"
company: "{ctx.get('name','')}"
review_type: "quarterly"
date: {today}
prior_review_date: "{ctx.get('last_review_date','')}"
tags: [thesis-review, quarterly]
---

## Thesis Status: {status}

{assessment.get('overall_reasoning','')}

## Pillar Assessment
""")
        for label, key in pillar_labels:
            s = assessment.get(f"{key}_status","INTACT")
            note = assessment.get(f"{key}_note","")
            f.write(f"\n### {label}\n**Status:** {s}\n{note}\n")
        f.write(f"\n## Action\n{assessment.get('recommended_action','')}\n")

    conn.commit()
    cur.close()
    print(f"\n  [Saved] Review written to DB + {note_path.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str)
    parser.add_argument("--force",  action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    conn.autocommit = False
    cur  = conn.cursor()

    if args.ticker:
        tickers = [args.ticker.upper()]
    else:
        cur.execute("SELECT ticker FROM companies WHERE in_portfolio=TRUE AND active=TRUE ORDER BY ticker")
        tickers = [r[0] for r in cur.fetchall()]

    print(f"\n  THESIS MONITOR — {date.today()} — {len(tickers)} holding(s)\n")

    for ticker in tickers:
        ctx = fetch_context(ticker, cur, force=args.force)
        if not ctx:
            print(f"  ⚪ {ticker}: not found")
            continue
        if ctx.get("skip"):
            print(f"  ⏭  {ticker}: reviewed {ctx['days_since']} days ago (use --force to override)")
            continue
        print(f"  Assessing {ticker} ({ctx.get('name','')})...")
        prompt = build_thesis_prompt(ctx)
        assessment = call_claude(prompt)
        if not assessment:
            print(f"  ❌ {ticker}: Claude assessment failed")
            continue
        display_and_save(ctx, assessment, conn)

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
