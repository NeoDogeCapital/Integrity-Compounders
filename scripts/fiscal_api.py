"""
fiscal_api.py — Fiscal.ai REST client for the scripted pipeline

The MCP connector is session-bound to Claude's OAuth, so cron/scripted work
needs this REST client instead. Endpoints mirror the MCP helper surface
(verified against https://api.fiscal.ai/openapi.json, 2026-08-18).

Auth: X-Api-Key header, key from FISCAL_API_KEY in .env (never hardcoded,
never committed — .env is gitignored). If the key is absent every call raises
FiscalKeyMissing so callers can fall back to yfinance cleanly.

Conventions:
  - Prices are split-adjusted closes (NOT dividend-adjusted like yfinance's
    adj_close). Fine as a gap-fill/fallback for names yfinance can't serve;
    a full source migration must pick one convention first.
  - Company identity: canonical EXCHANGE_TICKER companyKey, or bare US ticker.

Usage:
    from fiscal_api import FiscalAPI, FiscalKeyMissing
    api = FiscalAPI()
    px = api.stock_prices(ticker="MOG.A", start="2024-08-01")
    python scripts/fiscal_api.py --selftest AAPL      # connectivity check
"""
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import requests
from dotenv import dotenv_values

BASE = "https://api.fiscal.ai"


class FiscalKeyMissing(RuntimeError):
    pass


class FiscalAPI:
    def __init__(self, key: str | None = None, timeout: int = 30):
        self.key = key or dotenv_values(ROOT / ".env").get("FISCAL_API_KEY")
        self.timeout = timeout
        self.s = requests.Session()

    def _get(self, path: str, **params):
        if not self.key:
            raise FiscalKeyMissing(
                "FISCAL_API_KEY not set in .env — add it (echo 'FISCAL_API_KEY=...' >> .env)")
        r = self.s.get(BASE + path, params={k: v for k, v in params.items() if v is not None},
                       headers={"X-Api-Key": self.key}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ── prices ────────────────────────────────────────────────────────────────
    def stock_prices(self, companyKey=None, ticker=None, start=None, end=None):
        """Daily split-adjusted OHLC+volume, newest first. v3 supports server-side date range."""
        return self._get("/v3/company/stock-prices", companyKey=companyKey, ticker=ticker,
                         startDate=start, endDate=end)

    # ── fundamentals ─────────────────────────────────────────────────────────
    def financials_standardized(self, statementType, companyKey=None, ticker=None,
                                periodType=None, currency=None):
        return self._get(f"/v1/company/financials/{statementType}/standardized",
                         companyKey=companyKey, ticker=ticker,
                         periodType=periodType, currency=currency)

    def earnings_summary(self, companyKey=None, ticker=None):
        return self._get("/v1/company/earnings-summary", companyKey=companyKey, ticker=ticker)

    def profile(self, companyKey=None, ticker=None):
        return self._get("/v1/company/profile", companyKey=companyKey, ticker=ticker)

    def companies_list(self, pageNumber=1, pageSize=1000):
        return self._get("/v1/companies-list", pageNumber=pageNumber, pageSize=pageSize)

    def events_calendar(self, companyKey=None, ticker=None, start=None, end=None,
                        page=None, pageSize=None):
        return self._get("/v1/events-calendar", companyKey=companyKey, ticker=ticker,
                         startDate=start, endDate=end, page=page, pageSize=pageSize)

    def insider_transactions(self, companyKey=None, ticker=None, pageNumber=1, pageSize=200):
        return self._get("/v1/company/ownership/insider/transactions",
                         companyKey=companyKey, ticker=ticker,
                         pageNumber=pageNumber, pageSize=pageSize)


def fetch_prices_fallback(tk: str, start: str | None = None):
    """Adapter for backfill_price_history: returns [(date, close, volume), ...] or None.

    Tries bare US ticker first (handles MOG.A-style class shares that yfinance
    needed symbol-mapping for), oldest-first for upsert convenience.
    """
    try:
        api = FiscalAPI()
        data = api.stock_prices(ticker=tk, start=start)
    except FiscalKeyMissing:
        return None
    except Exception:
        return None
    prices = (data or {}).get("prices") or []
    rows = [(p["date"], p.get("closePrice"), p.get("volume"))
            for p in prices if p.get("closePrice") is not None]
    rows.sort(key=lambda r: r[0])
    return rows or None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", metavar="TICKER", help="fetch profile + 5d prices for TICKER")
    a = ap.parse_args()
    if a.selftest:
        try:
            api = FiscalAPI()
            prof = api.profile(ticker=a.selftest.upper())
            px = api.stock_prices(ticker=a.selftest.upper(), start="2026-08-10")
            n = len((px or {}).get("prices") or [])
            name = prof.get("companyName") or prof.get("name") or "?"
            print(f"  ✅ Fiscal REST OK — {a.selftest.upper()}: {name} · {n} price rows since 2026-08-10")
        except FiscalKeyMissing as e:
            print(f"  ⚠️  {e}")
        except requests.HTTPError as e:
            print(f"  ❌ HTTP {e.response.status_code}: {e.response.text[:120]}")
