"""
alignment.py — Compounders Alignment Score (3-Signal, v10.0)
Integrity Compounders Alpha System v10.0

Signal weights (sum to 1.0):
  Fundamental Velocity (FV):          50%  — Combined X-axis (Rev Momentum) +
                                              Y-axis (EPS Momentum); avg of both
                                              rank-normalized signals. Both must be
                                              positive for a high FV rank.
  Market Conviction (MC):             25%  — Blended price momentum (TR 1M + YTD)
  Earnings Surprise Velocity (ESV):   25%  — Avg(Rev Surprise Q, EPS Surprise Q)

Valuation Confirmation (VC) removed. FCF Yield Spread is now a standalone
valuation overlay in quad.py (compute_fcf_spread), not a signal input.

Each signal rank-normalized 0-100 across universe before weighting.
Missing ESV -> assigned 50.0 (universe median) to avoid penalizing missing data.

Buckets:
  Accumulate  >= 65
  Neutral     35-65
  Distribute  < 35
"""

import pandas as pd
import numpy as np

# -- Weights (must sum to 1.0) -------------------------------------------------
WEIGHTS = {
    "fv":  0.50,   # Fundamental Velocity (combined X + Y axes)
    "mc":  0.25,   # Market Conviction
    "esv": 0.25,   # Earnings Surprise Velocity
}

ACCUMULATE_THRESH = 65
DISTRIBUTE_THRESH = 35

# -- Convergence signal language -----------------------------------------------
CONVERGENCE_LABELS = {
    3: "Full alignment -- all three signals confirming",
    2: "Two of three -- check which signal is diverging",
    1: "Weak alignment -- wait for confirmation",
    0: "No alignment -- do not add",
}


def _rank_normalize(series: pd.Series) -> pd.Series:
    """
    Rank-normalize a series to 0-100 (higher raw value = higher rank).
    NaN values are assigned 50.0 (universe median).
    """
    filled = series.copy()
    nan_mask = filled.isna()
    ranked = filled.rank(method="average", na_option="keep", pct=True) * 100
    ranked[nan_mask] = 50.0
    return ranked


def compute_esv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Earnings Surprise Velocity = average of Rev Surprise Q and EPS Surprise Q.
    If one is missing, use the available one.
    If both missing, mark as NaN (will be assigned median rank).
    """
    df = df.copy()
    df["esv"] = df[["rev_surprise_q", "eps_surprise_q"]].mean(axis=1)
    return df


def compute_alignment(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the 3-signal Compounders Alignment Score (v10.0).
    Requires: earnings_mom_roc (X = Rev Momentum), multiple_roc (Y = EPS Momentum),
              tr_1m, ytd_perf, rev_surprise_q, eps_surprise_q
    """
    df = df.copy()

    # ESV
    df = compute_esv(df)

    # Market Conviction: blended 1M + YTD price momentum
    df["price_mom"] = df[["tr_1m", "ytd_perf"]].mean(axis=1)

    # FV = average of rank-normalized X-axis and Y-axis
    # Both X (revenue momentum) and Y (earnings momentum) must be high for a high FV rank
    x_rank = _rank_normalize(df["earnings_mom_roc"])
    y_rank = _rank_normalize(df["multiple_roc"])
    df["fv_rank"]  = (x_rank + y_rank) / 2

    df["mc_rank"]  = _rank_normalize(df["price_mom"])
    df["esv_rank"] = _rank_normalize(df["esv"])

    # Weighted alignment score (3 signals, no VC)
    df["alignment_score"] = (
        WEIGHTS["fv"]  * df["fv_rank"]  +
        WEIGHTS["mc"]  * df["mc_rank"]  +
        WEIGHTS["esv"] * df["esv_rank"]
    ).round(2)

    # Bucket assignment
    def _bucket(score):
        if pd.isna(score):
            return "Neutral"
        if score >= ACCUMULATE_THRESH:
            return "Accumulate"
        if score < DISTRIBUTE_THRESH:
            return "Distribute"
        return "Neutral"

    df["alignment_bucket"] = df["alignment_score"].apply(_bucket)
    df["alignment_rank"]   = df["alignment_score"].rank(ascending=False, method="min").astype(int)

    # Convergence count (how many of the 3 signals are positive)
    df["convergence_count"] = df.apply(_convergence_count, axis=1)
    df["convergence_label"] = df["convergence_count"].map(CONVERGENCE_LABELS)

    # PEAD Flag
    df["pead_flag"] = df.apply(_pead_flag, axis=1)

    return df


def _convergence_count(row: pd.Series) -> int:
    """Count how many of the 3 signals (FV, MC, ESV) are positive."""
    fv_pos  = (row.get("earnings_mom_roc", 0) or 0) > 0 and (row.get("multiple_roc", 0) or 0) > 0
    mc_pos  = (row.get("price_mom", 0) or 0) > 0
    esv_val = row.get("esv", np.nan)
    esv_pos = not pd.isna(esv_val) and esv_val > 0
    return sum([fv_pos, mc_pos, esv_pos])


def _pead_flag(row: pd.Series) -> str:
    """
    Classify Post-Earnings Announcement Drift setup.
    3 signals: FV (both X and Y positive), MC (price mom positive), ESV (surprise positive)

    Strong PEAD:  all 3 positive + ESV >= 3%
    PEAD Confirm: 2 of 3 positive + ESV >= 0
    PEAD Warn:    2 of 3 positive but ESV < -3%
    Reverse PEAD: most signals weak but ESV >= 3%
    """
    fv_pos     = (row.get("earnings_mom_roc", 0) or 0) > 0 and (row.get("multiple_roc", 0) or 0) > 0
    mc_pos     = (row.get("price_mom", 0) or 0) > 0
    esv_val    = row.get("esv", np.nan)
    esv_pos    = not pd.isna(esv_val) and esv_val > 0
    esv_strong = not pd.isna(esv_val) and esv_val >= 0.03
    esv_weak   = not pd.isna(esv_val) and esv_val <= -0.03

    pos_count = sum([fv_pos, mc_pos, esv_pos])

    if pos_count == 3 and esv_strong:
        return "Strong PEAD"
    if pos_count >= 2 and esv_pos and not esv_weak:
        return "PEAD Confirm"
    if pos_count >= 2 and esv_weak:
        return "PEAD Warn"
    if pos_count <= 1 and esv_strong:
        return "Reverse PEAD"
    return "—"


def alignment_summary(df: pd.DataFrame) -> dict:
    buckets = df["alignment_bucket"].value_counts().to_dict()
    pead    = df["pead_flag"].value_counts().to_dict()
    return {
        "accumulate":   buckets.get("Accumulate", 0),
        "neutral":      buckets.get("Neutral", 0),
        "distribute":   buckets.get("Distribute", 0),
        "strong_pead":  pead.get("Strong PEAD", 0),
        "pead_confirm": pead.get("PEAD Confirm", 0),
        "pead_warn":    pead.get("PEAD Warn", 0),
        "reverse_pead": pead.get("Reverse PEAD", 0),
    }


def print_alignment_report(df: pd.DataFrame, top_n: int = 15):
    s = alignment_summary(df)
    print("\n" + "=" * 65)
    print("  COMPOUNDERS ALIGNMENT SCORE REPORT  v10.0")
    print(f"  Weights: FV {WEIGHTS['fv']:.0%} | MC {WEIGHTS['mc']:.0%} | ESV {WEIGHTS['esv']:.0%}")
    print(f"  (VC removed -- FCF Spread is now a standalone valuation overlay)")
    print("=" * 65)
    print(f"  Accumulate (>={ACCUMULATE_THRESH}):  {s['accumulate']:>4}")
    print(f"  Neutral ({DISTRIBUTE_THRESH}-{ACCUMULATE_THRESH}):      {s['neutral']:>4}")
    print(f"  Distribute (<{DISTRIBUTE_THRESH}):   {s['distribute']:>4}")
    print(f"\n  PEAD Flags: Strong={s['strong_pead']}  Confirm={s['pead_confirm']}  "
          f"Warn={s['pead_warn']}  Reverse={s['reverse_pead']}")

    print(f"\n  TOP {top_n} ACCUMULATE CANDIDATES (sorted by Alignment Score):")
    print("  " + "-" * 60)
    acc = df[df["alignment_bucket"] == "Accumulate"].sort_values(
        "alignment_score", ascending=False
    )
    cols = ["ticker", "quadrant", "alignment_score", "pead_flag",
            "ev_rank", "fv_rank", "mc_rank", "esv_rank", "convergence_count"]
    present = [c for c in cols if c in acc.columns]
    print(acc[present].head(top_n).to_string(index=False))

    print(f"\n  DISTRIBUTE CANDIDATES (trim / review):")
    print("  " + "-" * 60)
    dist = df[df["alignment_bucket"] == "Distribute"].sort_values("alignment_score")
    print(dist[present].head(10).to_string(index=False))
    print("=" * 65 + "\n")


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
        df = compute_alignment(df)
        print_alignment_report(df)
