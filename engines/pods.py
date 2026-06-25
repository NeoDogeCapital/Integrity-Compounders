"""
pods.py — Business-Model Pod Waterfall  [DEPRECATED IN V12]

⚠️  RETIRED in Methodology V12 (Issue 9). POD (Point of Differentiation) is no
longer part of the pipeline — it is replaced by the diagnostic quality_profile
(engines/screener.py) plus the six-factor exposure model. This module is kept
only so historical scripts that import it do not crash; it is not called by
run.py's pipeline. Do not add new dependencies on it.

Deterministic waterfall: first-match wins, evaluated in priority order.
"""

import pandas as pd
import numpy as np
import json

# ── Pod rules (priority order, first match wins) ──────────────────────────────
# Each rule: (pod_name, [(field, op, threshold), ...])  — all conditions must pass
POD_RULES = [
    ("Capital Returner", [
        ("buyback_yield", ">=", 0.03),
        ("capex_to_rev",  "<=", 0.05),
    ]),
    ("Reinvestor", [
        ("capex_to_rev",  ">=", 0.05),
        ("fwd_rev_cagr",  ">=", 0.10),
        ("roic",          ">=", 0.15),
    ]),
    ("Franchise / Pricing Power", [
        ("op_margin",  ">=", 0.25),   # proxy for gross margin
        ("fcf_yield",  ">=", 0.15),
    ]),
    ("HQ Growth", [
        ("fwd_rev_cagr", ">=", 0.15),
        ("fcf_yield",    ">=", 0.10),
        ("roic",         ">=", 0.15),
    ]),
    ("Cyclical", [
        ("beta", ">=", 1.30),
    ]),
    ("Defensive", [
        ("beta", "<=", 0.80),
    ]),
    ("Balance-Sheet Strong", [
        ("net_debt_ebitda", "<=", 1.00),
    ]),
    ("GARP", [
        ("peg",  "<=", 1.50),
        ("roic", ">=", 0.12),
    ]),
    ("Rate-Sensitive Growth", [
        ("fwd_rev_cagr", ">=", 0.15),
        ("peg",          ">=", 2.00),
    ]),
]


def _eval_condition(value, op: str, threshold: float) -> bool:
    if pd.isna(value):
        return False
    if op == ">=":
        return float(value) >= threshold
    if op == "<=":
        return float(value) <= threshold
    raise ValueError(f"Unknown operator: {op}")


def _pod_flags(row: pd.Series) -> dict:
    """Evaluate all pod rules and return a dict of {pod_name: bool}."""
    flags = {}
    for pod_name, conditions in POD_RULES:
        passes = all(
            _eval_condition(row.get(field, np.nan), op, thresh)
            for field, op, thresh in conditions
        )
        flags[pod_name] = passes
    return flags


def assign_pods(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign a pod to each name via deterministic waterfall.
    Adds: pod, pod_flags (JSON), pod_count
    """
    df = df.copy()
    pods = []
    flags_list = []
    counts = []

    for _, row in df.iterrows():
        flags = _pod_flags(row)
        flags_list.append(json.dumps(flags))
        counts.append(sum(flags.values()))

        # First match wins
        assigned = "Unclassified"
        for pod_name, _ in POD_RULES:
            if flags.get(pod_name):
                assigned = pod_name
                break
        pods.append(assigned)

    df["pod"] = pods
    df["pod_flags"] = flags_list
    df["pod_count"] = counts
    return df


def pod_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Return a summary of pod distribution across the universe."""
    summary = (
        df.groupby("pod")
        .agg(
            count=("ticker", "count"),
            avg_roic=("roic", "mean"),
            avg_fcf_yield=("fcf_yield", "mean"),
            avg_alignment=("alignment_score", "mean"),
        )
        .reset_index()
        .sort_values("count", ascending=False)
    )
    total = len(df)
    summary["pct"] = (summary["count"] / total).round(3)
    return summary


def print_pod_distribution(df: pd.DataFrame):
    dist = pod_distribution(df)
    print("\n" + "═" * 65)
    print("  BUSINESS-MODEL POD DISTRIBUTION")
    print("═" * 65)
    print(f"  {'Pod':<30} {'N':>4}  {'%':>6}  {'AvgROIC':>8}  {'AvgFCF':>8}")
    print("  " + "─" * 60)
    for _, r in dist.iterrows():
        roic_str = f"{r['avg_roic']:.1%}" if pd.notna(r["avg_roic"]) else "  N/A "
        fcf_str  = f"{r['avg_fcf_yield']:.1%}" if pd.notna(r["avg_fcf_yield"]) else "  N/A "
        print(f"  {r['pod']:<30} {r['count']:>4}  {r['pct']:>5.1%}  {roic_str:>8}  {fcf_str:>8}")
    print("═" * 65 + "\n")


def pod_by_quad(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-tab of pod vs quadrant — useful for factor exposure audit."""
    if "quadrant" not in df.columns or "pod" not in df.columns:
        return pd.DataFrame()
    ct = pd.crosstab(df["pod"], df["quadrant"])
    return ct


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from engines.database import get_universe, init_db
    from engines.screener import run_gates
    from engines.quad import compute_axes, assign_quadrants

    init_db()
    df = get_universe()
    if df.empty:
        print("Universe empty — run `python run.py refresh` first.")
    else:
        df = run_gates(df)
        df = compute_axes(df)
        df = assign_quadrants(df)
        df = assign_pods(df)
        print_pod_distribution(df)
        print("\nPod × Quadrant cross-tab:")
        print(pod_by_quad(df).to_string())
