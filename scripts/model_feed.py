"""
model_feed.py — publish the model's per-ticker read as a JSON feed for TrendSpider

Writes docs/model_feed.json (served by GitHub Pages at
https://NeoDogeCapital.github.io/Integrity-Compounders/model_feed.json).
TrendSpider custom-JS indicators fetch it with request.http(), look up
current.symbol, and paint the model's state on the chart — alignment v3, quad,
QGS tier, earnings quality, trend/extension, theme, holding flag, plus the
recent alignment_v3 history from signal_history.

NOTE: the feed is public (same as the dashboards, which already expose these
fields on the quad-map hovers). No position sizes, costs or P&L are included.

Wired into scripts/publish.py so every publish refreshes it.
"""
import sys
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
from config.settings import settings


def build():
    conn = psycopg2.connect(settings.DATABASE_URL); cur = conn.cursor()
    cur.execute("""SELECT c.ticker, cmd.alignment_score_v3, cmd.alignment_bucket_v3,
            cmd.quadrant, cmd.qgs_tier, cmd.earnings_quality_flag, cmd.trend_status,
            cmd.extension_flag, cmd.mom_12_1_risk_adj, c.theme, COALESCE(c.in_portfolio, FALSE)
        FROM companies c JOIN company_market_data cmd ON cmd.ticker = c.ticker
         AND cmd.data_date = (SELECT MAX(data_date) FROM company_market_data
                              WHERE ticker = c.ticker)
        WHERE c.active = TRUE""")
    f = lambda v: float(v) if v is not None else None
    tickers = {}
    for r in cur.fetchall():
        tickers[r[0]] = {
            "alignment_v3": f(r[1]), "bucket": r[2], "quad": r[3], "qgs_tier": r[4],
            "earnings_quality": r[5], "trend": r[6], "extension": r[7],
            "mom_12_1": f(r[8]), "theme": r[9], "held": bool(r[10]),
        }
    cur.execute("""SELECT ticker, snapshot_date, alignment_score_v3 FROM signal_history
                   WHERE alignment_score_v3 IS NOT NULL ORDER BY ticker, snapshot_date""")
    for tk, d, v in cur.fetchall():
        if tk in tickers:
            tickers[tk].setdefault("alignment_history", []).append(
                {"date": str(d), "v3": f(v)})
    conn.close()

    out = {"asof": str(date.today()), "source": "Integrity Compounders Alpha System v12.1",
           "count": len(tickers), "tickers": tickers}
    path = ROOT / "docs" / "model_feed.json"
    path.write_text(json.dumps(out, separators=(",", ":")))
    print(f"  model_feed.json: {len(tickers)} tickers, {path.stat().st_size:,}b")


if __name__ == "__main__":
    build()
