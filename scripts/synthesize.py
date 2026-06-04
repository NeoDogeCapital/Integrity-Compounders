"""
synthesize.py
-------------
Weekly portfolio synthesis. Summarizes new research and drafts weekly memo.

Usage:
    python scripts/synthesize.py
    python scripts/synthesize.py --since 7
    python scripts/synthesize.py --html
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
NAVY  = "#1F3A5F"
GOLD  = "#C9A84C"

def get_conn():
    return psycopg2.connect(settings.DATABASE_URL)


def fetch_weekly_data(since_days: int, cur) -> dict:
    since = date.today() - timedelta(days=since_days)
    data  = {}

    # New research inputs
    cur.execute("""
        SELECT c.ticker, ri.content_type, ri.research_date, ri.ai_summary,
               ri.thesis_impact, ri.signal_strength
        FROM research_inputs ri JOIN companies c ON c.id=ri.company_id
        WHERE ri.research_date >= %s ORDER BY ri.research_date DESC LIMIT 30
    """, (since,))
    data["research"] = [dict(zip(["ticker","type","date","summary","impact","strength"], r))
                        for r in cur.fetchall()]

    # Completed earnings memos
    cur.execute("""
        SELECT ticker, quarter, beat_miss_meet, guidance_change, thesis_status_post
        FROM earnings_memos
        WHERE post_completed=TRUE AND post_completed_at >= %s
        ORDER BY post_completed_at DESC
    """, (since,))
    data["earnings"] = [dict(zip(["ticker","quarter","beat","guidance","thesis"], r))
                        for r in cur.fetchall()]

    # Quad migrations
    cur.execute("""
        SELECT ticker, from_quad, to_quad, migration_date, confirmed
        FROM quad_migration_log WHERE migration_date >= %s ORDER BY migration_date DESC
    """, (since,))
    data["migrations"] = [dict(zip(["ticker","from","to","date","confirmed"], r))
                          for r in cur.fetchall()]

    # Active concerns
    cur.execute("""
        SELECT DISTINCT ON (cr.company_id) c.ticker, c.company_name, cr.thesis_status, cr.review_date
        FROM company_reviews cr JOIN companies c ON c.id=cr.company_id
        WHERE cr.thesis_status IN ('WATCH','REVIEW','BROKEN') AND c.in_portfolio=TRUE
        ORDER BY cr.company_id, cr.review_date DESC
    """)
    data["concerns"] = [dict(zip(["ticker","name","status","date"], r)) for r in cur.fetchall()]

    # Watchlist approaching
    cur.execute("""
        SELECT ticker, company_name, status, current_composite_score, why_watching
        FROM watchlist WHERE status IN ('APPROACHING','READY')
        ORDER BY current_composite_score DESC NULLS LAST
    """)
    data["watchlist"] = [dict(zip(["ticker","name","status","score","why"], r))
                         for r in cur.fetchall()]

    # Upcoming earnings (14 days)
    cur.execute("""
        SELECT c.ticker, c.company_name, cmd.next_earnings_date
        FROM company_market_data cmd JOIN companies c ON c.id=cmd.company_id
        WHERE c.in_portfolio=TRUE AND cmd.next_earnings_date BETWEEN CURRENT_DATE AND CURRENT_DATE+14
          AND cmd.data_date=(SELECT MAX(data_date) FROM company_market_data WHERE company_id=cmd.company_id)
        ORDER BY cmd.next_earnings_date
    """)
    data["upcoming_earnings"] = [dict(zip(["ticker","name","date"], r)) for r in cur.fetchall()]

    # Fired triggers
    cur.execute("""
        SELECT t.ticker, t.trigger_type, t.trigger_action, t.triggered_at
        FROM triggers t WHERE t.triggered_at >= %s ORDER BY t.triggered_at DESC
    """, (since,))
    data["triggers"] = [dict(zip(["ticker","type","action","at"], r)) for r in cur.fetchall()]

    # Portfolio counts
    cur.execute("SELECT COUNT(*) FROM companies WHERE in_portfolio=TRUE AND active=TRUE")
    data["n_holdings"] = cur.fetchone()[0]

    return data


def build_synthesis_prompt(data: dict, since_days: int) -> str:
    def fmt_list(items, fn):
        return "\n".join(fn(i) for i in items[:20]) or "  None"

    return f"""Generate a weekly Integrity Compounders portfolio memo for the past {since_days} days.
Portfolio: {data['n_holdings']} active holdings.

NEW RESEARCH ({len(data['research'])} items):
{fmt_list(data['research'], lambda r: f"  {r['ticker']} [{r['type']}] {r['impact']} — {(r.get('summary') or '')[:120]}")}

EARNINGS RESULTS ({len(data['earnings'])} completed):
{fmt_list(data['earnings'], lambda e: f"  {e['ticker']} {e['quarter']}: {e['beat']} guidance:{e['guidance']} thesis:{e['thesis']}")}

QUAD MIGRATIONS ({len(data['migrations'])}):
{fmt_list(data['migrations'], lambda m: f"  {m['ticker']}: {m['from']}→{m['to']} {'CONFIRMED' if m['confirmed'] else 'provisional'}")}

ACTIVE THESIS CONCERNS:
{fmt_list(data['concerns'], lambda c: f"  {c['ticker']}: {c['status']} ({c['date']})")}

WATCHLIST APPROACHING:
{fmt_list(data['watchlist'], lambda w: f"  {w['ticker']}: {w['status']} score:{w.get('score','?')} — {w.get('why','')[:60]}")}

EARNINGS NEXT 14 DAYS:
{fmt_list(data['upcoming_earnings'], lambda e: f"  {e['ticker']}: {e['date']}")}

FIRED TRIGGERS ({len(data['triggers'])}):
{fmt_list(data['triggers'], lambda t: f"  {t['ticker']}: {t['type']} → {t['action']}")}

Write a professional weekly IC memo with these EXACT sections:
1. Portfolio Pulse — one paragraph on overall portfolio health this week
2. Research Highlights — key findings from new research, by holding
3. Thesis Updates — any holdings with changed thesis status
4. Quad Watch — migrations confirmed or approaching confirmation
5. Watchlist — names approaching initiation conditions
6. Earnings Ahead — upcoming earnings and key things to watch
7. Action Items — explicit PM to-do list for the week (bulleted)

Be direct, analytical, specific. Reference actual ticker names and data points. No filler."""


def call_claude(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=MODEL, max_tokens=2500,
        system="You are a senior portfolio manager writing an internal weekly memo. Be direct and specific.",
        messages=[{"role":"user","content":prompt}]
    )
    return resp.content[0].text.strip()


def save_html(memo_text: str, data: dict, since_days: int) -> str:
    today    = date.today().strftime("%Y-%m-%d")
    run_ts   = datetime.now().strftime("%B %d, %Y · %I:%M %p")

    import re
    lines = memo_text.split("\n")
    html_body = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^#+\s", line):
            level = len(line) - len(line.lstrip("#"))
            text  = line.lstrip("# ").strip()
            if level == 1:
                html_body.append(f'<h2 style="font-size:18px;font-weight:800;color:{NAVY};margin:24px 0 10px;padding-bottom:6px;border-bottom:2px solid #e5e7eb">{text}</h2>')
            else:
                html_body.append(f'<h3 style="font-size:14px;font-weight:700;color:#374151;margin:16px 0 6px;border-left:3px solid {GOLD};padding-left:10px">{text}</h3>')
        elif line.strip().startswith("- ") or line.strip().startswith("* "):
            bullets = []
            while i < len(lines) and (lines[i].strip().startswith("- ") or lines[i].strip().startswith("* ")):
                content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", lines[i].strip()[2:])
                bullets.append(f'<li style="margin-bottom:6px;line-height:1.6;color:#374151">{content}</li>')
                i += 1
            html_body.append(f'<ul style="margin:6px 0 12px 20px">{"".join(bullets)}</ul>')
            continue
        elif line.strip():
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line.strip())
            html_body.append(f'<p style="font-size:13px;color:#374151;line-height:1.75;margin-bottom:8px">{content}</p>')
        i += 1

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Weekly Memo · {today}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:'Source Sans 3',Calibri,sans-serif;background:#f1f5f9;color:#1e293b}}</style>
</head><body>
<div style="background:linear-gradient(135deg,{NAVY},#2d5282);padding:28px 40px 24px">
  <div style="max-width:900px;margin:0 auto">
    <div style="font-size:11px;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:2px;margin-bottom:8px">Integrity Compounders · Weekly Memo</div>
    <div style="font-family:'Playfair Display',serif;font-size:30px;font-weight:800;color:white">Weekly Portfolio Synthesis</div>
    <div style="font-size:13px;color:rgba(255,255,255,0.55);margin-top:6px">{run_ts} · {data['n_holdings']} holdings · Last {since_days} days</div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px">
      {"".join(f'<div style="background:rgba(255,255,255,0.1);border-radius:8px;padding:10px;text-align:center"><div style="font-size:18px;font-weight:800;color:white">{v}</div><div style="font-size:10px;color:rgba(255,255,255,0.5);margin-top:2px;text-transform:uppercase">{l}</div></div>'
        for v,l in [(len(data["research"]),"New Research"),(len(data["earnings"]),"Earnings"),(len(data["migrations"]),"Migrations"),(len(data["upcoming_earnings"]),"Earnings Ahead")])}
    </div>
  </div>
</div>
<div style="max-width:900px;margin:0 auto;padding:28px 40px 48px">
  <div style="background:white;border-radius:14px;padding:32px;box-shadow:0 2px 8px rgba(0,0,0,0.08);border:1px solid #e5e7eb">
    {"".join(html_body)}
  </div>
</div>
<div style="background:{NAVY};color:rgba(255,255,255,0.4);text-align:center;padding:14px;font-size:11px">
  Integrity Compounders · Alpha System v10.0 · {run_ts} · Internal Use Only
</div></body></html>"""

    out_dir = ROOT / "outputs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"weekly_memo_{today}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return str(out_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", type=int, default=7)
    parser.add_argument("--html",  action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    cur  = conn.cursor()

    print(f"\n  WEEKLY SYNTHESIS — last {args.since} days — {date.today()}")
    print(f"  Fetching portfolio data...")
    data = fetch_weekly_data(args.since, cur)

    print(f"  Research: {len(data['research'])}  Earnings: {len(data['earnings'])}  "
          f"Migrations: {len(data['migrations'])}  Concerns: {len(data['concerns'])}")
    print(f"  Calling Claude ({MODEL})...")

    prompt = build_synthesis_prompt(data, args.since)
    memo   = call_claude(prompt)

    print(f"\n{'─'*60}")
    print(memo)
    print(f"{'─'*60}\n")

    if args.html:
        out_path = save_html(memo, data, args.since)
        print(f"  [HTML] Saved: {out_path}")
        try:
            import os, webbrowser
            webbrowser.open(f"file:///{out_path.replace(os.sep,'/')}")
        except Exception:
            pass

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
