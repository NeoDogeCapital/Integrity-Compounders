"""
momentum_engine.py — V12.1
Four distinct momentum signals, each doing one job:
  1. Selection      — risk-adjusted 12-1 momentum (the real momentum anomaly)
  2. Trend filter   — absolute UPTREND/NEUTRAL/DOWNTREND (initiation veto)
  3. Extension      — distance from 200-DMA in stdevs (entry timing / exhaustion)
  4. Reversal setup — strong 12-1 + weak 1M + above 200-DMA (buy-the-dip)

Principle: momentum is for TIMING and CONFIRMATION, never thesis.
It never drives an exit on its own.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2, pandas as pd, numpy as np
from datetime import date, timedelta
from config.settings import settings

TRADING_DAYS_1M  = 21
TRADING_DAYS_12M = 252

def compute_momentum(conn):
    cur = conn.cursor()

    # Pull all active tickers with enough price history
    cur.execute("SELECT DISTINCT ticker FROM companies WHERE active = TRUE")
    tickers = [r[0] for r in cur.fetchall()]

    results = []
    insufficient = 0

    for ticker in tickers:
        cur.execute("""
            SELECT price_date, adj_close
            FROM ic_price_history
            WHERE ticker = %s AND adj_close IS NOT NULL
            ORDER BY price_date
        """, (ticker,))
        rows = cur.fetchall()
        if len(rows) < TRADING_DAYS_12M + 5:
            insufficient += 1
            continue

        df = pd.DataFrame(rows, columns=['date','close'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        px = df['close'].astype(float)

        # ── Returns ──────────────────────────────────────────
        price_now   = px.iloc[-1]
        price_1m    = px.iloc[-(TRADING_DAYS_1M+1)]
        price_12m   = px.iloc[-(TRADING_DAYS_12M+1)]
        ret_1m      = price_now / price_1m  - 1
        ret_12m     = price_now / price_12m - 1

        # 12-1 momentum: skips the mean-reverting recent month
        mom_12_1    = ret_12m - ret_1m

        # ── Volatility (trailing 12M, annualized) ────────────
        daily_ret   = px.pct_change().dropna().iloc[-TRADING_DAYS_12M:]
        vol_12m     = daily_ret.std() * np.sqrt(252)

        # ── Risk-adjusted 12-1 (the selection signal) ────────
        mom_12_1_ra = mom_12_1 / vol_12m if vol_12m and vol_12m > 0 else None

        # ── Moving averages + trend status ───────────────────
        sma_50  = px.iloc[-50:].mean()  if len(px) >= 50  else None
        sma_200 = px.iloc[-200:].mean() if len(px) >= 200 else None

        trend_status = 'NEUTRAL'
        if sma_200 is not None and sma_50 is not None:
            if price_now > sma_200 and sma_50 > sma_200:
                trend_status = 'UPTREND'
            elif price_now < sma_200 and sma_50 < sma_200:
                trend_status = 'DOWNTREND'
            else:
                trend_status = 'NEUTRAL'

        # ── Extension: distance from 200-DMA, z-scored ───────
        dist_200 = ext_z = None
        ext_flag = 'HEALTHY'
        if sma_200 is not None:
            dist_200 = (price_now - sma_200) / sma_200
            # historical distribution of that distance over trailing year
            hist_200 = px.rolling(200).mean().dropna()
            hist_dist = ((px.reindex(hist_200.index) - hist_200) / hist_200).dropna().iloc[-TRADING_DAYS_12M:]
            if len(hist_dist) > 30 and hist_dist.std() > 0:
                ext_z = (dist_200 - hist_dist.mean()) / hist_dist.std()
                if   ext_z >  2:  ext_flag = 'OVEREXTENDED'
                elif ext_z < -2:  ext_flag = 'OVERSOLD'
                else:             ext_flag = 'HEALTHY'

        # ── Reversal setup (buy-the-dip in an uptrend) ───────
        # strong 12-1 momentum + recent 1M weakness + still above 200-DMA
        reversal = False
        if (mom_12_1_ra is not None and mom_12_1_ra > 0
            and ret_1m < 0
            and sma_200 is not None and price_now > sma_200):
            reversal = True

        # cast numpy scalars → native Python (psycopg2 can't adapt numpy 2.x types)
        results.append({
            'ticker': ticker,
            'mom_1m_return': round(float(ret_1m), 6),
            'mom_12m_return': round(float(ret_12m), 6),
            'mom_12_1': round(float(mom_12_1), 6),
            'vol_12m': round(float(vol_12m), 6) if vol_12m else None,
            'mom_12_1_risk_adj': round(float(mom_12_1_ra), 6) if mom_12_1_ra is not None else None,
            'trend_status': trend_status,
            'dist_200dma': round(float(dist_200), 6) if dist_200 is not None else None,
            'dist_200dma_z': round(float(ext_z), 4) if ext_z is not None else None,
            'extension_flag': ext_flag,
            'reversal_setup': bool(reversal),
        })

    # Write to company_market_data (latest row per ticker)
    written = 0
    for r in results:
        cur.execute("""
            UPDATE company_market_data SET
                mom_1m_return=%s, mom_12m_return=%s, mom_12_1=%s, vol_12m=%s,
                mom_12_1_risk_adj=%s, trend_status=%s, dist_200dma=%s,
                dist_200dma_z=%s, extension_flag=%s, reversal_setup=%s
            WHERE ticker=%s AND data_date=(
                SELECT MAX(data_date) FROM company_market_data WHERE ticker=%s)
        """, (r['mom_1m_return'], r['mom_12m_return'], r['mom_12_1'], r['vol_12m'],
              r['mom_12_1_risk_adj'], r['trend_status'], r['dist_200dma'],
              r['dist_200dma_z'], r['extension_flag'], r['reversal_setup'],
              r['ticker'], r['ticker']))
        written += 1

    conn.commit()
    cur.close()
    print(f"  ✅ Momentum computed for {written} tickers ({insufficient} lacked history)")
    # Quick distribution
    from collections import Counter
    trends = Counter(r['trend_status'] for r in results)
    exts   = Counter(r['extension_flag'] for r in results)
    revs   = sum(1 for r in results if r['reversal_setup'])
    print(f"  Trend: {dict(trends)}")
    print(f"  Extension: {dict(exts)}")
    print(f"  Reversal setups (buy-the-dip candidates): {revs}")
    return results

if __name__ == '__main__':
    conn = psycopg2.connect(settings.DATABASE_URL)
    compute_momentum(conn)
    conn.close()
