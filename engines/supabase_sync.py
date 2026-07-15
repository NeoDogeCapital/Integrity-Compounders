"""
supabase_sync.py — Screener → Supabase sync  (bidirectional)
Integrity Compounders Alpha System v11.0

Push:  full IC pipeline → Supabase (companies + company_market_data)
Pull:  QGS / GER / enriched fields → local SQLite

Called automatically at the end of every `python run.py refresh`.
Non-fatal: if Supabase is unreachable, refresh still succeeds locally.
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


# ── IC pipeline fields to push into company_market_data ──────────────────────
# (column_in_local_df, column_in_supabase, pg_type)
IC_PIPELINE_FIELDS = [
    # Screener fundamentals not yet in CMD
    ("eps_surprise_q",    "eps_surprise_q",        "NUMERIC"),
    ("rev_surprise_q",    "rev_surprise_q",        "NUMERIC"),
    ("ytd_perf",          "ytd_perf",              "NUMERIC"),
    ("tr_1m",             "momentum_1m",           "NUMERIC"),
    ("tr_3y_cagr",        "tr_3y_cagr",            "NUMERIC"),
    ("tr_5y_cagr",        "tr_5y_cagr",            "NUMERIC"),
    ("eps_3y_cagr",       "eps_3y_cagr_trailing",  "NUMERIC"),
    ("capex_to_rev",      "capex_to_rev",          "NUMERIC"),
    ("peg",               "peg",                   "NUMERIC"),
    ("op_margin",         "op_margin",             "NUMERIC"),
    # IC pipeline computed
    ("alignment_score",   "alignment_score",       "NUMERIC"),
    ("alignment_bucket",  "alignment_bucket",      "TEXT"),
    ("ev_rank",           "ev_rank",               "NUMERIC"),
    ("fv_rank",           "fv_rank",               "NUMERIC"),
    ("mc_rank",           "mc_rank",               "NUMERIC"),
    ("vc_rank",           "vc_rank",               "NUMERIC"),
    ("esv_rank",          "esv_rank",              "NUMERIC"),
    ("pod",               "pod",                   "TEXT"),
    ("pod_count",         "pod_count",             "INTEGER"),
    ("pead_flag",         "pead_flag",             "TEXT"),
    ("flip_score",        "flip_score",            "NUMERIC"),
    ("flip_setup_type",   "flip_setup_type",       "TEXT"),
    ("flip_price",        "flip_price",            "NUMERIC"),
    ("flip_direction",    "flip_direction",        "TEXT"),
    ("sensitivity_pct",   "sensitivity_pct",       "NUMERIC"),
    ("migration_severity","migration_severity",    "TEXT"),
    ("severity_tier",     "severity_tier",         "TEXT"),
    ("gates_pass",        "gates_pass",            "INTEGER"),
    ("gate_quality",      "gate_quality",          "BOOLEAN"),
    ("gate_durability",   "gate_durability",       "BOOLEAN"),
    ("gate_cash_conv",    "gate_cash_conv",        "BOOLEAN"),
    ("gate_reinvestment", "gate_reinvestment",     "BOOLEAN"),
    ("gate_balance_sheet","gate_balance_sheet",    "BOOLEAN"),
    ("x_rev_mom",         "x_rev_mom",             "NUMERIC"),
    ("x_eps_mom",         "x_eps_mom",             "NUMERIC"),
    ("earnings_mom_roc",  "earnings_momentum_roc", "NUMERIC"),
    ("multiple_roc",      "multiple_roc",          "NUMERIC"),
    ("quadrant",          "quadrant",              "TEXT"),
    ("watch_flags",       "watch_flags",           "TEXT"),
    ("consecutive_fails", "consecutive_fails",     "INTEGER"),
    # ── V12 ───────────────────────────────────────────────────────────────
    ("alignment_score_v2",  "alignment_score_v2",  "NUMERIC"),
    ("alignment_bucket_v2", "alignment_bucket_v2", "TEXT"),
    ("fv_rank_v2",          "fv_rank_v2",          "NUMERIC"),
    ("mc_rank_v2",          "mc_rank_v2",          "NUMERIC"),
    ("esv_rank_v2",         "esv_rank_v2",         "NUMERIC"),
    ("quality_profile",     "quality_profile",     "TEXT"),
    ("indicators_pass",     "indicators_pass",     "INTEGER"),
    ("earnings_quality_flag","earnings_quality_flag","TEXT"),
    ("eps_acceleration",    "eps_acceleration",    "NUMERIC"),
    ("gp_acceleration",     "gp_acceleration",     "NUMERIC"),
    ("ind_capital_efficiency",     "gate_capital_efficiency",     "BOOLEAN"),
    ("ind_pricing_power",          "gate_pricing_power",          "BOOLEAN"),
    ("ind_operational_efficiency", "gate_operational_efficiency", "BOOLEAN"),
    ("ind_cash_conversion",        "gate_cash_conversion",        "BOOLEAN"),
    ("ind_growth_durability",      "gate_growth_durability",      "BOOLEAN"),
    # NB: gate_balance_sheet is already pushed via the legacy alias above —
    # do not re-map ind_balance_sheet to it (would duplicate the INSERT column).
]

# Fields to pull back from Supabase into local SQLite
PULL_BACK_FIELDS = [
    # QGS / GER
    "quality_growth_score",
    "growth_efficiency_ratio",
    "qgs_tier",
    "ger_flag",
    "fcf_ev_yield",
    "sbc_pct_revenue",
    "shares_out_growth_3y_cagr",
    "enterprise_value",
    "fcf_margin_trailing",
    # enriched market data
    "momentum_3m",
    "momentum_6m",
    "momentum_12m",
    "rsi_14",
    "atr_14",
    "short_interest_pct",
    "institutional_own_pct",
    "sma_50",
    "sma_200",
    "analyst_count",
    "pe_forward",
    "ev_ebitda",
    "sbc_dollar",
    "roic_spread",
    "fcf_conversion",
    # V12 enriched
    "fcf_ev_rank",
    "earnings_quality_flag",
    "eps_acceleration",
    "gp_acceleration",
]


def _safe(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return str(v) if isinstance(v, str) else None


def _safe_bool(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    try:
        return bool(int(float(v)))
    except (TypeError, ValueError):
        return None


def _ensure_columns(cur) -> None:
    """Add any IC pipeline columns missing from company_market_data."""
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'company_market_data' AND table_schema = 'public'
    """)
    existing = {r[0] for r in cur.fetchall()}

    for _, sb_col, pg_type in IC_PIPELINE_FIELDS:
        if sb_col not in existing:
            cur.execute(f"""
                ALTER TABLE company_market_data
                ADD COLUMN IF NOT EXISTS {sb_col} {pg_type}
            """)

    # Also add alignment_score etc. to companies for quick lookup
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'companies' AND table_schema = 'public'
    """)
    existing_co = {r[0] for r in cur.fetchall()}
    co_adds = [
        ("alignment_score", "NUMERIC"),
        ("ev_rank",         "NUMERIC"),
        ("flip_score",      "NUMERIC"),
        ("pead_flag",       "TEXT"),
        ("pod",             "TEXT"),
        ("pod_count",       "INTEGER"),
    ]
    for col, pg_type in co_adds:
        if col not in existing_co:
            cur.execute(f"ALTER TABLE companies ADD COLUMN IF NOT EXISTS {col} {pg_type}")


def _get_or_create_companies(tickers, rows_dict, cur):
    batch = [
        (
            ticker,
            str(rows_dict.get(ticker, {}).get("company", ticker))[:200],
            str(rows_dict.get(ticker, {}).get("sector",  "") or "")[:100],
            str(rows_dict.get(ticker, {}).get("industry","") or "")[:100],
            str(rows_dict.get(ticker, {}).get("country", "") or "")[:50],
            str(rows_dict.get(ticker, {}).get("exchange", "") or "")[:50],
            True,
        )
        for ticker in tickers
    ]
    pg_extras.execute_values(cur, """
        INSERT INTO companies (ticker, company_name, sector, industry, country, exchange, active)
        VALUES %s
        ON CONFLICT (ticker) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            sector       = COALESCE(NULLIF(EXCLUDED.sector,   ''), companies.sector),
            industry     = COALESCE(NULLIF(EXCLUDED.industry, ''), companies.industry),
            country      = COALESCE(NULLIF(EXCLUDED.country,  ''), companies.country),
            exchange     = COALESCE(NULLIF(EXCLUDED.exchange, ''), companies.exchange),
            active       = TRUE,
            updated_at   = NOW()
    """, batch, page_size=100)
    cur.execute("SELECT ticker, id FROM companies WHERE ticker = ANY(%s)", (tickers,))
    return {r[0]: str(r[1]) for r in cur.fetchall()}


def _gate_status(row) -> str:
    gates_pass = _safe(row.get("gates_pass"))
    if gates_pass is None:
        return "UNSCREENED"
    return {5: "PASS", 4: "WATCH_1", 3: "WATCH_2"}.get(int(gates_pass), "FAIL")


def sync_universe_to_supabase(df: pd.DataFrame, data_date: str) -> None:
    """
    Full bidirectional sync:
      1. Ensure all IC columns exist in Supabase (ALTER TABLE idempotent)
      2. Upsert companies (name, sector, quad, gates, alignment, pod, etc.)
      3. Upsert company_market_data (all screener + IC pipeline fields)
    """
    if df.empty:
        return

    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = False
        cur = conn.cursor()

        tickers   = df["ticker"].tolist()
        rows_dict = df.set_index("ticker").to_dict("index")

        print(f"[Supabase] Syncing {len(tickers)} companies...", end=" ", flush=True)

        # 1. Ensure schema is up to date
        _ensure_columns(cur)

        # 2. Upsert companies
        id_map = _get_or_create_companies(tickers, rows_dict, cur)

        # 3. Update companies with IC signals (quad, gates, alignment, pod)
        co_rows = []
        df_idx = df.set_index("ticker")
        for ticker in tickers:
            cid = id_map.get(ticker)
            if not cid:
                continue
            row = df_idx.loc[ticker] if ticker in df_idx.index else {}
            quad = str(row.get("quadrant", "") or "")
            co_rows.append((
                quad if quad not in ("N/A", "NA", "") else None,
                _gate_status(row),
                _safe(row.get("alignment_score")),
                _safe(row.get("ev_rank")),
                _safe(row.get("flip_score")),
                str(row.get("pead_flag") or "")[:50] or None,
                str(row.get("pod") or "")[:50] or None,
                _safe(row.get("pod_count")),
                cid,
            ))

        if co_rows:
            values_sql = ",".join(
                cur.mogrify("(%s,%s,%s,%s,%s,%s,%s,%s,%s::uuid)", r).decode()
                for r in co_rows
            )
            cur.execute(f"""
                UPDATE companies AS c SET
                    quad_current           = v.quad,
                    five_gate_status       = v.gate,
                    five_gate_last_checked = CURRENT_DATE,
                    alignment_score        = v.alignment_score::numeric,
                    ev_rank                = v.ev_rank::numeric,
                    flip_score             = v.flip_score::numeric,
                    pead_flag              = v.pead_flag,
                    pod                    = v.pod,
                    pod_count              = v.pod_count::integer,
                    updated_at             = NOW()
                FROM (VALUES {values_sql})
                    AS v(quad, gate, alignment_score, ev_rank, flip_score,
                         pead_flag, pod, pod_count, id)
                WHERE c.id = v.id
            """)

        # 4. Upsert full market data row per company per date
        # Build dynamic column list from IC_PIPELINE_FIELDS
        # NOTE: gross_margin_trailing is intentionally NOT pushed here. It is owned
        # by data_updater (yfinance grossMargins). Previously op_margin was written
        # into gross_margin_trailing here, clobbering the real gross margin every
        # refresh — that mapping bug is removed.
        base_cols = [
            "company_id", "ticker", "data_date",
            "current_price", "market_cap",
            "roic_trailing",
            "fcf_yield_current", "fcf_yield_forward",
            "revenue_3y_cagr_trailing", "net_debt_ebitda",
            "fwd_revenue_3y_cagr", "fwd_eps_3y_cagr",
        ]
        ic_sb_cols = [sb for _, sb, _ in IC_PIPELINE_FIELDS]
        all_cols = base_cols + ic_sb_cols

        update_pairs = ", ".join(
            f"{c} = EXCLUDED.{c}"
            for c in all_cols
            if c not in ("company_id", "ticker", "data_date")
        )

        md_rows = []
        for ticker in tickers:
            cid = id_map.get(ticker)
            if not cid:
                continue
            row = df_idx.loc[ticker] if ticker in df_idx.index else {}

            base_vals = [
                cid, ticker, data_date,
                _safe(row.get("stock_price")),  _safe(row.get("market_cap")),
                _safe(row.get("roic")),
                _safe(row.get("fcf_yield")),     _safe(row.get("fwd_fcf_yield")),
                _safe(row.get("rev_3y_cagr")),   _safe(row.get("net_debt_ebitda")),
                _safe(row.get("fwd_rev_cagr")),  _safe(row.get("fwd_eps_cagr")),
            ]
            ic_vals = []
            for local_col, _, pg_type in IC_PIPELINE_FIELDS:
                v = row.get(local_col)
                if pg_type == "BOOLEAN":
                    ic_vals.append(_safe_bool(v))
                else:
                    ic_vals.append(_safe(v) if pg_type == "NUMERIC" or pg_type == "INTEGER"
                                   else (str(v)[:255] if v is not None else None))
            md_rows.append(tuple(base_vals + ic_vals))

        col_placeholders = ", ".join(["%s"] * len(all_cols))
        insert_sql = f"""
            INSERT INTO company_market_data ({", ".join(all_cols)})
            VALUES ({col_placeholders})
            ON CONFLICT (company_id, data_date) DO UPDATE SET {update_pairs}
        """
        pg_extras.execute_batch(cur, insert_sql, md_rows, page_size=50)

        conn.commit()
        cur.close()
        conn.close()
        print(f"OK  {len(tickers)} companies · {len(md_rows)} market rows · {data_date}")

    except Exception as e:
        print(f"\n[Supabase] Sync failed (non-fatal): {e}")
        import traceback; traceback.print_exc()
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass


def pull_enriched_to_local(data_date: str | None = None) -> int:
    """
    Pull Supabase-only fields (QGS, GER, yfinance enrichments) back into
    the local SQLite universe table.  Returns number of rows updated.
    """
    from engines.database import get_conn as local_conn, init_db
    import sqlite3

    try:
        sb_conn = psycopg2.connect(settings.DATABASE_URL)
        sb_cur  = sb_conn.cursor()

        # Each field group pulls from the latest row where that group is populated.
        # Today's screener push writes nulls for yfinance/QGS fields — we must reach
        # back to the last enrichment date for those.

        qgs_fields = ["quality_growth_score", "growth_efficiency_ratio", "qgs_tier",
                      "ger_flag", "fcf_ev_yield", "sbc_pct_revenue",
                      "shares_out_growth_3y_cagr", "enterprise_value", "fcf_margin_trailing",
                      "sbc_dollar", "roic_spread", "fcf_conversion"]

        yf_fields  = ["momentum_3m", "momentum_6m", "momentum_12m",
                      "rsi_14", "atr_14", "short_interest_pct", "institutional_own_pct",
                      "sma_50", "sma_200", "analyst_count", "pe_forward", "ev_ebitda"]

        # anything not in qgs or yf buckets
        rest_fields = [f for f in PULL_BACK_FIELDS
                       if f not in qgs_fields and f not in yf_fields]

        def _query_latest_nonnull(cur, fields, anchor):
            """Pull latest row per ticker where `anchor` field is not null."""
            cur.execute(f"""
                SELECT DISTINCT ON (ticker)
                    ticker, {", ".join(fields)}
                FROM company_market_data
                WHERE {anchor} IS NOT NULL
                ORDER BY ticker, data_date DESC
            """)
            rows = cur.fetchall()
            cols = ["ticker"] + fields
            return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)

        df_qgs = _query_latest_nonnull(sb_cur, qgs_fields, "quality_growth_score")
        df_yf  = _query_latest_nonnull(sb_cur, yf_fields,  "rsi_14")
        # rest_fields (contamination flag, accelerations, fcf_ev_rank) are pushed
        # together on the pipeline data_date — anchor on earnings_quality_flag.
        df_rest = _query_latest_nonnull(sb_cur, rest_fields, "earnings_quality_flag") \
                  if rest_fields else pd.DataFrame(columns=["ticker"])

        # Ticker spine: every ticker that has ever appeared in company_market_data
        sb_cur.execute("SELECT DISTINCT ticker FROM company_market_data ORDER BY ticker")
        tickers = [r[0] for r in sb_cur.fetchall()]
        df_pull = pd.DataFrame({"ticker": tickers})

        if not df_qgs.empty:
            df_pull = df_pull.merge(df_qgs, on="ticker", how="left")
        if not df_yf.empty:
            df_pull = df_pull.merge(df_yf, on="ticker", how="left")
        if not df_rest.empty:
            df_pull = df_pull.merge(df_rest, on="ticker", how="left")

        # Fill any PULL_BACK_FIELDS columns that didn't come through
        for f in PULL_BACK_FIELDS:
            if f not in df_pull.columns:
                df_pull[f] = None

        sb_conn.close()

        if df_pull.empty:
            print("[Supabase] pull_enriched: no rows returned")
            return 0

        # Ensure local DB has these columns
        lconn = local_conn()
        lcur  = lconn.cursor()
        lcur.execute("PRAGMA table_info(universe)")
        existing_local = {r[1] for r in lcur.fetchall()}

        type_map = {
            "quality_growth_score":     "REAL",
            "growth_efficiency_ratio":  "REAL",
            "qgs_tier":                 "TEXT",
            "ger_flag":                 "TEXT",
            "fcf_ev_yield":             "REAL",
            "sbc_pct_revenue":          "REAL",
            "shares_out_growth_3y_cagr":"REAL",
            "enterprise_value":         "REAL",
            "fcf_margin_trailing":      "REAL",
            "momentum_3m":              "REAL",
            "momentum_6m":              "REAL",
            "momentum_12m":             "REAL",
            "rsi_14":                   "REAL",
            "atr_14":                   "REAL",
            "short_interest_pct":       "REAL",
            "institutional_own_pct":    "REAL",
            "sma_50":                   "REAL",
            "sma_200":                  "REAL",
            "analyst_count":            "INTEGER",
            "pe_forward":               "REAL",
            "ev_ebitda":                "REAL",
            "sbc_dollar":               "REAL",
            "roic_spread":              "REAL",
            "fcf_conversion":           "REAL",
        }
        for col in PULL_BACK_FIELDS:
            if col not in existing_local:
                lcur.execute(f"ALTER TABLE universe ADD COLUMN {col} {type_map.get(col, 'TEXT')}")

        def _to_sqlite(v):
            """Coerce Postgres Decimal / Numeric to Python native for SQLite."""
            if v is None:
                return None
            import decimal
            if isinstance(v, decimal.Decimal):
                f = float(v)
                return None if (math.isnan(f) or math.isinf(f)) else f
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return None
            return v

        # Update each ticker
        updated = 0
        set_clause = ", ".join(f"{c} = ?" for c in PULL_BACK_FIELDS)
        for _, row in df_pull.iterrows():
            vals = [_to_sqlite(row[c]) for c in PULL_BACK_FIELDS] + [row["ticker"]]
            lcur.execute(
                f"UPDATE universe SET {set_clause} WHERE ticker = ?",
                vals,
            )
            updated += lcur.rowcount

        lconn.commit()
        lconn.close()
        print(f"[Supabase] pull_enriched: updated {updated} local rows with enriched fields")
        return updated

    except Exception as e:
        print(f"[Supabase] pull_enriched failed (non-fatal): {e}")
        import traceback; traceback.print_exc()
        return 0


# ── Trade tables (trade_log / portfolio_holdings / decision_journal) ──────────
# These live in local SQLite by default; mirror them to Supabase so trade history
# and cost basis survive device migrations. Supabase table names are ic_-prefixed.
_TRADE_SPEC = {
    "trade_log": ("ic_trade_log", "trade_id", [
        "trade_id","logged_at","trade_date","ticker","company","action","shares","price",
        "dollar_amount","weight_before","weight_after","sleeve","quadrant","quad_provisional",
        "ev_rank","alignment_score","alignment_bucket","pead_flag","x_axis","y_axis",
        "fcf_spread_tag","convergence_signals","trigger_type","why_now","thesis","bear_case",
        "quad_flip_price","add_trigger","trim_trigger","exit_trigger","target_weight","max_weight",
        "review_date","status","close_date","close_price","total_return","vs_base_case",
        "thesis_outcome","what_we_learned"]),
    "portfolio_holdings": ("ic_portfolio_holdings", "id", [
        "id","snapshot_date","ticker","company","shares","avg_cost","current_price","current_value",
        "weight_actual","weight_target","weight_drift","sleeve","is_discretionary",
        "unrealized_pnl_dollar","unrealized_pnl_pct","vs_base_case","migration_warning","quadrant",
        "quad_name","ev_rank","alignment_score","alignment_bucket","pead_flag","x_axis","y_axis",
        "fcf_spread_tag","convergence_signals","industry","added_at"]),
    "decision_journal": ("ic_decision_journal", "id", [
        "id","logged_at","ticker","event_type","note","auto"]),
}
# Tables whose local `id` is a SQLite autoincrement that has NO relationship to the
# cloud id space. Syncing those on `id` silently OVERWRITES unrelated cloud rows
# (this destroyed a journal entry on 2026-07-15). These sync on a natural key
# instead; each side keeps its own id.
_NATURAL_KEY = {
    "decision_journal": ["logged_at", "ticker", "event_type"],
}


def _sqlite_bind(v):
    """psycopg2 hands back Decimal / date / datetime — sqlite3 can bind none of them.
    Silently skipped the whole pull before this existed."""
    from decimal import Decimal
    import datetime as _dt
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    return v


def _nat_target(nat):
    """Conflict target expression — ticker is nullable, so COALESCE it."""
    return "(" + ", ".join(f"COALESCE({c},'')" if c == "ticker" else c for c in nat) + ")"


_PG_TYPE = {  # columns not in this map default to text
    "trade_id":"integer","id":"integer","shares":"numeric","price":"numeric","dollar_amount":"numeric",
    "weight_before":"numeric","weight_after":"numeric","quad_provisional":"integer","ev_rank":"integer",
    "alignment_score":"numeric","x_axis":"numeric","y_axis":"numeric","convergence_signals":"integer",
    "quad_flip_price":"numeric","target_weight":"numeric","max_weight":"numeric","close_price":"numeric",
    "total_return":"numeric","avg_cost":"numeric","current_price":"numeric","current_value":"numeric",
    "weight_actual":"numeric","weight_target":"numeric","weight_drift":"numeric","is_discretionary":"integer",
    "unrealized_pnl_dollar":"numeric","unrealized_pnl_pct":"numeric","migration_warning":"integer","auto":"integer",
}


def _local_db_path():
    from pathlib import Path
    return Path(__file__).parent.parent / "data" / "universe.db"


def sync_trade_tables_to_supabase() -> None:
    """Mirror local trade_log / portfolio_holdings / decision_journal → Supabase (upsert by PK)."""
    import sqlite3
    from psycopg2.extras import execute_values
    try:
        db = sqlite3.connect(_local_db_path()); db.row_factory = sqlite3.Row
        conn = psycopg2.connect(settings.DATABASE_URL); conn.autocommit = True; cur = conn.cursor()
        total = 0
        for local, (pgt, pk, cols) in _TRADE_SPEC.items():
            ddl = ", ".join(f"{c} {_PG_TYPE.get(c,'text')}" + (" PRIMARY KEY" if c == pk else "") for c in cols)
            cur.execute(f"CREATE TABLE IF NOT EXISTS {pgt} ({ddl})")
            try:
                rows = db.execute(f"SELECT {','.join(cols)} FROM {local}").fetchall()
            except sqlite3.OperationalError:
                continue
            if not rows:
                continue
            nat = _NATURAL_KEY.get(local)
            if nat:
                # Never push the local autoincrement id — let the cloud assign its own.
                icols = [c for c in cols if c != pk]
                tgt   = _nat_target(nat)
                cur.execute(f"CREATE SEQUENCE IF NOT EXISTS {pgt}_{pk}_seq OWNED BY {pgt}.{pk}")
                cur.execute(f"SELECT setval('{pgt}_{pk}_seq', COALESCE((SELECT MAX({pk}) FROM {pgt}), 1))")
                cur.execute(f"ALTER TABLE {pgt} ALTER COLUMN {pk} SET DEFAULT nextval('{pgt}_{pk}_seq')")
                cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{pgt}_nat ON {pgt} {tgt}")
                upd = ", ".join(f"{c}=EXCLUDED.{c}" for c in icols if c not in nat)
                vals = [tuple(r[c] for c in icols) for r in rows]
                execute_values(cur, f"INSERT INTO {pgt} ({','.join(icols)}) VALUES %s "
                                    f"ON CONFLICT {tgt} DO UPDATE SET {upd}", vals)
            else:
                vals = [tuple(r[c] for c in cols) for r in rows]
                upd = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != pk)
                execute_values(cur, f"INSERT INTO {pgt} ({','.join(cols)}) VALUES %s "
                                    f"ON CONFLICT ({pk}) DO UPDATE SET {upd}", vals)
            total += len(rows)
        db.close(); cur.close(); conn.close()
        print(f"[Supabase] trade tables synced ({total} rows across trade_log/holdings/journal)")
    except Exception as e:
        print(f"[Supabase] trade-table sync skipped (non-fatal): {e}")


def pull_trade_tables_to_local() -> None:
    """Seed local trade_log / portfolio_holdings / decision_journal from Supabase (fresh device)."""
    import sqlite3
    try:
        conn = psycopg2.connect(settings.DATABASE_URL); cur = conn.cursor()
        db = sqlite3.connect(_local_db_path())
        from engines.database import init_db
        init_db()  # ensures local tables exist
        total = 0
        for local, (pgt, pk, cols) in _TRADE_SPEC.items():
            try:
                cur.execute(f"SELECT {','.join(cols)} FROM {pgt}")
            except Exception:
                conn.rollback(); continue
            rows = cur.fetchall()
            if not rows:
                continue
            nat = _NATURAL_KEY.get(local)
            if nat:
                # Mirror on the natural key so the cloud id never clobbers a local row.
                icols = [c for c in cols if c != pk]
                idx   = [cols.index(c) for c in icols]
                tgt   = _nat_target(nat)
                ph    = ",".join("?" * len(icols))
                upd   = ", ".join(f"{c}=excluded.{c}" for c in icols if c not in nat)
                db.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{local}_nat ON {local} {tgt}")
                for r in rows:
                    db.execute(f"INSERT INTO {local} ({','.join(icols)}) VALUES ({ph}) "
                               f"ON CONFLICT {tgt} DO UPDATE SET {upd}",
                               [_sqlite_bind(r[i]) for i in idx])
                total += len(rows)
                continue
            ph = ",".join("?" * len(cols))
            upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c != pk)
            for r in rows:
                db.execute(f"INSERT INTO {local} ({','.join(cols)}) VALUES ({ph}) "
                           f"ON CONFLICT({pk}) DO UPDATE SET {upd}", [_sqlite_bind(v) for v in r])
            total += len(rows)
        db.commit(); db.close(); cur.close(); conn.close()
        print(f"[Supabase] pulled {total} trade-table rows into local SQLite")
    except Exception as e:
        print(f"[Supabase] trade-table pull skipped (non-fatal): {e}")
