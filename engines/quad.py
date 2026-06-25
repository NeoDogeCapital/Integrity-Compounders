"""
quad.py — Stock-Level Quad Framework + Severity (v10.0)
Integrity Compounders Alpha System v10.0

X-Axis (Revenue Momentum):
    X = Fwd Rev CAGR (col 13) - Rev 3Y CAGR (col 18)
    Positive = revenue accelerating. Negative = revenue decelerating.

Y-Axis (Earnings Momentum):
    Y = Fwd EPS CAGR capped (col 24, cap 25%) - EPS 3Y CAGR (col 23)
    Positive = earnings accelerating. Negative = earnings decelerating.

Quadrant Assignment:
    Q1 Full Compounders:    X > 0, Y > 0  (EV Rank 1 — Best)
    Q2 Earnings Resilience: X < 0, Y > 0  (EV Rank 2)
    Q3 Margin Compression:  X > 0, Y < 0  (EV Rank 3)
    Q4 Full Deterioration:  X < 0, Y < 0  (EV Rank 4 — Worst)
    N/A: either axis is missing or uncomputable

FCF Yield Spread is now a separate valuation overlay (not a quad input).
See compute_fcf_spread() below.
"""

import pandas as pd
import numpy as np
from datetime import datetime

# ── Clip bounds for scatter visualization ─────────────────────────────────────
X_CLIP = (-0.30, 0.30)
Y_CLIP = (-0.30, 0.30)

# ── EV Rank lookup ────────────────────────────────────────────────────────────
EV_RANK = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "N/A": 99}
EV_LABEL = {
    1:  "1 — Best (Full Compounders)",
    2:  "2 — Quality Signal (Earnings Resilience)",
    3:  "3 — Warning (Margin Compression)",
    4:  "4 — Worst (Full Deterioration)",
    99: "N/A",
}

# ── Quad name lookup ──────────────────────────────────────────────────────────
QUAD_NAME = {
    "Q1": "Full Compounders",
    "Q2": "Earnings Resilience",
    "Q3": "Margin Compression",
    "Q4": "Full Deterioration",
    "N/A": "Axis Incomplete",
}

# ── Migration severity matrix ─────────────────────────────────────────────────
SEVERITY_MAP = {
    ("Q1", "Q2"): ("CONSTRUCTIVE", "Revenue slowing but earnings holding — monitor"),
    ("Q1", "Q3"): ("WARNING",      "Earnings fading despite revenue growth — margin risk"),
    ("Q1", "Q4"): ("DANGEROUS",    "Full deterioration from best bucket"),
    ("Q2", "Q1"): ("FAVORABLE",    "Revenue reaccelerating — full confirmation"),
    ("Q2", "Q3"): ("DANGEROUS",    "Lost earnings resilience AND revenue now compressing"),
    ("Q2", "Q4"): ("DANGEROUS",    "Full deterioration from earnings resilience"),
    ("Q3", "Q1"): ("FAVORABLE",    "Earnings recovering while revenue still strong"),
    ("Q3", "Q4"): ("WARNING",      "Revenue now also slowing — full deterioration incoming"),
    ("Q4", "Q1"): ("FAVORABLE",    "Full recovery — strongest signal"),
    ("Q4", "Q2"): ("CONSTRUCTIVE", "Earnings recovering first — quality signal"),
    ("Q4", "Q3"): ("CONSTRUCTIVE", "Revenue recovering first — watch margins"),
    ("Q3", "Q2"): ("DANGEROUS",    "Revenue slowing to match earnings — both now weak"),
}


def _assign_quadrant(x: float, y: float) -> str:
    """
    Assign quadrant from X (Revenue Momentum) and Y (Earnings Momentum).
    Q1 Full Compounders:    X > 0 AND Y > 0  (EV Rank 1 — Best)
    Q2 Earnings Resilience: X < 0 AND Y > 0  (EV Rank 2)
    Q3 Margin Compression:  X > 0 AND Y < 0  (EV Rank 3)
    Q4 Full Deterioration:  X < 0 AND Y < 0  (EV Rank 4 — Worst)
    """
    if pd.isna(x) or pd.isna(y):
        return "N/A"
    if x >= 0 and y >= 0:
        return "Q1"   # Full Compounders
    if x < 0 and y >= 0:
        return "Q2"   # Earnings Resilience
    if x >= 0 and y < 0:
        return "Q3"   # Margin Compression
    return "Q4"       # Full Deterioration (x < 0 and y < 0)


def compute_axes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute X (Revenue Momentum) and Y (Earnings Momentum) for every name.

    X-axis = Fwd Rev CAGR - Rev 3Y CAGR
    Y-axis = Fwd EPS CAGR (capped 25%) - EPS 3Y CAGR

    Column aliases for backward compat with reports/alignment:
      earnings_mom_roc = X-axis (Revenue Momentum)
      multiple_roc     = Y-axis (Earnings Momentum)
    """
    df = df.copy()

    # X-axis: Revenue Momentum
    df["x_rev_mom"] = df["fwd_rev_cagr"] - df["rev_3y_cagr"]
    df["earnings_mom_roc"] = df["x_rev_mom"]   # backward-compat alias

    # Y-axis: Earnings Momentum (apply 25% cap to forward EPS before computing)
    fwd_eps_capped = df["fwd_eps_cagr_capped"].fillna(df["fwd_eps_cagr"])
    df["y_eps_mom"] = fwd_eps_capped - df["eps_3y_cagr"]
    df["multiple_roc"] = df["y_eps_mom"]       # backward-compat alias

    df["x_axis_complete"] = df["x_rev_mom"].notna().astype(int)
    df["y_axis_complete"] = df["y_eps_mom"].notna().astype(int)

    # FCF Yield Spread — valuation overlay (not a quad input)
    df["fcf_spread"] = df["fcf_yield"] - df["fwd_fcf_yield"]

    return df


# ── V12: Earnings Quality Contamination Detector ──────────────────────────────
def _earnings_quality_flag(eps_acc, gp_acc) -> str:
    """
    Classify earnings acceleration against gross-profit acceleration.

    EPS is vulnerable to buybacks, tax, SBC, and D&A choices. We verify the
    earnings signal against trailing gross profit, which is far harder to
    financially engineer.

      EPS_CONFIRMED   — EPS accelerating AND gross profit accelerating
      EPS_ENGINEERED  — EPS accelerating, gross profit NOT — scrutinize
      GP_LEADING      — gross profit accelerating ahead of EPS — early inflection
      NEUTRAL         — neither accelerating
      DATA_INCOMPLETE — an input is missing (never a false classification)
    """
    if eps_acc is None or gp_acc is None or pd.isna(eps_acc) or pd.isna(gp_acc):
        return "DATA_INCOMPLETE"
    eps_up = eps_acc > 0
    gp_up  = gp_acc > 0
    if eps_up and gp_up:
        return "EPS_CONFIRMED"
    if eps_up and not gp_up:
        return "EPS_ENGINEERED"
    if gp_up and not eps_up:
        return "GP_LEADING"
    return "NEUTRAL"


def compute_earnings_quality(df: pd.DataFrame) -> pd.DataFrame:
    """
    V12 contamination detector. Requires trailing 1Y/3Y CAGR columns from the
    Fiscal AI CSV: eps_cagr_1y, eps_3y_cagr, gp_cagr_1y, gp_cagr_3y.

    Adds: eps_acceleration, gp_acceleration, earnings_quality_flag.
    Missing inputs yield DATA_INCOMPLETE rather than a false flag.
    """
    df = df.copy()

    eps_1y = df["eps_cagr_1y"] if "eps_cagr_1y" in df.columns else pd.Series(np.nan, index=df.index)
    eps_3y = df["eps_3y_cagr"] if "eps_3y_cagr" in df.columns else pd.Series(np.nan, index=df.index)
    gp_1y  = df["gp_cagr_1y"]  if "gp_cagr_1y"  in df.columns else pd.Series(np.nan, index=df.index)
    gp_3y  = df["gp_cagr_3y"]  if "gp_cagr_3y"  in df.columns else pd.Series(np.nan, index=df.index)

    df["eps_acceleration"] = eps_1y - eps_3y
    df["gp_acceleration"]  = gp_1y  - gp_3y
    df["earnings_quality_flag"] = df.apply(
        lambda r: _earnings_quality_flag(r["eps_acceleration"], r["gp_acceleration"]),
        axis=1,
    )
    return df


def compute_fcf_spread(df: pd.DataFrame) -> pd.DataFrame:
    """
    FCF Yield Spread — standalone valuation overlay.
    fcf_spread = Current FCF Yield - Forward FCF Yield

    Tags:
      'Re-rating'  if spread > 0.005  (current > forward: market expects multiple compression)
      'De-rating'  if spread < -0.005 (forward > current: growth expected to catch up)
      'Neutral'    if abs(spread) <= 0.005
    """
    df = df.copy()
    if "fcf_spread" not in df.columns:
        df["fcf_spread"] = df["fcf_yield"] - df["fwd_fcf_yield"]

    def _tag(v):
        if pd.isna(v):
            return "—"
        if v > 0.005:
            return "Re-rating"
        if v < -0.005:
            return "De-rating"
        return "Neutral"

    df["fcf_spread_tag"] = df["fcf_spread"].apply(_tag)
    return df


def assign_quadrants(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign quadrants, EV ranks, quad names, and valuation overlay.
    Requires compute_axes() to have been run first.
    """
    df = df.copy()

    def _quad(row):
        if not row.get("x_axis_complete") or not row.get("y_axis_complete"):
            return "N/A"
        return _assign_quadrant(row["earnings_mom_roc"], row["multiple_roc"])

    df["quadrant"]      = df.apply(_quad, axis=1)
    df["quad_name"]     = df["quadrant"].map(QUAD_NAME).fillna("Axis Incomplete")
    df["ev_rank"]       = df["quadrant"].map(EV_RANK).fillna(99).astype(int)
    df["severity_tier"] = df["ev_rank"].map(EV_LABEL)

    # FCF Yield Spread valuation overlay
    df = compute_fcf_spread(df)

    # V12 — earnings-quality contamination detector
    df = compute_earnings_quality(df)

    # Clipped coordinates for chart (visualization layer)
    df["x_clipped"]    = df["earnings_mom_roc"].clip(*X_CLIP)
    df["y_clipped"]    = df["multiple_roc"].clip(*Y_CLIP)
    df["x_is_clipped"] = (df["earnings_mom_roc"] < X_CLIP[0]) | (df["earnings_mom_roc"] > X_CLIP[1])
    df["y_is_clipped"] = (df["multiple_roc"] < Y_CLIP[0]) | (df["multiple_roc"] > Y_CLIP[1])

    return df


def compute_migrations(current: pd.DataFrame, previous: pd.DataFrame | None) -> pd.DataFrame:
    """
    Compare current vs previous quad assignments.
    Returns a DataFrame of migrations with severity labels.
    Respects the two-consecutive-month stability rule:
        quad_provisional = 1 on first appearance in new quad.
    """
    if previous is None or previous.empty:
        current = current.copy()
        current["from_quad"] = None
        current["migration_severity"] = None
        current["flip_direction"] = None
        current["quad_provisional"] = 1
        return current

    prev_map = previous.set_index("ticker")[["quadrant", "quad_provisional"]].to_dict("index")
    current = current.copy()
    migrations = []

    for idx, row in current.iterrows():
        ticker = row["ticker"]
        curr_q = row["quadrant"]

        if ticker not in prev_map:
            current.at[idx, "from_quad"] = None
            current.at[idx, "quad_provisional"] = 1
            current.at[idx, "migration_severity"] = None
            current.at[idx, "flip_direction"] = None
            continue

        prev_q = prev_map[ticker]["quadrant"]
        prev_prov = prev_map[ticker].get("quad_provisional", 0)

        current.at[idx, "from_quad"] = prev_q

        if curr_q == prev_q:
            # Same quad — confirm if it was provisional
            current.at[idx, "quad_provisional"] = 0
            current.at[idx, "migration_severity"] = None
            current.at[idx, "flip_direction"] = None
        elif curr_q == "N/A" or prev_q == "N/A":
            current.at[idx, "quad_provisional"] = 1
            current.at[idx, "migration_severity"] = None
            current.at[idx, "flip_direction"] = None
        else:
            # Real migration
            sev_key = (prev_q, curr_q)
            sev_label, sev_desc = SEVERITY_MAP.get(sev_key, ("NEUTRAL", "Unclassified migration"))
            direction = f"{prev_q} → {curr_q}"

            current.at[idx, "quad_provisional"] = 1  # new quad, starts provisional
            current.at[idx, "migration_severity"] = f"{sev_label} — {sev_desc}"
            current.at[idx, "flip_direction"] = direction

            migrations.append({
                "ticker":   ticker,
                "from":     prev_q,
                "to":       curr_q,
                "severity": sev_label,
                "desc":     sev_desc,
            })

    current.attrs["migrations"] = migrations
    return current


def print_quad_distribution(df: pd.DataFrame):
    """Print current quad distribution with EV context."""
    counts = df["quadrant"].value_counts()
    total = len(df)

    print("\n" + "=" * 65)
    print("  QUAD DISTRIBUTION — INTEGRITY COMPOUNDERS UNIVERSE  v10.0")
    print("=" * 65)
    for q, label, ev in [
        ("Q1", "Full Compounders       [EV Rank 1 — BEST]",  "++"),
        ("Q2", "Earnings Resilience    [EV Rank 2]",          "+ "),
        ("Q3", "Margin Compression     [EV Rank 3]",          "- "),
        ("Q4", "Full Deterioration     [EV Rank 4 — WORST]", "--"),
        ("N/A","Axis Incomplete",                             "  "),
    ]:
        n = counts.get(q, 0)
        bar = "#" * int(n / max(total, 1) * 30)
        print(f"  {ev} {q}  {label:<40} {n:>3}  {bar}")
    print(f"\n  Total universe: {total}")
    print("=" * 65 + "\n")


def top_by_quad(df: pd.DataFrame, quadrant: str, n: int = 10,
                sort_col: str = "alignment_score") -> pd.DataFrame:
    """Return top N names in a quadrant sorted by a score column."""
    q_df = df[df["quadrant"] == quadrant].copy()
    if sort_col in q_df.columns:
        q_df = q_df.sort_values(sort_col, ascending=False)
    cols = ["ticker", "company", "industry", "quadrant", "ev_rank",
            "earnings_mom_roc", "multiple_roc", "alignment_score",
            "alignment_bucket", "pead_flag", "stock_price", "market_cap"]
    present = [c for c in cols if c in q_df.columns]
    return q_df[present].head(n)


def dangerous_migrations(df: pd.DataFrame) -> pd.DataFrame:
    """Return all DANGEROUS migrations in current run — highest priority review."""
    if "migration_severity" not in df.columns:
        return pd.DataFrame()
    mask = df["migration_severity"].str.startswith("DANGEROUS", na=False)
    cols = ["ticker", "company", "from_quad", "quadrant", "migration_severity",
            "alignment_score", "pead_flag", "stock_price"]
    present = [c for c in cols if c in df.columns]
    return df[mask][present].sort_values("alignment_score", ascending=True)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from engines.database import get_universe, init_db

    init_db()
    df = get_universe()
    if df.empty:
        print("Universe is empty — run `python run.py refresh` first.")
    else:
        df = compute_axes(df)
        df = assign_quadrants(df)
        print_quad_distribution(df)
        print("\nTop Q1 names (Full Compounders, by Alignment Score):")
        print(top_by_quad(df, "Q1").to_string(index=False))
