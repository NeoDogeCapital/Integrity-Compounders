"""
database.py — SQLite schema, connection management, and raw data ingestion
Integrity Compounders Alpha System v9.1
"""

import sqlite3
import pandas as pd
import os
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "universe.db"

# ── Column definitions matching the 26-column Fiscal AI v9 export ────────────
RAW_COLUMNS = [
    "ticker", "company", "country", "exchange", "industry",
    "eps_surprise_q", "rev_surprise_q",
    "fcf_yield", "fwd_fcf_yield", "stock_price",
    "tr_1m", "ytd_perf",
    "fwd_rev_cagr", "capex_to_rev", "peg",
    "market_cap", "buyback_yield", "rev_3y_cagr",
    "op_margin", "net_debt_ebitda", "beta",
    "tr_3y_cagr", "eps_3y_cagr", "fwd_eps_cagr",
    "roic", "tr_5y_cagr",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS universe (
    ticker          TEXT PRIMARY KEY,
    company         TEXT,
    country         TEXT,
    exchange        TEXT,
    industry        TEXT,
    eps_surprise_q  REAL,
    rev_surprise_q  REAL,
    fcf_yield       REAL,
    fwd_fcf_yield   REAL,
    stock_price     REAL,
    tr_1m           REAL,
    ytd_perf        REAL,
    fwd_rev_cagr    REAL,
    capex_to_rev    REAL,
    peg             REAL,
    market_cap      REAL,
    buyback_yield   REAL,
    rev_3y_cagr     REAL,
    op_margin       REAL,
    net_debt_ebitda REAL,
    beta            REAL,
    tr_3y_cagr      REAL,
    eps_3y_cagr     REAL,
    fwd_eps_cagr    REAL,
    roic            REAL,
    tr_5y_cagr      REAL,
    -- Computed fields (populated by engines)
    gate_quality        INTEGER,   -- 1=pass, 0=fail
    gate_durability     INTEGER,
    gate_cash_conv      INTEGER,
    gate_reinvestment   INTEGER,
    gate_balance_sheet  INTEGER,
    gates_pass          INTEGER,   -- total gates passing (0-5)
    watch_flags         TEXT,      -- JSON: which gates failed this month
    consecutive_fails   TEXT,      -- JSON: {gate: N_consecutive_fails}
    universe_status     TEXT,      -- 'active' | 'watch' | 'removed'
    -- Quad
    x_rev_mom           REAL,
    x_eps_mom           REAL,
    earnings_mom_roc    REAL,      -- X-axis
    multiple_roc        REAL,      -- Y-axis
    quadrant            TEXT,      -- Q1/Q2/Q3/Q4/N/A
    quad_provisional    INTEGER,   -- 1 if first appearance this quad
    -- Pod
    pod                 TEXT,
    pod_flags           TEXT,      -- JSON: all matching pod booleans
    pod_count           INTEGER,
    -- Alignment Score
    fv_rank             REAL,
    mc_rank             REAL,
    vc_rank             REAL,
    esv_rank            REAL,
    alignment_score     REAL,
    alignment_bucket    TEXT,      -- Accumulate/Neutral/Distribute
    pead_flag           TEXT,
    -- FCF Flip
    flip_score          REAL,
    flip_setup_type     TEXT,
    -- Severity (v9.1)
    ev_rank             INTEGER,   -- 1-4
    severity_tier       TEXT,
    flip_price          REAL,
    sensitivity_pct     REAL,
    flip_direction      TEXT,
    migration_severity  TEXT,
    -- Metadata
    data_date           TEXT,      -- YYYY-MM-DD of the source snapshot
    last_updated        TEXT       -- ISO timestamp of last computation
);

CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    data_date   TEXT NOT NULL,
    loaded_at   TEXT NOT NULL,
    source_file TEXT,
    row_count   INTEGER
);

CREATE TABLE IF NOT EXISTS quad_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    data_date   TEXT NOT NULL,
    quadrant    TEXT,
    ev_rank     INTEGER,
    earnings_mom_roc REAL,
    multiple_roc     REAL,
    alignment_score  REAL,
    alignment_bucket TEXT,
    stock_price      REAL
);

CREATE TABLE IF NOT EXISTS migration_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at       TEXT NOT NULL,
    data_date       TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    company         TEXT,
    from_quad       TEXT,
    to_quad         TEXT,
    severity        TEXT,
    alignment_score REAL,
    pead_flag       TEXT,
    x_delta         REAL,
    y_delta         REAL,
    note            TEXT
);

CREATE TABLE IF NOT EXISTS decision_journal (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at   TEXT NOT NULL,
    ticker      TEXT,
    event_type  TEXT,
    note        TEXT,
    auto        INTEGER DEFAULT 0  -- 1=auto-generated, 0=manual
);

CREATE TABLE IF NOT EXISTS portfolio_holdings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date       TEXT NOT NULL,          -- YYYY-MM-DD of this snapshot
    ticker              TEXT NOT NULL,
    company             TEXT,
    shares              REAL,
    avg_cost            REAL,                   -- average cost basis per share
    current_price       REAL,
    current_value       REAL,                   -- shares * current_price
    weight_actual       REAL,                   -- % of total portfolio value
    weight_target       REAL DEFAULT 4.0,       -- target weight %
    weight_drift        REAL,                   -- actual - target
    sleeve              TEXT,
    is_discretionary    INTEGER DEFAULT 0,      -- 1 = discretionary position
    unrealized_pnl_dollar REAL,                 -- (current_price - avg_cost) * shares
    unrealized_pnl_pct  REAL,                   -- (current_price / avg_cost - 1) * 100
    vs_base_case        TEXT,                   -- Above / In Line / Below
    migration_warning   INTEGER DEFAULT 0,      -- 1 if price within 10% of quad flip
    -- Model state
    quadrant            TEXT,
    quad_name           TEXT,
    ev_rank             INTEGER,
    alignment_score     REAL,
    alignment_bucket    TEXT,
    pead_flag           TEXT,
    x_axis              REAL,
    y_axis              REAL,
    fcf_spread_tag      TEXT,
    convergence_signals INTEGER,
    industry            TEXT,
    added_at            TEXT                    -- ISO timestamp when first loaded
);

CREATE TABLE IF NOT EXISTS portfolio_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date       TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    company             TEXT,
    shares              REAL,
    avg_cost            REAL,
    current_price       REAL,
    current_value       REAL,
    weight_actual       REAL,
    weight_target       REAL,
    weight_drift        REAL,
    sleeve              TEXT,
    is_discretionary    INTEGER DEFAULT 0,
    unrealized_pnl_dollar REAL,
    unrealized_pnl_pct  REAL,
    vs_base_case        TEXT,
    migration_warning   INTEGER DEFAULT 0,
    quadrant            TEXT,
    quad_name           TEXT,
    ev_rank             INTEGER,
    alignment_score     REAL,
    alignment_bucket    TEXT,
    pead_flag           TEXT,
    x_axis              REAL,
    y_axis              REAL,
    fcf_spread_tag      TEXT,
    convergence_signals INTEGER,
    industry            TEXT,
    added_at            TEXT
);

CREATE TABLE IF NOT EXISTS trade_log (
    trade_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at           TEXT NOT NULL,           -- ISO timestamp of log entry
    trade_date          TEXT NOT NULL,           -- YYYY-MM-DD of actual trade
    ticker              TEXT NOT NULL,
    company             TEXT,
    action              TEXT NOT NULL,           -- BUY/ADD/TRIM/SELL/CLOSE
    shares              REAL,
    price               REAL,
    dollar_amount       REAL,                    -- price * shares
    weight_before       REAL,                    -- portfolio weight before trade (%)
    weight_after        REAL,                    -- portfolio weight after trade (%)
    sleeve              TEXT,                    -- Core/Catalyst/Relative Value/Speculative
    -- Model state at entry
    quadrant            TEXT,
    quad_provisional    INTEGER,
    ev_rank             INTEGER,
    alignment_score     REAL,
    alignment_bucket    TEXT,
    pead_flag           TEXT,
    x_axis              REAL,                    -- Revenue Momentum at entry
    y_axis              REAL,                    -- EPS Momentum at entry
    fcf_spread_tag      TEXT,                    -- Re-rating/De-rating/Neutral
    convergence_signals INTEGER,                 -- 0-3
    -- Decision rationale
    trigger_type        TEXT,                    -- e.g. Q1 Confirmation/Momentum Entry/Rebalance
    why_now             TEXT,                    -- short: why this month
    thesis              TEXT,                    -- full thesis
    bear_case           TEXT,                    -- what would break the thesis
    -- Trigger prices
    quad_flip_price     REAL,                    -- price at which quad changes
    add_trigger         TEXT,                    -- conditions/price to add
    trim_trigger        TEXT,                    -- conditions/price to trim
    exit_trigger        TEXT,                    -- hard exit conditions
    -- Position management
    target_weight       REAL,                    -- target portfolio weight (%)
    max_weight          REAL,                    -- max allowed weight (%)
    review_date         TEXT,                    -- next scheduled review date
    -- Close tracking
    status              TEXT DEFAULT 'Open',     -- Open/Partial/Closed
    close_date          TEXT,
    close_price         REAL,
    total_return        REAL,                    -- % return on closed trade
    vs_base_case        TEXT,                    -- Ahead/In-line/Behind
    thesis_outcome      TEXT,                    -- Confirmed/Invalidated/Inconclusive
    what_we_learned     TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    print(f"[DB] Initialized: {DB_PATH}")


def load_csv(path: str | Path, data_date: str | None = None) -> pd.DataFrame:
    """
    Load a Fiscal AI v9 CSV export (26 columns).
    Handles both comma and tab-delimited files.
    Returns a clean DataFrame with standardized column names.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    # Try tab then comma delimiter
    for sep in ["\t", ","]:
        try:
            df = pd.read_csv(path, sep=sep, header=0)
            if df.shape[1] >= 10:
                break
        except Exception:
            continue

    # If the CSV has 26+ columns, use positional assignment
    if df.shape[1] >= 26:
        df = df.iloc[:, :26]
        df.columns = RAW_COLUMNS
    else:
        # Try to map by header names (case-insensitive fuzzy)
        df.columns = [c.strip().lower().replace(" ", "_").replace("/", "_")
                      for c in df.columns]

    # Drop completely empty rows
    df = df.dropna(subset=["ticker"]).copy()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()

    # Coerce all numeric columns (strip $, %, commas first)
    numeric_cols = RAW_COLUMNS[5:]  # everything after industry
    for col in numeric_cols:
        if col in df.columns:
            df[col] = (
                df[col].astype(str)
                .str.replace("$", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Infer data_date from filename if not provided
    if data_date is None:
        stem = path.stem
        for fmt in ["%Y-%m-%d", "%Y%m%d"]:
            try:
                data_date = datetime.strptime(stem[:10], fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                pass
        if data_date is None:
            data_date = datetime.today().strftime("%Y-%m-%d")

    df["data_date"] = data_date
    print(f"[DB] Loaded {len(df)} rows from {path.name} (date: {data_date})")
    return df


def upsert_universe(df: pd.DataFrame):
    """Write raw data into universe table (upsert on ticker)."""
    now = datetime.utcnow().isoformat()
    df = df.copy()
    df["last_updated"] = now
    df["universe_status"] = df.get("universe_status", "active")

    cols = [c for c in RAW_COLUMNS + ["data_date", "last_updated", "universe_status"]
            if c in df.columns]

    placeholders = ", ".join(["?" for _ in cols])
    col_str = ", ".join(cols)
    update_str = ", ".join([f"{c}=excluded.{c}" for c in cols if c != "ticker"])

    with get_conn() as conn:
        for _, row in df[cols].iterrows():
            conn.execute(
                f"""INSERT INTO universe ({col_str}) VALUES ({placeholders})
                    ON CONFLICT(ticker) DO UPDATE SET {update_str}""",
                list(row)
            )
        conn.execute(
            "INSERT INTO snapshots (data_date, loaded_at, source_file, row_count) VALUES (?,?,?,?)",
            [df["data_date"].iloc[0], now, None, len(df)]
        )
    print(f"[DB] Upserted {len(df)} rows into universe table.")


def get_universe(status: str = "active") -> pd.DataFrame:
    """Return the current universe as a DataFrame."""
    with get_conn() as conn:
        if status == "all":
            df = pd.read_sql("SELECT * FROM universe", conn)
        else:
            df = pd.read_sql(
                "SELECT * FROM universe WHERE universe_status = ?", conn, params=[status]
            )
    return df


def get_last_snapshot_date() -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data_date FROM snapshots ORDER BY loaded_at DESC LIMIT 1"
        ).fetchone()
    return row["data_date"] if row else None


def log_migration(ticker: str, company: str, from_quad: str, to_quad: str,
                  severity: str, alignment_score: float, pead_flag: str,
                  x_delta: float, y_delta: float, data_date: str, note: str = ""):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO migration_log
               (logged_at, data_date, ticker, company, from_quad, to_quad,
                severity, alignment_score, pead_flag, x_delta, y_delta, note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [datetime.utcnow().isoformat(), data_date, ticker, company,
             from_quad, to_quad, severity, alignment_score, pead_flag,
             x_delta, y_delta, note]
        )


def log_decision(note: str, ticker: str = "", event_type: str = "manual"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO decision_journal (logged_at, ticker, event_type, note, auto) VALUES (?,?,?,?,0)",
            [datetime.utcnow().isoformat(), ticker.upper(), event_type, note]
        )
    print(f"[Journal] Logged: {note[:80]}")


def save_quad_history(df: pd.DataFrame, data_date: str):
    """Snapshot current quad assignments into history table."""
    cols = ["ticker", "quadrant", "ev_rank", "earnings_mom_roc",
            "multiple_roc", "alignment_score", "alignment_bucket", "stock_price"]
    present = [c for c in cols if c in df.columns]
    snap = df[present].copy()
    snap["data_date"] = data_date
    with get_conn() as conn:
        snap.to_sql("quad_history", conn, if_exists="append", index=False)
    print(f"[DB] Saved {len(snap)} rows to quad_history.")


def log_trade(record: dict) -> int:
    """Insert a trade record into trade_log. Returns new trade_id."""
    cols = [
        "logged_at","trade_date","ticker","company","action","shares","price",
        "dollar_amount","weight_before","weight_after","sleeve",
        "quadrant","quad_provisional","ev_rank","alignment_score","alignment_bucket",
        "pead_flag","x_axis","y_axis","fcf_spread_tag","convergence_signals",
        "trigger_type","why_now","thesis","bear_case",
        "quad_flip_price","add_trigger","trim_trigger","exit_trigger",
        "target_weight","max_weight","review_date","status",
    ]
    row = {c: record.get(c) for c in cols}
    row.setdefault("logged_at", datetime.utcnow().isoformat())
    row.setdefault("status", "Open")

    col_str     = ", ".join(row.keys())
    placeholders = ", ".join(["?" for _ in row])
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO trade_log ({col_str}) VALUES ({placeholders})",
            list(row.values())
        )
        trade_id = cur.lastrowid
    return trade_id


def get_trade_log(status: str | None = None) -> pd.DataFrame:
    """Return trade_log rows, optionally filtered by status."""
    with get_conn() as conn:
        if status:
            return pd.read_sql(
                "SELECT * FROM trade_log WHERE status=? ORDER BY trade_date DESC",
                conn, params=[status]
            )
        return pd.read_sql(
            "SELECT * FROM trade_log ORDER BY trade_date DESC", conn
        )


def get_trade_by_id(trade_id: int) -> dict | None:
    """Fetch a single trade record by ID."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM trade_log WHERE trade_id=?", [trade_id]
        ).fetchone()
    return dict(row) if row else None


def close_trade(trade_id: int, close_date: str, close_price: float,
                total_return: float, vs_base_case: str,
                thesis_outcome: str, what_we_learned: str):
    """Mark a trade as Closed and record outcome fields."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE trade_log SET status='Closed', close_date=?, close_price=?,
               total_return=?, vs_base_case=?, thesis_outcome=?, what_we_learned=?
               WHERE trade_id=?""",
            [close_date, close_price, total_return, vs_base_case,
             thesis_outcome, what_we_learned, trade_id]
        )


def save_portfolio_snapshot(df: pd.DataFrame, snapshot_date: str):
    """Overwrite portfolio_holdings with current snapshot; append to portfolio_history."""
    df = df.copy()
    df["snapshot_date"] = snapshot_date

    cols = [
        "snapshot_date","ticker","company","shares","avg_cost","current_price",
        "current_value","weight_actual","weight_target","weight_drift","sleeve",
        "is_discretionary","unrealized_pnl_dollar","unrealized_pnl_pct",
        "vs_base_case","migration_warning","quadrant","quad_name","ev_rank",
        "alignment_score","alignment_bucket","pead_flag","x_axis","y_axis",
        "fcf_spread_tag","convergence_signals","industry","added_at",
    ]
    present = [c for c in cols if c in df.columns]
    snap = df[present].copy()

    with get_conn() as conn:
        conn.execute("DELETE FROM portfolio_holdings")
        snap.to_sql("portfolio_holdings", conn, if_exists="append", index=False)
        snap.to_sql("portfolio_history",  conn, if_exists="append", index=False)
    print(f"[Portfolio] Saved {len(snap)} holdings to portfolio_holdings + portfolio_history.")


def get_portfolio(snapshot_date: str | None = None) -> pd.DataFrame:
    """Return current portfolio_holdings, or a specific historical snapshot."""
    with get_conn() as conn:
        if snapshot_date:
            return pd.read_sql(
                "SELECT * FROM portfolio_history WHERE snapshot_date=? ORDER BY weight_actual DESC",
                conn, params=[snapshot_date]
            )
        return pd.read_sql(
            "SELECT * FROM portfolio_holdings ORDER BY weight_actual DESC", conn
        )


def get_portfolio_history_dates() -> list[str]:
    """Return all distinct snapshot dates from portfolio_history, descending."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT snapshot_date FROM portfolio_history ORDER BY snapshot_date DESC"
        ).fetchall()
    return [r["snapshot_date"] for r in rows]


def get_trades_this_month() -> pd.DataFrame:
    """Return all trades logged in the current calendar month."""
    month_prefix = datetime.today().strftime("%Y-%m")
    with get_conn() as conn:
        return pd.read_sql(
            "SELECT * FROM trade_log WHERE trade_date LIKE ? ORDER BY trade_date DESC",
            conn, params=[f"{month_prefix}%"]
        )


if __name__ == "__main__":
    init_db()
