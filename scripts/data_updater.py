"""
data_updater.py
---------------
Pulls live price, fundamental, and estimate data for all active companies
and writes to company_market_data table. Run daily.

Usage:
    python scripts/data_updater.py                 # update all active companies
    python scripts/data_updater.py --ticker AAPL   # single ticker
"""

import sys
import math
import argparse
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
import yfinance as yf
import numpy as np
from config.settings import settings


# ── DB connection ──────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(settings.DATABASE_URL)


# ── Technical indicator helpers ────────────────────────────────────────────────

def compute_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def compute_atr(highs: list[float], lows: list[float],
                closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        hl  = highs[i]  - lows[i]
        hcp = abs(highs[i]  - closes[i-1])
        lcp = abs(lows[i]   - closes[i-1])
        trs.append(max(hl, hcp, lcp))
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return round(atr, 4)


def compute_revenue_cagr(financials, years: int = 3) -> float | None:
    """Compute trailing revenue CAGR from yfinance financials DataFrame."""
    try:
        rev_row = financials.loc["Total Revenue"] if "Total Revenue" in financials.index else None
        if rev_row is None:
            return None
        rev_vals = rev_row.dropna().sort_index(ascending=False)
        if len(rev_vals) < years + 1:
            return None
        end_val   = float(rev_vals.iloc[0])
        start_val = float(rev_vals.iloc[years])
        if start_val <= 0 or end_val <= 0:
            return None
        return round((end_val / start_val) ** (1 / years) - 1, 4)
    except Exception:
        return None


def safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return None


# ── Single ticker fetch ────────────────────────────────────────────────────────

def fetch_ticker_data(ticker: str) -> tuple[dict, list[str]]:
    """
    Fetch all data for one ticker.
    Returns (data_dict, missing_fields).
    data_dict has None for unavailable fields — never raises.
    """
    data    = {}
    missing = []

    try:
        yf_ticker = yf.Ticker(ticker)
        info      = yf_ticker.info or {}

        # ── Price & market ────────────────────────────────────────────────────
        data["current_price"]  = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        data["market_cap"]     = safe_float(info.get("marketCap"))
        data["pe_forward"]     = safe_float(info.get("forwardPE"))
        data["ev_ebitda"]      = safe_float(info.get("enterpriseToEbitda"))
        data["week_52_high"]   = safe_float(info.get("fiftyTwoWeekHigh"))
        data["week_52_low"]    = safe_float(info.get("fiftyTwoWeekLow"))

        # Day change %
        prev  = safe_float(info.get("regularMarketPreviousClose"))
        curr  = data["current_price"]
        data["day_change_pct"] = round((curr - prev) / prev, 4) if curr and prev and prev != 0 else None

        # ── Fundamentals ─────────────────────────────────────────────────────
        fcf = safe_float(info.get("freeCashflow"))
        mc  = data["market_cap"]
        data["fcf_yield_current"] = round(fcf / mc, 4) if fcf and mc and mc > 0 else None
        if data["fcf_yield_current"] is None:
            missing.append("fcf_yield_current")

        data["gross_margin_trailing"] = safe_float(info.get("grossMargins"))
        if data["gross_margin_trailing"] is None:
            missing.append("gross_margin_trailing")

        # FCF margin = FCF / revenue
        rev = safe_float(info.get("totalRevenue"))
        data["fcf_margin_trailing"] = round(fcf / rev, 4) if fcf and rev and rev > 0 else None
        if data["fcf_margin_trailing"] is None:
            missing.append("fcf_margin_trailing")

        # ROIC proxy: returnOnEquity (note: true ROIC needs invested capital)
        data["roic_trailing"] = safe_float(info.get("returnOnEquity"))
        if data["roic_trailing"] is None:
            missing.append("roic_trailing (returnOnEquity proxy)")

        # Net Debt / EBITDA
        total_debt = safe_float(info.get("totalDebt"))
        cash       = safe_float(info.get("totalCash"))
        ebitda     = safe_float(info.get("ebitda"))
        net_debt   = (total_debt or 0) - (cash or 0)
        data["net_debt_ebitda"] = round(net_debt / ebitda, 4) if ebitda and ebitda > 0 else None
        if data["net_debt_ebitda"] is None:
            missing.append("net_debt_ebitda")

        # Revenue 3Y CAGR from financials
        try:
            fin = yf_ticker.financials
            data["revenue_3y_cagr_trailing"] = compute_revenue_cagr(fin, years=3)
        except Exception:
            data["revenue_3y_cagr_trailing"] = None
            missing.append("revenue_3y_cagr_trailing")

        # ── Forward estimates (1Y proxies — note in comments) ─────────────────
        # NOTE: yfinance revenueGrowth / earningsGrowth are 1Y forward estimates,
        # used as proxies for fwd_revenue_3y_cagr / fwd_eps_3y_cagr until a
        # better consensus source (e.g. Bloomberg, FactSet) is wired in.
        data["fwd_revenue_3y_cagr"] = safe_float(info.get("revenueGrowth"))
        data["fwd_eps_3y_cagr"]     = safe_float(info.get("earningsGrowth"))

        # FCF yield forward: use forwardEps / currentPrice as rough proxy
        fwd_eps = safe_float(info.get("forwardEps"))
        if fwd_eps and curr and curr > 0:
            data["fcf_yield_forward"] = round(fwd_eps / curr, 4)
        else:
            data["fcf_yield_forward"] = None
            missing.append("fcf_yield_forward")

        # ── Earnings momentum / multiple ROC for quad ─────────────────────────
        fwd_rev  = data.get("fwd_revenue_3y_cagr")
        trail_rev = data.get("revenue_3y_cagr_trailing")
        fwd_eps_g  = data.get("fwd_eps_3y_cagr")
        trail_eps  = safe_float(info.get("trailingEps"))
        fwd_eps_v  = safe_float(info.get("forwardEps"))

        x_rev = (fwd_rev - trail_rev) if (fwd_rev is not None and trail_rev is not None) else None
        # EPS momentum: forward EPS growth vs trailing growth proxy
        x_eps = None
        if fwd_eps_g is not None and trail_eps is not None and trail_eps != 0 and fwd_eps_v is not None:
            trailing_eps_g = (fwd_eps_v - trail_eps) / abs(trail_eps)
            x_eps = fwd_eps_g - trailing_eps_g

        if x_rev is not None and x_eps is not None:
            data["earnings_momentum_roc"] = round(0.5 * (x_rev + x_eps), 4)
        elif x_rev is not None:
            data["earnings_momentum_roc"] = round(x_rev, 4)
        else:
            data["earnings_momentum_roc"] = None

        fcf_curr = data.get("fcf_yield_current")
        fcf_fwd  = data.get("fcf_yield_forward")
        data["multiple_roc"] = round(fcf_curr - fcf_fwd, 4) if (fcf_curr and fcf_fwd) else None

        # ── Technical indicators from price history ────────────────────────────
        try:
            hist = yf_ticker.history(period="1y", interval="1d")
            if not hist.empty and len(hist) >= 20:
                closes  = hist["Close"].tolist()
                highs   = hist["High"].tolist()
                lows    = hist["Low"].tolist()

                # SMAs
                data["sma_50"]  = round(sum(closes[-50:])  / min(50,  len(closes)), 4) if len(closes) >= 50  else None
                data["sma_200"] = round(sum(closes[-200:]) / min(200, len(closes)), 4) if len(closes) >= 200 else None

                # RSI 14
                data["rsi_14"]  = compute_rsi(closes[-30:])

                # ATR 14
                data["atr_14"]  = compute_atr(highs[-30:], lows[-30:], closes[-30:])
            else:
                data.update({"sma_50": None, "sma_200": None, "rsi_14": None, "atr_14": None})
                missing.append("technicals")
        except Exception as e:
            data.update({"sma_50": None, "sma_200": None, "rsi_14": None, "atr_14": None})
            missing.append(f"technicals ({e})")

        # ── Other ──────────────────────────────────────────────────────────────
        earnings_ts = info.get("earningsDate") or info.get("earningsTimestamp")
        data["next_earnings_date"] = None
        if earnings_ts:
            try:
                if isinstance(earnings_ts, (list, tuple)):
                    earnings_ts = earnings_ts[0]
                if isinstance(earnings_ts, (int, float)):
                    data["next_earnings_date"] = datetime.fromtimestamp(earnings_ts).date()
                elif hasattr(earnings_ts, "date"):
                    data["next_earnings_date"] = earnings_ts.date()
            except Exception:
                pass

        data["analyst_count"]      = info.get("numberOfAnalystOpinions")
        data["short_interest_pct"] = safe_float(info.get("shortPercentOfFloat"))

        # ── Beta ──────────────────────────────────────────────────────────────
        data["beta"] = safe_float(info.get("beta"))

        # ── Price momentum from history ───────────────────────────────────────
        # Re-use hist if already fetched above; otherwise it's in scope
        try:
            if not hist.empty and len(hist) >= 21:
                cp = hist["Close"].iloc[-1]
                def mom(n):
                    if len(hist) < n: return None
                    return safe_float(round((float(cp) / float(hist["Close"].iloc[-n]) - 1), 4))
                data["momentum_1m"]  = mom(21)
                data["momentum_3m"]  = mom(63)
                data["momentum_6m"]  = mom(126)
                data["momentum_12m"] = mom(252)
            else:
                data.update({"momentum_1m": None, "momentum_3m": None,
                              "momentum_6m": None, "momentum_12m": None})
        except Exception:
            data.update({"momentum_1m": None, "momentum_3m": None,
                          "momentum_6m": None, "momentum_12m": None})
            missing.append("momentum")

        # ── FCF conversion = FCF / Net Income ─────────────────────────────────
        net_income = safe_float(info.get("netIncomeToCommon"))
        data["fcf_conversion"] = round(fcf / net_income, 4) if (
            fcf and net_income and net_income > 0) else None

        # ── ROIC spread = ROIC - 8% WACC proxy ───────────────────────────────
        roic = data.get("roic_trailing")
        data["roic_spread"] = round(roic - 0.08, 4) if roic is not None else None

        # ── Buyback yield — placeholder until FMP wired in ────────────────────
        data["buyback_yield"] = None

        # ── Institutional ownership ───────────────────────────────────────────
        data["institutional_own_pct"] = safe_float(info.get("heldPercentInstitutions"))

        # Revision velocity placeholders (need weekly snapshot to compute)
        data["fwd_revenue_cagr_prior_week"] = None
        data["fwd_eps_cagr_prior_week"]     = None
        data["revision_velocity_revenue"]   = None
        data["revision_velocity_eps"]       = None

    except Exception as e:
        return {}, [f"FATAL: {e}"]

    return data, missing


# ── DB upsert ──────────────────────────────────────────────────────────────────

UPSERT_SQL = """
INSERT INTO company_market_data (
    company_id, ticker, data_date,
    current_price, day_change_pct, week_52_high, week_52_low,
    market_cap, pe_forward, ev_ebitda,
    fcf_yield_current, fcf_yield_forward,
    roic_trailing, gross_margin_trailing, fcf_margin_trailing,
    revenue_3y_cagr_trailing, net_debt_ebitda,
    fwd_revenue_3y_cagr, fwd_eps_3y_cagr,
    earnings_momentum_roc, multiple_roc,
    fwd_revenue_cagr_prior_week, fwd_eps_cagr_prior_week,
    revision_velocity_revenue, revision_velocity_eps,
    sma_50, sma_200, rsi_14, atr_14,
    next_earnings_date, analyst_count, short_interest_pct,
    beta, momentum_1m, momentum_3m, momentum_6m, momentum_12m,
    fcf_conversion, roic_spread, buyback_yield, institutional_own_pct
) VALUES (
    %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s,
    %s, %s, %s,
    %s, %s,
    %s, %s,
    %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s
)
ON CONFLICT (company_id, data_date) DO UPDATE SET
    current_price               = EXCLUDED.current_price,
    day_change_pct              = EXCLUDED.day_change_pct,
    week_52_high                = EXCLUDED.week_52_high,
    week_52_low                 = EXCLUDED.week_52_low,
    market_cap                  = EXCLUDED.market_cap,
    pe_forward                  = EXCLUDED.pe_forward,
    ev_ebitda                   = EXCLUDED.ev_ebitda,
    fcf_yield_current           = EXCLUDED.fcf_yield_current,
    fcf_yield_forward           = EXCLUDED.fcf_yield_forward,
    roic_trailing               = EXCLUDED.roic_trailing,
    gross_margin_trailing       = EXCLUDED.gross_margin_trailing,
    fcf_margin_trailing         = EXCLUDED.fcf_margin_trailing,
    revenue_3y_cagr_trailing    = EXCLUDED.revenue_3y_cagr_trailing,
    net_debt_ebitda             = EXCLUDED.net_debt_ebitda,
    fwd_revenue_3y_cagr         = EXCLUDED.fwd_revenue_3y_cagr,
    fwd_eps_3y_cagr             = EXCLUDED.fwd_eps_3y_cagr,
    earnings_momentum_roc       = EXCLUDED.earnings_momentum_roc,
    multiple_roc                = EXCLUDED.multiple_roc,
    sma_50                      = EXCLUDED.sma_50,
    sma_200                     = EXCLUDED.sma_200,
    rsi_14                      = EXCLUDED.rsi_14,
    atr_14                      = EXCLUDED.atr_14,
    next_earnings_date          = EXCLUDED.next_earnings_date,
    analyst_count               = EXCLUDED.analyst_count,
    short_interest_pct          = EXCLUDED.short_interest_pct,
    beta                        = EXCLUDED.beta,
    momentum_1m                 = EXCLUDED.momentum_1m,
    momentum_3m                 = EXCLUDED.momentum_3m,
    momentum_6m                 = EXCLUDED.momentum_6m,
    momentum_12m                = EXCLUDED.momentum_12m,
    fcf_conversion              = EXCLUDED.fcf_conversion,
    roic_spread                 = EXCLUDED.roic_spread,
    buyback_yield               = EXCLUDED.buyback_yield,
    institutional_own_pct       = EXCLUDED.institutional_own_pct
"""

def upsert_market_data(company_id: str, ticker: str, data: dict, conn) -> None:
    today = date.today()
    cur = conn.cursor()
    cur.execute(UPSERT_SQL, (
        company_id, ticker, today,
        data.get("current_price"), data.get("day_change_pct"),
        data.get("week_52_high"),  data.get("week_52_low"),
        data.get("market_cap"),    data.get("pe_forward"), data.get("ev_ebitda"),
        data.get("fcf_yield_current"), data.get("fcf_yield_forward"),
        data.get("roic_trailing"), data.get("gross_margin_trailing"),
        data.get("fcf_margin_trailing"), data.get("revenue_3y_cagr_trailing"),
        data.get("net_debt_ebitda"),
        data.get("fwd_revenue_3y_cagr"), data.get("fwd_eps_3y_cagr"),
        data.get("earnings_momentum_roc"), data.get("multiple_roc"),
        data.get("fwd_revenue_cagr_prior_week"), data.get("fwd_eps_cagr_prior_week"),
        data.get("revision_velocity_revenue"), data.get("revision_velocity_eps"),
        data.get("sma_50"), data.get("sma_200"),
        data.get("rsi_14"), data.get("atr_14"),
        data.get("next_earnings_date"), data.get("analyst_count"),
        data.get("short_interest_pct"),
        data.get("beta"),
        data.get("momentum_1m"), data.get("momentum_3m"),
        data.get("momentum_6m"), data.get("momentum_12m"),
        data.get("fcf_conversion"), data.get("roic_spread"),
        data.get("buyback_yield"), data.get("institutional_own_pct"),
    ))
    cur.close()


# ── Sector concentration check ─────────────────────────────────────────────────

def print_sector_check(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT sector, COUNT(*) as n,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
        FROM companies
        WHERE in_portfolio = TRUE AND active = TRUE AND sector IS NOT NULL
        GROUP BY sector
        ORDER BY n DESC
    """)
    rows = cur.fetchall()
    cur.close()

    print("\n  SECTOR CONCENTRATION CHECK (equal weight, portfolio holdings)")
    print(f"  {'Sector':<38} {'Weight':>7}  Status")
    print("  " + "-" * 55)
    for sector, n, pct in rows:
        pct_f = float(pct)
        flag  = "⚠️  ABOVE 28% CAP" if pct_f > 28 else "✅"
        print(f"  {str(sector):<38} {pct_f:>5.1f}%  {flag}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, default=None,
                        help="Single ticker to update (default: all active)")
    args = parser.parse_args()

    conn = get_conn()
    conn.autocommit = False
    cur  = conn.cursor()

    if args.ticker:
        cur.execute(
            "SELECT id, ticker FROM companies WHERE ticker = %s AND active = TRUE",
            (args.ticker.upper(),)
        )
    else:
        cur.execute("SELECT id, ticker FROM companies WHERE active = TRUE ORDER BY ticker")

    companies = cur.fetchall()
    cur.close()

    if not companies:
        print(f"No {'active ' if not args.ticker else ''}companies found.")
        conn.close()
        return

    n_total  = len(companies)
    n_ok     = 0
    n_partial= 0
    n_failed = 0

    print(f"\n  DATA UPDATER — {date.today()} — {n_total} ticker(s)\n")

    for company_id, ticker in companies:
        data, missing = fetch_ticker_data(ticker)

        if not data:
            err = missing[0] if missing else "unknown error"
            print(f"  ❌ {ticker:<6} — failed: {err}")
            n_failed += 1
            continue

        try:
            upsert_market_data(str(company_id), ticker, data, conn)
            conn.commit()
            price_str = f"${data['current_price']:,.2f}" if data.get('current_price') else "n/a"
            if missing:
                clean_missing = [m for m in missing if "FATAL" not in m]
                print(f"  ⚠️  {ticker:<6} — partial (price: {price_str}, missing: {', '.join(clean_missing[:3])})")
                n_partial += 1
            else:
                print(f"  ✅ {ticker:<6} — updated (price: {price_str})")
                n_ok += 1
        except Exception as e:
            conn.rollback()
            print(f"  ❌ {ticker:<6} — DB write failed: {e}")
            n_failed += 1

    print(f"\n  SUMMARY: {n_ok} updated  |  {n_partial} partial  |  {n_failed} failed\n")
    print_sector_check(conn)
    conn.close()


if __name__ == "__main__":
    main()
