"""
alignment_scorer_v3.py — V12.1
Three-lens Alignment Score. Each component blends:
  - Absolute grade (fixed standard)       ← leads
  - Historical self-comparison (own past) ← meaningful
  - Universe percentile (relative)        ← demoted to tiebreaker

FV  = QGS tier 55% + QGS vs own history 30% + universe pctile 15%
MC  = trend status 45% + risk-adj 12-1 vs own history 40% + universe pctile 15%
VAL = FCF/EV vs own range 65% + universe pctile 35%

Alignment v3 = FV × 0.40 + MC × 0.25 + VAL × 0.35  (weights across the three
components unchanged from v2; what changed is how each component is built)

Cold-start: when a ticker has < 3 historical snapshots, the historical lens
defaults to the absolute grade so scores stay sane. history_maturity records
COLD_START / BUILDING / MATURE.

NOTE (workspace reconciliation): company_market_data stores ROIC and FCF margin
as `roic_trailing` / `fcf_margin_trailing` — the signal_history snapshot pulls
from those, not the (non-existent) `roic` / `fcf_margin` columns.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2, pandas as pd, numpy as np
from datetime import date
from config.settings import settings

# QGS tier → absolute 0-100 score
QGS_TIER_SCORE = {
    'RARE_ELITE': 95, 'EXCEPTIONAL': 80, 'GOOD_COMPOUNDER': 62,
    'AVERAGE': 42, 'LOW_QUALITY': 20,
}
TREND_SCORE = {'UPTREND': 85, 'NEUTRAL': 50, 'DOWNTREND': 20}

def _pyf(v):
    """numpy/Decimal/NaN → native Python float or None (psycopg2-safe)."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return float(v)

def pctile(series):
    return series.rank(pct=True, na_option='bottom') * 100

def hist_percentile(current, history_vals):
    """Where does current sit within this company's own history? 0-100."""
    if current is None or len(history_vals) < 3:
        return None
    arr = np.array([v for v in history_vals if v is not None])
    if len(arr) < 3:
        return None
    return float((arr < current).mean() * 100)

def compute_alignment_v3(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT c.ticker, c.in_portfolio,
               cmd.quality_growth_score, cmd.qgs_tier,
               cmd.fcf_ev_yield, cmd.trend_status, cmd.mom_12_1_risk_adj
        FROM companies c
        JOIN company_market_data cmd ON cmd.ticker = c.ticker
          AND cmd.data_date = (SELECT MAX(data_date) FROM company_market_data WHERE ticker=c.ticker)
        WHERE c.active = TRUE
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        print("  ⚠️  No data"); cur.close(); return

    # numeric coercion (psycopg2 returns Decimal)
    for col in ['quality_growth_score', 'fcf_ev_yield', 'mom_12_1_risk_adj']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # ── Universe percentiles (the demoted lens) ─────────────
    df['qgs_pctile']     = pctile(df['quality_growth_score'])
    df['mom_pctile']     = pctile(df['mom_12_1_risk_adj'])
    df['fcf_ev_pctile']  = pctile(df['fcf_ev_yield'])

    # ── Pull per-ticker history for the historical lens ─────
    def get_history(ticker, colname):
        cur.execute(f"""
            SELECT {colname} FROM signal_history
            WHERE ticker=%s AND {colname} IS NOT NULL
            ORDER BY snapshot_date DESC LIMIT 12
        """, (ticker,))
        return [float(r[0]) for r in cur.fetchall() if r[0] is not None]

    out = []
    for _, r in df.iterrows():
        tk = r['ticker']

        # history counts for maturity flag
        qgs_hist   = get_history(tk, 'quality_growth_score')
        mom_hist   = get_history(tk, 'mom_12_1_risk_adj')
        fcfev_hist = get_history(tk, 'fcf_ev_yield')
        n_hist = max(len(qgs_hist), len(mom_hist), len(fcfev_hist))
        maturity = 'COLD_START' if n_hist < 3 else ('BUILDING' if n_hist < 6 else 'MATURE')

        # ── FV composite ────────────────────────────────────
        fv_abs = QGS_TIER_SCORE.get(r['qgs_tier'], 40)
        fv_hist = hist_percentile(r['quality_growth_score'], qgs_hist)
        if fv_hist is None: fv_hist = fv_abs           # cold-start → absolute
        fv_uni = r['qgs_pctile'] if pd.notna(r['qgs_pctile']) else 50
        fv_comp = fv_abs*0.55 + fv_hist*0.30 + fv_uni*0.15

        # ── MC composite ────────────────────────────────────
        mc_abs = TREND_SCORE.get(r['trend_status'], 50)
        mc_hist = hist_percentile(r['mom_12_1_risk_adj'], mom_hist)
        if mc_hist is None: mc_hist = mc_abs
        mc_uni = r['mom_pctile'] if pd.notna(r['mom_pctile']) else 50
        mc_comp = mc_abs*0.45 + mc_hist*0.40 + mc_uni*0.15

        # ── Valuation composite ─────────────────────────────
        val_hist = hist_percentile(r['fcf_ev_yield'], fcfev_hist)
        val_uni = r['fcf_ev_pctile'] if pd.notna(r['fcf_ev_pctile']) else 50
        if val_hist is None: val_hist = val_uni        # cold-start → universe (valuation has no absolute grade)
        val_comp = val_hist*0.65 + val_uni*0.35

        # ── Alignment v3 ────────────────────────────────────
        align = fv_comp*0.40 + mc_comp*0.25 + val_comp*0.35
        bucket = 'ACCUMULATE' if align >= 65 else ('HOLD' if align >= 35 else 'DISTRIBUTE')

        # cast to native Python floats (psycopg2 can't adapt numpy 2.x scalars)
        out.append((round(float(fv_abs),2), round(float(fv_hist),2), round(float(fv_uni),2), round(float(fv_comp),2),
                    round(float(mc_abs),2), round(float(mc_hist),2), round(float(mc_uni),2), round(float(mc_comp),2),
                    round(float(val_hist),2), round(float(val_uni),2), round(float(val_comp),2),
                    round(float(align),2), bucket, maturity, tk))

    for vals in out:
        cur.execute("""
            UPDATE company_market_data SET
              fv_absolute=%s, fv_historical=%s, fv_universe=%s, fv_composite=%s,
              mc_absolute=%s, mc_historical=%s, mc_universe=%s, mc_composite=%s,
              val_historical=%s, val_universe=%s, val_composite=%s,
              alignment_score_v3=%s, alignment_bucket_v3=%s, history_maturity=%s
            WHERE ticker=%s AND data_date=(
              SELECT MAX(data_date) FROM company_market_data WHERE ticker=%s)
        """, (*vals, vals[-1]))
    conn.commit()

    # ── Snapshot into signal_history for future self-comparison ──
    #     (roic_trailing / fcf_margin_trailing are the real CMD column names)
    today = date.today()
    for _, r in df.iterrows():
        cur.execute("""
            INSERT INTO signal_history
              (ticker, snapshot_date, quality_growth_score, fcf_ev_yield,
               mom_12_1_risk_adj, roic, fcf_margin, alignment_score_v3)
            VALUES (%s,%s,%s,%s,%s,
              (SELECT roic_trailing FROM company_market_data WHERE ticker=%s ORDER BY data_date DESC LIMIT 1),
              (SELECT fcf_margin_trailing FROM company_market_data WHERE ticker=%s ORDER BY data_date DESC LIMIT 1),
              NULL)
            ON CONFLICT (ticker, snapshot_date) DO UPDATE SET
              quality_growth_score=EXCLUDED.quality_growth_score,
              fcf_ev_yield=EXCLUDED.fcf_ev_yield,
              mom_12_1_risk_adj=EXCLUDED.mom_12_1_risk_adj
        """, (r['ticker'], today, _pyf(r['quality_growth_score']), _pyf(r['fcf_ev_yield']),
              _pyf(r['mom_12_1_risk_adj']), r['ticker'], r['ticker']))
    conn.commit()
    cur.close()

    print(f"  ✅ Alignment v3 computed for {len(out)} tickers")
    print(f"  Snapshot written to signal_history for {len(df)} tickers (accumulating)")

if __name__ == '__main__':
    conn = psycopg2.connect(settings.DATABASE_URL)
    compute_alignment_v3(conn)
    conn.close()
