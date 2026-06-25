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
        data["day_change_pct"] = round((curr - prev) / prev * 100, 2) if curr and prev and prev != 0 else None

        # ── Fundamentals — ALL stored as PLAIN % to match screener format ────────
        # yfinance returns ratios as decimals (0.46 = 46%) → multiply by 100
        fcf = safe_float(info.get("freeCashflow"))
        mc  = data["market_cap"]
        data["fcf_yield_current"] = round(fcf / mc * 100, 2) if fcf and mc and mc > 0 else None
        if data["fcf_yield_current"] is None:
            missing.append("fcf_yield_current")

        gm_raw = safe_float(info.get("grossMargins"))
        data["gross_margin_trailing"] = round(gm_raw * 100, 2) if gm_raw is not None else None
        if data["gross_margin_trailing"] is None:
            missing.append("gross_margin_trailing")

        # FCF margin = FCF / revenue  (both in $, ratio → ×100 for %)
        rev = safe_float(info.get("totalRevenue"))
        data["fcf_margin_trailing"] = round(fcf / rev * 100, 2) if fcf and rev and rev > 0 else None
        if data["fcf_margin_trailing"] is None:
            missing.append("fcf_margin_trailing")

        # ROIC proxy: returnOnEquity — yfinance decimal → ×100 for plain %
        roe_raw = safe_float(info.get("returnOnEquity"))
        data["roic_trailing"] = round(roe_raw * 100, 2) if roe_raw is not None else None
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

        # Revenue 3Y CAGR — compute_revenue_cagr returns decimal, ×100 for plain %
        try:
            fin  = yf_ticker.financials
            cagr = compute_revenue_cagr(fin, years=3)
            data["revenue_3y_cagr_trailing"] = round(cagr * 100, 2) if cagr is not None else None
        except Exception:
            data["revenue_3y_cagr_trailing"] = None
            missing.append("revenue_3y_cagr_trailing")

        # ── Forward estimates — yfinance returns decimals → ×100 for plain % ──
        rev_growth = safe_float(info.get("revenueGrowth"))
        eps_growth = safe_float(info.get("earningsGrowth"))
        data["fwd_revenue_3y_cagr"] = round(rev_growth * 100, 2) if rev_growth is not None else None
        data["fwd_eps_3y_cagr"]     = round(eps_growth * 100, 2) if eps_growth is not None else None

        # FCF yield forward: forwardEps / price → decimal → ×100 for plain %
        fwd_eps = safe_float(info.get("forwardEps"))
        if fwd_eps and curr and curr > 0:
            data["fcf_yield_forward"] = round(fwd_eps / curr * 100, 2)
        else:
            data["fcf_yield_forward"] = None
            missing.append("fcf_yield_forward")

        # ── Earnings momentum / multiple ROC — all in plain % now ────────────
        # fwd_rev, trail_rev, fwd_eps_g are already plain % after ×100 above
        fwd_rev   = data.get("fwd_revenue_3y_cagr")
        trail_rev = data.get("revenue_3y_cagr_trailing")
        fwd_eps_g = data.get("fwd_eps_3y_cagr")
        trail_eps = safe_float(info.get("trailingEps"))
        fwd_eps_v = safe_float(info.get("forwardEps"))

        x_rev = (fwd_rev - trail_rev) if (fwd_rev is not None and trail_rev is not None) else None
        x_eps = None
        if fwd_eps_g is not None and trail_eps is not None and trail_eps != 0 and fwd_eps_v is not None:
            trailing_eps_g_pct = (fwd_eps_v - trail_eps) / abs(trail_eps) * 100
            x_eps = fwd_eps_g - trailing_eps_g_pct

        if x_rev is not None and x_eps is not None:
            data["earnings_momentum_roc"] = round(0.5 * (x_rev + x_eps), 2)
        elif x_rev is not None:
            data["earnings_momentum_roc"] = round(x_rev, 2)
        else:
            data["earnings_momentum_roc"] = None

        # multiple_roc = fcf_yield_current - fcf_yield_forward (both plain %)
        fcf_curr = data.get("fcf_yield_current")
        fcf_fwd  = data.get("fcf_yield_forward")
        data["multiple_roc"] = round(fcf_curr - fcf_fwd, 2) if (fcf_curr and fcf_fwd) else None

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
        # shortPercentOfFloat is decimal (0.008 = 0.8%) → ×100 for plain %
        si_raw = safe_float(info.get("shortPercentOfFloat"))
        data["short_interest_pct"] = round(si_raw * 100, 2) if si_raw is not None else None

        # ── Beta ──────────────────────────────────────────────────────────────
        data["beta"] = safe_float(info.get("beta"))

        # ── Price momentum from history ───────────────────────────────────────
        # Re-use hist if already fetched above; otherwise it's in scope
        try:
            if not hist.empty and len(hist) >= 21:
                cp = hist["Close"].iloc[-1]
                def mom(n):
                    if len(hist) < n: return None
                    raw = (float(cp) / float(hist["Close"].iloc[-n]) - 1)
                    return safe_float(round(raw * 100, 2))  # decimal → plain %
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

        # ── FCF conversion = FCF / Net Income → ratio → ×100 for plain % ──────
        net_income = safe_float(info.get("netIncomeToCommon"))
        data["fcf_conversion"] = round(fcf / net_income * 100, 2) if (
            fcf and net_income and net_income > 0) else None

        # ── ROIC spread = ROIC(plain%) - 8.0 (WACC as plain %) ──────────────
        roic = data.get("roic_trailing")  # already plain % after ×100 above
        data["roic_spread"] = round(roic - 8.0, 2) if roic is not None else None

        # ── Buyback yield — placeholder until FMP wired in ────────────────────
        data["buyback_yield"] = None

        # ── Institutional ownership — decimal → ×100 for plain % ────────────
        inst_raw = safe_float(info.get("heldPercentInstitutions"))
        data["institutional_own_pct"] = round(inst_raw * 100, 2) if inst_raw is not None else None

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

    print("\n[Signal Layer] Loading Fiscal AI signals...")
    load_fiscal_csv_signals(conn)

    conn.close()


def load_fiscal_csv_signals(conn):
    """
    Load new Fiscal AI columns, compute QGS and GER,
    write to company_market_data and ic_signal_rankings.

    QGS = ((Fwd Rev 3Y CAGR + Fwd EPS 3Y CAGR) x FCF/EV) x ROIC x FCF Margin
    GER = (Fwd Rev 3Y CAGR + Fwd EPS 3Y CAGR) / (SBC% Revenue + Shares Out Growth 3Y CAGR)

    All inputs are as decimals (e.g. 0.20 = 20%). The screener exports % strings
    which are stripped and divided by 100 during parsing.
    """
    import math
    from pathlib import Path
    from datetime import date as date_cls

    data_dir = Path(__file__).parent.parent / "data" / "raw"
    csv_files = sorted(
        list(data_dir.glob("Screener_Results_*.csv")),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    if not csv_files:
        print("  No Screener_Results_*.csv in data/raw/ — skipping signal computation")
        return []

    csv_path = csv_files[0]
    print(f"  CSV: {csv_path.name}")

    import pandas as pd
    df = pd.read_csv(csv_path)

    # ── Column mapping ─────────────────────────────────────────────────────
    col_map = {}
    for col in df.columns:
        cl = col.lower().strip()
        if cl in ('ticker', 'symbol'):
            col_map[col] = 'ticker'
        elif cl == 'company':
            col_map[col] = 'company'
        elif 'free cash flow (m)' in cl or cl == 'fcf (m)':
            col_map[col] = 'fcf_ttm'
        elif 'total enterprise value' in cl or 'tev' in cl:
            col_map[col] = 'enterprise_value'
        elif 'stock-based compensation' in cl or 'stock based comp' in cl:
            col_map[col] = 'sbc_dollar'
        elif 'free cash flow margin' in cl or 'fcf margin' in cl:
            col_map[col] = 'fcf_margin'
        elif 'shares out growth' in cl:
            col_map[col] = 'shares_out_growth_3y_cagr'
        elif 'revenue forward' in cl and ('cagr' in cl or 'growth' in cl):
            col_map[col] = 'fwd_rev_cagr'
        elif 'eps normalized forward' in cl:
            col_map[col] = 'fwd_eps_cagr'
        elif 'return on invested capital' in cl or cl == 'roic':
            col_map[col] = 'roic'
        elif 'revenue 3y cagr' in cl and 'forward' not in cl:
            col_map[col] = 'rev_3y_cagr'
        elif 'market cap' in cl:
            col_map[col] = 'market_cap'
        # ── V12 contamination-detector inputs ──────────────────────────────
        elif 'diluted eps 1y cagr' in cl or ('eps' in cl and '1y cagr' in cl and 'forward' not in cl):
            col_map[col] = 'eps_cagr_1y'
        elif 'diluted eps 3y cagr' in cl or ('eps' in cl and '3y cagr' in cl and 'forward' not in cl):
            col_map[col] = 'eps_3y_cagr'
        elif 'gross profit 1y cagr' in cl:
            col_map[col] = 'gp_cagr_1y'
        elif 'gross profit 3y cagr' in cl:
            col_map[col] = 'gp_cagr_3y'
        else:
            col_map[col] = col

    df = df.rename(columns=col_map)

    def _clean(series):
        """Strip $/%/commas and coerce to float."""
        return pd.to_numeric(
            series.astype(str)
                  .str.replace('$', '', regex=False)
                  .str.replace('%', '', regex=False)
                  .str.replace(',', '', regex=False)
                  .str.strip(),
            errors='coerce'
        )

    # Clean and convert % fields to decimals
    pct_fields = ['fcf_margin', 'shares_out_growth_3y_cagr', 'fwd_rev_cagr',
                  'fwd_eps_cagr', 'roic', 'rev_3y_cagr',
                  'eps_cagr_1y', 'eps_3y_cagr', 'gp_cagr_1y', 'gp_cagr_3y']
    dollar_fields = ['fcf_ttm', 'enterprise_value', 'sbc_dollar', 'market_cap']

    for f in pct_fields + dollar_fields:
        if f in df.columns:
            df[f] = _clean(df[f])
            if f in pct_fields:
                df[f] = df[f] / 100.0  # store as decimal

    results = []
    counts = {'qgs_valid': 0, 'qgs_skip': 0, 'ger_valid': 0,
              'ger_skip': 0, 'net_returner': 0, 'ger_floored': 0}

    for _, row in df.iterrows():
        ticker = str(row.get('ticker', '')).strip().upper()
        if not ticker or ticker in ('NAN', 'CASH', ''):
            continue

        def get(field):
            val = row.get(field)
            if val is None:
                return None
            try:
                f = float(val)
                return None if (math.isnan(f) or math.isinf(f)) else f
            except (TypeError, ValueError):
                return None

        fwd_rev    = get('fwd_rev_cagr')
        fwd_eps    = get('fwd_eps_cagr')
        roic       = get('roic')
        fcf_margin = get('fcf_margin')
        # V12 contamination-detector inputs (decimals)
        eps_1y     = get('eps_cagr_1y')
        eps_3y     = get('eps_3y_cagr')
        gp_1y      = get('gp_cagr_1y')
        gp_3y      = get('gp_cagr_3y')
        fcf_ttm    = get('fcf_ttm')
        ev         = get('enterprise_value')
        sbc_raw    = get('sbc_dollar')
        rev_ttm    = get('market_cap')        # use market_cap as rev proxy for SBC%
        shr_growth = get('shares_out_growth_3y_cagr')

        # FCF/EV — Owner Earnings Yield
        fcf_ev = None
        if fcf_ttm is not None and ev is not None and ev > 0:
            fcf_ev = fcf_ttm / ev

        # ── QGS ───────────────────────────────────────────────────────────
        qgs = None
        qgs_tier = None
        if all(v is not None for v in [fwd_rev, fwd_eps, fcf_ev, roic, fcf_margin]):
            if fcf_ev > 0:
                qgs = (fwd_rev + fwd_eps) * fcf_ev * roic * fcf_margin
                # Tiers calibrated to decimal-input distribution (P95/P90/P75/P50)
                if   qgs > 0.0028: qgs_tier = 'RARE_ELITE'
                elif qgs > 0.0016: qgs_tier = 'EXCEPTIONAL'
                elif qgs > 0.0006: qgs_tier = 'GOOD_COMPOUNDER'
                elif qgs > 0.0002: qgs_tier = 'AVERAGE'
                else:              qgs_tier = 'LOW_QUALITY'
                counts['qgs_valid'] += 1
            else:
                counts['qgs_skip'] += 1
        else:
            counts['qgs_skip'] += 1

        # ── GER ───────────────────────────────────────────────────────────
        ger = None
        ger_flag = None
        sbc_pct = None

        # SBC% = SBC dollars / revenue TTM
        # We use market_cap as a rough proxy if revenue not available;
        # this will be imprecise but directionally correct for ranking.
        rev_for_sbc = get('rev_3y_cagr')   # not revenue level, skip
        # Use absolute revenue from market_cap column not available — use EV as proxy
        if sbc_raw is not None and ev is not None and ev > 0:
            sbc_pct = sbc_raw / ev  # SBC as % of EV (conservative proxy)

        if all(v is not None for v in [fwd_rev, fwd_eps, sbc_pct, shr_growth]):
            growth_num  = fwd_rev + fwd_eps
            denominator = sbc_pct + shr_growth

            if denominator < 0:
                ger_flag = 'NET_RETURNER'
                counts['net_returner'] += 1
            elif denominator < 0.01:
                denominator = 0.01
                ger = growth_num / denominator
                ger_flag = 'FLOORED'
                counts['ger_floored'] += 1
                counts['ger_valid'] += 1
            else:
                ger = growth_num / denominator
                ger_flag = 'NORMAL'
                counts['ger_valid'] += 1
        else:
            counts['ger_skip'] += 1

        # ── V12 Earnings Quality Contamination Detector ───────────────────
        eps_accel = (eps_1y - eps_3y) if (eps_1y is not None and eps_3y is not None) else None
        gp_accel  = (gp_1y - gp_3y)   if (gp_1y is not None and gp_3y is not None) else None
        if eps_accel is None or gp_accel is None:
            eq_flag = 'DATA_INCOMPLETE'
        elif eps_accel > 0 and gp_accel > 0:
            eq_flag = 'EPS_CONFIRMED'
        elif eps_accel > 0 and gp_accel <= 0:
            eq_flag = 'EPS_ENGINEERED'
        elif gp_accel > 0 and eps_accel <= 0:
            eq_flag = 'GP_LEADING'
        else:
            eq_flag = 'NEUTRAL'
        counts.setdefault('eq_' + eq_flag.lower(), 0)
        counts['eq_' + eq_flag.lower()] += 1

        results.append({
            'ticker':                    ticker,
            'eps_cagr_1y':               eps_1y,
            'gp_cagr_1y':                gp_1y,
            'gp_cagr_3y':                gp_3y,
            'eps_acceleration':          round(eps_accel, 6) if eps_accel is not None else None,
            'gp_acceleration':           round(gp_accel, 6) if gp_accel is not None else None,
            'earnings_quality_flag':     eq_flag,
            'fwd_rev_3y_cagr':           fwd_rev,
            'fwd_eps_3y_cagr':           fwd_eps,
            'roic_trailing':             roic,
            'fcf_margin_trailing':       fcf_margin,
            'enterprise_value':          ev,
            'fcf_ttm':                   fcf_ttm,
            'fcf_ev_yield':              round(fcf_ev, 6) if fcf_ev is not None else None,
            'sbc_dollar':                sbc_raw,
            'sbc_pct_revenue':           round(sbc_pct, 6) if sbc_pct is not None else None,
            'shares_out_growth_3y_cagr': shr_growth,
            'quality_growth_score':      round(qgs, 6) if qgs is not None else None,
            'growth_efficiency_ratio':   round(ger, 4) if ger is not None else None,
            'qgs_tier':                  qgs_tier,
            'ger_flag':                  ger_flag,
        })

    print(f"  Processed {len(results)} tickers")
    print(f"  QGS: {counts['qgs_valid']} valid | {counts['qgs_skip']} skipped")
    print(f"  GER: {counts['ger_valid']} valid | {counts['ger_skip']} skipped | "
          f"{counts['net_returner']} net returners | {counts['ger_floored']} floored")
    print(f"  Earnings Quality: "
          f"CONFIRMED={counts.get('eq_eps_confirmed',0)} "
          f"ENGINEERED={counts.get('eq_eps_engineered',0)} "
          f"GP_LEADING={counts.get('eq_gp_leading',0)} "
          f"NEUTRAL={counts.get('eq_neutral',0)} "
          f"INCOMPLETE={counts.get('eq_data_incomplete',0)}")

    # ── Rankings ───────────────────────────────────────────────────────────
    valid_qgs = [(r['ticker'], r['quality_growth_score'])
                 for r in results if r['quality_growth_score'] is not None]
    valid_ger = [(r['ticker'], r['growth_efficiency_ratio'])
                 for r in results if r['growth_efficiency_ratio'] is not None]

    qgs_ranked = {t: i+1 for i, (t, _) in
                  enumerate(sorted(valid_qgs, key=lambda x: x[1], reverse=True))}
    ger_ranked = {t: i+1 for i, (t, _) in
                  enumerate(sorted(valid_ger, key=lambda x: x[1], reverse=True))}
    n_qgs = max(len(valid_qgs), 1)
    n_ger = max(len(valid_ger), 1)

    # V12 — FCF/EV percentile rank (replaces raw EV rank). 100 = cheapest on cash yield.
    valid_fcfev = [(r['ticker'], r['fcf_ev_yield'])
                   for r in results if r['fcf_ev_yield'] is not None]
    fcfev_ranked = {t: i+1 for i, (t, _) in
                    enumerate(sorted(valid_fcfev, key=lambda x: x[1], reverse=True))}
    n_fcfev = max(len(valid_fcfev), 1)

    # ── Write to Supabase ──────────────────────────────────────────────────
    cur   = conn.cursor()
    today = date_cls.today()
    written = errors = 0

    for r in results:
        ticker   = r['ticker']
        qgs_rank = qgs_ranked.get(ticker)
        ger_rank = ger_ranked.get(ticker)
        qgs_pct  = round((1 - qgs_rank / n_qgs) * 100, 1) if qgs_rank else None
        ger_pct  = round((1 - ger_rank / n_ger) * 100, 1) if ger_rank else None
        fcfev_rank = fcfev_ranked.get(ticker)
        fcfev_pct  = round((1 - fcfev_rank / n_fcfev) * 100, 1) if fcfev_rank else None

        cur.execute("""
            SELECT quad_current, in_portfolio, company_name
            FROM companies WHERE ticker = %s
        """, (ticker,))
        co      = cur.fetchone()
        quad    = co[0] if co else None
        in_port = co[1] if co else False
        co_name = co[2] if co else ticker
        is_q2   = (quad == 'Q2')

        try:
            # Update most-recent company_market_data row
            cur.execute("""
                UPDATE company_market_data SET
                    sbc_dollar                  = %s,
                    sbc_pct_revenue             = %s,
                    shares_out_growth_3y_cagr   = %s,
                    enterprise_value            = %s,
                    fcf_ev_yield                = %s,
                    quality_growth_score        = %s,
                    growth_efficiency_ratio     = %s,
                    qgs_tier                    = %s,
                    ger_flag                    = %s,
                    fcf_ev_rank                 = %s,
                    eps_cagr_1y                 = %s,
                    gp_cagr_1y                  = %s,
                    gp_cagr_3y                  = %s,
                    eps_acceleration            = %s,
                    gp_acceleration             = %s,
                    earnings_quality_flag       = %s
                WHERE ticker = %s
                AND data_date = (
                    SELECT MAX(data_date) FROM company_market_data
                    WHERE ticker = %s
                )
            """, (
                r['sbc_dollar'],
                r['sbc_pct_revenue'],
                r['shares_out_growth_3y_cagr'],
                r['enterprise_value'],
                r['fcf_ev_yield'],
                r['quality_growth_score'],
                r['growth_efficiency_ratio'],
                r['qgs_tier'],
                r['ger_flag'],
                fcfev_pct,
                r['eps_cagr_1y'],
                r['gp_cagr_1y'],
                r['gp_cagr_3y'],
                r['eps_acceleration'],
                r['gp_acceleration'],
                r['earnings_quality_flag'],
                ticker, ticker
            ))
            # Mirror earnings_quality_flag onto companies for quad-level cache
            cur.execute("""
                UPDATE companies SET earnings_quality_flag = %s, fcf_ev_rank = %s
                WHERE ticker = %s
            """, (r['earnings_quality_flag'], fcfev_pct, ticker))

            # Upsert into ic_signal_rankings
            cur.execute("""
                INSERT INTO ic_signal_rankings (
                    rank_date, ticker, company_name, quad_current,
                    fwd_rev_3y_cagr, fwd_eps_3y_cagr,
                    roic_trailing, fcf_margin_trailing, fcf_ev_yield,
                    sbc_pct_revenue, shares_out_growth_3y_cagr,
                    quality_growth_score, growth_efficiency_ratio,
                    qgs_tier, ger_flag,
                    qgs_rank, ger_rank,
                    qgs_percentile, ger_percentile,
                    is_q2, in_portfolio
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                ON CONFLICT (rank_date, ticker) DO UPDATE SET
                    quality_growth_score      = EXCLUDED.quality_growth_score,
                    growth_efficiency_ratio   = EXCLUDED.growth_efficiency_ratio,
                    fcf_ev_yield              = EXCLUDED.fcf_ev_yield,
                    qgs_rank                  = EXCLUDED.qgs_rank,
                    ger_rank                  = EXCLUDED.ger_rank,
                    qgs_percentile            = EXCLUDED.qgs_percentile,
                    ger_percentile            = EXCLUDED.ger_percentile,
                    qgs_tier                  = EXCLUDED.qgs_tier,
                    ger_flag                  = EXCLUDED.ger_flag,
                    is_q2                     = EXCLUDED.is_q2,
                    in_portfolio              = EXCLUDED.in_portfolio
            """, (
                today, ticker, co_name, quad,
                r['fwd_rev_3y_cagr'], r['fwd_eps_3y_cagr'],
                r['roic_trailing'], r['fcf_margin_trailing'], r['fcf_ev_yield'],
                r['sbc_pct_revenue'], r['shares_out_growth_3y_cagr'],
                r['quality_growth_score'], r['growth_efficiency_ratio'],
                r['qgs_tier'], r['ger_flag'],
                qgs_rank, ger_rank,
                qgs_pct, ger_pct,
                is_q2, in_port
            ))
            written += 1

        except Exception as e:
            errors += 1
            print(f"  [{ticker}] {e}")

    # Q2-specific ranking
    cur.execute("""
        WITH q2_ranked AS (
            SELECT ticker,
                   ROW_NUMBER() OVER (
                       ORDER BY quality_growth_score DESC NULLS LAST
                   ) AS q2_rank
            FROM ic_signal_rankings
            WHERE rank_date = %s AND is_q2 = TRUE
              AND quality_growth_score IS NOT NULL
        )
        UPDATE ic_signal_rankings r
        SET qgs_rank_within_q2 = q.q2_rank
        FROM q2_ranked q
        WHERE r.ticker = q.ticker AND r.rank_date = %s
    """, (today, today))

    conn.commit()
    cur.close()
    print(f"  Written: {written} | Errors: {errors}")
    return results


if __name__ == "__main__":
    main()
