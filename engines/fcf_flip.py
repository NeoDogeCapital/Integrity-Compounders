"""
fcf_flip.py — FCF Yield Flip Screen (Options Candidates)
Integrity Compounders Alpha System v9.1

Composite score (0–100):
  40% Current FCF Yield rank    (absolute cheapness)
  35% Yield Decline rank        (magnitude of implied re-rating)
  25% Reverse Price Momentum    (negative price action scores higher)

Setup types classify the quality of the setup beyond the raw score.
This is a satellite framework (defined-risk options structures), not core equity sizing.
Every candidate has already cleared the five-gate quality screen.
"""

import pandas as pd
import numpy as np

FLIP_WEIGHTS = {
    "fcf_yield_rank":    0.40,
    "yield_decline_rank": 0.35,
    "reverse_price_rank": 0.25,
}

HIGH_CONVICTION_THRESHOLD = 0.80   # Q2 names above this → LEAPS candidates
CALL_SPREAD_DTE = "60–90 DTE"
LEAPS_LABEL     = "LEAPS (high-conviction Q2)"


def compute_flip_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute FCF Flip composite score for every name.
    Adds: yield_decline, flip_score, flip_score_pct, flip_setup_type
    """
    df = df.copy()

    # Yield decline: how much the forward FCF yield falls below current
    # Positive = forward yield is lower = re-rating implied = good
    df["yield_decline"] = df["fcf_yield"] - df["fwd_fcf_yield"]

    # Rank-normalize (higher = better for each component)
    n = len(df)

    df["fcf_yield_rank"]     = df["fcf_yield"].rank(pct=True, na_option="bottom")
    df["yield_decline_rank"] = df["yield_decline"].rank(pct=True, na_option="bottom")

    # Reverse price momentum: negative trailing return = higher score
    df["reverse_price_mom"]  = -df["tr_1m"].fillna(0)
    df["reverse_price_rank"] = df["reverse_price_mom"].rank(pct=True, na_option="bottom")

    # Composite score (0–1 scale, then convert to 0–100)
    df["flip_score"] = (
        FLIP_WEIGHTS["fcf_yield_rank"]    * df["fcf_yield_rank"] +
        FLIP_WEIGHTS["yield_decline_rank"] * df["yield_decline_rank"] +
        FLIP_WEIGHTS["reverse_price_rank"] * df["reverse_price_rank"]
    )
    df["flip_score_pct"] = (df["flip_score"] * 100).round(1)
    df["flip_rank"] = df["flip_score"].rank(ascending=False, method="min").astype(int)

    # Setup type classification
    df["flip_setup_type"] = df.apply(_setup_type, axis=1)

    # Options structure suggestion
    df["options_structure"] = df.apply(_options_structure, axis=1)

    return df


def _setup_type(row: pd.Series) -> str:
    """
    Classify the flip setup type based on qualitative conditions.
    """
    fcf_high      = row.get("fcf_yield", 0) >= 0.06
    fwd_declining = row.get("yield_decline", 0) > 0        # fwd yield < current
    fwd_flat      = abs(row.get("yield_decline", 0)) < 0.005
    fwd_rising    = row.get("yield_decline", 0) < -0.005   # fwd yield > current
    price_stable  = abs(row.get("tr_1m", 0)) < 0.03
    price_falling = row.get("tr_1m", 0) < -0.03
    price_rising  = row.get("tr_1m", 0) > 0.03
    fcf_low       = row.get("fcf_yield", 0) < 0.03
    quadrant      = row.get("quadrant", "")

    if fcf_high and fwd_declining and price_stable:
        return "Value Re-rate Underway"
    if fcf_high and fwd_declining and price_falling:
        return "Value Trap Watch"
    if not fcf_high and fwd_declining and price_rising:
        return "Momentum Re-rate"
    if fcf_high and fwd_flat:
        return "Deep Value (stable)"
    if fcf_low and fwd_rising:
        return "Premium + FCF Declining"
    if fcf_low and fwd_declining and quadrant in ("Q1", "Q2"):
        return "Premium + FCF Growing"
    return "Watch"


def _options_structure(row: pd.Series) -> str:
    """Suggest options structure based on setup type and quadrant."""
    setup   = row.get("flip_setup_type", "")
    quadrant = row.get("quadrant", "")
    score   = row.get("flip_score", 0)

    if quadrant == "Q2" and score >= HIGH_CONVICTION_THRESHOLD:
        return LEAPS_LABEL
    if setup == "Value Re-rate Underway":
        return f"Call spread {CALL_SPREAD_DTE}"
    if setup in ("Value Trap Watch", "Watch"):
        return "Monitor — no structure yet"
    if setup == "Premium + FCF Declining":
        return "Avoid — negative setup"
    return "Review discretion"


def print_flip_screen(df: pd.DataFrame, top_n: int = 20):
    if "flip_score_pct" not in df.columns:
        df = compute_flip_scores(df)

    print("\n" + "═" * 75)
    print("  FCF YIELD FLIP SCREEN — OPTIONS CANDIDATES  (Satellite Framework)")
    print("  Weights: FCF Yield 40% | Yield Decline 35% | Rev Price Momentum 25%")
    print("═" * 75)

    top = df.sort_values("flip_score", ascending=False).head(top_n)
    cols = ["ticker", "quadrant", "flip_score_pct", "flip_setup_type",
            "options_structure", "fcf_yield", "fwd_fcf_yield",
            "yield_decline", "tr_1m", "alignment_bucket"]
    present = [c for c in cols if c in top.columns]

    for _, r in top[present].iterrows():
        fcf = f"{r['fcf_yield']:.1%}" if pd.notna(r.get("fcf_yield")) else "N/A"
        fwd = f"{r['fwd_fcf_yield']:.1%}" if pd.notna(r.get("fwd_fcf_yield")) else "N/A"
        yld = f"{r['yield_decline']:.1%}" if pd.notna(r.get("yield_decline")) else "N/A"
        mom = f"{r['tr_1m']:.1%}" if pd.notna(r.get("tr_1m")) else "N/A"
        print(
            f"  {r['ticker']:<7} {r.get('quadrant',''):<4}  "
            f"Score:{r['flip_score_pct']:>5.1f}  "
            f"FCF:{fcf}→{fwd}(Δ{yld})  "
            f"1M:{mom}  "
            f"{r.get('flip_setup_type',''):<28}  "
            f"→ {r.get('options_structure','')}"
        )

    leaps = df[
        (df["quadrant"] == "Q2") &
        (df["flip_score"] >= HIGH_CONVICTION_THRESHOLD)
    ]
    if not leaps.empty:
        print(f"\n  ★ HIGH-CONVICTION Q2 LEAPS CANDIDATES ({len(leaps)} names, score ≥ {HIGH_CONVICTION_THRESHOLD:.0%}):")
        for _, r in leaps.sort_values("flip_score", ascending=False).iterrows():
            print(f"    {r['ticker']:<7} Flip Score: {r['flip_score_pct']:.1f}  "
                  f"Alignment: {r.get('alignment_bucket','')}")
    print("═" * 75 + "\n")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from engines.database import get_universe, init_db
    from engines.screener import run_gates
    from engines.quad import compute_axes, assign_quadrants
    from engines.alignment import compute_alignment

    init_db()
    df = get_universe()
    if df.empty:
        print("Universe empty — run `python run.py refresh` first.")
    else:
        df = run_gates(df)
        df = compute_axes(df)
        df = assign_quadrants(df)
        df = compute_alignment(df)
        df = compute_flip_scores(df)
        print_flip_screen(df)
