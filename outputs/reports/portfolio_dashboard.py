"""
portfolio_dashboard.py
Generate portfolio-dashboard.html from live Supabase data.
Usage: python outputs/reports/portfolio_dashboard.py
"""
import sys
import json
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
from config.settings import settings

NAVY = "#1F3A5F"
GOLD = "#C9A84C"

def get_conn():
    return psycopg2.connect(settings.DATABASE_URL)

def badge(text, color, bg):
    return f'<span style="background:{bg};color:{color};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:600">{text}</span>'

def _build_factor_charts() -> tuple[str, str, str]:
    """
    Run the factor exposure engine and return
    (dynamic_chart_html, drift_grid_html, bps_chart_html).
    Returns empty strings on failure.
    """
    try:
        import psycopg2, warnings
        warnings.filterwarnings("ignore")
        from scripts.factor_exposure import (
            get_conn as fe_conn,
            get_factor_etf_returns, get_portfolio_daily_returns,
            compute_factor_exposures_bps, compute_sentiment_score,
            compute_reversal_score, compute_historical_sentiment_reversal,
            compute_rolling_factor_exposures, compute_all_factor_drifts,
            generate_dynamic_factor_chart, generate_factor_risk_charts,
            FACTOR_TOLERANCE_BPS, FACTOR_START_DATE, ROLLING_WINDOW, FACTOR_DEFINITIONS,
        )
        conn2 = fe_conn()
        cur2  = conn2.cursor()
        cur2.execute("SELECT ticker FROM companies WHERE in_portfolio=TRUE AND active=TRUE ORDER BY ticker")
        tickers = [r[0] for r in cur2.fetchall()]
        cur2.close()

        factor_rets = get_factor_etf_returns(conn2, start_date=FACTOR_START_DATE)
        if factor_rets.empty:
            conn2.close()
            return "", "", ""

        port_rets = get_portfolio_daily_returns(conn2, start_date=FACTOR_START_DATE)
        if port_rets is None or len(port_rets) < 60:
            conn2.close()
            return "", "", ""

        factor_exposures_bps = compute_factor_exposures_bps(port_rets, factor_rets)
        sent_now = compute_sentiment_score(conn2, tickers)
        rev_now  = compute_reversal_score(conn2, tickers)
        factor_exposures_bps['Sentiment'] = {
            'beta': round(sent_now, 4), 'r_squared': None, 'p_value': None,
            'factor_2sigma': None, 'bps_per_2sigma': round(sent_now * 100, 1),
            'within_tolerance': abs(sent_now * 100) <= FACTOR_TOLERANCE_BPS,
        }
        factor_exposures_bps['Reversal'] = {
            'beta': round(rev_now, 4), 'r_squared': None, 'p_value': None,
            'factor_2sigma': None, 'bps_per_2sigma': round(rev_now * 100, 1),
            'within_tolerance': abs(rev_now * 100) <= FACTOR_TOLERANCE_BPS,
        }

        sent_hist, rev_hist = compute_historical_sentiment_reversal(conn2, tickers, factor_rets.index)
        rolling = compute_rolling_factor_exposures(port_rets, factor_rets, sent_hist, rev_hist, window=ROLLING_WINDOW)
        factor_drifts = compute_all_factor_drifts(port_rets, factor_rets, sent_hist, rev_hist)

        ytd = f"{datetime.today().year}-01-01"
        dynamic_html           = generate_dynamic_factor_chart(rolling, port_rets, start_date=ytd)
        drift_html, bps_html   = generate_factor_risk_charts(factor_exposures_bps, factor_drifts, start_date=ytd)

        conn2.close()
        return dynamic_html, drift_html, bps_html
    except Exception as e:
        print(f"  [factor charts] {e}")
        return "", "", ""


def _factor_summary_section(cur, navy) -> str:
    """Pull latest factor snapshot, generate charts, render full factor section."""
    cur.execute("""
        SELECT wtd_avg_roic, wtd_avg_gross_margin, wtd_avg_fcf_margin,
               wtd_avg_fcf_yield_current, wtd_avg_pe_forward,
               wtd_avg_beta, avg_pairwise_correlation,
               it_sector_pct, wtd_avg_momentum_3m, wtd_avg_momentum_12m,
               flags, snapshot_date
        FROM factor_snapshots ORDER BY snapshot_date DESC LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        return f'<div style="background:white;border-radius:14px;padding:18px;margin-bottom:20px;border:1px solid #e5e7eb"><div style="font-size:13px;color:#6b7280">No factor snapshot yet — run: python scripts/factor_exposure.py --snapshot</div></div>'

    r = row
    def p(v):  return f"{float(v):.1f}%" if v else "—"
    def fv(v, d=1, s=""): return f"{float(v):.{d}f}{s}" if v else "—"
    flags = r[10] if isinstance(r[10], list) else (json.loads(r[10]) if r[10] else [])
    flag_badges = " ".join(
        f'<span style="background:#fee2e2;color:#dc2626;padding:2px 8px;border-radius:8px;font-size:10px;font-weight:700">{f}</span>'
        for f in flags
    ) or '<span style="color:#16a34a;font-size:11px">✅ No flags</span>'

    metric_tiles = "".join(
        f'<div style="background:#f8fafc;border-radius:8px;padding:10px"><div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px">{label}</div><div style="font-weight:700;color:#1e293b">{val}</div></div>'
        for label, val in [
            ("ROIC", p(r[0])), ("Gross Margin", p(r[1])), ("FCF Margin", p(r[2])), ("FCF Yield", p(r[3])),
            ("Fwd P/E", fv(r[4], s="x")), ("Beta", fv(r[5], 2)), ("Pairwise Corr", fv(r[6], 2)),
            ("IT Sector", f"{float(r[7]):.0f}%" if r[7] else "—"),
            ("Momentum 3M", p(r[8])), ("Momentum 12M", p(r[9])),
        ]
    )

    print("  [Factor charts] Building Plotly charts...")
    dynamic_html, drift_html, bps_html = _build_factor_charts()

    charts_block = ""
    if dynamic_html:
        charts_block += f"""
      <div style="margin-top:20px;border-top:1px solid #e5e7eb;padding-top:16px">
        <div style="font-size:11px;font-weight:700;color:{navy};text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">Portfolio Return vs. Factor Exposure</div>
        <div style="background:#fff;border-radius:8px">{dynamic_html}</div>
      </div>"""
    if drift_html:
        charts_block += f"""
      <div style="margin-top:20px;border-top:1px solid #e5e7eb;padding-top:16px">
        <div style="font-size:11px;font-weight:700;color:{navy};text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">Factor Distance from 200-DMA</div>
        <div style="background:#fff;border-radius:8px">{drift_html}</div>
      </div>"""
    if bps_html:
        charts_block += f"""
      <div style="margin-top:20px;border-top:1px solid #e5e7eb;padding-top:16px">
        <div style="font-size:11px;font-weight:700;color:{navy};text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">Factor Bps per 2σ — Six Canonical Factors</div>
        <div style="background:#fff;border-radius:8px">{bps_html}</div>
      </div>"""

    return f"""
    <div style="background:white;border-radius:14px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.07);border:1px solid #e5e7eb">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div style="border-left:4px solid {navy};padding-left:10px">
          <h2 style="font-size:14px;font-weight:800;color:{navy}">Factor Exposure</h2>
          <p style="font-size:11px;color:#6b7280">As of {r[11]} · equal weight · six canonical factors</p>
        </div>
        <div>{flag_badges}</div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px;font-size:12px">
        {metric_tiles}
      </div>
      {charts_block}
    </div>"""


def main():
    conn = get_conn()
    cur  = conn.cursor()

    # Holdings (V12: quality_profile + earnings_quality_flag + alignment v2 + QGS/GER)
    cur.execute("""
        SELECT c.ticker, c.company_name, c.sector, c.quad_current,
               cmd.quality_profile, c.is_discretionary,
               COALESCE(cs.composite_score_v2, cs.composite_score) AS composite,
               cs.tier_classification,
               cr.thesis_status,
               cmd.earnings_quality_flag,
               COALESCE(cmd.alignment_bucket_v2, cmd.alignment_bucket) AS align_bucket,
               cmd.qgs_tier, cmd.ger_flag, cmd.fcf_ev_rank
        FROM companies c
        LEFT JOIN LATERAL (
            SELECT composite_score_v2, composite_score, tier_classification
            FROM company_scores
            WHERE company_id=c.id ORDER BY score_date DESC LIMIT 1
        ) cs ON TRUE
        LEFT JOIN LATERAL (
            SELECT quality_profile, earnings_quality_flag, alignment_bucket_v2,
                   alignment_bucket, qgs_tier, ger_flag, fcf_ev_rank
            FROM company_market_data
            WHERE company_id=c.id ORDER BY data_date DESC LIMIT 1
        ) cmd ON TRUE
        LEFT JOIN LATERAL (
            SELECT thesis_status FROM company_reviews
            WHERE company_id=c.id ORDER BY review_date DESC LIMIT 1
        ) cr ON TRUE
        WHERE c.in_portfolio=TRUE AND c.active=TRUE
        ORDER BY cs.composite_score DESC NULLS LAST
    """)
    holdings = cur.fetchall()
    n = len(holdings)
    target_wt = round(100.0/n, 1) if n else 4.0

    # Sector allocation
    cur.execute("""
        SELECT sector, COUNT(*),
               ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER (), 1) AS pct
        FROM companies WHERE in_portfolio=TRUE AND active=TRUE AND sector IS NOT NULL
        GROUP BY sector ORDER BY 3 DESC
    """)
    sectors = cur.fetchall()

    # Quad distribution
    cur.execute("""
        SELECT quad_current, COUNT(*) FROM companies
        WHERE in_portfolio=TRUE AND active=TRUE
        GROUP BY quad_current ORDER BY quad_current
    """)
    quads = {r[0]: r[1] for r in cur.fetchall()}

    # Average composite score
    cur.execute("""
        SELECT AVG(cs.composite_score) FROM companies c
        JOIN LATERAL (SELECT composite_score FROM company_scores WHERE company_id=c.id
                       ORDER BY score_date DESC LIMIT 1) cs ON TRUE
        WHERE c.in_portfolio=TRUE AND c.active=TRUE
    """)
    avg_score_row = cur.fetchone()
    avg_score = round(float(avg_score_row[0]),1) if avg_score_row and avg_score_row[0] else None

    # Upcoming earnings (14 days)
    cur.execute("""
        SELECT c.ticker, c.company_name, cmd.next_earnings_date
        FROM company_market_data cmd JOIN companies c ON c.id=cmd.company_id
        WHERE c.in_portfolio=TRUE AND cmd.next_earnings_date BETWEEN CURRENT_DATE AND CURRENT_DATE+14
          AND cmd.data_date=(SELECT MAX(data_date) FROM company_market_data WHERE company_id=cmd.company_id)
        ORDER BY cmd.next_earnings_date
    """)
    upcoming = cur.fetchall()

    # Active triggers
    cur.execute("""
        SELECT ticker, trigger_type, trigger_action, trigger_condition, created_at
        FROM triggers WHERE trigger_status='PENDING'
        ORDER BY created_at DESC LIMIT 20
    """)
    triggers = cur.fetchall()

    run_ts = datetime.now().strftime("%B %d, %Y · %I:%M %p")
    data_date = date.today().strftime("%Y-%m-%d")

    # IT sector pct
    it_pct = 0
    for sec, cnt, pct in sectors:
        if sec and "Technology" in str(sec):
            it_pct = float(pct)
            break

    # Build holdings table rows (V12)
    PROFILE_STYLE = {
        "FULL_COMPOUNDER": ("#16a34a", "#dcfce7"),
        "QUALITY_WATCH":   ("#d97706", "#fef3c7"),
        "DEVELOPING":      ("#6b7280", "#f3f4f6"),
        "QUALITY_CONCERN": ("#dc2626", "#fee2e2"),
    }
    EQ_STYLE = {
        "EPS_CONFIRMED":   ("#16a34a", "#dcfce7"),
        "GP_LEADING":      ("#b8860b", "#fef9e7"),
        "EPS_ENGINEERED":  ("#dc2626", "#fee2e2"),
        "NEUTRAL":         ("#6b7280", "#f3f4f6"),
        "DATA_INCOMPLETE": ("#9ca3af", "#f3f4f6"),
    }
    ALIGN_STYLE = {
        "ACCUMULATE": ("#16a34a", "#dcfce7"),
        "HOLD":       ("#6b7280", "#f3f4f6"),
        "DISTRIBUTE": ("#dc2626", "#fee2e2"),
    }
    holdings_rows = ""
    for (t, name, sector, quad, profile, is_disc, score, tier, thesis,
         eq_flag, align_bucket, qgs_tier, ger_flag, fcf_ev_rank) in holdings:
        q = quad or "NA"
        q_colors = {"Q1":"#2563eb","Q2":"#16a34a","Q3":"#dc2626","Q4":"#d97706","NA":"#6b7280"}
        q_bgs    = {"Q1":"#dbeafe","Q2":"#dcfce7","Q3":"#fee2e2","Q4":"#fef3c7","NA":"#f3f4f6"}
        qc = q_colors.get(q,"#6b7280")
        qb = q_bgs.get(q,"#f3f4f6")

        sc_str = f"{float(score):.1f}" if score else "—"
        sc_color = "#16a34a" if score and float(score)>=7.5 else "#d97706" if score and float(score)>=6 else "#dc2626"

        pc, pb = PROFILE_STYLE.get(str(profile), ("#6b7280", "#f3f4f6"))
        prof_short = {"FULL_COMPOUNDER":"FULL","QUALITY_WATCH":"WATCH",
                      "DEVELOPING":"DEV","QUALITY_CONCERN":"CONCERN"}.get(str(profile), "—")
        ec, eb = EQ_STYLE.get(str(eq_flag), ("#9ca3af", "#f3f4f6"))
        eq_short = {"EPS_CONFIRMED":"CONFIRM","GP_LEADING":"GP-LEAD",
                    "EPS_ENGINEERED":"ENGIN.","NEUTRAL":"NEUT","DATA_INCOMPLETE":"—"}.get(str(eq_flag), "—")
        ac, ab = ALIGN_STYLE.get(str(align_bucket), ("#6b7280", "#f3f4f6"))

        ts_colors = {"INTACT":"#16a34a","WATCH":"#d97706","REVIEW":"#dc2626","BROKEN":"#dc2626"}
        tc = ts_colors.get(str(thesis),"#6b7280")
        fcf_str = f"{float(fcf_ev_rank):.0f}" if fcf_ev_rank is not None else "—"

        disc_tag = badge("DISC","#92400e","#fef3c7") if is_disc else ""

        holdings_rows += f"""
        <tr>
          <td style="padding:9px 12px;font-weight:700;color:{NAVY}">{t} {disc_tag}</td>
          <td style="padding:9px 12px;font-size:12px;color:#374151">{str(name or '')[:22]}</td>
          <td style="padding:9px 12px;text-align:center">{badge(q,qc,qb)}</td>
          <td style="padding:9px 12px;text-align:center">{badge(eq_short,ec,eb)}</td>
          <td style="padding:9px 12px;text-align:center;font-weight:700;color:{sc_color}">{sc_str}</td>
          <td style="padding:9px 12px;text-align:center">{badge(str(align_bucket or '—'),ac,ab)}</td>
          <td style="padding:9px 12px;text-align:center">{badge(prof_short,pc,pb)}</td>
          <td style="padding:9px 12px;text-align:center;font-size:11px;color:#374151">{str(qgs_tier or '—')[:6]}</td>
          <td style="padding:9px 12px;text-align:center;font-size:11px;color:#6b7280">{fcf_str}</td>
          <td style="padding:9px 12px;text-align:center;color:{tc};font-weight:600">{thesis or '—'}</td>
        </tr>"""

    # Sector rows
    sector_rows = ""
    for sec, cnt, pct in sectors:
        over = float(pct) > 28
        pct_color = "#dc2626" if over else "#374151"
        flag = ' <span style="color:#dc2626;font-size:11px;font-weight:700">!! OVER CAP</span>' if over else ""
        bar_w = min(int(float(pct)/100*200), 200)
        bar_c = "#dc2626" if over else NAVY
        sector_rows += f"""
        <tr>
          <td style="padding:8px 12px;color:#374151;font-size:13px">{sec}</td>
          <td style="padding:8px 12px;text-align:center;color:#374151">{cnt}</td>
          <td style="padding:8px 12px">
            <div style="background:#e5e7eb;border-radius:3px;height:8px;width:200px;display:inline-block">
              <div style="background:{bar_c};width:{bar_w}px;height:8px;border-radius:3px"></div>
            </div>
          </td>
          <td style="padding:8px 12px;font-weight:700;color:{pct_color}">{pct}%{flag}</td>
        </tr>"""

    # Quad distribution rows
    quad_rows = ""
    for q, label in [("Q1","Full Compounders"),("Q2","Earnings Resilience"),
                      ("Q3","Margin Compression"),("Q4","Reset / Avoid"),("NA","Axis Incomplete")]:
        cnt = quads.get(q,0)
        pct = round(cnt/n*100,1) if n else 0
        q_colors = {"Q1":"#2563eb","Q2":"#16a34a","Q3":"#dc2626","Q4":"#d97706","NA":"#6b7280"}
        c = q_colors.get(q,"#6b7280")
        flag = " ⚠️ REVIEW" if q in ("Q3","Q4") and cnt > 0 else ""
        quad_rows += f'<tr><td style="padding:8px 12px;font-weight:700;color:{c}">{q}</td><td style="padding:8px 12px;color:#374151">{label}</td><td style="padding:8px 12px;text-align:center;font-weight:700;color:{c}">{cnt}</td><td style="padding:8px 12px;color:#374151">{pct}%{flag}</td></tr>'

    # Earnings rows
    earn_rows = ""
    for ticker, name, earn_date in upcoming:
        days = (earn_date - date.today()).days
        earn_rows += f'<tr><td style="padding:8px 12px;font-weight:700;color:{NAVY}">{ticker}</td><td style="padding:8px 12px;font-size:12px;color:#374151">{name[:24]}</td><td style="padding:8px 12px;color:#374151">{earn_date}</td><td style="padding:8px 12px;color:#6b7280">{days}d</td></tr>'
    if not earn_rows:
        earn_rows = '<tr><td colspan="4" style="padding:12px;color:#6b7280;text-align:center;font-style:italic">No earnings in next 14 days</td></tr>'

    # Trigger rows
    trig_rows = ""
    for ticker, ttype, taction, cond, created in triggers[:10]:
        days_old = (date.today() - created.date()).days if created else 0
        trig_rows += f'<tr><td style="padding:8px 12px;font-weight:700;color:{NAVY}">{ticker or "—"}</td><td style="padding:8px 12px;font-size:12px;color:#374151">{ttype}</td><td style="padding:8px 12px;font-size:11px;font-weight:600;color:#dc2626">{taction}</td><td style="padding:8px 12px;font-size:11px;color:#6b7280">{str(cond or "")[:50]}</td><td style="padding:8px 12px;color:#6b7280">{days_old}d</td></tr>'
    if not trig_rows:
        trig_rows = '<tr><td colspan="5" style="padding:12px;color:#6b7280;text-align:center;font-style:italic">No pending triggers</td></tr>'

    def section(title, subtitle, content):
        return f"""
        <div style="background:white;border-radius:14px;padding:24px;margin-bottom:20px;
                    box-shadow:0 1px 4px rgba(0,0,0,0.07);border:1px solid #e5e7eb">
          <div style="border-left:4px solid {NAVY};padding-left:12px;margin-bottom:16px">
            <h2 style="font-size:15px;font-weight:800;color:{NAVY}">{title}</h2>
            <p style="font-size:12px;color:#6b7280;margin-top:2px">{subtitle}</p>
          </div>
          {content}
        </div>"""

    tbl_hdr = lambda cols: f'<tr style="background:{NAVY};color:white">{"".join(f"<th style=\'padding:9px 12px;text-align:left;font-size:12px\'>{c}</th>" for c in cols)}</tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Portfolio Dashboard · {data_date}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:'Source Sans 3',Calibri,sans-serif;background:#f1f5f9;color:#1e293b;-webkit-font-smoothing:antialiased}}
@media(max-width:640px){{.hdr-grid{{grid-template-columns:repeat(2,1fr)!important}}.body{{padding:12px!important}}}}</style>
</head><body>
<div style="background:linear-gradient(135deg,{NAVY},#2d5282);padding:24px 32px 20px">
  <div style="max-width:1200px;margin:0 auto">
    <div style="font-family:'Playfair Display',serif;font-size:24px;font-weight:800;color:white;margin-bottom:4px">Portfolio Dashboard</div>
    <div style="font-size:12px;color:rgba(255,255,255,0.5);margin-bottom:18px">{run_ts} · Data as of {data_date}</div>
    <div class="hdr-grid" style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px">
      {"".join(f'<div style="background:rgba(255,255,255,0.1);border-radius:10px;padding:12px;text-align:center"><div style="font-size:22px;font-weight:800;color:{"#ef4444" if v=="⚠️" else "white"}">{v}</div><div style="font-size:10px;color:rgba(255,255,255,0.5);margin-top:3px;text-transform:uppercase">{l}</div></div>'
        for v,l in [(n,"Holdings"),(f"{target_wt}%","Target Wt"),
                    (f"{avg_score or '—'}","Avg Score"),
                    (f"{it_pct:.0f}%{'  ⚠️' if it_pct>28 else ''}","IT Sector"),
                    (data_date,"As Of")])}
    </div>
  </div>
</div>
<div class="body" style="max-width:1200px;margin:0 auto;padding:24px 32px 40px">
  {section("Holdings","All portfolio positions sorted by composite score (V12 signals)",
    f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:13px"><thead>{tbl_hdr(["Ticker","Company","Quad","Earns Q","Score (v2)","Align","Profile","QGS","FCF/EV","Thesis"])}</thead><tbody>{holdings_rows}</tbody></table></div>')}
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
    {section("Quad Distribution","Portfolio holdings by quadrant",
      f'<table style="width:100%;border-collapse:collapse;font-size:13px"><thead>{tbl_hdr(["Q","Name","Count","Weight"])}</thead><tbody>{quad_rows}</tbody></table>')}
    {section("Sector Allocation","vs 28% cap",
      f'<table style="width:100%;border-collapse:collapse;font-size:13px"><thead>{tbl_hdr(["Sector","N","Bar","Pct"])}</thead><tbody>{sector_rows}</tbody></table>')}
  </div>
  {_factor_summary_section(cur, NAVY)}
  {section("Upcoming Earnings","Next 14 days",
    f'<table style="width:100%;border-collapse:collapse;font-size:13px"><thead>{tbl_hdr(["Ticker","Company","Date","Days"])}</thead><tbody>{earn_rows}</tbody></table>')}
  {section("Active Alerts","Pending triggers",
    f'<table style="width:100%;border-collapse:collapse;font-size:13px"><thead>{tbl_hdr(["Ticker","Type","Action","Condition","Age"])}</thead><tbody>{trig_rows}</tbody></table>')}
</div>
<div style="background:{NAVY};color:rgba(255,255,255,0.4);text-align:center;padding:14px;font-size:11px">
  Integrity Compounders · Alpha System V12 · {run_ts} · Internal Use Only<br>
  <span style="font-size:10px">Refresh: python outputs/reports/portfolio_dashboard.py</span>
</div></body></html>"""

    out_path = Path(__file__).parent / "portfolio-dashboard.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    cur.close()
    conn.close()
    print(f"  [Dashboard] Saved: {out_path}")

if __name__ == "__main__":
    main()
