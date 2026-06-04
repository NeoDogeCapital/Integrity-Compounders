"""
factor_exposure.py
------------------
Monthly portfolio factor exposure report.
Computes weighted average factors across all active holdings.

Usage:
    python scripts/factor_exposure.py
    python scripts/factor_exposure.py --html
    python scripts/factor_exposure.py --snapshot
    python scripts/factor_exposure.py --html --snapshot
"""

import sys
import argparse
import json
import warnings
warnings.filterwarnings("ignore")
from pathlib import Path
from datetime import date, timedelta, datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
import numpy as np
from config.settings import settings

REPORTS = ROOT / "outputs" / "reports"
DOCS    = ROOT / "docs"
REPORTS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)


def get_conn():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    return conn


def compute_pairwise_correlation(cur, company_ids):
    """Compute average pairwise correlation from 90 days of price returns."""
    try:
        cur.execute("""
            SELECT company_id, data_date, current_price
            FROM company_market_data
            WHERE company_id = ANY(%s::uuid[])
              AND data_date >= %s
              AND current_price IS NOT NULL
            ORDER BY company_id, data_date
        """, (company_ids, date.today() - timedelta(days=90)))

        from collections import defaultdict
        prices = defaultdict(dict)
        for cid, dt, price in cur.fetchall():
            prices[str(cid)][dt] = float(price)

        if len(prices) < 2:
            return None

        all_dates = sorted(set(d for p in prices.values() for d in p.keys()))
        returns   = {}
        for cid, price_dict in prices.items():
            sorted_prices = [price_dict.get(d) for d in all_dates]
            valid = [p for p in sorted_prices if p is not None]
            if len(valid) > 10:
                rets = [valid[i]/valid[i-1]-1 for i in range(1, len(valid))]
                returns[cid] = rets

        if len(returns) < 2:
            return None

        min_len = min(len(r) for r in returns.values())
        matrix  = np.array([r[:min_len] for r in returns.values()])
        corr    = np.corrcoef(matrix)
        n       = len(corr)
        pairs   = [corr[i][j] for i in range(n) for j in range(i+1, n)]
        return round(float(np.mean(pairs)), 4) if pairs else None
    except Exception as e:
        print(f"  ⚠️  Correlation failed: {e}")
        return None


def run_factor_exposure(save_html: bool = False, save_snapshot: bool = False):
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        SELECT c.id, c.ticker, c.sector,
               cmd.roic_trailing, cmd.gross_margin_trailing, cmd.fcf_margin_trailing,
               cmd.fwd_revenue_3y_cagr, cmd.net_debt_ebitda,
               cmd.fcf_yield_current, cmd.fcf_yield_forward,
               cmd.pe_forward, cmd.ev_ebitda, cmd.market_cap,
               cmd.beta, cmd.momentum_3m, cmd.momentum_6m, cmd.momentum_12m,
               cmd.fcf_conversion, cmd.roic_spread, cmd.buyback_yield,
               cmd.short_interest_pct, cmd.institutional_own_pct,
               cmd.revision_velocity_revenue
        FROM companies c
        JOIN LATERAL (
            SELECT * FROM company_market_data
            WHERE company_id = c.id ORDER BY data_date DESC LIMIT 1
        ) cmd ON TRUE
        WHERE c.in_portfolio=TRUE AND c.active=TRUE
        ORDER BY c.ticker
    """)
    holdings = cur.fetchall()
    cols     = [d[0] for d in cur.description]
    ci       = {c: i for i, c in enumerate(cols)}
    n        = len(holdings)

    if n == 0:
        print("No active portfolio holdings with market data.")
        conn.close()
        return

    def wavg(field):
        vals = [float(h[ci[field]]) for h in holdings if h[ci[field]] is not None]
        return round(sum(vals)/len(vals), 4) if vals else None

    # ── Compute all factors ────────────────────────────────────────────────────
    # Style
    fwd_rev_growth = wavg('fwd_revenue_3y_cagr')
    momentum_3m    = wavg('momentum_3m')
    momentum_6m    = wavg('momentum_6m')
    momentum_12m   = wavg('momentum_12m')
    beta           = wavg('beta')
    market_cap     = wavg('market_cap')

    # Quality
    roic         = wavg('roic_trailing')
    gross_margin = wavg('gross_margin_trailing')
    fcf_margin   = wavg('fcf_margin_trailing')
    fcf_conv     = wavg('fcf_conversion')
    roic_spread  = wavg('roic_spread')

    # Valuation
    fcf_yield_curr = wavg('fcf_yield_current')
    fcf_yield_fwd  = wavg('fcf_yield_forward')
    pe_forward     = wavg('pe_forward')
    ev_ebitda      = wavg('ev_ebitda')

    # Capital allocation
    nd_ebitda     = wavg('net_debt_ebitda')
    buyback_yield = wavg('buyback_yield')

    # Risk & sentiment
    short_interest = wavg('short_interest_pct')
    rev_vals = [h[ci['revision_velocity_revenue']] for h in holdings if h[ci['revision_velocity_revenue']] is not None]
    pos_revisions = round(sum(1 for v in rev_vals if float(v) > 0)/len(rev_vals)*100, 1) if rev_vals else None

    # Earnings beat rate
    company_ids = [str(h[ci['id']]) for h in holdings]
    cur.execute("""
        SELECT COUNT(*) FILTER (WHERE beat_miss_meet='BEAT') AS beats, COUNT(*) AS total
        FROM earnings_memos
        WHERE company_id = ANY(%s::uuid[]) AND earnings_date >= %s AND post_completed=TRUE
    """, (company_ids, date.today() - timedelta(days=365)))
    beat_row  = cur.fetchone()
    beat_rate = round(beat_row[0]/beat_row[1]*100, 1) if beat_row and beat_row[1] > 0 else None

    # Pairwise correlation
    avg_corr = compute_pairwise_correlation(cur, company_ids)

    # Sector concentration
    sector_counts: dict[str, int] = {}
    for h in holdings:
        s = h[ci['sector']] or 'Unknown'
        sector_counts[s] = sector_counts.get(s, 0) + 1
    it_pct = round(sector_counts.get('Information Technology', 0)/n*100, 1)

    # ── Flags ──────────────────────────────────────────────────────────────────
    flags = []
    if it_pct > 28:                                          flags.append('IT_SECTOR_CAP_BREACH')
    if beta and float(beta) > 1.3:                           flags.append('HIGH_BETA_PORTFOLIO')
    if nd_ebitda and float(nd_ebitda) > 2.0:                flags.append('LEVERAGE_ELEVATED')
    if avg_corr and float(avg_corr) > 0.65:                 flags.append('HIGH_CORRELATION')
    if pos_revisions is not None and pos_revisions < 40:    flags.append('REVISION_MOMENTUM_WEAK')
    if fcf_yield_curr and float(fcf_yield_curr) < 2.0:      flags.append('VALUATION_STRETCHED')

    # ── Terminal output ────────────────────────────────────────────────────────
    def p(v): return f"{float(v):.1f}%" if v is not None else "N/A"
    def x(v): return f"{float(v):.1f}x" if v is not None else "N/A"
    def n2(v): return f"{float(v):.2f}" if v is not None else "N/A"

    print(f"\n{'═'*62}")
    print(f"  INTEGRITY COMPOUNDERS — FACTOR EXPOSURE REPORT")
    print(f"  {date.today()}  |  {n} Holdings  |  {100/n:.1f}% Equal Weight")
    print(f"{'═'*62}")

    print(f"\n  STYLE FACTORS")
    print(f"    Fwd Revenue Growth (wtd avg):  {p(fwd_rev_growth)}")
    print(f"    Price Momentum 3M (wtd avg):   {p(momentum_3m)}")
    print(f"    Price Momentum 12M (wtd avg):  {p(momentum_12m)}")
    beta_flag = '  ⚠️  HIGH_BETA' if beta and float(beta) > 1.3 else '  ✅'
    print(f"    Beta to SPY (wtd avg):         {n2(beta)}{beta_flag}")
    mc_str = f"${float(market_cap)/1e9:.0f}B" if market_cap and float(market_cap) >= 1e9 else (f"${float(market_cap)/1e6:.0f}M" if market_cap else "N/A")
    print(f"    Market Cap (wtd avg):          {mc_str}")

    print(f"\n  QUALITY FACTORS")
    print(f"    ROIC (wtd avg):                {p(roic)}  {'✅' if roic and float(roic)>=12 else '⚠️ '}  (floor: 12%)")
    print(f"    Gross Margin (wtd avg):        {p(gross_margin)}  {'✅' if gross_margin and float(gross_margin)>=35 else '⚠️ '}  (floor: 35%)")
    print(f"    FCF Margin (wtd avg):          {p(fcf_margin)}  {'✅' if fcf_margin and float(fcf_margin)>=10 else '⚠️ '}  (floor: 10%)")
    print(f"    FCF Conversion (wtd avg):      {p(fcf_conv)}")
    print(f"    ROIC Spread vs WACC (wtd avg): {p(roic_spread)}")

    print(f"\n  VALUATION FACTORS")
    vy_flag = '  ⚠️  VALUATION_STRETCHED' if fcf_yield_curr and float(fcf_yield_curr) < 2.0 else '  ✅'
    print(f"    FCF Yield Current (wtd avg):   {p(fcf_yield_curr)}{vy_flag}")
    print(f"    FCF Yield Forward (wtd avg):   {p(fcf_yield_fwd)}")
    print(f"    Forward P/E (wtd avg):         {x(pe_forward)}")
    print(f"    EV/EBITDA (wtd avg):           {x(ev_ebitda)}")

    print(f"\n  CAPITAL ALLOCATION")
    nd_flag = '  ✅' if nd_ebitda and float(nd_ebitda) <= 2.0 else '  ⚠️  LEVERAGE_ELEVATED'
    print(f"    Net Debt/EBITDA (wtd avg):     {x(nd_ebitda)}{nd_flag}")
    print(f"    Buyback Yield (wtd avg):       {'Pending FMP' if buyback_yield is None else p(buyback_yield)}")

    print(f"\n  RISK & SENTIMENT")
    print(f"    Short Interest (wtd avg):      {p(short_interest) if short_interest else 'N/A'}")
    pr_flag = '  ✅' if pos_revisions and pos_revisions >= 40 else '  ⚠️ '
    print(f"    Positive Revision Velocity:    {f'{pos_revisions:.0f}%' if pos_revisions is not None else 'N/A (pending)'}{pr_flag if pos_revisions is not None else ''}")
    print(f"    Earnings Beat Rate (TTM):      {f'{beat_rate:.0f}%' if beat_rate else 'N/A'}")
    corr_flag = '  ✅' if avg_corr and float(avg_corr) <= 0.65 else ('  ⚠️  HIGH_CORRELATION' if avg_corr else '')
    print(f"    Avg Pairwise Correlation:      {n2(avg_corr) if avg_corr else 'N/A (need 90d history)'}{corr_flag}")

    print(f"\n  CONCENTRATION")
    for sector, count in sorted(sector_counts.items(), key=lambda kv: -kv[1]):
        pct_s = count/n*100
        flag  = '  🚨 ABOVE 28% CAP' if sector == 'Information Technology' and pct_s > 28 else ''
        print(f"    {str(sector)[:35]:<35}  {pct_s:.1f}%{flag}")
    print(f"    Effective N:                    {n}")

    if flags:
        print(f"\n  🚨 FLAGS: {', '.join(flags)}")
    else:
        print(f"\n  ✅  No threshold breaches")
    print(f"{'═'*62}")

    # ── Save snapshot ──────────────────────────────────────────────────────────
    if save_snapshot:
        cur.execute("""
            INSERT INTO factor_snapshots (
                snapshot_date,
                wtd_avg_fwd_revenue_growth, wtd_avg_momentum_3m, wtd_avg_momentum_12m,
                wtd_avg_beta, wtd_avg_market_cap,
                wtd_avg_roic, wtd_avg_gross_margin, wtd_avg_fcf_margin,
                wtd_avg_fcf_conversion, wtd_avg_roic_spread,
                wtd_avg_fcf_yield_current, wtd_avg_fcf_yield_forward,
                wtd_avg_pe_forward, wtd_avg_ev_ebitda,
                wtd_avg_net_debt_ebitda, wtd_avg_buyback_yield,
                wtd_avg_short_interest, pct_positive_revisions,
                pct_earnings_beats_ttm, avg_pairwise_correlation,
                it_sector_pct, top5_concentration_pct, effective_n,
                flags, n_holdings
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            date.today(),
            fwd_rev_growth, momentum_3m, momentum_12m, beta, market_cap,
            roic, gross_margin, fcf_margin, fcf_conv, roic_spread,
            fcf_yield_curr, fcf_yield_fwd, pe_forward, ev_ebitda,
            nd_ebitda, buyback_yield, short_interest,
            pos_revisions, beat_rate, avg_corr,
            it_pct, 20.0, float(n),
            json.dumps(flags), n
        ))
        print(f"\n  ✅  Snapshot written to factor_snapshots · {date.today()}")

    # ── Save HTML ──────────────────────────────────────────────────────────────
    if save_html:
        html = _generate_html(
            n, fwd_rev_growth, momentum_3m, momentum_12m, beta, market_cap,
            roic, gross_margin, fcf_margin, fcf_conv, roic_spread,
            fcf_yield_curr, fcf_yield_fwd, pe_forward, ev_ebitda,
            nd_ebitda, buyback_yield, short_interest,
            pos_revisions, beat_rate, avg_corr,
            it_pct, sector_counts, flags
        )
        today_str = date.today().strftime("%Y-%m-%d")
        for path in [REPORTS / f"factor_exposure_{today_str}.html",
                     DOCS / "factor_exposure.html"]:
            path.write_text(html, encoding='utf-8')
        print(f"  📄  HTML → factor_exposure_{today_str}.html")

    cur.close()
    conn.close()


def _generate_html(n, fwd_rev_growth, momentum_3m, momentum_12m, beta, market_cap,
                   roic, gross_margin, fcf_margin, fcf_conv, roic_spread,
                   fcf_yield_curr, fcf_yield_fwd, pe_forward, ev_ebitda,
                   nd_ebitda, buyback_yield, short_interest,
                   pos_revisions, beat_rate, avg_corr,
                   it_pct, sector_counts, flags) -> str:
    run_ts = datetime.now().strftime("%B %d, %Y · %I:%M %p")

    def p(v): return f"{float(v):.1f}%" if v is not None else "N/A"
    def x(v): return f"{float(v):.1f}x" if v is not None else "N/A"
    def n2(v): return f"{float(v):.2f}" if v is not None else "N/A"

    flag_html = ''.join(
        f'<span style="background:#2d1b1b;color:#ff6b6b;padding:3px 10px;border-radius:4px;font-size:12px;font-weight:700;margin-right:6px">{f}</span>'
        for f in flags
    ) or '<span style="background:#1b2d1b;color:#00aa44;padding:3px 10px;border-radius:4px;font-size:12px;font-weight:700">✅ No breaches</span>'

    sector_rows = ''.join(
        f'<tr><td style="padding:7px 10px">{s}</td><td style="padding:7px 10px;text-align:center">{c}</td>'
        f'<td style="padding:7px 10px;font-weight:700;color:{"#ff6b6b" if s=="Information Technology" and c/n*100>28 else "#e6edf3"}">{c/n*100:.1f}%{"  🚨" if s=="Information Technology" and c/n*100>28 else ""}</td></tr>'
        for s, c in sorted(sector_counts.items(), key=lambda kv: -kv[1])
    )

    def row(label, val, ok_fn=None, note="", raw_val=None):
        # ok_fn receives raw_val (numeric) not the formatted string
        check_val = raw_val if raw_val is not None else val
        ok = None if ok_fn is None else ok_fn(check_val)
        icon = "" if ok is None else ("✅" if ok else "⚠️")
        color = "#e6edf3" if ok is None else ("#00aa44" if ok else "#C9A84C")
        note_html = f' <span style="font-size:11px;color:#6b7280">{note}</span>' if note else ""
        return f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #21262d;font-size:13px"><span style="color:#8b949e">{label}</span><span style="font-weight:600;color:{color}">{val} {icon}{note_html}</span></div>'

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>IC Factor Exposure — {date.today()}</title>
<style>
  body{{font-family:Calibri,sans-serif;background:#0d1117;color:#e6edf3;margin:0}}
  .hdr{{background:#1F3A5F;border-bottom:3px solid #C9A84C;padding:20px 32px}}
  .hdr h1{{color:#fff;font-size:18px;margin:0}}
  .hdr .sub{{color:#C9A84C;font-size:12px;margin-top:4px}}
  .body{{max-width:960px;margin:0 auto;padding:24px 20px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}}
  .card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:18px}}
  .card h3{{color:#C9A84C;font-size:12px;text-transform:uppercase;letter-spacing:1px;margin:0 0 12px;border-bottom:1px solid #21262d;padding-bottom:8px}}
  table{{width:100%;border-collapse:collapse}}
  th{{background:#1F3A5F;color:#fff;padding:8px 10px;text-align:left;font-size:12px}}
  td{{padding:7px 10px;border-bottom:1px solid #21262d;font-size:13px;color:#8b949e}}
  .footer{{background:#1F3A5F;color:rgba(255,255,255,0.4);text-align:center;padding:14px;font-size:11px;margin-top:20px}}
  @media(max-width:600px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body>
<div class="hdr">
  <h1>INTEGRITY COMPOUNDERS — FACTOR EXPOSURE REPORT</h1>
  <div class="sub">{date.today()}  ·  {n} Holdings  ·  {100/n:.1f}% Equal Weight</div>
</div>
<div class="body">
  <div style="margin-bottom:16px">{flag_html}</div>
  <div class="grid">
    <div class="card"><h3>Style Factors</h3>
      {row("Fwd Revenue Growth", p(fwd_rev_growth))}
      {row("Momentum 3M", p(momentum_3m))}
      {row("Momentum 12M", p(momentum_12m))}
      {row("Beta to SPY", n2(beta), lambda v: v is None or float(v)<=1.3, "limit 1.3", raw_val=beta)}
      {row("Market Cap", f"${float(market_cap)/1e9:.0f}B" if market_cap and float(market_cap)>=1e9 else "N/A")}
    </div>
    <div class="card"><h3>Quality Factors</h3>
      {row("ROIC", p(roic), lambda v: v is not None and float(v)>=12, "floor 12%", raw_val=roic)}
      {row("Gross Margin", p(gross_margin), lambda v: v is not None and float(v)>=35, "floor 35%", raw_val=gross_margin)}
      {row("FCF Margin", p(fcf_margin), lambda v: v is not None and float(v)>=10, "floor 10%", raw_val=fcf_margin)}
      {row("FCF Conversion", p(fcf_conv))}
      {row("ROIC Spread", p(roic_spread), lambda v: v is not None and float(v)>0, "vs 8% WACC", raw_val=roic_spread)}
    </div>
    <div class="card"><h3>Valuation Factors</h3>
      {row("FCF Yield (current)", p(fcf_yield_curr), lambda v: v is not None and float(v)>=2, "min 2%", raw_val=fcf_yield_curr)}
      {row("FCF Yield (forward)", p(fcf_yield_fwd))}
      {row("Forward P/E", x(pe_forward))}
      {row("EV/EBITDA", x(ev_ebitda))}
    </div>
    <div class="card"><h3>Risk & Sentiment</h3>
      {row("Net Debt/EBITDA", x(nd_ebitda), lambda v: v is not None and float(v)<=2.0, "limit 2.0x", raw_val=nd_ebitda)}
      {row("Short Interest", p(short_interest) if short_interest else "N/A")}
      {row("Positive Revisions", f"{pos_revisions:.0f}%" if pos_revisions else "N/A", lambda v: v is not None and v != 'N/A' and float(v)>=40, "min 40%", raw_val=pos_revisions)}
      {row("Earnings Beat TTM", f"{beat_rate:.0f}%" if beat_rate else "N/A")}
      {row("Pairwise Correlation", n2(avg_corr) if avg_corr else "N/A", lambda v: v is not None and v != 'N/A' and float(v)<=0.65, "limit 0.65", raw_val=avg_corr)}
    </div>
  </div>
  <div class="card"><h3>Sector Concentration</h3>
    <table>
      <tr><th>Sector</th><th>Holdings</th><th>Weight</th></tr>
      {sector_rows}
    </table>
  </div>
</div>
<div class="footer">Integrity Compounders · Alpha System v11.0 · {run_ts} · Internal Use Only</div>
</body></html>"""


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--html',     action='store_true')
    parser.add_argument('--snapshot', action='store_true')
    args = parser.parse_args()
    run_factor_exposure(save_html=args.html, save_snapshot=args.snapshot)
