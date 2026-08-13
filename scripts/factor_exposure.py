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


def compute_pairwise_correlation(cur, tickers, days=90):
    """Average pairwise correlation of daily returns over `days`.

    Reads ic_price_history (dense daily bars). The previous implementation read
    company_market_data, which only holds a handful of snapshot dates — so this
    always returned N/A and the 0.65 correlation hard rule was unenforceable.
    Dates are properly aligned before correlating (the old version truncated each
    series to a common LENGTH, which silently correlated mismatched dates).
    """
    try:
        import pandas as pd
        cur.execute("""
            SELECT ticker, price_date, adj_close
            FROM ic_price_history
            WHERE ticker = ANY(%s) AND price_date >= %s AND adj_close IS NOT NULL
            ORDER BY price_date
        """, (list(tickers), date.today() - timedelta(days=days)))
        rows = cur.fetchall()
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["ticker", "d", "px"])
        df["px"] = df["px"].astype(float)
        wide = df.pivot(index="d", columns="ticker", values="px").sort_index()
        rets = wide.pct_change().dropna(how="all")
        rets = rets.loc[:, rets.notna().sum() > 10]          # need a usable series
        rets = rets.dropna()                                  # align on common dates
        if rets.shape[1] < 2 or len(rets) < 10:
            return None
        cm = rets.corr()
        cols = list(cm.columns)
        pairs = [(cols[i], cols[j], float(cm.iloc[i, j]))
                 for i in range(len(cols)) for j in range(i + 1, len(cols))]
        if not pairs:
            return None, []
        avg = round(float(np.mean([p[2] for p in pairs])), 4)
        # The rule is a PAIRWISE limit (0.65). Averaging 300+ pairs can never breach it,
        # so also return the individual pairs that do.
        over = sorted([p for p in pairs if p[2] > 0.65], key=lambda x: -x[2])
        return avg, over
    except Exception as e:
        print(f"  ⚠️  Correlation failed: {e}")
        return None, []


def run_factor_exposure(save_html: bool = False, save_snapshot: bool = False):
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        SELECT c.id, c.ticker, c.sector,
               ph.weight_actual,
               cmd.roic_trailing, cmd.gross_margin_trailing, cmd.fcf_margin_trailing,
               cmd.fwd_revenue_3y_cagr, cmd.net_debt_ebitda,
               cmd.fcf_yield_current, cmd.fcf_yield_forward,
               cmd.pe_forward, cmd.ev_ebitda, cmd.market_cap,
               cmd.beta, cmd.momentum_3m, cmd.momentum_6m, cmd.momentum_12m, cmd.mom_12m_return,
               cmd.fcf_conversion, cmd.roic_spread, cmd.buyback_yield,
               cmd.short_interest_pct, cmd.institutional_own_pct,
               cmd.revision_velocity_revenue
        FROM companies c
        JOIN LATERAL (
            SELECT * FROM company_market_data
            WHERE company_id = c.id ORDER BY data_date DESC LIMIT 1
        ) cmd ON TRUE
        LEFT JOIN LATERAL (
            SELECT weight_actual FROM ic_portfolio_holdings ph2
            WHERE ph2.ticker = c.ticker ORDER BY ph2.snapshot_date DESC LIMIT 1
        ) ph ON TRUE
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

    # Position weights. The book is no longer strictly 1/N (2% starters / trims coexist
    # with 4% positions), so every aggregate must weight by actual position size —
    # a simple mean overstates the small positions and misstates sector concentration.
    def _w(h):
        v = h[ci['weight_actual']]
        return float(v) if v is not None and float(v) > 0 else (100.0 / n)

    def wavg(field):
        pairs = [(_w(h), float(h[ci[field]])) for h in holdings if h[ci[field]] is not None]
        tw = sum(w for w, _ in pairs)
        return round(sum(w * v for w, v in pairs) / tw, 4) if tw else None

    # ── Compute all factors ────────────────────────────────────────────────────
    # Style
    fwd_rev_growth = wavg('fwd_revenue_3y_cagr')
    momentum_3m    = wavg('momentum_3m')
    momentum_6m    = wavg('momentum_6m')
    momentum_12m   = wavg('momentum_12m')
    if momentum_12m is None:            # momentum_12m is unpopulated; V12.1 writes mom_12m_return (decimal)
        _m = wavg('mom_12m_return')
        momentum_12m = round(_m * 100, 4) if _m is not None else None
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
    tickers  = [h[ci['ticker']] for h in holdings]
    avg_corr, corr_pairs_over = compute_pairwise_correlation(cur, tickers)

    # Sector concentration
    sector_counts: dict[str, float] = {}
    for h in holdings:
        s = h[ci['sector']] or 'Unknown'
        sector_counts[s] = sector_counts.get(s, 0.0) + _w(h)
    _totw = sum(sector_counts.values()) or 1.0
    sector_counts = {s: round(w / _totw * 100, 1) for s, w in sector_counts.items()}   # % of NAV
    it_pct = round(sector_counts.get('Information Technology', 0.0), 1)

    # ── Flags ──────────────────────────────────────────────────────────────────
    flags = []
    # The 28% cap is a SECTOR rule, not an IT rule — flag any sector over the cap.
    for _s, _p in sorted(sector_counts.items(), key=lambda kv: -kv[1]):
        if _p > 28:
            flags.append('IT_SECTOR_CAP_BREACH' if _s == 'Information Technology'
                         else f'SECTOR_CAP_BREACH:{_s}')
    if beta and float(beta) > 1.3:                           flags.append('HIGH_BETA_PORTFOLIO')
    if nd_ebitda and float(nd_ebitda) > 2.0:                flags.append('LEVERAGE_ELEVATED')
    if avg_corr and float(avg_corr) > 0.65:                 flags.append('HIGH_CORRELATION')
    if corr_pairs_over:                                      flags.append(f'CORRELATION_PAIR_BREACH:{len(corr_pairs_over)}')
    if pos_revisions is not None and pos_revisions < 40:    flags.append('REVISION_MOMENTUM_WEAK')
    if fcf_yield_curr and float(fcf_yield_curr) < 2.0:      flags.append('VALUATION_STRETCHED')

    # ── Terminal output ────────────────────────────────────────────────────────
    def p(v): return f"{float(v):.1f}%" if v is not None else "N/A"
    def x(v): return f"{float(v):.1f}x" if v is not None else "N/A"
    def n2(v): return f"{float(v):.2f}" if v is not None else "N/A"

    print(f"\n{'═'*62}")
    print(f"  INTEGRITY COMPOUNDERS — FACTOR EXPOSURE REPORT")
    print(f"  {date.today()}  |  {n} Holdings  |  position-weighted (largest {max(_w(h) for h in holdings):.1f}%)")
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
    if corr_pairs_over:
        print(f"    Pairs over 0.65 limit:         {len(corr_pairs_over)}  🚨")
        for _a, _b, _v in corr_pairs_over[:6]:
            print(f"        {_a}-{_b}: {_v:+.2f}")

    print(f"\n  CONCENTRATION")
    for sector, pct_s in sorted(sector_counts.items(), key=lambda kv: -kv[1]):
        flag  = '  🚨 ABOVE 28% CAP' if pct_s > 28 else ''
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


# ═══════════════════════════════════════════════════════════════════════════
# PORTFOLIO FACTOR-EXPOSURE CHART ENGINE  (rebuilt · V12.1)
# Six canonical factor ETFs measured as EXCESS return vs SPY. Per-factor
# univariate exposure (β + bps per 2σ), σ-distance-from-200DMA drift (same
# extension methodology as the V12.1 momentum engine), and rolling exposures.
# Entry point: build_portfolio_factor_charts(conn) -> (dynamic, drift, bps) HTML.
# ═══════════════════════════════════════════════════════════════════════════
import pandas as pd

_NAVY = "#1F3A5F"
FACTOR_ETFS = {'Value': 'VLUE', 'Momentum': 'MTUM', 'Quality': 'QUAL',
               'Low Vol': 'USMV', 'Size': 'IWM', 'Growth': 'IWF'}
MARKET_ETF = 'SPY'
FACTOR_ORDER = list(FACTOR_ETFS)
FACTOR_DEFINITIONS = FACTOR_ETFS
FACTOR_START_DATE = '2023-01-01'       # price-load start (200-DMA + z-score warmup)
ROLLING_WINDOW = 63                    # ~3 months for rolling β
FACTOR_TOLERANCE_BPS = 50.0
_SMA_WIN, _Z_WIN = 200, 252
_FCOLORS = {'Value': '#2a78d6', 'Momentum': '#1baf7a', 'Quality': '#4a3aa7',
            'Low Vol': '#eda100', 'Size': '#e34948', 'Growth': '#e87ba4'}


def _load_prices(conn, tickers, start=FACTOR_START_DATE):
    cur = conn.cursor()
    cur.execute("""SELECT ticker, price_date, adj_close FROM ic_price_history
                   WHERE ticker = ANY(%s) AND price_date >= %s AND adj_close IS NOT NULL
                   ORDER BY price_date""", (list(tickers), start))
    rows = cur.fetchall(); cur.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=['ticker', 'date', 'px'])
    df['date'] = pd.to_datetime(df['date']); df['px'] = df['px'].astype(float)
    return df.pivot(index='date', columns='ticker', values='px').sort_index()


def _spy_returns(conn):
    px = _load_prices(conn, [MARKET_ETF])
    return px[MARKET_ETF].pct_change() if (not px.empty and MARKET_ETF in px) else pd.Series(dtype=float)


def get_portfolio_daily_returns(conn, start_date=FACTOR_START_DATE):
    cur = conn.cursor()
    cur.execute("SELECT ticker FROM companies WHERE in_portfolio=TRUE AND active=TRUE")
    tks = [r[0] for r in cur.fetchall()]; cur.close()
    px = _load_prices(conn, tks, start_date)
    if px.empty:
        return None
    return px.pct_change().mean(axis=1, skipna=True).dropna()      # equal weight


def get_factor_etf_returns(conn, start_date=FACTOR_START_DATE):
    px = _load_prices(conn, list(FACTOR_ETFS.values()) + [MARKET_ETF], start_date)
    if px.empty or MARKET_ETF not in px:
        return pd.DataFrame()
    rets = px.pct_change(); spy = rets[MARKET_ETF]
    return pd.DataFrame({f: rets[etf] - spy for f, etf in FACTOR_ETFS.items() if etf in rets}).dropna(how='all')


def compute_factor_exposures_bps(port_rets, factor_excess, spy_rets):
    port_ex = (port_rets - spy_rets).dropna()
    out = {}
    for f in FACTOR_ORDER:
        if f not in factor_excess:
            continue
        j = pd.concat([port_ex, factor_excess[f]], axis=1, keys=['p', 'f']).dropna()
        if len(j) < 60:
            continue
        var = j['f'].var()
        beta = (j['p'].cov(j['f']) / var) if var > 0 else 0.0
        bps = beta * (2 * j['f'].std()) * 1e4
        r = j['p'].corr(j['f'])
        out[f] = {'beta': round(float(beta), 4), 'r_squared': round(float(r * r), 3),
                  'bps_per_2sigma': round(float(bps), 1),
                  'within_tolerance': bool(abs(bps) <= FACTOR_TOLERANCE_BPS)}
    return out


def compute_all_factor_drifts(conn, start_display):
    px = _load_prices(conn, list(FACTOR_ETFS.values()) + [MARKET_ETF])
    if px.empty or MARKET_ETF not in px:
        return {}
    rets = px.pct_change(); spy = rets[MARKET_ETF]
    drifts = {}
    for f, etf in FACTOR_ETFS.items():
        if etf not in rets:
            continue
        ex = (rets[etf] - spy).dropna()
        rs = (1 + ex).cumprod()                              # relative-strength vs market
        dist = (rs - rs.rolling(_SMA_WIN).mean()) / rs.rolling(_SMA_WIN).mean()
        z = (dist - dist.rolling(_Z_WIN).mean()) / dist.rolling(_Z_WIN).std()
        s = pd.DataFrame({'z': z}).dropna()
        drifts[f] = s[s.index >= pd.to_datetime(start_display)]
    return drifts


def compute_rolling_factor_exposures(port_rets, factor_excess, spy_rets, window=ROLLING_WINDOW):
    port_ex = (port_rets - spy_rets).dropna()
    out = {}
    for f in FACTOR_ORDER:
        if f not in factor_excess:
            continue
        j = pd.concat([port_ex, factor_excess[f]], axis=1, keys=['p', 'f']).dropna()
        # min_periods: expanding warm-up so rolling β starts near portfolio
        # inception (2025-10-10) rather than 63 trading days in (~Jan 2026).
        out[f] = (j['p'].rolling(window, min_periods=21).cov(j['f'])
                  / j['f'].rolling(window, min_periods=21).var()).dropna()
    return pd.DataFrame(out)


def _fig_html(fig, first=False):
    return fig.to_html(full_html=False, include_plotlyjs=('cdn' if first else False),
                       config={'displayModeBar': False})


def _base_layout(fig, title, height):
    fig.update_layout(title={'text': title, 'font': {'size': 13, 'color': _NAVY, 'family': 'Calibri'}, 'x': 0.5},
                      font={'family': 'Calibri', 'color': '#333', 'size': 11},
                      paper_bgcolor='#ffffff', plot_bgcolor='#f8f9fa',
                      height=height, margin={'l': 50, 'r': 25, 't': 55, 'b': 40}, showlegend=False)
    return fig


def generate_factor_drift_chart(drifts, first=False):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    facs = [f for f in FACTOR_ORDER if f in drifts and not drifts[f].empty]
    if not facs:
        return ""
    fig = make_subplots(rows=2, cols=3, subplot_titles=facs, vertical_spacing=0.16, horizontal_spacing=0.07)
    for i, f in enumerate(facs):
        r, c = i // 3 + 1, i % 3 + 1
        s = drifts[f]
        fig.add_trace(go.Scatter(x=s.index, y=s['z'], mode='lines',
                      line={'color': _FCOLORS.get(f, _NAVY), 'width': 1.5}, fill='tozeroy',
                      fillcolor='rgba(31,58,95,0.06)'), row=r, col=c)
        for yb, dash in ((2, 'dot'), (-2, 'dot'), (0, 'solid')):
            fig.add_hline(y=yb, line={'color': '#C9A84C' if yb else '#888', 'width': 0.8,
                          'dash': dash}, row=r, col=c)
        fig.update_yaxes(title_text='σ' if c == 1 else '', range=[-3.2, 3.2], row=r, col=c,
                         gridcolor='#eee', zeroline=False, tickfont={'size': 9})
        fig.update_xaxes(gridcolor='#eee', tickfont={'size': 9}, row=r, col=c)
    for a in fig['layout']['annotations']:
        a['font'] = {'size': 11, 'color': _NAVY, 'family': 'Calibri'}
    _base_layout(fig, 'Factor distance from 200-DMA — σ vs own trailing-year trend', 420)
    return _fig_html(fig, first)


def generate_bps_chart(bps, first=False):
    import plotly.graph_objects as go
    facs = [f for f in FACTOR_ORDER if f in bps]
    if not facs:
        return ""
    vals = [bps[f]['bps_per_2sigma'] for f in facs]
    colors = ['#1baf7a' if bps[f]['within_tolerance'] else '#e34948' for f in facs]
    fig = go.Figure(go.Bar(x=vals, y=facs, orientation='h', marker={'color': colors},
                    text=[f"{v:+.0f}" for v in vals], textposition='outside',
                    textfont={'size': 10}))
    for xb in (FACTOR_TOLERANCE_BPS, -FACTOR_TOLERANCE_BPS):
        fig.add_vline(x=xb, line={'color': '#C9A84C', 'width': 0.8, 'dash': 'dot'})
    fig.add_vline(x=0, line={'color': '#888', 'width': 0.8})
    fig.update_xaxes(title={'text': 'bps of portfolio daily return per 2σ factor move', 'font': {'size': 10}},
                     gridcolor='#eee', zeroline=False)
    fig.update_yaxes(categoryorder='array', categoryarray=facs[::-1], tickfont={'size': 11})
    _base_layout(fig, f'Factor bps per 2σ — six canonical factors (±{FACTOR_TOLERANCE_BPS:.0f} bps tolerance)', 300)
    return _fig_html(fig, first)


def generate_dynamic_factor_chart(rolling, port_rets, first=False):
    import plotly.graph_objects as go
    if rolling is None or rolling.empty:
        return ""
    fig = go.Figure()
    for f in FACTOR_ORDER:
        if f in rolling:
            fig.add_trace(go.Scatter(x=rolling.index, y=rolling[f], mode='lines', name=f,
                          line={'color': _FCOLORS.get(f, _NAVY), 'width': 1.6}))
    fig.add_hline(y=0, line={'color': '#888', 'width': 0.8})
    fig.update_xaxes(gridcolor='#eee', tickfont={'size': 10})
    fig.update_yaxes(title={'text': 'rolling β (excess vs SPY)', 'font': {'size': 10}}, gridcolor='#eee',
                     zeroline=False)
    _base_layout(fig, f'Rolling {ROLLING_WINDOW}-day factor exposure (β)', 320)
    fig.update_layout(showlegend=True, legend={'orientation': 'h', 'y': -0.18,
                      'font': {'size': 10}, 'x': 0.5, 'xanchor': 'center'})
    return _fig_html(fig, first)


def build_portfolio_factor_charts(conn, display_months=12):
    """Entry point → (dynamic_html, drift_html, bps_html). Raises on missing data."""
    from datetime import date, timedelta
    start_display = (date.today() - timedelta(days=int(display_months * 30.5))).isoformat()
    factor_excess = get_factor_etf_returns(conn)
    if factor_excess.empty:
        raise RuntimeError("no factor-ETF returns in ic_price_history")
    port = get_portfolio_daily_returns(conn)
    if port is None or len(port) < 60:
        raise RuntimeError(f"insufficient portfolio return history ({0 if port is None else len(port)} days)")
    spy = _spy_returns(conn)
    bps = compute_factor_exposures_bps(port, factor_excess, spy)
    drifts = compute_all_factor_drifts(conn, start_display)
    rolling = compute_rolling_factor_exposures(port, factor_excess, spy)
    if not rolling.empty:
        rolling = rolling[rolling.index >= pd.to_datetime(start_display)]
    dynamic_html = generate_dynamic_factor_chart(rolling, port, first=True)
    drift_html = generate_factor_drift_chart(drifts, first=not bool(dynamic_html))
    bps_html = generate_bps_chart(bps, first=not bool(dynamic_html) and not bool(drift_html))
    return dynamic_html, drift_html, bps_html


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--html',     action='store_true')
    parser.add_argument('--snapshot', action='store_true')
    args = parser.parse_args()
    run_factor_exposure(save_html=args.html, save_snapshot=args.snapshot)
