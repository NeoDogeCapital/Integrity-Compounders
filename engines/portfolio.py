"""
portfolio.py — Portfolio tracking engine
Integrity Compounders Alpha System v10.0

Handles portfolio CSV ingestion, model state enrichment,
weight/P&L calculations, alert detection, and terminal output.
"""

import sys
import os
import csv
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engines.database import (
    get_universe, get_conn, save_portfolio_snapshot, get_portfolio,
    get_portfolio_history_dates, log_decision, get_last_snapshot_date,
)
from engines.screener  import run_gates
from engines.quad      import compute_axes, assign_quadrants, QUAD_NAME
from engines.alignment import compute_alignment
from engines.fcf_flip  import compute_flip_scores
from engines.pods      import assign_pods

# ── Sleeve targets (%) ────────────────────────────────────────────────────────
SLEEVE_TARGETS = {
    "Core Compounders":              45.0,
    "Catalyst Momentum":             30.0,
    "Relative Value Pairs":          15.0,
    "High Conviction Speculative":   10.0,
}
SECTOR_CAP = 28.0
DEFAULT_TARGET_WEIGHT = 4.0
MIGRATION_WARNING_PCT  = 0.10   # within 10% of quad flip price


# ── Pipeline helper ───────────────────────────────────────────────────────────

def _get_enriched_universe() -> pd.DataFrame:
    """Run full pipeline and return enriched universe DataFrame."""
    df = get_universe("all")
    if df.empty:
        return df
    df = run_gates(df)
    df = compute_axes(df)
    df = assign_quadrants(df)
    df = assign_pods(df)
    df = compute_alignment(df)
    df = compute_flip_scores(df)
    return df


# ── CSV loader ────────────────────────────────────────────────────────────────

def load_portfolio_csv(path: Path | None = None) -> pd.DataFrame:
    """
    Load portfolio.csv from data/raw/.
    Required columns: ticker, shares, avg_cost, sleeve, is_discretionary
    """
    if path is None:
        raw_dir = ROOT / "data" / "raw"
        # Prefer portfolio.csv; fall back to portfolio_template.csv
        for fname in ["portfolio.csv", "portfolio_template.csv"]:
            candidate = raw_dir / fname
            if candidate.exists():
                path = candidate
                break
    if path is None or not path.exists():
        raise FileNotFoundError(
            "No portfolio.csv found in data/raw/. "
            "Create one with columns: ticker, shares, avg_cost, sleeve, is_discretionary"
        )

    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()

    # Coerce numerics
    for col in ["shares", "avg_cost", "is_discretionary"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["is_discretionary"] = df["is_discretionary"].fillna(0).astype(int)
    df["sleeve"] = df["sleeve"].fillna("Core Compounders").str.strip()
    print(f"[Portfolio] Loaded {len(df)} positions from {path.name}")
    return df


# ── Core enrichment ───────────────────────────────────────────────────────────

def build_portfolio(csv_df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich raw portfolio CSV with current prices, model state,
    P&L, weights, and alerts.
    """
    universe = _get_enriched_universe()
    if universe.empty:
        print("[Portfolio] WARNING: universe is empty — run refresh first.")
        return csv_df

    now = datetime.utcnow().isoformat()

    rows = []
    for _, pos in csv_df.iterrows():
        ticker = pos["ticker"]
        uni_row = universe[universe["ticker"] == ticker]

        if uni_row.empty:
            print(f"  [Portfolio] {ticker} not found in universe — using avg_cost as price.")
            cur_price = float(pos.get("avg_cost") or 0)
            company = ticker
            model = {}
        else:
            r = uni_row.iloc[0]
            cur_price = float(r.get("stock_price") or 0)
            company   = str(r.get("company") or ticker)
            model = {
                "quadrant":           str(r.get("quadrant") or "N/A"),
                "quad_name":          str(r.get("quad_name") or QUAD_NAME.get(str(r.get("quadrant","N/A")), "N/A")),
                "ev_rank":            int(r.get("ev_rank") or 99),
                "alignment_score":    float(r.get("alignment_score") or 0),
                "alignment_bucket":   str(r.get("alignment_bucket") or "Neutral"),
                "pead_flag":          str(r.get("pead_flag") or "—"),
                "x_axis":             float(r.get("earnings_mom_roc") or 0),
                "y_axis":             float(r.get("multiple_roc") or 0),
                "fcf_spread_tag":     str(r.get("fcf_spread_tag") or "—"),
                "convergence_signals":int(r.get("convergence_count") or 0),
                "industry":           str(r.get("industry") or ""),
            }

        shares    = float(pos.get("shares") or 0)
        avg_cost  = float(pos.get("avg_cost") or 0)
        cur_value = round(shares * cur_price, 2)
        unreal_usd = round((cur_price - avg_cost) * shares, 2)
        unreal_pct = round((cur_price / avg_cost - 1) * 100, 2) if avg_cost else 0.0

        # vs_base_case: Above / In Line / Below  (±5% band = In Line)
        if avg_cost > 0:
            pct_vs_cost = (cur_price - avg_cost) / avg_cost
            vs_base = "Above" if pct_vs_cost > 0.05 else "Below" if pct_vs_cost < -0.05 else "In Line"
        else:
            vs_base = "—"

        # migration_warning: price within 10% of flip_price from universe
        migration_warn = 0
        if not uni_row.empty:
            flip_p = uni_row.iloc[0].get("flip_price")
            if flip_p and flip_p > 0 and cur_price > 0:
                if abs(cur_price - flip_p) / cur_price <= MIGRATION_WARNING_PCT:
                    migration_warn = 1

        target_wt = DEFAULT_TARGET_WEIGHT

        row = {
            "ticker":              ticker,
            "company":             company,
            "shares":              shares,
            "avg_cost":            avg_cost,
            "current_price":       cur_price,
            "current_value":       cur_value,
            "weight_actual":       0.0,   # filled after total calc
            "weight_target":       target_wt,
            "weight_drift":        0.0,   # filled after total calc
            "sleeve":              str(pos.get("sleeve") or "Core Compounders"),
            "is_discretionary":    int(pos.get("is_discretionary") or 0),
            "unrealized_pnl_dollar": unreal_usd,
            "unrealized_pnl_pct":  unreal_pct,
            "vs_base_case":        vs_base,
            "migration_warning":   migration_warn,
            "added_at":            now,
            **model,
        }
        rows.append(row)

    port = pd.DataFrame(rows)

    # Calculate actual weights
    total_value = port["current_value"].sum()
    if total_value > 0:
        port["weight_actual"] = (port["current_value"] / total_value * 100).round(2)
        port["weight_drift"]  = (port["weight_actual"] - port["weight_target"]).round(2)

    return port, total_value


# ── Load command ──────────────────────────────────────────────────────────────

def cmd_load_portfolio(csv_path: Path | None = None) -> pd.DataFrame:
    """Load portfolio CSV, enrich, save to DB, print confirmation."""
    csv_df = load_portfolio_csv(csv_path)
    port, total_value = build_portfolio(csv_df)
    snapshot_date = datetime.today().strftime("%Y-%m-%d")
    save_portfolio_snapshot(port, snapshot_date)
    _print_load_summary(port, total_value)
    return port


def _print_load_summary(port: pd.DataFrame, total_value: float):
    n = len(port)
    avg_score = port["alignment_score"].mean() if "alignment_score" in port.columns else 0
    warns = int(port["migration_warning"].sum()) if "migration_warning" in port.columns else 0
    dist  = int((port["alignment_bucket"] == "Distribute").sum()) if "alignment_bucket" in port.columns else 0

    print(f"\n{'='*60}")
    print(f"  PORTFOLIO LOADED — {n} holdings")
    print(f"{'='*60}")
    print(f"  Total Value:    ${total_value:>12,.2f}")
    print(f"  Avg Align Score: {avg_score:.1f}")
    print(f"  Migration Warns: {warns}")
    print(f"  Distribute:      {dist}")
    print()

    q_counts = port["quadrant"].value_counts().to_dict() if "quadrant" in port.columns else {}
    for q, label in [("Q1","Full Compounders"),("Q2","Earnings Resilience"),
                     ("Q3","Margin Compression"),("Q4","Full Deterioration"),("N/A","N/A")]:
        n_q = q_counts.get(q, 0)
        if n_q:
            wt = port[port["quadrant"]==q]["weight_actual"].sum() if "quadrant" in port.columns else 0
            print(f"  {q} {label:<22} {n_q:>3} holdings  {wt:.1f}%")
    print(f"{'='*60}\n")


# ── Portfolio status command ──────────────────────────────────────────────────

def cmd_portfolio_status():
    """Print full portfolio status to terminal."""
    port = get_portfolio()
    if port.empty:
        print("[Portfolio] No portfolio loaded. Run: python run.py load portfolio")
        return

    total_value  = port["current_value"].sum()
    avg_score    = port["alignment_score"].mean() if "alignment_score" in port.columns else 0
    avg_ev       = port["ev_rank"].mean() if "ev_rank" in port.columns else 0
    n            = len(port)

    print(f"\n{'='*72}")
    print(f"  PORTFOLIO STATUS — {port['snapshot_date'].iloc[0] if 'snapshot_date' in port.columns else 'current'}")
    print(f"{'='*72}")
    print(f"  Holdings: {n}   Total Value: ${total_value:,.2f}   "
          f"Avg Score: {avg_score:.1f}   Avg EV Rank: {avg_ev:.1f}")

    # Sector distribution
    print(f"\n  SECTOR DISTRIBUTION (cap: {SECTOR_CAP}%)")
    print(f"  {'Sector':<38} {'Wt%':>6}  {'Flag'}")
    print(f"  {'-'*55}")
    if "industry" in port.columns:
        for sector, grp in port.groupby("industry"):
            wt = grp["weight_actual"].sum()
            flag = " !! OVER CAP" if wt > SECTOR_CAP else ""
            print(f"  {str(sector)[:38]:<38} {wt:>5.1f}%{flag}")

    # Sleeve distribution
    print(f"\n  SLEEVE ALLOCATION")
    print(f"  {'Sleeve':<32} {'Target':>7} {'Actual':>7} {'Drift':>7}  {'Flag'}")
    print(f"  {'-'*62}")
    for sleeve, target in SLEEVE_TARGETS.items():
        grp = port[port["sleeve"] == sleeve]
        actual = grp["weight_actual"].sum()
        drift  = actual - target
        flag   = " !! >5pp off" if abs(drift) > 5 else ""
        print(f"  {sleeve:<32} {target:>6.1f}% {actual:>6.1f}% {drift:>+6.1f}%{flag}")

    # Holdings table
    print(f"\n  HOLDINGS (sorted by EV rank then Alignment Score)")
    print(f"  {'Ticker':<7} {'Quad':<4} {'EV':>3} {'Score':>6} {'Bucket':<11} "
          f"{'Actual%':>7} {'Target%':>7} {'Drift':>6} {'P&L%':>7} {'vs Base':<9} {'Warn'}")
    print(f"  {'-'*88}")

    sorted_port = port.sort_values(
        ["ev_rank", "alignment_score"], ascending=[True, False]
    )
    for _, r in sorted_port.iterrows():
        warn_flag = " !!WARN" if r.get("migration_warning") else ""
        q4_flag   = " [Q4]"  if r.get("quadrant") == "Q4" else ""
        bucket    = str(r.get("alignment_bucket") or "—")[:10]
        score_str = f"{r.get('alignment_score', 0):.1f}" if pd.notna(r.get('alignment_score')) else "—"
        ev_str    = str(r.get("ev_rank") or "—")
        pnl_str   = f"{r.get('unrealized_pnl_pct', 0):+.1f}%" if pd.notna(r.get("unrealized_pnl_pct")) else "—"
        print(f"  {str(r['ticker']):<7} {str(r.get('quadrant','—')):<4} {ev_str:>3} "
              f"{score_str:>6} {bucket:<11} "
              f"{r.get('weight_actual', 0):>6.1f}% {r.get('weight_target', 0):>6.1f}% "
              f"{r.get('weight_drift', 0):>+5.1f}% {pnl_str:>7} "
              f"{str(r.get('vs_base_case','—')):<9}{warn_flag}{q4_flag}")

    # Alerts
    warns      = port[port["migration_warning"] == 1]
    distribs   = port[port["alignment_bucket"] == "Distribute"]
    drifts     = port[port["weight_drift"].abs() > 2]

    print(f"\n  ALERTS")
    print(f"  {'-'*55}")
    if warns.empty and distribs.empty and drifts.empty:
        print(f"  No alerts. All clear.")
    else:
        if not warns.empty:
            print(f"\n  MIGRATION WARNINGS ({len(warns)}):")
            for _, r in warns.iterrows():
                print(f"    {r['ticker']:<7} {r.get('quadrant','—')} | "
                      f"Score {r.get('alignment_score',0):.1f} | "
                      f"Price ${r.get('current_price',0):,.2f}")
        if not distribs.empty:
            print(f"\n  DISTRIBUTE SIGNALS ({len(distribs)}):")
            for _, r in distribs.iterrows():
                print(f"    {r['ticker']:<7} Score {r.get('alignment_score',0):.1f} | "
                      f"P&L {r.get('unrealized_pnl_pct',0):+.1f}%")
        if not drifts.empty:
            print(f"\n  WEIGHT DRIFT > +/-2% ({len(drifts)}):")
            for _, r in drifts.iterrows():
                print(f"    {r['ticker']:<7} Actual {r.get('weight_actual',0):.1f}% | "
                      f"Target {r.get('weight_target',0):.1f}% | "
                      f"Drift {r.get('weight_drift',0):+.1f}%")
    print(f"\n{'='*72}\n")


# ── Snapshot command ──────────────────────────────────────────────────────────

def cmd_portfolio_snapshot(csv_path: Path | None = None):
    """
    Full monthly snapshot:
    1. Load portfolio
    2. Save to DB
    3. Export CSV
    4. Generate HTML memo
    5. Log journal entry
    """
    port = cmd_load_portfolio(csv_path)
    if port is None or (hasattr(port, "empty") and port.empty):
        return

    snapshot_date = datetime.today().strftime("%Y-%m-%d")
    total_value   = port["current_value"].sum()
    avg_score     = port["alignment_score"].mean() if "alignment_score" in port.columns else 0
    warns         = int(port["migration_warning"].sum())

    # CSV export
    export_dir = ROOT / "outputs" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    csv_out = export_dir / f"portfolio_{snapshot_date}.csv"
    port.to_csv(csv_out, index=False)
    print(f"[Portfolio] CSV exported: {csv_out}")

    # HTML memo
    from engines.portfolio_report import generate_portfolio_memo
    html_path = generate_portfolio_memo(port, snapshot_date)

    # Journal entry
    log_decision(
        note=(f"Monthly portfolio snapshot taken — {len(port)} holdings, "
              f"total ${total_value:,.0f}, "
              f"weighted avg score {avg_score:.1f}, "
              f"{warns} migration warning(s)"),
        event_type="PORTFOLIO_SNAPSHOT"
    )

    # Open in browser
    try:
        import webbrowser
        webbrowser.open(f"file:///{str(html_path).replace(os.sep, '/')}")
    except Exception:
        pass

    print(f"[Portfolio] Snapshot complete: {snapshot_date}")
    return html_path
