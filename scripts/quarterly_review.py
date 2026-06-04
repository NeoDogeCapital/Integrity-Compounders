"""
quarterly_review.py
-------------------
Quarterly learning loop — analyzes process discipline and generates recalibration recommendations.

Usage:
    python scripts/quarterly_review.py
    python scripts/quarterly_review.py --period Q1-2026
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, date

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


def current_period() -> tuple[str, str, str]:
    today = date.today()
    q     = (today.month - 1) // 3 + 1
    year  = today.year
    starts = {1:"01-01",2:"04-01",3:"07-01",4:"10-01"}
    ends   = {1:"03-31",2:"06-30",3:"09-30",4:"12-31"}
    return f"Q{q}-{year}", f"{year}-{starts[q]}", f"{year}-{ends[q]}"


def parse_period(period_str: str) -> tuple[str, str, str]:
    try:
        q, year = period_str.split("-")
        q_num = int(q[1])
        starts = {1:"01-01",2:"04-01",3:"07-01",4:"10-01"}
        ends   = {1:"03-31",2:"06-30",3:"09-30",4:"12-31"}
        return period_str, f"{year}-{starts[q_num]}", f"{year}-{ends[q_num]}"
    except Exception:
        return current_period()


def fetch_quarterly_data(period: str, start: str, end: str, cur) -> dict:
    data = {"period": period, "start": start, "end": end}

    # Decisions
    cur.execute("""
        SELECT decision_type, COUNT(*), SUM(CASE WHEN override_applied THEN 1 ELSE 0 END)
        FROM decision_log WHERE decision_date BETWEEN %s AND %s
        GROUP BY decision_type
    """, (start, end))
    rows = cur.fetchall()
    data["decisions"]      = {r[0]: {"count": r[1], "overrides": r[2] or 0} for r in rows}
    data["total_decisions"]= sum(r["count"] for r in data["decisions"].values())
    total_overrides        = sum(r["overrides"] for r in data["decisions"].values())
    data["override_rate"]  = round(total_overrides / max(data["total_decisions"],1) * 100, 1)

    # Exit analysis
    cur.execute("""
        SELECT COUNT(*),
               AVG(pnl_pct) FILTER (WHERE pnl_pct IS NOT NULL),
               COUNT(*) FILTER (WHERE pnl_pct > 0),
               AVG(holding_days) FILTER (WHERE holding_days IS NOT NULL)
        FROM exit_journal WHERE exit_date BETWEEN %s AND %s
    """, (start, end))
    row = cur.fetchone()
    data["exit_count"]    = row[0] or 0
    data["avg_return"]    = round(float(row[1])*100, 1) if row[1] else None
    data["win_rate"]      = round(float(row[2])/max(row[0],1)*100, 1) if row[0] else None
    data["avg_hold_days"] = round(float(row[3]), 0) if row[3] else None

    # Exit by thesis status
    cur.execute("""
        SELECT thesis_integrity_at_exit, COUNT(*), AVG(pnl_pct)
        FROM exit_journal WHERE exit_date BETWEEN %s AND %s AND thesis_integrity_at_exit IS NOT NULL
        GROUP BY thesis_integrity_at_exit
    """, (start, end))
    data["exits_by_thesis"] = [dict(zip(["status","count","avg_pnl"], r)) for r in cur.fetchall()]

    # Learning tags
    cur.execute("""
        SELECT unnest(learning_tags), COUNT(*)
        FROM exit_journal WHERE exit_date BETWEEN %s AND %s AND learning_tags IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC LIMIT 10
    """, (start, end))
    data["learning_tags"] = [{"tag": r[0], "count": r[1]} for r in cur.fetchall()]

    # Score predictiveness (entry score vs return)
    cur.execute("""
        SELECT p.ticker, p.composite_score_at_entry, p.pnl_pct
        FROM positions p WHERE p.status='CLOSED' AND p.exit_date BETWEEN %s AND %s
          AND p.composite_score_at_entry IS NOT NULL AND p.pnl_pct IS NOT NULL
    """, (start, end))
    score_data = cur.fetchall()
    data["score_return_pairs"] = [(float(r[1]),float(r[2])*100) for r in score_data]

    # Source performance — from research_inputs
    cur.execute("""
        SELECT ri.source_id, COUNT(*) as signals,
               COUNT(*) FILTER (WHERE ri.thesis_impact='STRENGTHENS') as bullish,
               COUNT(*) FILTER (WHERE ri.thesis_impact='WEAKENS') as bearish
        FROM research_inputs ri
        WHERE ri.research_date BETWEEN %s AND %s
        GROUP BY ri.source_id ORDER BY signals DESC LIMIT 10
    """, (start, end))
    data["source_stats"] = [dict(zip(["source","signals","bullish","bearish"], r))
                            for r in cur.fetchall()]

    # Quad migration analysis
    cur.execute("""
        SELECT COUNT(*) FILTER (WHERE confirmed=TRUE) as confirmed,
               COUNT(*) FILTER (WHERE confirmed=FALSE) as provisional
        FROM quad_migration_log WHERE migration_date BETWEEN %s AND %s
    """, (start, end))
    row = cur.fetchone()
    data["migrations_confirmed"]  = row[0] or 0
    data["migrations_provisional"]= row[1] or 0

    # Q3 holdings — did monitoring catch them?
    cur.execute("""
        SELECT COUNT(*) FROM quad_migration_log
        WHERE to_quad='Q3' AND migration_date BETWEEN %s AND %s
    """, (start, end))
    data["q3_migrations"] = cur.fetchone()[0] or 0

    return data


def generate_review(data: dict) -> str:
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    pairs_summary = ""
    if data["score_return_pairs"]:
        avg_high = [p[1] for p in data["score_return_pairs"] if p[0]>=7.5]
        avg_low  = [p[1] for p in data["score_return_pairs"] if p[0]<7.5]
        pairs_summary = (f"High score (≥7.5) avg return: {sum(avg_high)/len(avg_high):.1f}% ({len(avg_high)} exits)\n"
                         f"Low score (<7.5) avg return: {sum(avg_low)/len(avg_low):.1f}% ({len(avg_low)} exits)"
                         if avg_high or avg_low else "Insufficient data")

    prompt = f"""Generate a quarterly review for Integrity Compounders — {data['period']}.

DECISION LOG:
  Total decisions: {data['total_decisions']}
  Override rate: {data['override_rate']}%
  By type: {dict(((k,v['count']) for k,v in data['decisions'].items()))}

EXIT PERFORMANCE:
  Exits: {data['exit_count']}  Avg return: {data.get('avg_return','N/A')}%  Win rate: {data.get('win_rate','N/A')}%
  Avg holding days: {data.get('avg_hold_days','N/A')}
  By thesis status: {[(e['status'],e['count'],f"{float(e['avg_pnl']*100):.1f}%" if e['avg_pnl'] else 'N/A') for e in data['exits_by_thesis']]}
  Learning tags: {[(t['tag'],t['count']) for t in data['learning_tags'][:5]]}

SCORE PREDICTIVENESS:
{pairs_summary}

SOURCE STATS (top sources by signal volume):
{chr(10).join(f"  {s['source']}: {s['signals']} signals ({s['bullish']} bullish, {s['bearish']} bearish)" for s in data['source_stats'][:5])}

QUAD MIGRATIONS:
  Confirmed: {data['migrations_confirmed']}  Provisional: {data['migrations_provisional']}
  Q3 migrations caught: {data['q3_migrations']}

Write a structured quarterly review with:
1. Process Discipline Assessment — override rate, decision quality
2. Portfolio Performance — win rate, return by thesis integrity
3. Score Predictiveness — did higher scores produce better returns?
4. Source Quality — which sources added the most value?
5. Quad Framework Effectiveness — migration catch rate
6. Recalibration Recommendations — 3-5 specific actionable changes
7. Top 3 Lessons This Quarter

Be direct, specific, and honest about what is and isn't working."""

    resp = client.messages.create(
        model=MODEL, max_tokens=2000,
        system="You are a systematic investor doing a quarterly process review. Be honest about weaknesses.",
        messages=[{"role":"user","content":prompt}]
    )
    return resp.content[0].text.strip()


def save_html(review_text: str, data: dict) -> str:
    import re
    today  = date.today().strftime("%Y-%m-%d")
    run_ts = datetime.now().strftime("%B %d, %Y · %I:%M %p")

    lines = review_text.split("\n")
    html_body = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^#+\s", line):
            text = line.lstrip("# ").strip()
            level = len(line) - len(line.lstrip("#"))
            if level <= 2:
                html_body.append(f'<h2 style="font-size:16px;font-weight:800;color:{NAVY};margin:24px 0 10px;padding-bottom:6px;border-bottom:2px solid #e5e7eb">{text}</h2>')
            else:
                html_body.append(f'<h3 style="font-size:13px;font-weight:700;color:#374151;margin:14px 0 6px;border-left:3px solid {GOLD};padding-left:10px">{text}</h3>')
        elif line.strip().startswith(("- ","* ")):
            bullets = []
            while i < len(lines) and lines[i].strip().startswith(("- ","* ")):
                content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", lines[i].strip()[2:])
                bullets.append(f'<li style="margin-bottom:5px;line-height:1.6;color:#374151">{content}</li>')
                i += 1
            html_body.append(f'<ul style="margin:6px 0 12px 20px">{"".join(bullets)}</ul>')
            continue
        elif line.strip():
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line.strip())
            html_body.append(f'<p style="font-size:13px;color:#374151;line-height:1.75;margin-bottom:8px">{content}</p>')
        i += 1

    stat_cards = [
        (data["total_decisions"], "Total Decisions"),
        (f"{data['override_rate']}%", "Override Rate"),
        (f"{data.get('win_rate','—')}%", "Win Rate"),
        (f"{data.get('avg_return','—')}%", "Avg Return"),
    ]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Quarterly Review · {data['period']}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:'Source Sans 3',Calibri,sans-serif;background:#f1f5f9;color:#1e293b}}</style>
</head><body>
<div style="background:linear-gradient(135deg,{NAVY},#2d5282);padding:28px 40px 24px">
  <div style="max-width:900px;margin:0 auto">
    <div style="font-size:11px;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:2px;margin-bottom:8px">Integrity Compounders · Quarterly Review</div>
    <div style="font-family:'Playfair Display',serif;font-size:30px;font-weight:800;color:white">{data['period']} Review</div>
    <div style="font-size:13px;color:rgba(255,255,255,0.55);margin-top:4px">{data['start']} → {data['end']} · {run_ts}</div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px">
      {"".join(f'<div style="background:rgba(255,255,255,0.1);border-radius:8px;padding:10px;text-align:center"><div style="font-size:20px;font-weight:800;color:white">{v}</div><div style="font-size:10px;color:rgba(255,255,255,0.5);margin-top:2px;text-transform:uppercase">{l}</div></div>'
        for v,l in stat_cards)}
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
    out_path = out_dir / f"quarterly_review_{data['period']}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return str(out_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", type=str)
    args = parser.parse_args()

    if args.period:
        period, start, end = parse_period(args.period)
    else:
        period, start, end = current_period()

    conn = get_conn()
    cur  = conn.cursor()

    print(f"\n  QUARTERLY REVIEW — {period} ({start} → {end})\n")
    data = fetch_quarterly_data(period, start, end, cur)

    print(f"  Decisions: {data['total_decisions']}  Overrides: {data['override_rate']}%")
    print(f"  Exits: {data['exit_count']}  Win rate: {data.get('win_rate','N/A')}%  Avg return: {data.get('avg_return','N/A')}%")
    print(f"  Sources: {len(data['source_stats'])}  Migrations confirmed: {data['migrations_confirmed']}")

    print(f"  Calling Claude for review synthesis...")
    review = generate_review(data)

    print(f"\n{'─'*60}")
    print(review)
    print(f"{'─'*60}\n")

    # Write score_predictiveness
    if data["score_return_pairs"]:
        pairs = data["score_return_pairs"]
        avg_h = [p[1] for p in pairs if p[0] >= 7.5]
        avg_l = [p[1] for p in pairs if p[0] < 7.5]
        cur.execute("""
            INSERT INTO score_predictiveness (evaluation_period,
                avg_return_tier1, avg_return_tier2, notes, evaluated_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (period,
              sum(avg_h)/len(avg_h) if avg_h else None,
              sum(avg_l)/len(avg_l) if avg_l else None,
              f"Win rate: {data.get('win_rate','N/A')}%  Exits: {data['exit_count']}"))
        conn.commit()

    out_path = save_html(review, data)
    print(f"  [HTML] Saved: {out_path}")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
