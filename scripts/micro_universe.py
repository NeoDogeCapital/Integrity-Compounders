"""
micro_universe.py — the Micro Compounders sleeve (separate from the core model)

A standing satellite universe for speculative micro/small-cap ideas traded in
personal accounts (Niko, 2026-09-02). Applies the full Compounders V12 quant
stack to a dedicated Fiscal AI micro screen while staying structurally
firewalled from the core universe:

  - Results live in their own table, micro_universe_snapshot — never in the
    core cross-sections (factor z-scores, alignment percentiles, reports).
  - companies rows are created ONLY for tickers the core model doesn't know,
    with active = FALSE and universe_tag = 'micro', so every core query
    (WHERE active = TRUE) ignores them by construction. Names that overlap
    the core universe are never modified here.
  - company_market_data rows are written only for micro-tagged names (core
    filters keep them invisible), which lets company_scorer and `who is`
    work on micro names when asked.
  - ic_price_history is shared (same prices for the same tickers; harmless).

Layers computed per name, straight from the screen CSV + price history:
  V12 quad axes/assignment · QGS + tier · six quality indicators + profile ·
  earnings-quality contamination flag · GER · 200-DMA trend / extension z /
  12-1 risk-adjusted momentum (V12.1 semantics, computed locally).

Pillar scores are NOT computed here; use --score N to LLM-score the top N
micro-only names via company_scorer (overlapping names carry core scores).

Usage:
    python scripts/micro_universe.py data/raw/micro/Screener_Results_YYYY-MM-DD.csv
    python scripts/micro_universe.py <csv> --no-prices        # skip backfill
    python scripts/micro_universe.py <csv> --score 25         # LLM pillar-score top 25
"""
import sys
import csv
import math
import argparse
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import psycopg2
from config.settings import settings

QGS_TIERS = [(0.0028, 'RARE_ELITE'), (0.0016, 'EXCEPTIONAL'),
             (0.0006, 'GOOD_COMPOUNDER'), (0.0002, 'AVERAGE')]
TIER_RANK = {"RARE_ELITE": 5, "EXCEPTIONAL": 4, "GOOD_COMPOUNDER": 3,
             "AVERAGE": 2, "LOW_QUALITY": 1, None: 0}
QUAD_RANK = {"Q1": 2, "Q2": 1, "Q3": 0, "Q4": -1, None: -2}


def _num(s):
    if s is None:
        return None
    s = str(s).replace('$', '').replace(',', '').replace('%', '').strip()
    if s in ('', '-'):
        return None
    try:
        v = float(s)
        return None if (math.isinf(v) or math.isnan(v)) else v
    except ValueError:
        return None


def load_screen(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            d = {"tk": r["Ticker"].strip().upper(), "name": r["Company"],
                 "ind": r["Industry"], "cty": r["Country"], "exch": r["Exchange"]}
            d["gm"] = _num(r["Gross Profit Margin"]);   d["eps1y"] = _num(r["Diluted EPS 1Y Growth"])
            d["gp3y"] = _num(r["Gross Profit 3Y CAGR"]); d["gp1y"] = _num(r["Gross Profit 1Y Growth"])
            d["fcf"] = _num(r["Free Cash Flow (M)"]);    d["tev"] = _num(r["Total Enterprise Value (TEV) (M)"])
            d["sbc"] = _num(r["Stock-Based Compensation (Cash Flow Statement) (M)"])
            d["fcfm"] = _num(r["Free Cash Flow Margin"]); d["shrg"] = _num(r["Shares Out Growth 3Y (CAGR)"])
            d["epssur"] = _num(r["EPS Normalized Actual vs Estimate (Quarterly)"])
            d["revsur"] = _num(r["Revenue Actual vs Estimate (Quarterly)"])
            d["fcfy"] = _num(r["FCF Yield"]);            d["price"] = _num(r["Stock Price"])
            d["tr1m"] = _num(r["TR 1M Performance"]);    d["ytd"] = _num(r["YTD Performance"])
            d["fwdrev"] = _num(r["Revenue Forward 2Y CAGR"]); d["capex"] = _num(r["CapEx to Revenue"])
            d["mcap"] = _num(r["Market Cap (M)"]);       d["bb"] = _num(r["Buyback Yield"])
            d["rev3y"] = _num(r["Revenue 3Y CAGR"]);     d["om"] = _num(r["Operating Margin"])
            d["nde"] = _num(r["Net Debt / EBITDA"]);     d["beta"] = _num(r["Beta"])
            d["eps3y"] = _num(r["Diluted EPS 3Y CAGR"]); d["fwdeps"] = _num(r["EPS Normalized Forward 2Y CAGR"])
            d["roic"] = _num(r["Return on Invested Capital"])
            rows.append(d)
    return rows


def compute_layers(d):
    x = d["fwdrev"] - d["rev3y"] if None not in (d["fwdrev"], d["rev3y"]) else None
    y = (min(d["fwdeps"], 25.0) - d["eps3y"]) if None not in (d["fwdeps"], d["eps3y"]) else None
    quad = None
    if x is not None and y is not None:
        quad = "Q1" if (x > 0 and y > 0) else "Q2" if x > 0 else "Q4" if y > 0 else "Q3"
    fcf_ev = d["fcf"] / d["tev"] if d["fcf"] is not None and d["tev"] and d["tev"] > 0 else None
    qgs = tier = None
    if None not in (d["fwdrev"], d["fwdeps"], fcf_ev, d["roic"], d["fcfm"]) and fcf_ev > 0:
        qgs = round((d["fwdrev"]/100 + d["fwdeps"]/100) * fcf_ev * (d["roic"]/100) * (d["fcfm"]/100), 6)
        tier = next((t for lo, t in QGS_TIERS if qgs > lo), 'LOW_QUALITY')
    n_pass = 0
    for v, th, sgn in [(d["roic"], 10, 1), (d["gm"], 30, 1), (d["om"], 15, 1),
                       (d["fcfm"], 7, 1), (d["rev3y"], 5, 1), (d["nde"], 3, -1)]:
        if v is None:
            continue
        n_pass += (v >= th) if sgn > 0 else (v <= th)
    prof = ("FULL_COMPOUNDER" if n_pass >= 5 else "QUALITY_WATCH" if n_pass >= 3
            else "DEVELOPING" if n_pass >= 1 else "QUALITY_CONCERN")
    eps_acc = (d["eps1y"] - d["eps3y"]) if None not in (d["eps1y"], d["eps3y"]) else None
    gp_acc = (d["gp1y"] - d["gp3y"]) if None not in (d["gp1y"], d["gp3y"]) else None
    eq = "DATA_INCOMPLETE"
    if eps_acc is not None and gp_acc is not None:
        eq = ("EPS_CONFIRMED" if eps_acc > 0 and gp_acc > 0 else
              "EPS_ENGINEERED" if eps_acc > 0 else
              "GP_LEADING" if gp_acc > 0 else "NEUTRAL")
    ger = None
    if None not in (d["fwdrev"], d["fwdeps"], d["sbc"], d["fcf"], d["fcfm"], d["shrg"]) and d["fcfm"]:
        rev_ttm = d["fcf"] / (d["fcfm"] / 100) if d["fcfm"] != 0 else None
        if rev_ttm and rev_ttm > 0:
            den = d["sbc"] / rev_ttm + d["shrg"] / 100
            ger = round((d["fwdrev"]/100 + d["fwdeps"]/100) / max(den, 0.01), 4) if den >= 0 else None
    score = (QUAD_RANK[quad] * 2 + TIER_RANK[tier] * 1.5 + n_pass * 0.7
             + (2 if eq == "EPS_CONFIRMED" else -3 if eq == "EPS_ENGINEERED" else 0)
             + min(fcf_ev or 0, 0.15) * 20)
    d.update(x=x, y=y, quad=quad, fcf_ev=fcf_ev, qgs=qgs, tier=tier, inds=n_pass,
             prof=prof, eq=eq, eps_acc=eps_acc, gp_acc=gp_acc, ger=ger, score=round(score, 2))
    return d


def technicals(cur, tk):
    cur.execute("""SELECT adj_close FROM ic_price_history
        WHERE ticker=%s AND adj_close IS NOT NULL ORDER BY price_date""", (tk,))
    px = [float(r[0]) for r in cur.fetchall()]
    if len(px) < 210:
        return None, None, None
    sma200 = sum(px[-200:]) / 200
    mu = sma200
    sd = (sum((p - mu) ** 2 for p in px[-200:]) / 200) ** 0.5
    last = px[-1]
    ext_z = (last - sma200) / sd if sd > 0 else None
    trend = "UPTREND" if last > sma200 * 1.02 else "DOWNTREND" if last < sma200 * 0.98 else "NEUTRAL"
    mom = None
    if len(px) >= 273:
        r12_1 = px[-21] / px[-273] - 1
        rets = [px[i] / px[i - 1] - 1 for i in range(len(px) - 251, len(px))]
        m = sum(rets) / len(rets)
        vol = (sum((r - m) ** 2 for r in rets) / len(rets)) ** 0.5 * (252 ** 0.5)
        mom = round(r12_1 / vol, 4) if vol > 0 else None
    return trend, (round(ext_z, 3) if ext_z is not None else None), mom


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--no-prices", action="store_true")
    ap.add_argument("--score", type=int, default=0, help="LLM pillar-score top N micro-only names")
    a = ap.parse_args()
    snap_date = date.today()

    rows = [compute_layers(d) for d in load_screen(a.csv)]
    rows.sort(key=lambda d: -d["score"])
    print(f"  micro screen: {len(rows)} names loaded from {Path(a.csv).name}")

    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS universe_tag TEXT DEFAULT 'core'")
    cur.execute("""CREATE TABLE IF NOT EXISTS micro_universe_snapshot (
        snapshot_date DATE NOT NULL, ticker VARCHAR(12) NOT NULL,
        company_name TEXT, industry TEXT, country TEXT,
        quadrant VARCHAR(4), x_rev_mom NUMERIC, y_eps_mom NUMERIC,
        qgs NUMERIC, qgs_tier TEXT, indicators_pass INTEGER, quality_profile TEXT,
        earnings_quality_flag TEXT, eps_acceleration NUMERIC, gp_acceleration NUMERIC,
        fcf_ev_yield NUMERIC, roic NUMERIC, gross_margin NUMERIC, op_margin NUMERIC,
        fcf_margin NUMERIC, rev_3y_cagr NUMERIC, eps_3y_cagr NUMERIC,
        fwd_rev_cagr NUMERIC, fwd_eps_cagr NUMERIC, net_debt_ebitda NUMERIC,
        buyback_yield NUMERIC, sbc_m NUMERIC, ger NUMERIC, beta NUMERIC,
        market_cap_m NUMERIC, price NUMERIC, ytd_perf NUMERIC,
        eps_surprise_q NUMERIC, rev_surprise_q NUMERIC,
        trend_status TEXT, extension_z NUMERIC, mom_12_1_risk_adj NUMERIC,
        rank_score NUMERIC, created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (snapshot_date, ticker))""")

    # companies rows for micro-only tickers (invisible to every core query)
    cur.execute("SELECT ticker, universe_tag, active FROM companies")
    known = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    new_names, overlap = [], []
    for d in rows:
        if d["tk"] not in known:
            new_names.append(d)
        elif known[d["tk"]][0] != 'micro':
            overlap.append(d["tk"])
    for d in new_names:
        cur.execute("""INSERT INTO companies (ticker, company_name, sector, industry, country,
                exchange, active, in_portfolio, universe_tag)
            VALUES (%s,%s,%s,%s,%s,%s,FALSE,FALSE,'micro') ON CONFLICT (ticker) DO NOTHING""",
            (d["tk"], d["name"], d["ind"], d["ind"], d["cty"], d["exch"]))
    print(f"  companies: +{len(new_names)} micro-only inserted (inactive, tagged) · "
          f"{len(overlap)} overlap core and are untouched")

    # cmd rows ONLY for micro-tagged names — enables scorer / who-is, invisible to core
    cur.execute("SELECT id, ticker FROM companies WHERE universe_tag='micro'")
    micro_ids = {t: i for i, t in cur.fetchall()}
    for d in rows:
        cid = micro_ids.get(d["tk"])
        if not cid:
            continue
        pct = lambda v: v  # screen values are already percent-scale
        cur.execute("""INSERT INTO company_market_data (company_id, ticker, data_date,
                current_price, market_cap, roic_trailing, gross_margin_trailing, op_margin,
                fcf_margin_trailing, fcf_yield_current, net_debt_ebitda, revenue_3y_cagr_trailing,
                eps_3y_cagr_trailing, fwd_revenue_3y_cagr, fwd_eps_3y_cagr, buyback_yield, beta,
                quadrant, quality_growth_score, qgs_tier, earnings_quality_flag, quality_profile,
                indicators_pass, fcf_ev_yield, eps_surprise_q, rev_surprise_q, ytd_perf,
                enterprise_value, trailing_source)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'micro_csv')
            ON CONFLICT (company_id, data_date) DO UPDATE SET
                current_price=EXCLUDED.current_price, market_cap=EXCLUDED.market_cap,
                roic_trailing=EXCLUDED.roic_trailing, gross_margin_trailing=EXCLUDED.gross_margin_trailing,
                op_margin=EXCLUDED.op_margin, fcf_margin_trailing=EXCLUDED.fcf_margin_trailing,
                fcf_yield_current=EXCLUDED.fcf_yield_current, net_debt_ebitda=EXCLUDED.net_debt_ebitda,
                revenue_3y_cagr_trailing=EXCLUDED.revenue_3y_cagr_trailing,
                eps_3y_cagr_trailing=EXCLUDED.eps_3y_cagr_trailing,
                fwd_revenue_3y_cagr=EXCLUDED.fwd_revenue_3y_cagr, fwd_eps_3y_cagr=EXCLUDED.fwd_eps_3y_cagr,
                buyback_yield=EXCLUDED.buyback_yield, beta=EXCLUDED.beta, quadrant=EXCLUDED.quadrant,
                quality_growth_score=EXCLUDED.quality_growth_score, qgs_tier=EXCLUDED.qgs_tier,
                earnings_quality_flag=EXCLUDED.earnings_quality_flag, quality_profile=EXCLUDED.quality_profile,
                indicators_pass=EXCLUDED.indicators_pass, fcf_ev_yield=EXCLUDED.fcf_ev_yield,
                eps_surprise_q=EXCLUDED.eps_surprise_q, rev_surprise_q=EXCLUDED.rev_surprise_q,
                ytd_perf=EXCLUDED.ytd_perf, enterprise_value=EXCLUDED.enterprise_value,
                trailing_source='micro_csv'""",
            (str(cid), d["tk"], snap_date, d["price"],
             d["mcap"] * 1e6 if d["mcap"] else None,
             pct(d["roic"]), pct(d["gm"]), pct(d["om"]), pct(d["fcfm"]), pct(d["fcfy"]),
             d["nde"], pct(d["rev3y"]), pct(d["eps3y"]), pct(d["fwdrev"]), pct(d["fwdeps"]),
             pct(d["bb"]), d["beta"], d["quad"], d["qgs"], d["tier"], d["eq"], d["prof"],
             d["inds"], round(d["fcf_ev"], 6) if d["fcf_ev"] is not None else None,
             d["epssur"], d["revsur"], d["ytd"],
             d["tev"] * 1e6 if d["tev"] else None))

    # price history (shared table; explicit list works for inactive micro names)
    if not a.no_prices:
        from backfill_price_history import backfill
        print("  price backfill (2y, only-missing) for the micro list...")
        try:
            backfill(period="2y", only_missing=True, only_ticker=[d["tk"] for d in rows])
        except Exception as e:
            print(f"  ⚠️  backfill issue (non-fatal): {e}")

    # technicals + snapshot
    for d in rows:
        trend, ext_z, mom = technicals(cur, d["tk"])
        cur.execute("""INSERT INTO micro_universe_snapshot VALUES
            (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (snapshot_date, ticker) DO UPDATE SET
                quadrant=EXCLUDED.quadrant, qgs=EXCLUDED.qgs, qgs_tier=EXCLUDED.qgs_tier,
                indicators_pass=EXCLUDED.indicators_pass, quality_profile=EXCLUDED.quality_profile,
                earnings_quality_flag=EXCLUDED.earnings_quality_flag,
                trend_status=EXCLUDED.trend_status, extension_z=EXCLUDED.extension_z,
                mom_12_1_risk_adj=EXCLUDED.mom_12_1_risk_adj, rank_score=EXCLUDED.rank_score""",
            (snap_date, d["tk"], d["name"], d["ind"], d["cty"], d["quad"], d["x"], d["y"],
             d["qgs"], d["tier"], d["inds"], d["prof"], d["eq"], d["eps_acc"], d["gp_acc"],
             round(d["fcf_ev"], 6) if d["fcf_ev"] is not None else None,
             d["roic"], d["gm"], d["om"], d["fcfm"], d["rev3y"], d["eps3y"],
             d["fwdrev"], d["fwdeps"], d["nde"], d["bb"], d["sbc"], d["ger"], d["beta"],
             d["mcap"], d["price"], d["ytd"], d["epssur"], d["revsur"],
             trend, ext_z, mom, d["score"]))
    print(f"  micro_universe_snapshot: {len(rows)} rows for {snap_date}")

    # console leaderboard + HTML
    print(f"\n  {'#':<3}{'tk':<7}{'quad':<5}{'tier':<16}{'ind':<4}{'eq':<15}{'fcf/ev':<8}{'trend':<10}name")
    for i, d in enumerate(rows[:20], 1):
        cur.execute("SELECT trend_status FROM micro_universe_snapshot WHERE snapshot_date=%s AND ticker=%s",
                    (snap_date, d["tk"]))
        tr = (cur.fetchone() or [None])[0] or "—"
        fe = f"{d['fcf_ev']*100:.1f}%" if d["fcf_ev"] is not None else "—"
        print(f"  {i:<3}{d['tk']:<7}{d['quad'] or '—':<5}{d['tier'] or '—':<16}{d['inds']:<4}"
              f"{d['eq']:<15}{fe:<8}{tr:<10}{d['name'][:30]}")

    html_rows = "".join(
        f"<tr><td>{i}</td><td><b>{d['tk']}</b></td><td>{d['name'][:36]}</td><td>{d['ind'][:28]}</td>"
        f"<td>{d['quad'] or '—'}</td><td>{d['tier'] or '—'}</td><td>{d['inds']}/6</td>"
        f"<td{' style=color:#B54334' if d['eq']=='EPS_ENGINEERED' else ''}>{d['eq']}</td>"
        f"<td>{d['fcf_ev']*100:.1f}%</td><td>{d['roic'] or 0:.1f}%</td><td>{d['fcfm'] or 0:.1f}%</td>"
        f"<td>${d['mcap'] or 0:,.0f}M</td><td>{d['score']:.2f}</td></tr>"
        for i, d in enumerate(rows, 1) if d["fcf_ev"] is not None)
    out = ROOT / "outputs" / "reports" / f"micro_universe_{snap_date}.html"
    out.write_text(f"""<!doctype html><html><head><meta charset="utf-8"><title>Micro Compounders — {snap_date}</title>
<style>body{{font-family:Calibri,Arial,sans-serif;margin:24px;color:#222}}h1{{color:#1F3A5F}}
table{{border-collapse:collapse;font-size:12px}}td,th{{padding:4px 9px;border-bottom:1px solid #e3e6ea;text-align:left}}
th{{background:#1F3A5F;color:#fff;position:sticky;top:0}}tr:hover{{background:#f4f6f9}}</style></head><body>
<h1>Micro Compounders — {snap_date}</h1>
<p style="color:#666">Satellite sleeve · V12 quant layers · {len(rows)} names · personal accounts ·
kept separate from the core Integrity Compounders universe</p>
<table><tr><th>#</th><th>Ticker</th><th>Company</th><th>Industry</th><th>Quad</th><th>QGS tier</th>
<th>Ind</th><th>Earnings quality</th><th>FCF/EV</th><th>ROIC</th><th>FCF mgn</th><th>Mkt cap</th><th>Score</th></tr>
{html_rows}</table>
<p style="color:#999;font-size:11px">Generated {datetime.now():%Y-%m-%d %H:%M} · internal/personal use only</p>
</body></html>""")
    print(f"\n  HTML → {out.relative_to(ROOT)}")

    # optional LLM pillar scoring for top micro-only names
    if a.score:
        from company_scorer import score_company
        targets = [d["tk"] for d in rows if d["tk"] in micro_ids][:a.score]
        print(f"\n  pillar-scoring top {len(targets)} micro-tagged names...")
        ok = fail = 0
        for t in targets:
            try:
                ok += bool(score_company(t, interactive=False, score_only=True))
            except Exception as e:
                fail += 1
                print(f"   ⚠️  {t}: {str(e)[:70]}")
        print(f"  scored {ok} · failed {fail}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
