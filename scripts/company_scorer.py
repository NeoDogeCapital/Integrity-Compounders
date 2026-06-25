"""
company_scorer.py
-----------------
AI-assisted 3-pillar scoring for Integrity Compounders.
Default: fully automatic — Claude scores, writes to Supabase, generates memo.
Interactive: pass --interactive to review and adjust before saving.

Pillars:
  P1 Business Quality    (40%) — ROIC, margins, moat, FCF quality
  P2 Management Integrity(35%) — founder-led, alignment, capital allocation
  P3 Financial Strength  (25%) — balance sheet, FCF consistency, margin trajectory

Composite = P1×0.40 + P2×0.35 + P3×0.25
Eligibility: ≥8.0 TIER_1 | 6.5-7.9 TIER_2 | 5.0-6.4 WATCHLIST | <5.0 DNQ

Hard floors: P2 ≥ 6.0 and P3 ≥ 6.0 required for any position

Usage:
    python scripts/company_scorer.py --ticker AAPL
    python scripts/company_scorer.py --ticker AAPL --interactive
    python scripts/company_scorer.py --quarterly
    python scripts/company_scorer.py --review-all
    python scripts/company_scorer.py --memo AAPL
"""

import sys
import argparse
import json
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from pathlib import Path
from datetime import date, timedelta, datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
import anthropic
from config.settings import settings

REPORTS = ROOT / "outputs" / "reports"
DOCS    = ROOT / "docs"
REPORTS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)

MODEL = "claude-sonnet-4-5"

PILLAR_PROMPT = """
You are a senior equity analyst scoring a company for the Integrity Compounders
portfolio — a concentrated quality-compounder strategy (Methodology V12).

Score each of the three pillars from 1.0 to 10.0 with one decimal place.
Provide 2-3 sentences of reasoning per pillar citing specific data.

CRITICAL V12 RULE: VALUATION IS NOT PART OF ANY PILLAR. Do not reward or penalize
a company for being cheap or expensive in any pillar. Valuation is handled
separately by QGS and FCF/EV. Score business quality, management, and financial
strength on their own merits regardless of price.

PILLAR 1 — BUSINESS QUALITY (40% weight) — three anchors, score each then average:
  (a) Moat Durability — what structurally keeps competitors out (switching costs,
      network effects, brand, cost/scale advantages, regulatory). How durable.
  (b) Economics Sustainability — will margins and returns hold for 5 years? Use the
      ROIC LEVEL as a structural-quality signal (high absolute ROIC = strong economics).
      Consider gross margin, FCF margin, pricing power, revenue quality (recurring
      vs transactional), FCF conversion (FCF/NI).
  (c) Reinvestment Quality — is there organic runway to deploy capital at high
      incremental returns? Reinvestment rate × incremental ROIC.
  Report p1_moat_score, p1_economics_score, p1_reinvestment_score; p1_score is their average.
  A 9-10 requires a clearly durable moat, ROIC >25%, and a long high-return runway.

PILLAR 2 — MANAGEMENT & CAPITAL ALLOCATION (35% weight) — HARD FLOOR 6.0:
  - Capital Allocation Effectiveness (40%): use ROIC TRAJECTORY (rising / stable /
    eroding) as the primary evidence of management skill; M&A discipline, buyback
    discipline (price-aware), SBC as % of revenue.
  - Alignment & Integrity (35%): founder-led / owner-operator, insider ownership,
    compensation structure aligned to long-term value.
  - Communication Quality (25%): honesty about problems, guidance accuracy,
    strategy consistency, no promotional language.
  HARD FLOOR: a score below 6.0 blocks any portfolio position.

PILLAR 3 — FINANCIAL STRENGTH (25% weight) — HARD FLOOR 6.0:
  - Balance Sheet Resilience (35%): Net Debt/EBITDA (reward net cash), interest coverage.
  - Earnings & Cash Quality (35%): FCF conversion, revenue consistency, multi-year FCF track record.
  - Self-Funding Ability (30%): can growth be funded internally without dilution?
  HARD FLOOR: a score below 6.0 blocks any portfolio position.

EARNINGS QUALITY CONTEXT: if the company is flagged EPS_ENGINEERED (EPS accelerating
but gross profit NOT), apply extra scrutiny to P1 economics sustainability and P2
capital allocation — the earnings growth may be financially engineered rather than
backed by unit economics. Note this explicitly in your reasoning when present.

Return ONLY valid JSON in exactly this format — no markdown, no preamble:
{
  "p1_score": 8.5,
  "p1_moat_score": 8.0,
  "p1_economics_score": 9.0,
  "p1_reinvestment_score": 8.5,
  "p1_reasoning": "...",
  "p2_score": 7.5,
  "p2_reasoning": "...",
  "p3_score": 8.0,
  "p3_reasoning": "...",
  "key_risks": ["risk 1", "risk 2"],
  "key_strengths": ["strength 1", "strength 2"],
  "investment_summary": "2-3 sentence overall assessment"
}
"""


def get_conn():
    return psycopg2.connect(settings.DATABASE_URL)


def get_company_data(cur, ticker):
    cur.execute("""
        SELECT c.*,
               cs.p1_business_quality, cs.p2_management, cs.p3_financial_strength,
               cs.composite_score_v2, cs.score_date,
               cmd.roic_trailing, cmd.gross_margin_trailing, cmd.fcf_margin_trailing,
               cmd.revenue_3y_cagr_trailing, cmd.net_debt_ebitda,
               cmd.fwd_revenue_3y_cagr, cmd.fwd_eps_3y_cagr,
               cmd.fcf_yield_current, cmd.fcf_yield_forward,
               cmd.earnings_momentum_roc, cmd.multiple_roc,
               cmd.beta, cmd.momentum_3m, cmd.momentum_12m,
               cmd.fcf_conversion, cmd.roic_spread, cmd.market_cap,
               cmd.pe_forward, cmd.ev_ebitda, cmd.current_price,
               cmd.earnings_quality_flag, cmd.eps_acceleration, cmd.gp_acceleration,
               cmd.quality_growth_score, cmd.qgs_tier, cmd.ger_flag,
               cmd.fcf_ev_rank, cmd.sbc_pct_revenue, cmd.quality_profile
        FROM companies c
        LEFT JOIN LATERAL (
            SELECT p1_business_quality, p2_management, p3_financial_strength,
                   composite_score_v2, score_date
            FROM company_scores WHERE company_id = c.id
            ORDER BY score_date DESC LIMIT 1
        ) cs ON TRUE
        LEFT JOIN LATERAL (
            SELECT roic_trailing, gross_margin_trailing, fcf_margin_trailing,
                   revenue_3y_cagr_trailing, net_debt_ebitda,
                   fwd_revenue_3y_cagr, fwd_eps_3y_cagr,
                   fcf_yield_current, fcf_yield_forward,
                   earnings_momentum_roc, multiple_roc,
                   beta, momentum_3m, momentum_12m,
                   fcf_conversion, roic_spread, market_cap,
                   pe_forward, ev_ebitda, current_price,
                   earnings_quality_flag, eps_acceleration, gp_acceleration,
                   quality_growth_score, qgs_tier, ger_flag,
                   fcf_ev_rank, sbc_pct_revenue, quality_profile
            FROM company_market_data WHERE company_id = c.id
            ORDER BY data_date DESC LIMIT 1
        ) cmd ON TRUE
        WHERE c.ticker = %s AND c.active = TRUE
    """, (ticker.upper(),))
    return cur.fetchone(), [d[0] for d in cur.description]


def get_research(cur, company_id):
    cur.execute("""
        SELECT source_id, content_type, research_date, ai_summary,
               thesis_impact, pillar_affected, signal_strength
        FROM research_inputs
        WHERE company_id = %s AND research_date >= %s
        ORDER BY research_date DESC LIMIT 20
    """, (company_id, date.today() - timedelta(days=180)))
    research = cur.fetchall()

    cur.execute("""
        SELECT quarter, earnings_date, beat_miss_meet, guidance_change,
               demand_commentary, margin_trajectory, management_tone_vs_prior,
               thesis_status_post, full_notes
        FROM earnings_memos
        WHERE company_id = %s AND post_completed = TRUE
        ORDER BY earnings_date DESC NULLS LAST LIMIT 4
    """, (company_id,))
    earnings = cur.fetchall()
    return research, earnings


def _fmt(val, suffix=''):
    if val is None:
        return 'N/A'
    try:
        f = float(val)
        if suffix == '%':
            return f"{f:.1f}%"
        if suffix == 'x':
            return f"{f:.1f}x"
        return f"{f:.2f}"
    except Exception:
        return str(val)


def build_context(row, col_names, research, earnings):
    d = dict(zip(col_names, row))
    lines = [
        f"COMPANY: {d.get('company_name')} ({d.get('ticker')})",
        f"Sector: {d.get('sector')} | Industry: {d.get('industry')}",
        f"Founder-led: {d.get('is_founder_led')} | Insider ownership: {d.get('insider_ownership_pct')}%",
        "",
        "QUANTITATIVE FUNDAMENTALS (score P1-P3 on these; IGNORE valuation):",
        f"  ROIC (trailing) [P1 LEVEL]:   {_fmt(d.get('roic_trailing'), '%')}",
        f"  ROIC Spread vs WACC [P2 TRAJ]:{_fmt(d.get('roic_spread'), '%')}",
        f"  Gross Margin:            {_fmt(d.get('gross_margin_trailing'), '%')}",
        f"  FCF Margin:              {_fmt(d.get('fcf_margin_trailing'), '%')}",
        f"  Revenue 3Y CAGR:         {_fmt(d.get('revenue_3y_cagr_trailing'), '%')}",
        f"  Fwd Revenue CAGR:        {_fmt(d.get('fwd_revenue_3y_cagr'), '%')}",
        f"  Net Debt/EBITDA:         {_fmt(d.get('net_debt_ebitda'), 'x')}",
        f"  FCF Conversion (FCF/NI): {_fmt(d.get('fcf_conversion'), '%')}",
        f"  SBC % of Revenue:        {_fmt(d.get('sbc_pct_revenue'))}",
        f"  Beta:                    {_fmt(d.get('beta'))}",
        f"  3M / 12M Momentum:       {_fmt(d.get('momentum_3m'), '%')} / {_fmt(d.get('momentum_12m'), '%')}",
        "",
        "V12 SIGNALS (context — valuation lives here, NOT in the pillars):",
        f"  Quality Profile:         {d.get('quality_profile') or 'N/A'}",
        f"  QGS Tier:                {d.get('qgs_tier') or 'N/A'}  (QGS={_fmt(d.get('quality_growth_score'))})",
        f"  GER Flag:                {d.get('ger_flag') or 'N/A'}",
        f"  FCF/EV Rank (valuation): {_fmt(d.get('fcf_ev_rank'))}",
        f"  EARNINGS QUALITY FLAG:   {d.get('earnings_quality_flag') or 'N/A'}  "
        f"(EPS accel={_fmt(d.get('eps_acceleration'))}, GP accel={_fmt(d.get('gp_acceleration'))})",
        f"  Valuation (NOT scored):  Fwd P/E {_fmt(d.get('pe_forward'),'x')} | EV/EBITDA {_fmt(d.get('ev_ebitda'),'x')}",
        "",
        "PRIOR SCORES (v2):",
        f"  P1 Business Quality:     {d.get('p1_business_quality') or 'None'}",
        f"  P2 Management:           {d.get('p2_management') or 'None'}",
        f"  P3 Financial Strength:   {d.get('p3_financial_strength') or 'None'}",
        f"  Composite v2:            {d.get('composite_score_v2') or 'None'}",
        f"  Score date:              {d.get('score_date') or 'Never scored'}",
    ]
    if research:
        lines += ["", "RECENT RESEARCH INPUTS:"]
        for r in research[:10]:
            summary = str(r[3] or '')[:200]
            lines.append(f"  [{r[2]}] {r[1]} via {r[0]} | Impact: {r[4]} | {summary}")
    if earnings:
        lines += ["", "RECENT EARNINGS:"]
        for e in earnings:
            lines.append(
                f"  {e[0]}: {e[2]} | Guidance: {e[3]} | "
                f"Demand: {e[4]} | Margins: {e[5]} | "
                f"Mgmt tone: {e[6]} | Thesis: {e[7]}"
            )
    return "\n".join(lines)


def score_company(ticker: str, interactive: bool = False, memo_only: bool = False,
                  force: bool = False, score_only: bool = False) -> bool:
    conn = get_conn()
    cur  = conn.cursor()

    row, col_names = get_company_data(cur, ticker)
    if not row:
        print(f"  ❌ {ticker} not found in companies table")
        conn.close()
        return False

    d          = dict(zip(col_names, row))
    company_id = d['id']

    # Skip if scored recently unless force
    if not force and not memo_only:
        score_date = d.get('score_date')
        if score_date and (date.today() - score_date).days < 30:
            if not score_only:
                print(f"  ⏭  {ticker} scored {(date.today()-score_date).days}d ago — skipping")
            return False

    research, earnings = get_research(cur, company_id)

    if memo_only:
        _generate_and_save_memo(ticker, d, None, None, None, None, None, None, None)
        conn.close()
        return True

    context = build_context(row, col_names, research, earnings)

    # Call Claude
    if not score_only:
        print(f"  [{ticker}] Calling Claude ({MODEL})...")
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": f"{PILLAR_PROMPT}\n\nCOMPANY DATA:\n{context}"}]
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]
        scores = json.loads(raw)
    except Exception as e:
        print(f"  ❌ {ticker} Claude scoring failed: {e}")
        conn.close()
        return False

    p1 = float(scores['p1_score'])
    p2 = float(scores['p2_score'])
    p3 = float(scores['p3_score'])
    composite = round(p1*0.40 + p2*0.35 + p3*0.25, 2)
    tier = ('TIER_1' if composite >= 8.0 else
            'TIER_2' if composite >= 6.5 else
            'WATCHLIST' if composite >= 5.0 else 'DOES_NOT_QUALIFY')
    p2_pass  = p2 >= 6.0
    p3_pass  = p3 >= 6.0
    eligible = composite >= 6.5 and p2_pass and p3_pass

    prior      = d.get('composite_score_v2')
    prior_f    = float(prior) if prior else None
    delta_str  = f"{composite - prior_f:+.2f}" if prior_f else "first score"

    if not score_only:
        print(f"\n{'═'*55}")
        print(f"  COMPANY SCORER — {ticker.upper()} — {d.get('company_name')}")
        print(f"{'═'*55}")
        print(f"  Data: {date.today()}")
        print(f"\n  AI SCORES:")
        print(f"    P1 Business Quality    (40%):  {p1}  — {scores['p1_reasoning'][:75]}...")
        print(f"    P2 Management          (35%):  {p2}  — {scores['p2_reasoning'][:75]}...")
        print(f"    P3 Financial Strength  (25%):  {p3}  — {scores['p3_reasoning'][:75]}...")
        print(f"\n    COMPOSITE:  {composite}  → {tier}")
        print(f"    PRIOR:      {prior or 'None'}  → DELTA: {delta_str}")
        print(f"\n  HARD RULE CHECK:")
        print(f"    P2 Management ≥ 6.0:         {'✅' if p2_pass else '❌'}  {p2}")
        print(f"    P3 Financial Strength ≥ 6.0: {'✅' if p3_pass else '❌'}  {p3}")
        print(f"    Portfolio eligible:           {'✅ YES' if eligible else '❌ NO'}")

    if interactive:
        resp = input("\n  Accept AI scores? (y=accept / n=enter own / q=quit): ").strip().lower()
        if resp == 'q':
            conn.close()
            return False
        if resp == 'n':
            print("  Enter your scores (1.0–10.0):")
            p1 = float(input("    P1 Business Quality: "))
            p2 = float(input("    P2 Management: "))
            p3 = float(input("    P3 Financial Strength: "))
            composite = round(p1*0.40 + p2*0.35 + p3*0.25, 2)
            tier = ('TIER_1' if composite >= 8.0 else
                    'TIER_2' if composite >= 6.5 else
                    'WATCHLIST' if composite >= 5.0 else 'DOES_NOT_QUALIFY')
            scored_by = 'PM'
        else:
            scored_by = 'AI-Assisted'
    else:
        scored_by = 'AI-Assisted'

    # V12 P1 sub-scores (default to p1 if model omits them)
    p1_moat = float(scores.get('p1_moat_score', p1))
    p1_econ = float(scores.get('p1_economics_score', p1))
    p1_reinv = float(scores.get('p1_reinvestment_score', p1))
    eq_flag = d.get('earnings_quality_flag')

    # Write to Supabase
    cur.execute("""
        INSERT INTO company_scores (
            company_id, score_date, scored_by,
            p1_business_quality, p2_management, p3_financial_strength,
            composite_score_v2, tier_classification,
            prior_composite_score, score_delta, score_changed,
            score_notes,
            pillar_4_reinvestment, pillar_5_valuation,
            p1_moat_score, p1_economics_score, p1_reinvestment_score,
            earnings_quality_flag
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        company_id, date.today(), scored_by,
        p1, p2, p3, composite, tier,
        prior_f,
        round(composite - prior_f, 2) if prior_f else None,
        prior_f is not None and abs(composite - prior_f) > 0.1,
        json.dumps({
            'key_risks':     scores.get('key_risks', []),
            'key_strengths': scores.get('key_strengths', []),
            'summary':       scores.get('investment_summary', ''),
        }),
        None, None,  # p4/p5 retired (valuation removed from pillars in V12)
        p1_moat, p1_econ, p1_reinv, eq_flag,
    ))
    conn.commit()

    if not score_only:
        print(f"\n  ✅ Written to company_scores ({scored_by})")

    # Generate HTML memo (skip in batch score-only mode)
    if not score_only:
        _generate_and_save_memo(ticker, d, scores, p1, p2, p3, composite, tier, eligible)

    cur.close()
    conn.close()
    return True


def _generate_and_save_memo(ticker, d, scores, p1, p2, p3, composite, tier, eligible):
    if scores is None:
        print(f"  ⚠️  No scores available — run scorer first")
        return
    tier_color = '#00aa44' if tier == 'TIER_1' else '#C9A84C' if tier == 'TIER_2' else '#cc3333'
    today_str  = date.today().strftime("%Y-%m-%d")
    run_ts     = datetime.now().strftime("%B %d, %Y · %I:%M %p")

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>IC — {ticker} Company Memo</title>
<style>
  body{{font-family:Calibri,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:0}}
  .hdr{{background:#1F3A5F;border-bottom:3px solid #C9A84C;padding:20px 32px}}
  .hdr h1{{color:#fff;font-size:20px;margin:0}}
  .hdr .sub{{color:#C9A84C;font-size:13px;margin-top:4px}}
  .body{{max-width:900px;margin:0 auto;padding:32px 24px}}
  .score-box{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;margin-bottom:20px}}
  .score-box h2{{color:#C9A84C;font-size:14px;text-transform:uppercase;letter-spacing:1px;margin:0 0 14px}}
  .pillar{{display:flex;align-items:flex-start;margin-bottom:12px;gap:12px}}
  .pillar-score{{background:#1F3A5F;color:#fff;padding:4px 10px;border-radius:4px;font-weight:700;font-size:16px;min-width:42px;text-align:center}}
  .pillar-text{{font-size:13px;color:#8b949e;line-height:1.5}}
  .pillar-label{{font-weight:700;color:#e6edf3;font-size:14px}}
  .composite{{font-size:28px;font-weight:700;color:{tier_color};margin:8px 0}}
  .tag{{display:inline-block;padding:3px 10px;border-radius:4px;font-size:12px;font-weight:700;background:{tier_color};color:#fff;margin-left:8px}}
  .section{{margin-bottom:24px}}
  .section h3{{color:#C9A84C;font-size:13px;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #21262d;padding-bottom:6px;margin-bottom:12px}}
  .flag{{color:#ff6b6b;font-size:13px}}.pass{{color:#00aa44;font-size:13px}}
  ul{{margin:0;padding-left:18px}}li{{font-size:13px;color:#8b949e;margin-bottom:4px}}
  .footer{{background:#1F3A5F;color:rgba(255,255,255,0.4);text-align:center;padding:14px;font-size:11px;margin-top:40px}}
</style></head><body>
<div class="hdr">
  <h1>INTEGRITY COMPOUNDERS — {ticker.upper()} — {d.get('company_name')}</h1>
  <div class="sub">Company Research Memo  ·  {today_str}  ·  Sector: {d.get('sector')}</div>
</div>
<div class="body">
  <div class="score-box">
    <h2>Composite Score (v2)</h2>
    <div class="composite">{composite}<span class="tag">{tier}</span></div>
    <div style="font-size:13px;color:#8b949e">P1×0.40 + P2×0.35 + P3×0.25 = {composite}</div>
    <div style="margin-top:10px;font-size:13px">
      Portfolio eligible: {'<span class="pass">✅ YES</span>' if eligible else '<span class="flag">❌ NO</span>'}
    </div>
  </div>
  <div class="score-box">
    <h2>Pillar Scores</h2>
    <div class="pillar">
      <div><div class="pillar-score">{p1}</div></div>
      <div><div class="pillar-label">P1 — Business Quality (40%)</div>
      <div class="pillar-text">{scores['p1_reasoning']}</div></div>
    </div>
    <div class="pillar">
      <div><div class="pillar-score">{p2}</div></div>
      <div><div class="pillar-label">P2 — Management Integrity (35%)</div>
      <div class="pillar-text">{scores['p2_reasoning']}</div></div>
    </div>
    <div class="pillar">
      <div><div class="pillar-score">{p3}</div></div>
      <div><div class="pillar-label">P3 — Financial Strength (25%)</div>
      <div class="pillar-text">{scores['p3_reasoning']}</div></div>
    </div>
  </div>
  <div class="section">
    <h3>Investment Summary</h3>
    <p style="font-size:14px;line-height:1.6;color:#e6edf3">{scores.get('investment_summary','')}</p>
  </div>
  <div class="section">
    <h3>Key Strengths</h3>
    <ul>{''.join(f"<li>{s}</li>" for s in scores.get('key_strengths',[]))}</ul>
  </div>
  <div class="section">
    <h3>Key Risks</h3>
    <ul>{''.join(f"<li>{r}</li>" for r in scores.get('key_risks',[]))}</ul>
  </div>
  <div class="score-box">
    <h2>Hard Rule Check</h2>
    <div class="{'pass' if p2 >= 6.0 else 'flag'}">{'✅' if p2 >= 6.0 else '❌'} P2 Management ≥ 6.0: {p2}</div>
    <div class="{'pass' if p3 >= 6.0 else 'flag'}">{'✅' if p3 >= 6.0 else '❌'} P3 Financial Strength ≥ 6.0: {p3}</div>
  </div>
</div>
<div class="footer">Integrity Compounders · Alpha System V12 · {run_ts} · Internal Use Only</div>
</body></html>"""

    memo_path = REPORTS / f"{ticker.upper()}_company_memo_{date.today()}.html"
    docs_path = DOCS / f"company_memo_{ticker.upper()}.html"
    for path in [memo_path, docs_path]:
        path.write_text(html, encoding='utf-8')
    print(f"  📄 Memo → {memo_path.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker',      type=str)
    parser.add_argument('--quarterly',   action='store_true')
    parser.add_argument('--review-all',  action='store_true')
    parser.add_argument('--memo',        type=str)
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--force',       action='store_true')
    args = parser.parse_args()

    if args.memo:
        conn = get_conn(); cur = conn.cursor()
        row, col_names = get_company_data(cur, args.memo.upper())
        if row:
            d = dict(zip(col_names, row))
            print(f"  [{args.memo.upper()}] Generating memo from existing scores...")
            # Re-score to get the reasoning for the memo
            score_company(args.memo.upper(), force=True)
        cur.close(); conn.close()
        return

    if args.ticker:
        score_company(args.ticker.upper(), interactive=args.interactive, force=args.force)
        return

    # Batch modes
    conn = get_conn(); cur = conn.cursor()
    if args.quarterly:
        cur.execute("SELECT ticker FROM companies WHERE in_portfolio=TRUE AND active=TRUE ORDER BY ticker")
    elif args.review_all:
        cutoff = date.today() - timedelta(days=90)
        cur.execute("""
            SELECT DISTINCT c.ticker FROM companies c
            LEFT JOIN company_scores cs ON cs.company_id=c.id
            WHERE c.active=TRUE AND (cs.score_date IS NULL OR cs.score_date < %s)
            ORDER BY c.ticker
        """, (cutoff,))
    else:
        parser.print_help()
        conn.close(); return

    tickers = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()

    print(f"\n  Batch scoring {len(tickers)} companies (score_only mode)...")
    ok = skipped = failed = 0
    for t in tickers:
        result = score_company(t, interactive=False, score_only=True, force=args.force)
        if result is True:    ok += 1
        elif result is False: skipped += 1
        else:                 failed += 1
        if ok % 25 == 0 and ok > 0:
            print(f"  {ok} scored so far...")
    print(f"\n  BATCH COMPLETE: {ok} scored · {skipped} skipped · {failed} failed")


if __name__ == '__main__':
    main()
