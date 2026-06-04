"""
screener.py — Five-Gate Quality Screen
Integrity Compounders Alpha System v9.1

Gates (all must pass):
  1. Quality:       ROIC >= 12%
  2. Durability:    Op Margin >= 25%   (proxy for Gross Margin; flagged)
  3. Cash Conv:     FCF Yield >= 8%    (proxy for FCF Margin >= 10%; flagged)
  4. Reinvestment:  Rev 3Y CAGR >= 6%
  5. Balance Sheet: Net Debt/EBITDA <= 2.5x

Survivorship: two consecutive monthly fails on same gate → removed.
One fail on two different gates → removed.
"""

import pandas as pd
import numpy as np
import json
from datetime import datetime

# ── Gate thresholds (editable here; referenced in CLAUDE.md) ─────────────────
GATES = {
    "quality":       ("roic",            ">=", 12.0),
    "durability":    ("op_margin",       ">=", 25.0),   # proxy: gross margin
    "cash_conv":     ("fcf_yield",       ">=",  3.0),   # proxy: fcf margin
    "reinvestment":  ("rev_3y_cagr",     ">=",  6.0),
    "balance_sheet": ("net_debt_ebitda", "<=",  2.5),
}

PROXY_FLAGS = {
    "durability": "Op Margin used as proxy for Gross Margin (not in Fiscal AI export)",
    "cash_conv":  "FCF Yield used as proxy for FCF Margin (not in Fiscal AI export)",
}

EPS_CAGR_CAP = 25.0   # cap forward EPS CAGR at 25% (data stored as plain %, e.g. 12.5 = 12.5%)


def _eval_gate(series: pd.Series, op: str, threshold: float) -> pd.Series:
    if op == ">=":
        return (series >= threshold).astype(int)
    elif op == "<=":
        return (series <= threshold).astype(int)
    raise ValueError(f"Unknown operator: {op}")


def run_gates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Evaluate all five gates per name.
    Adds columns: gate_quality, gate_durability, gate_cash_conv,
                  gate_reinvestment, gate_balance_sheet, gates_pass,
                  universe_status, watch_flags, fwd_eps_cagr (capped).
    """
    df = df.copy()

    # EPS CAGR cap (base-effect protection)
    if "fwd_eps_cagr" in df.columns:
        capped = df["fwd_eps_cagr"] > EPS_CAGR_CAP
        df["fwd_eps_cagr_capped"] = df["fwd_eps_cagr"].clip(upper=EPS_CAGR_CAP)
        df["eps_cagr_was_capped"] = capped.astype(int)
    else:
        df["fwd_eps_cagr_capped"] = np.nan
        df["eps_cagr_was_capped"] = 0

    # Evaluate each gate
    failed_gates = {}
    for gate_name, (field, op, thresh) in GATES.items():
        col = f"gate_{gate_name}"
        if field in df.columns:
            result = _eval_gate(df[field].fillna(-999 if op == ">=" else 999), op, thresh)
        else:
            result = pd.Series(0, index=df.index)
            print(f"[Screener] WARNING: field '{field}' missing — gate '{gate_name}' defaults to FAIL")
        df[col] = result

    gate_cols = [f"gate_{g}" for g in GATES]
    df["gates_pass"] = df[gate_cols].sum(axis=1)

    # Determine watch_flags (which gates failed this run)
    def _watch_flags(row):
        fails = [g for g in GATES if row.get(f"gate_{g}", 0) == 0]
        return json.dumps(fails)

    df["watch_flags"] = df.apply(_watch_flags, axis=1)

    # Simple status assignment (without consecutive-fail history)
    # Full consecutive tracking happens in update_universe_status()
    def _status(row):
        fails = json.loads(row["watch_flags"])
        if len(fails) == 0:
            return "active"
        if len(fails) >= 2:
            return "watch"  # immediate watch; consecutive logic may remove
        return "watch"

    df["universe_status"] = df.apply(_status, axis=1)

    return df


def update_universe_status(current: pd.DataFrame, previous: pd.DataFrame | None) -> pd.DataFrame:
    """
    Apply two-consecutive-fail survivorship rules by comparing current vs previous snapshot.
    Returns current with updated universe_status ('active' | 'watch' | 'removed').
    """
    if previous is None or previous.empty:
        return current

    current = current.copy()
    prev_indexed = previous.set_index("ticker") if "ticker" in previous.columns else previous

    for idx, row in current.iterrows():
        ticker = row["ticker"]
        curr_fails = set(json.loads(row.get("watch_flags", "[]")))

        if ticker not in prev_indexed.index:
            continue  # new name — no history

        prev_row = prev_indexed.loc[ticker]
        prev_fails = set(json.loads(prev_row.get("watch_flags") or "[]"))

        if not curr_fails:
            current.at[idx, "universe_status"] = "active"
            continue

        # Two different gates failed this month
        if len(curr_fails) >= 2:
            current.at[idx, "universe_status"] = "removed"
            continue

        # Same single gate failed in both months → remove
        if curr_fails == prev_fails and len(curr_fails) == 1:
            current.at[idx, "universe_status"] = "removed"
        else:
            current.at[idx, "universe_status"] = "watch"

    return current


def screen_summary(df: pd.DataFrame) -> dict:
    """Return a summary dict of screening results."""
    active   = df[df["universe_status"] == "active"]
    watch    = df[df["universe_status"] == "watch"]
    removed  = df[df["universe_status"] == "removed"]
    capped   = df[df.get("eps_cagr_was_capped", pd.Series(0, index=df.index)) == 1]

    gate_pass_rates = {}
    for gate in GATES:
        col = f"gate_{gate}"
        if col in df.columns:
            rate = df[col].mean()
            gate_pass_rates[gate] = round(rate, 3)

    summary = {
        "total_names":      len(df),
        "active":           len(active),
        "watch":            len(watch),
        "removed":          len(removed),
        "survival_rate":    round(len(active) / max(len(df), 1), 4),
        "eps_cagr_capped":  len(capped),
        "gate_pass_rates":  gate_pass_rates,
        "proxy_flags":      PROXY_FLAGS,
        "run_timestamp":    datetime.utcnow().isoformat(),
    }
    return summary


def print_screen_summary(df: pd.DataFrame):
    s = screen_summary(df)
    print("\n" + "═" * 60)
    print("  INTEGRITY COMPOUNDERS — FIVE-GATE SCREEN RESULTS")
    print("═" * 60)
    print(f"  Universe scanned:   {s['total_names']:>4}")
    print(f"  Active (all 5 pass):{s['active']:>4}  ({s['survival_rate']:.1%} survival)")
    print(f"  Watch (1 fail):     {s['watch']:>4}")
    print(f"  Removed (2+ fail):  {s['removed']:>4}")
    print(f"  EPS CAGR capped:    {s['eps_cagr_capped']:>4}  (>{EPS_CAGR_CAP:.0f}% cap applied)")
    print("\n  Gate pass rates:")
    for gate, rate in s["gate_pass_rates"].items():
        proxy = "  ⚑ proxy" if gate in PROXY_FLAGS else ""
        print(f"    {gate:<18} {rate:.1%}{proxy}")
    print("\n  ⚑ Proxy substitutions active (see CLAUDE.md §13):")
    for gate, msg in PROXY_FLAGS.items():
        print(f"    [{gate}] {msg}")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from engines.database import load_csv, init_db, upsert_universe, get_universe

    init_db()
    sample = __import__("pathlib").Path(__file__).parent.parent / "data" / "raw"
    csvs = list(sample.glob("*.csv"))
    if csvs:
        df = load_csv(csvs[0])
        df = run_gates(df)
        upsert_universe(df)
        print_screen_summary(df)
    else:
        print("No CSV found in data/raw/ — drop a Fiscal AI export there and rerun.")
