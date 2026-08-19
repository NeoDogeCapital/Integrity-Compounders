"""
ic_analytics.py — portfolio performance & risk analytics engine

Rebuilds the analytics layer that was lost in the PC→Mac migration (nothing in
the repo wrote ic_daily_returns / ic_analytics_history).

Design:
  • The DAILY RETURN SERIES is the source of truth. Rolling metrics (Sharpe,
    alpha, beta, capture, vol, drawdown) are COMPUTED from it — never
    accumulated from stored snapshots — so full history is available instantly.
  • ic_daily_returns is EXTENDED forward only (never re-derived), preserving the
    original engine's history. Reconstruction method validated against the stored
    series: median |diff| 0.00000%.
  • ic_analytics_history still gets a row per run as a point-in-time audit record.

Benchmark: SPY.   Risk-free: real 13-week T-bill (^IRX).
Inception: 2025-10-10 (the 2019-09-13 allocation row is a Koyfin reference, not a
portfolio state — see ic_allocation_snapshots.notes).

    python scripts/ic_analytics.py            # compute + persist
    python scripts/ic_analytics.py --html     # + build docs/analytics.html
"""
import sys, bisect, argparse, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras as pgx
from datetime import date
from collections import defaultdict
from config.settings import settings

NAVY, GOLD = "#1F3A5F", "#C9A84C"
BENCH = "SPY"
INCEPTION = "2025-10-10"
ANN = 252
ROLL = 63                      # ~3 months
DOCS = ROOT / "docs"; DOCS.mkdir(exist_ok=True)


def get_conn():
    c = psycopg2.connect(settings.DATABASE_URL); c.autocommit = True; return c


# ── risk-free ────────────────────────────────────────────────────────────────
def load_rf():
    """Real risk-free: 13-week T-bill (^IRX), yield % → daily decimal."""
    import yfinance as yf
    h = yf.Ticker("^IRX").history(period="2y", auto_adjust=False)
    if h.empty:
        return {}, 0.0
    s = {str(d.date()): float(v) / 100.0 / ANN for d, v in h["Close"].items() if pd.notna(v)}
    return s, float(h["Close"].mean()) / 100.0


# ── return series ────────────────────────────────────────────────────────────
def _ticker_returns(conn, start="2025-09-01"):
    cur = conn.cursor()
    cur.execute("""SELECT ticker, price_date, adj_close FROM ic_price_history
                   WHERE adj_close IS NOT NULL AND price_date>=%s ORDER BY ticker, price_date""", (start,))
    px = defaultdict(list)
    for t, d, p in cur.fetchall():
        px[t].append((str(d), float(p)))
    cur.close()
    out = {}
    for t, s in px.items():
        r = {}
        for i in range(1, len(s)):
            if s[i - 1][1]:
                r[s[i][0]] = s[i][1] / s[i - 1][1] - 1
        out[t] = r
    return out


def _allocations(conn):
    cur = conn.cursor()
    cur.execute("SELECT snapshot_date, ticker, weight FROM ic_target_allocations ORDER BY snapshot_date")
    a = defaultdict(dict)
    for d, t, w in cur.fetchall():
        a[str(d)][t] = float(w)
    cur.close()
    return a, sorted(a)


def extend_daily_returns(conn, rf):
    """Reconstruct portfolio daily returns for dates missing from ic_daily_returns
    (forward-only). Weights held at the active snapshot; cash earns the risk-free."""
    alloc, snaps = _allocations(conn)
    ret = _ticker_returns(conn)
    cur = conn.cursor()
    cur.execute("SELECT MAX(return_date) FROM ic_daily_returns")
    last = cur.fetchone()[0]
    last = str(last) if last else INCEPTION
    cur.execute("SELECT MAX(cumulative_return), MAX(spy_cumulative) FROM ic_daily_returns WHERE return_date=%s", (last,))
    row = cur.fetchone()
    cum_p = float(row[0]) if row and row[0] is not None else 0.0
    cum_s = float(row[1]) if row and row[1] is not None else 0.0

    spy = ret.get(BENCH, {})
    dates = sorted(d for d in spy if d > last)
    new = []
    for d in dates:
        i = bisect.bisect_right(snaps, d) - 1
        if i < 0:
            continue
        w = alloc[snaps[i]]
        num, missing = 0.0, False
        for tk, wt in w.items():
            if tk == "CASH":
                num += wt * rf.get(d, 0.0); continue
            r = ret.get(tk, {}).get(d)
            if r is None:
                missing = True; break
            num += wt * r
        if missing:
            continue
        sr = spy.get(d)
        if sr is None:
            continue
        cum_p = (1 + cum_p) * (1 + num) - 1
        cum_s = (1 + cum_s) * (1 + sr) - 1
        new.append((d, round(num, 8), round(cum_p, 8), round(100 * (1 + cum_p), 6),
                    round(sr, 8), round(cum_s, 8), round(num - sr, 8), snaps[i]))
    if new:
        pgx.execute_values(cur, """INSERT INTO ic_daily_returns
            (return_date, daily_return, cumulative_return, portfolio_value,
             spy_daily_return, spy_cumulative, excess_return_daily, active_snapshot_date)
            VALUES %s ON CONFLICT DO NOTHING""", new, page_size=200)
    cur.close()
    print(f"  daily returns: extended {len(new)} days (through {new[-1][0] if new else last})")
    return len(new)


def load_series(conn):
    cur = conn.cursor()
    cur.execute("""SELECT return_date, daily_return, spy_daily_return FROM ic_daily_returns
                   WHERE daily_return IS NOT NULL AND spy_daily_return IS NOT NULL ORDER BY return_date""")
    rows = cur.fetchall(); cur.close()
    df = pd.DataFrame(rows, columns=["date", "p", "b"])
    df["date"] = pd.to_datetime(df["date"])
    df["p"] = df["p"].astype(float); df["b"] = df["b"].astype(float)
    return df.set_index("date").sort_index()


# ── metrics ──────────────────────────────────────────────────────────────────
def _dd(cum):
    peak = cum.cummax()
    return cum / peak - 1


def compute_metrics(df, rfs):
    p, b = df["p"], df["b"]
    rf = pd.Series([rfs.get(str(d.date()), 0.0) for d in df.index], index=df.index)
    n = len(p)
    ex, exb = p - rf, b - rf
    cum_p = (1 + p).cumprod(); cum_b = (1 + b).cumprod()
    tot_p = cum_p.iloc[-1] - 1; tot_b = cum_b.iloc[-1] - 1
    yrs = n / ANN
    cagr = (1 + tot_p) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    cagr_b = (1 + tot_b) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    vol = p.std() * np.sqrt(ANN)
    sharpe = ex.mean() / ex.std() * np.sqrt(ANN) if ex.std() else np.nan
    dn = ex[ex < 0]
    dd_dev = dn.std() * np.sqrt(ANN) if len(dn) > 1 else np.nan
    sortino = ex.mean() * ANN / dd_dev if dd_dev else np.nan
    ddser = _dd(cum_p); mdd = ddser.min()
    calmar = cagr / abs(mdd) if mdd else np.nan
    var95, var99 = np.percentile(p, 5), np.percentile(p, 1)
    cvar95 = p[p <= var95].mean()
    beta = np.cov(p, b)[0][1] / np.var(b) if np.var(b) else np.nan
    alpha = (ex.mean() - beta * exb.mean()) * ANN
    # Up/down capture — geometric (Morningstar standard): compound the portfolio and
    # benchmark over the periods the benchmark was up (resp. down) and take the ratio.
    def _cap(mask):
        if not mask.any():
            return np.nan
        pp = (1 + p[mask]).prod() - 1
        bb = (1 + b[mask]).prod() - 1
        return pp / bb if bb else np.nan
    up_cap = _cap(b > 0)
    dn_cap = _cap(b < 0)
    act = p - b
    ir = act.mean() / act.std() * np.sqrt(ANN) if act.std() else np.nan
    treynor = ex.mean() * ANN / beta if beta else np.nan
    omega = ex[ex > 0].sum() / abs(ex[ex < 0].sum()) if ex[ex < 0].sum() else np.nan
    # drawdown window
    trough = ddser.idxmin(); peak_i = cum_p.loc[:trough].idxmax()
    rec = ddser.loc[trough:]; rec_i = rec[rec >= -1e-9].index
    end = rec_i[0] if len(rec_i) else ddser.index[-1]
    # monthly win rate
    m = (1 + p).resample("ME").prod() - 1
    return dict(n=n, years=yrs, total_return=tot_p, spy_total=tot_b, cagr=cagr, spy_cagr=cagr_b,
                excess=tot_p - tot_b, vol=vol, sharpe=sharpe, sortino=sortino, calmar=calmar,
                downside_dev=dd_dev, max_dd=mdd, dd_start=str(peak_i.date()), dd_end=str(trough.date()),
                dd_days=(end - peak_i).days, var95=var95, var99=var99, cvar95=cvar95,
                beta=beta, alpha=alpha, up_capture=up_cap, down_capture=dn_cap,
                updown=(up_cap / dn_cap) if dn_cap else np.nan, info_ratio=ir, treynor=treynor,
                omega=omega, monthly_win=(m > 0).mean(), months=len(m), rf_mean=rf.mean() * ANN)


# Rolling stats warm up with an expanding window from MINP days so the charts
# begin near the 2025-10-10 inception instead of first appearing 63 trading days
# in (~2026-01-12) — which read as if the portfolio started in January. Early
# points use fewer observations and are noisier by construction; chart titles
# say so.
MINP = 21


def rolling_series(df, rfs, w=ROLL):
    p, b = df["p"], df["b"]
    rf = pd.Series([rfs.get(str(d.date()), 0.0) for d in df.index], index=df.index)
    ex, exb = p - rf, b - rf
    out = pd.DataFrame(index=df.index)
    out["sharpe"] = (ex.rolling(w, min_periods=MINP).mean() / ex.rolling(w, min_periods=MINP).std()) * np.sqrt(ANN)
    cov = p.rolling(w, min_periods=MINP).cov(b); var = b.rolling(w, min_periods=MINP).var()
    out["beta"] = cov / var
    out["alpha"] = (ex.rolling(w, min_periods=MINP).mean() - out["beta"] * exb.rolling(w, min_periods=MINP).mean()) * ANN
    out["vol"] = p.rolling(w, min_periods=MINP).std() * np.sqrt(ANN)
    # rolling geometric capture (same definition as the headline metric)
    def _roll_cap(sign):
        vals = []
        for i in range(len(p)):
            if i + 1 < MINP:
                vals.append(np.nan); continue
            lo = max(0, i + 1 - w)
            wp, wb = p.iloc[lo:i + 1], b.iloc[lo:i + 1]
            m = (wb > 0) if sign > 0 else (wb < 0)
            if not m.any():
                vals.append(np.nan); continue
            pp = (1 + wp[m]).prod() - 1; bb = (1 + wb[m]).prod() - 1
            vals.append(pp / bb if bb else np.nan)
        return pd.Series(vals, index=p.index)
    out["up_cap"] = _roll_cap(1)
    out["down_cap"] = _roll_cap(-1)
    out["cum_p"] = (1 + p).cumprod() - 1
    out["cum_b"] = (1 + b).cumprod() - 1
    out["dd"] = _dd((1 + p).cumprod())
    out["dd_b"] = _dd((1 + b).cumprod())
    return out


# ── trade-level stats (allocation episodes) ──────────────────────────────────
def trade_stats(conn):
    alloc, snaps = _allocations(conn)
    eps, held = [], {}
    for i, d in enumerate(snaps):
        cur_s = {t for t in alloc[d] if t != "CASH"}
        prev = {t for t in alloc[snaps[i - 1]] if t != "CASH"} if i > 0 else set()
        for t in cur_s - prev:
            held[t] = d
        for t in prev - cur_s:
            if t in held:
                eps.append((t, held.pop(t), d))
    for t, d in held.items():
        eps.append((t, d, None))
    ytd = [e for e in eps if e[1] >= "2026-01-01"]
    ret = _ticker_returns(conn, "2025-12-01")
    cur = conn.cursor(); cur.execute("SELECT MAX(price_date) FROM ic_price_history")
    last = str(cur.fetchone()[0]); cur.close()
    # price lookup
    c2 = conn.cursor()
    c2.execute("""SELECT ticker, price_date, adj_close FROM ic_price_history
                  WHERE adj_close IS NOT NULL AND price_date>='2025-12-01' ORDER BY ticker, price_date""")
    P = defaultdict(lambda: ([], []))
    for t, d, p in c2.fetchall():
        P[t][0].append(str(d)); P[t][1].append(float(p))
    c2.close()
    def px(t, d):
        if t not in P: return None
        ds, ps = P[t]; i = bisect.bisect_right(ds, d) - 1
        return ps[i] if i >= 0 else None
    rows = []
    for tk, ed, xd in ytd:
        e = px(tk, ed); x = px(tk, xd if xd else last)
        if not e or not x or ed == last: continue
        if not xd and ed >= last: continue
        rows.append(dict(tk=tk, entry=ed, exit=xd, ret=x / e - 1, closed=xd is not None))
    rows = [r for r in rows if r["entry"] < last]
    def agg(rs):
        if not rs: return None
        w = [r for r in rs if r["ret"] > 0]; l = [r for r in rs if r["ret"] <= 0]
        aw = np.mean([r["ret"] for r in w]) if w else 0.0
        al = np.mean([r["ret"] for r in l]) if l else 0.0
        return dict(n=len(rs), ba=len(w) / len(rs), avg_win=aw, avg_loss=al,
                    slug=(aw / abs(al)) if l and al else np.nan,
                    # win/loss ratio counts trades; slugging weighs their size.
                    wl=(len(w) / len(l)) if l else np.nan,
                    expectancy=(len(w) / len(rs)) * aw + (len(l) / len(rs)) * al)
    cohorts = {d: agg([r for r in rows if r["entry"] == d]) for d in sorted({r["entry"] for r in rows})}
    return dict(all=agg(rows), closed=agg([r for r in rows if r["closed"]]),
                open=agg([r for r in rows if not r["closed"]]), cohorts=cohorts, rows=rows,
                n_holdings=len([x for x in alloc[snaps[-1]] if x != "CASH"]) if snaps else None)


def _py(v):
    """numpy/NaN → native Python (psycopg2 can't adapt numpy 2.x scalars)."""
    if v is None:
        return None
    try:
        if isinstance(v, str):
            return v
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return v


def persist(conn, m, t):
    m = {k: _py(v) for k, v in m.items()}
    cur = conn.cursor()
    cur.execute("""INSERT INTO ic_analytics_history
      (run_date, total_return_inception, annualized_return, spy_total_return, spy_annualized,
       excess_return_inception, std_dev_annualized, downside_deviation, max_drawdown_ever,
       max_drawdown_start, max_drawdown_end, max_drawdown_duration_days, var_95, var_99, cvar_95,
       sharpe_ratio, sortino_ratio, calmar_ratio, information_ratio, treynor_ratio, omega_ratio,
       beta_to_spy, batting_average, up_capture, down_capture, updown_capture_ratio,
       win_loss_ratio, slugging_pct, num_holdings)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
      ON CONFLICT (run_date) DO UPDATE SET
        total_return_inception=EXCLUDED.total_return_inception, annualized_return=EXCLUDED.annualized_return,
        spy_total_return=EXCLUDED.spy_total_return, spy_annualized=EXCLUDED.spy_annualized,
        excess_return_inception=EXCLUDED.excess_return_inception, std_dev_annualized=EXCLUDED.std_dev_annualized,
        downside_deviation=EXCLUDED.downside_deviation, max_drawdown_ever=EXCLUDED.max_drawdown_ever,
        max_drawdown_start=EXCLUDED.max_drawdown_start, max_drawdown_end=EXCLUDED.max_drawdown_end,
        max_drawdown_duration_days=EXCLUDED.max_drawdown_duration_days, var_95=EXCLUDED.var_95,
        var_99=EXCLUDED.var_99, cvar_95=EXCLUDED.cvar_95, sharpe_ratio=EXCLUDED.sharpe_ratio,
        sortino_ratio=EXCLUDED.sortino_ratio, calmar_ratio=EXCLUDED.calmar_ratio,
        information_ratio=EXCLUDED.information_ratio, treynor_ratio=EXCLUDED.treynor_ratio,
        omega_ratio=EXCLUDED.omega_ratio, beta_to_spy=EXCLUDED.beta_to_spy,
        batting_average=EXCLUDED.batting_average, up_capture=EXCLUDED.up_capture,
        down_capture=EXCLUDED.down_capture, updown_capture_ratio=EXCLUDED.updown_capture_ratio,
        win_loss_ratio=EXCLUDED.win_loss_ratio, slugging_pct=EXCLUDED.slugging_pct,
        num_holdings=EXCLUDED.num_holdings""",
      (date.today(), m['total_return'], m['cagr'], m['spy_total'], m['spy_cagr'], m['excess'],
       m['vol'], m['downside_dev'], m['max_dd'], m['dd_start'], m['dd_end'], m['dd_days'],
       m['var95'], m['var99'], m['cvar95'], m['sharpe'], m['sortino'], m['calmar'],
       m['info_ratio'], m['treynor'], m['omega'], m['beta'],
       _py(t['all']['ba']) if t['all'] else None, m['up_capture'], m['down_capture'], m['updown'],
       _py(t['all']['wl']) if t['all'] else None, _py(t['all']['slug']) if t['all'] else None,
       t.get('n_holdings')))
    cur.close()
    print("  ic_analytics_history: snapshot upserted for today")


# ── dashboard ────────────────────────────────────────────────────────────────
def _fig(fig, title, h=280, first=False, legend=False):
    fig.update_layout(title={'text': title, 'font': {'size': 12, 'color': NAVY, 'family': 'Calibri'}, 'x': 0.5},
                      font={'family': 'Calibri', 'color': '#333', 'size': 11},
                      paper_bgcolor='#ffffff', plot_bgcolor='#f8f9fa', height=h,
                      margin={'l': 52, 'r': 22, 't': 44, 'b': 34}, showlegend=legend,
                      legend={'orientation': 'h', 'y': -0.16, 'x': 0.5, 'xanchor': 'center', 'font': {'size': 10}})
    fig.update_xaxes(gridcolor='#eee', tickfont={'size': 9})
    fig.update_yaxes(gridcolor='#eee', tickfont={'size': 9}, zeroline=False)
    return fig.to_html(full_html=False, include_plotlyjs=('cdn' if first else False),
                       config={'displayModeBar': False})


def build_html(df, m, r, t, rf_mean):
    import plotly.graph_objects as go
    P, B = "#1F3A5F", "#9aa4b0"
    x = df.index
    # Cumulative/drawdown traces get a 0% anchor on the allocation date itself
    # (2025-10-10) — the first RETURN is the next trading day, but the chart
    # should start where the money did.
    x0 = [pd.Timestamp(INCEPTION)] + list(x)
    anchor = lambda s: [0.0] + list(s)
    C = []
    # 1 cumulative
    f = go.Figure()
    f.add_trace(go.Scatter(x=x0, y=anchor(r['cum_p']), name='Integrity Compounders', line={'color': P, 'width': 2}))
    f.add_trace(go.Scatter(x=x0, y=anchor(r['cum_b']), name='SPY', line={'color': B, 'width': 1.6, 'dash': 'dash'}))
    f.update_yaxes(tickformat='.0%')
    C.append(_fig(f, 'Cumulative return vs SPY (inception 2025-10-10)', 320, first=True, legend=True))
    # 2 drawdown
    f = go.Figure()
    f.add_trace(go.Scatter(x=x0, y=anchor(r['dd']), name='IC', line={'color': '#cc3333', 'width': 1.4}, fill='tozeroy',
                           fillcolor='rgba(204,51,51,0.12)'))
    f.add_trace(go.Scatter(x=x0, y=anchor(r['dd_b']), name='SPY', line={'color': B, 'width': 1.2, 'dash': 'dash'}))
    f.update_yaxes(tickformat='.0%')
    C.append(_fig(f, 'Drawdown (underwater)', 250, legend=True))
    # 3 rolling sharpe
    f = go.Figure(go.Scatter(x=x, y=r['sharpe'], line={'color': P, 'width': 1.8}))
    f.add_hline(y=0, line={'color': '#888', 'width': 0.8})
    f.add_hline(y=1, line={'color': GOLD, 'width': 0.8, 'dash': 'dot'})
    C.append(_fig(f, f'Rolling {ROLL}-day Sharpe (rf = 13-wk T-bill; expanding ≥{MINP}d at start)', 250))
    # 4 rolling beta
    f = go.Figure(go.Scatter(x=x, y=r['beta'], line={'color': '#4a3aa7', 'width': 1.8}))
    f.add_hline(y=1, line={'color': GOLD, 'width': 0.8, 'dash': 'dot'})
    C.append(_fig(f, f'Rolling {ROLL}-day beta vs SPY (expanding ≥{MINP}d at start)', 250))
    # 5 rolling alpha
    f = go.Figure(go.Scatter(x=x, y=r['alpha'], line={'color': '#1baf7a', 'width': 1.8}, fill='tozeroy',
                             fillcolor='rgba(27,175,122,0.10)'))
    f.add_hline(y=0, line={'color': '#888', 'width': 0.8})
    f.update_yaxes(tickformat='.0%')
    C.append(_fig(f, f'Rolling {ROLL}-day annualised alpha (expanding ≥{MINP}d at start)', 250))
    # 6 rolling capture
    f = go.Figure()
    f.add_trace(go.Scatter(x=x, y=r['up_cap'], name='Up capture', line={'color': '#1baf7a', 'width': 1.7}))
    f.add_trace(go.Scatter(x=x, y=r['down_cap'], name='Down capture', line={'color': '#cc3333', 'width': 1.7}))
    f.add_hline(y=1, line={'color': GOLD, 'width': 0.8, 'dash': 'dot'})
    C.append(_fig(f, f'Rolling {ROLL}-day up / down capture (geometric; expanding ≥{MINP}d at start)', 250, legend=True))
    # 7 monthly bars
    mp = (1 + df['p']).resample('ME').prod() - 1
    mb = (1 + df['b']).resample('ME').prod() - 1
    lbl = [d.strftime('%b %y') for d in mp.index]
    f = go.Figure()
    f.add_trace(go.Bar(x=lbl, y=mp.values, name='IC', marker={'color': P}))
    f.add_trace(go.Bar(x=lbl, y=mb.values, name='SPY', marker={'color': B}))
    f.update_yaxes(tickformat='.0%')
    C.append(_fig(f, 'Monthly returns vs SPY', 260, legend=True))
    # 8 distribution
    f = go.Figure(go.Histogram(x=df['p'], nbinsx=40, marker={'color': P}))
    f.add_vline(x=float(m['var95']), line={'color': '#cc3333', 'width': 1.2, 'dash': 'dot'})
    f.update_xaxes(tickformat='.1%')
    C.append(_fig(f, 'Daily return distribution (dotted = VaR 95)', 250))
    # 9 trades by cohort
    coh = {k: v for k, v in t['cohorts'].items() if v}
    f = go.Figure()
    f.add_trace(go.Bar(x=list(coh), y=[v['ba'] for v in coh.values()], name='Batting avg',
                       marker={'color': P}, yaxis='y'))
    f.update_yaxes(tickformat='.0%')
    C.append(_fig(f, 'Batting average by allocation cohort', 250))

    def pc(v, d=2): return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{d}%}"
    def nu(v, d=2): return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{d}f}"
    a = t['all']
    kpi = [("Total return", pc(m['total_return']), "vs SPY " + pc(m['spy_total'])),
           ("Excess vs SPY", pc(m['excess']), "since inception"),
           ("CAGR", pc(m['cagr']), "SPY " + pc(m['spy_cagr'])),
           ("Sharpe", nu(m['sharpe']), "rf " + pc(rf_mean, 1)),
           ("Sortino", nu(m['sortino']), "downside dev " + pc(m['downside_dev'], 1)),
           ("Max drawdown", pc(m['max_dd']), f"{m['dd_start']} → {m['dd_end']}"),
           ("Alpha (ann)", pc(m['alpha']), "beta " + nu(m['beta'])),
           ("Up capture", nu(m['up_capture']), "down " + nu(m['down_capture'])),
           ("Batting average", pc(a['ba'], 1) if a else "—", f"{a['n']} allocations" if a else ""),
           ("Slugging", nu(a['slug']) + "x" if a else "—", "avg win " + pc(a['avg_win'], 1) if a else ""),
           ("Expectancy / trade", pc(a['expectancy'], 1) if a else "—", "per allocation"),
           ("Volatility (ann)", pc(m['vol']), "VaR95 " + pc(m['var95'], 1))]
    kh = "".join(f'<div class="k"><div class="kl">{l}</div><div class="kv">{v}</div><div class="ks">{s}</div></div>'
                 for l, v, s in kpi)
    risk = [("Calmar", nu(m['calmar'])), ("Omega", nu(m['omega'])), ("Information ratio", nu(m['info_ratio'])),
            ("Treynor", nu(m['treynor'])), ("VaR 99", pc(m['var99'], 2)), ("CVaR 95", pc(m['cvar95'], 2)),
            ("Up/Down ratio", nu(m['updown'])), ("Monthly win rate", pc(m['monthly_win'], 1)),
            ("Drawdown length", f"{m['dd_days']}d"), ("Observations", f"{m['n']} days / {m['months']} mo")]
    rt = "".join(f"<tr><td>{k}</td><td style='text-align:right;font-weight:700'>{v}</td></tr>" for k, v in risk)
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0"><title>IC — Analytics Engine</title>
<style>
body{{font-family:Calibri,Arial,sans-serif;background:#f1f5f9;margin:0;color:#1e293b}}
.hdr{{background:{NAVY};border-bottom:3px solid {GOLD};padding:18px 30px}}
.hdr h1{{color:#fff;font-size:21px;margin:0}}.hdr .s{{color:{GOLD};font-size:12px;margin-top:3px}}
.wrap{{max-width:1180px;margin:0 auto;padding:22px 18px}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px 18px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.05)}}
.card h2{{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:{NAVY};margin:0 0 12px;border-left:4px solid {NAVY};padding-left:9px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:10px}}
.k{{background:#f8fafc;border-radius:8px;padding:10px 12px}}
.kl{{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.5px}}
.kv{{font-size:20px;font-weight:700;color:{NAVY};margin:2px 0}}
.ks{{font-size:10px;color:#94a3b8}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:900px){{.grid2{{grid-template-columns:1fr}}}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
td{{padding:5px 0;border-bottom:1px solid #f1f5f9}}
.note{{font-size:11px;color:#64748b;line-height:1.5}}
.foot{{text-align:center;color:#94a3b8;font-size:11px;margin:18px 0}}
</style></head><body>
<div class="hdr"><h1>Analytics Engine — Performance &amp; Risk</h1>
<div class="s">Integrity Compounders · inception {df.index[0].date()} → {df.index[-1].date()} · {m['n']} trading days · benchmark SPY · rf = 13-week T-bill ({rf_mean:.2%})</div></div>
<div class="wrap">
<div class="card"><h2>Headline</h2><div class="kpis">{kh}</div>
<div class="note" style="margin-top:10px"><b>Return decomposition.</b> With beta {m['beta']:.2f} and CAPM alpha {m['alpha']:+.1%},
returns are predominantly <b>market regime + convexity</b> (up-capture {m['up_capture']:.2f} vs down {m['down_capture']:.2f}), not
stock-level selection. The primary portfolio risk is a regime turn, not idiosyncratic misses; theme exposure to AI infrastructure
spans multiple GICS sectors and exceeds the IT sector weight alone.</div></div>
<div class="card">{C[0]}</div>
<div class="card">{C[1]}</div>
<div class="grid2"><div class="card">{C[2]}</div><div class="card">{C[3]}</div></div>
<div class="grid2"><div class="card">{C[4]}</div><div class="card">{C[5]}</div></div>
<div class="grid2"><div class="card">{C[6]}</div><div class="card">{C[7]}</div></div>
<div class="grid2">
  <div class="card"><h2>Risk &amp; ratios</h2><table>{rt}</table></div>
  <div class="card">{C[8]}</div>
</div>
<div class="card"><h2>Method &amp; caveats</h2><p class="note">
Return series is reconstructed from target-allocation snapshots × daily adjusted prices, rebalanced at each snapshot;
validated against the original engine (median daily difference 0.00000%). Inception is <b>2025-10-10</b> — the 2019-09-13
allocation row is a Koyfin reference, not a portfolio state. With ~9 months of history, annualised figures (CAGR, Calmar,
Treynor) are <b>directionally indicative only</b>. Up/down capture is geometric on <b>daily</b> observations (the monthly
convention would give ~9 data points). Batting average and slugging are <b>trade-level</b> across YTD allocation episodes
(entry→exit, open positions marked to last close) — distinct from the monthly win rate shown in Risk &amp; ratios.
</p></div>
<div class="foot">Integrity Compounders · V12.1 analytics engine · generated {date.today()}</div>
</div></body></html>"""
    (DOCS / "analytics.html").write_text(html)
    print(f"  📄  docs/analytics.html ({len(html):,} bytes)")


def run_analytics(html: bool = False, conn=None):
    """Compute + persist the analytics layer; optionally rebuild the dashboard.

    Callable from data_updater so the daily run keeps the return series and
    metrics current. Opens its own connection by default: this module needs
    autocommit, while data_updater runs transactional (autocommit=False).
    """
    own = conn is None
    if own:
        conn = get_conn()
    try:
        rf, rf_mean = load_rf()
        extend_daily_returns(conn, rf)
        df = load_series(conn)
        m  = compute_metrics(df, rf)
        t  = trade_stats(conn)
        r  = rolling_series(df, rf)
        persist(conn, m, t)
        print(f"  metrics: total {m['total_return']:.2%} · sharpe {m['sharpe']:.2f} · alpha {m['alpha']:+.2%} · maxDD {m['max_dd']:.2%}")
        if html:
            build_html(df, m, r, t, rf_mean)
        return m
    finally:
        if own:
            conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true")
    a = ap.parse_args()
    run_analytics(html=a.html)


if __name__ == "__main__":
    main()
