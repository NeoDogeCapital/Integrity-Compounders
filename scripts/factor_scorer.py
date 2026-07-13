"""
factor_scorer.py — per-name characteristic factor scores (cross-sectional)

Six canonical factors scored for EVERY active name (portfolio or not) as
winsorized cross-sectional z-scores of fundamental descriptors — the standard
MSCI/Barra descriptor-standardization method. Pure pandas over one snapshot of
company_market_data; no yfinance, runs in seconds.

  Value    +fcf_ev_yield  −pe_forward(>0)  −ev_ebitda(>0)
  Momentum +mom_12_1_risk_adj  +mom_12m_return
  Quality  +roic_trailing  +gross_margin_trailing  +fcf_margin_trailing  −net_debt_ebitda
  Low Vol  −beta  −vol_12m
  Size     −ln(market_cap)                       # small-cap tilt = higher
  Growth   +fwd_revenue_3y_cagr  +fwd_eps_3y_cagr

Each descriptor is winsorized at the 1st/99th percentile, z-scored across the
active universe, sign-flipped so higher always means "more of the factor," then
averaged within the factor (skipping missing descriptors). Output: per-name z
(σ units, comparable across factors) + 0–100 percentile + a factor-profile label.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras as pgx
from datetime import date
from config.settings import settings

# factor -> list of (column, sign, transform)   transform: None | 'pos' | 'log'
FACTOR_DESC = {
    'value':    [('fcf_ev_yield', +1, None), ('pe_forward', -1, 'pos'), ('ev_ebitda', -1, 'pos')],
    'momentum': [('mom_12_1_risk_adj', +1, None), ('mom_12m_return', +1, None)],
    'quality':  [('roic_trailing', +1, None), ('gross_margin_trailing', +1, None),
                 ('fcf_margin_trailing', +1, None), ('net_debt_ebitda', -1, None)],
    'lowvol':   [('beta', -1, None), ('vol_12m', -1, None)],
    'size':     [('market_cap', -1, 'log')],
    'growth':   [('fwd_revenue_3y_cagr', +1, None), ('fwd_eps_3y_cagr', +1, None)],
}
FACTOR_ORDER = list(FACTOR_DESC)
FACTOR_LABEL = {'value': 'Value', 'momentum': 'Momentum', 'quality': 'Quality',
                'lowvol': 'Low Vol', 'size': 'Size', 'growth': 'Growth'}
STRONG_Z = 1.0   # a factor is a "profile" loading at ≥ +1σ


def _transform(s, kind):
    s = pd.to_numeric(s, errors='coerce')
    if kind == 'pos':
        s = s.where(s > 0)            # drop non-positive (loss-makers / neg EV/EBITDA)
    elif kind == 'log':
        s = np.log(s.where(s > 0))
    return s


def _winsor_z(s):
    lo, hi = s.quantile(0.01), s.quantile(0.99)
    s = s.clip(lo, hi)
    m, sd = s.mean(), s.std()
    return (s - m) / sd if (sd and not pd.isna(sd)) else s * 0.0


def compute_factor_scores(conn):
    cols = sorted({c for defs in FACTOR_DESC.values() for c, _, _ in defs})
    cur = conn.cursor()
    cur.execute(f"""
        SELECT c.ticker, {', '.join('cmd.' + c for c in cols)}
        FROM companies c
        JOIN company_market_data cmd ON cmd.ticker = c.ticker
          AND cmd.data_date = (SELECT MAX(data_date) FROM company_market_data WHERE ticker = c.ticker)
        WHERE c.active = TRUE
    """)
    rows = cur.fetchall()
    if not rows:
        print("  ⚠️  factor_scorer: no active names"); return
    df = pd.DataFrame(rows, columns=['ticker'] + cols).set_index('ticker')
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    out = pd.DataFrame(index=df.index)
    for fac, defs in FACTOR_DESC.items():
        parts = [(_winsor_z(_transform(df[c], kind)) * sign) for c, sign, kind in defs]
        fz = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
        out[fac + '_z'] = fz
        out[fac + '_pct'] = fz.rank(pct=True) * 100

    # factor profile: loadings ≥ +1σ (top 2), else the single strongest
    def _profile(r):
        zs = {f: r[f + '_z'] for f in FACTOR_ORDER if pd.notna(r[f + '_z'])}
        if not zs:
            return None
        ranked = sorted(zs.items(), key=lambda kv: -kv[1])
        strong = [FACTOR_LABEL[f] for f, v in ranked if v >= STRONG_Z][:2]
        return ' / '.join(strong) if strong else FACTOR_LABEL[ranked[0][0]]
    out['profile'] = out.apply(_profile, axis=1)

    today = date.today()

    def _n(v):
        return None if pd.isna(v) else round(float(v), 4)
    recs = []
    for tk, r in out.iterrows():
        flat = []
        for f in FACTOR_ORDER:
            flat += [_n(r[f + '_z']), _n(r[f + '_pct'])]
        recs.append((tk, today, *flat, r['profile']))

    zpct_cols = [f"{f}_z, {f}_pct" for f in FACTOR_ORDER]
    set_cols = ", ".join(c for f in FACTOR_ORDER for c in (f + '_z', f + '_pct'))
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for f in FACTOR_ORDER
                        for c in (f + '_z', f + '_pct')) + ", factor_profile=EXCLUDED.factor_profile"
    pgx.execute_values(cur, f"""
        INSERT INTO factor_scores (ticker, data_date, {set_cols}, factor_profile)
        VALUES %s
        ON CONFLICT (ticker, data_date) DO UPDATE SET {updates}
    """, recs, page_size=500)
    conn.commit()
    cur.close()

    print(f"  ✅ Factor scores computed for {len(out)} names (6 factors)")
    from collections import Counter
    prof = Counter(out['profile'].dropna())
    print("  Top factor profiles:", dict(prof.most_common(6)))


if __name__ == '__main__':
    conn = psycopg2.connect(settings.DATABASE_URL)
    compute_factor_scores(conn)
    conn.close()
