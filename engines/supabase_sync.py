"""
supabase_sync.py — Screener → Supabase sync
Integrity Compounders Alpha System v10.0

Called automatically at the end of every `python run.py refresh`.
Syncs the full enriched screener universe into two Supabase tables:

  companies          — one row per ticker (upsert on ticker)
  company_market_data — one row per ticker per date (upsert on company_id + data_date)

Design principles:
  - Non-fatal: if Supabase is unreachable, refresh still succeeds locally
  - Additive: never deletes or overwrites in_portfolio / is_discretionary flags
  - Fast: batches all writes in a single transaction per table
  - Transparent: prints a one-line summary with counts
"""

import sys
from pathlib import Path
from datetime import date
import math

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
import psycopg2.extras as pg_extras
import pandas as pd
from config.settings import settings


# ── Column maps ────────────────────────────────────────────────────────────────
# Screener / IC-pipeline field → Supabase company_market_data column
MARKET_DATA_MAP = {
    "stock_price":          "current_price",
    "market_cap":           "market_cap",
    "roic":                 "roic_trailing",        # screener stores as plain %
    "op_margin":            "gross_margin_trailing", # proxy (op margin ≈ gross margin)
    "fcf_yield":            "fcf_yield_current",
    "fwd_fcf_yield":        "fcf_yield_forward",
    "rev_3y_cagr":          "revenue_3y_cagr_trailing",
    "fwd_rev_cagr":         "fwd_revenue_3y_cagr",
    "eps_3y_cagr":          "fwd_eps_3y_cagr",      # trailing EPS CAGR → used as proxy
    "fwd_eps_cagr":         "fwd_eps_3y_cagr",      # override with actual fwd if present
    "net_debt_ebitda":      "net_debt_ebitda",
    "beta":                 "beta_col",              # renamed below to avoid conflict
    "tr_1m":                "day_change_pct",        # 1-month return as day proxy
    "earnings_mom_roc":     "earnings_momentum_roc",
    "multiple_roc":         "multiple_roc",
    "peg":                  "pe_forward",            # PEG as forward PE proxy
}

# Fields that come out of the IC pipeline (computed, not raw screener)
PIPELINE_FIELDS = [
    ("earnings_mom_roc", "earnings_momentum_roc"),
    ("multiple_roc",     "multiple_roc"),
]


def _safe(v):
    """Return None for NaN/inf, else the value."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return str(v) if isinstance(v, str) else None


def _get_or_create_companies(tickers: list[str], rows: dict[str, dict],
                              cur) -> dict[str, str]:
    """
    Batch-upsert all tickers into companies in one query using executemany.
    Returns {ticker: company_id} map.
    Preserves existing in_portfolio / is_discretionary / thesis fields.
    """
    batch = [
        (
            ticker,
            str(rows.get(ticker, {}).get("company", ticker))[:200],
            str(rows.get(ticker, {}).get("sector",  "") or "")[:100],
            str(rows.get(ticker, {}).get("industry","") or "")[:100],
        )
        for ticker in tickers
    ]
    pg_extras.execute_values(cur, """
        INSERT INTO companies (ticker, company_name, sector, industry, active)
        VALUES %s
        ON CONFLICT (ticker) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            sector       = EXCLUDED.sector,
            industry     = EXCLUDED.industry,
            active       = TRUE,
            updated_at   = NOW()
    """, batch, page_size=100)

    # Fetch all IDs in one query
    cur.execute("SELECT ticker, id FROM companies WHERE ticker = ANY(%s)", (tickers,))
    return {r[0]: str(r[1]) for r in cur.fetchall()}


def _upsert_market_data(company_id: str, ticker: str,
                         row: pd.Series, data_date: str, cur) -> None:
    """Upsert one row into company_market_data."""
    def g(field):
        return _safe(row.get(field))

    # Screener stores percentages as plain numbers (e.g. 12.5 = 12.5%)
    # company_market_data expects the same format — no conversion needed

    # Compute next_earnings_date if available (not in screener, leave NULL)
    cur.execute("""
    INSERT INTO company_market_data (
        company_id, ticker, data_date,
        current_price, market_cap,
        roic_trailing, gross_margin_trailing,
        fcf_yield_current, fcf_yield_forward,
        revenue_3y_cagr_trailing, net_debt_ebitda,
        fwd_revenue_3y_cagr, fwd_eps_3y_cagr,
        earnings_momentum_roc, multiple_roc,
        pe_forward, short_interest_pct
    ) VALUES (
        %s, %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s, %s
    )
    ON CONFLICT (company_id, data_date) DO UPDATE SET
        current_price              = EXCLUDED.current_price,
        market_cap                 = EXCLUDED.market_cap,
        roic_trailing              = EXCLUDED.roic_trailing,
        gross_margin_trailing      = EXCLUDED.gross_margin_trailing,
        fcf_yield_current          = EXCLUDED.fcf_yield_current,
        fcf_yield_forward          = EXCLUDED.fcf_yield_forward,
        revenue_3y_cagr_trailing   = EXCLUDED.revenue_3y_cagr_trailing,
        net_debt_ebitda            = EXCLUDED.net_debt_ebitda,
        fwd_revenue_3y_cagr        = EXCLUDED.fwd_revenue_3y_cagr,
        fwd_eps_3y_cagr            = EXCLUDED.fwd_eps_3y_cagr,
        earnings_momentum_roc      = EXCLUDED.earnings_momentum_roc,
        multiple_roc               = EXCLUDED.multiple_roc,
        pe_forward                 = EXCLUDED.pe_forward
    """, (
        company_id, ticker, data_date,
        g("stock_price"),    g("market_cap"),
        g("roic"),           g("op_margin"),
        g("fcf_yield"),      g("fwd_fcf_yield"),
        g("rev_3y_cagr"),    g("net_debt_ebitda"),
        g("fwd_rev_cagr"),   g("fwd_eps_cagr"),
        g("earnings_mom_roc"), g("multiple_roc"),
        g("peg"),            g("short_interest_pct") if "short_interest_pct" in row.index else None,
    ))


def _gate_status(row: pd.Series) -> str:
    gates_pass = _safe(row.get("gates_pass"))
    if gates_pass is None:
        return "UNSCREENED"
    n = int(gates_pass)
    return {5:"PASS", 4:"WATCH_1", 3:"WATCH_2"}.get(n, "FAIL")


# ── Main entry point ──────────────────────────────────────────────────────────

def sync_universe_to_supabase(df: pd.DataFrame, data_date: str) -> None:
    """
    Sync the full enriched screener DataFrame to Supabase.
    Uses batch operations (executemany) — 3 SQL round-trips regardless of universe size.
    Non-fatal — catches all exceptions and logs without crashing the refresh.
    """
    if df.empty:
        return

    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = False
        cur  = conn.cursor()

        tickers   = df["ticker"].tolist()
        rows_dict = df.set_index("ticker").to_dict("index")

        print(f"[Supabase] Syncing {len(tickers)} companies → Supabase...", end=" ", flush=True)

        # ── Step 1: batch upsert companies (1 round-trip) ─────────────────────
        id_map = _get_or_create_companies(tickers, rows_dict, cur)

        # ── Step 2: bulk upsert market data (single SQL statement) ───────────
        md_rows = []
        quad_rows = []
        df_indexed = df.set_index("ticker")
        for ticker in tickers:
            cid = id_map.get(ticker)
            if not cid:
                continue
            row = df_indexed.loc[ticker] if ticker in df_indexed.index else None
            if row is None:
                continue
            def g(f): return _safe(row.get(f))
            md_rows.append((
                cid, ticker, data_date,
                g("stock_price"), g("market_cap"),
                g("roic"),        g("op_margin"),
                g("fcf_yield"),   g("fwd_fcf_yield"),
                g("rev_3y_cagr"), g("net_debt_ebitda"),
                g("fwd_rev_cagr"),g("fwd_eps_cagr"),
                g("earnings_mom_roc"), g("multiple_roc"),
                g("peg"),
            ))
            quad = str(row.get("quadrant","NA") or "NA")
            quad_rows.append((
                quad if quad not in ("N/A","NA") else None,
                _gate_status(row),
                cid,
            ))

        # execute_values sends ONE SQL statement with all rows — true batch
        pg_extras.execute_values(cur, """
            INSERT INTO company_market_data (
                company_id, ticker, data_date,
                current_price, market_cap,
                roic_trailing, gross_margin_trailing,
                fcf_yield_current, fcf_yield_forward,
                revenue_3y_cagr_trailing, net_debt_ebitda,
                fwd_revenue_3y_cagr, fwd_eps_3y_cagr,
                earnings_momentum_roc, multiple_roc, pe_forward
            ) VALUES %s
            ON CONFLICT (company_id, data_date) DO UPDATE SET
                current_price            = EXCLUDED.current_price,
                market_cap               = EXCLUDED.market_cap,
                roic_trailing            = EXCLUDED.roic_trailing,
                gross_margin_trailing    = EXCLUDED.gross_margin_trailing,
                fcf_yield_current        = EXCLUDED.fcf_yield_current,
                fcf_yield_forward        = EXCLUDED.fcf_yield_forward,
                revenue_3y_cagr_trailing = EXCLUDED.revenue_3y_cagr_trailing,
                net_debt_ebitda          = EXCLUDED.net_debt_ebitda,
                fwd_revenue_3y_cagr      = EXCLUDED.fwd_revenue_3y_cagr,
                fwd_eps_3y_cagr          = EXCLUDED.fwd_eps_3y_cagr,
                earnings_momentum_roc    = EXCLUDED.earnings_momentum_roc,
                multiple_roc             = EXCLUDED.multiple_roc,
                pe_forward               = EXCLUDED.pe_forward
        """, md_rows, page_size=100)

        # ── Step 3: bulk update quad + gate via single UPDATE...FROM (VALUES) ─
        # Build a single UPDATE with a VALUES subquery — one round-trip
        if quad_rows:
            values_sql = ",".join(
                cur.mogrify("(%s,%s,%s::uuid)", r).decode() for r in quad_rows
            )
            cur.execute(f"""
                UPDATE companies AS c SET
                    quad_current           = v.quad,
                    five_gate_status       = v.gate,
                    five_gate_last_checked = CURRENT_DATE,
                    updated_at             = NOW()
                FROM (VALUES {values_sql}) AS v(quad, gate, id)
                WHERE c.id = v.id
            """)

        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ {len(tickers)} companies · {len(md_rows)} market rows · {data_date}")

    except Exception as e:
        print(f"\n[Supabase] Sync failed (non-fatal): {e}")
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass


