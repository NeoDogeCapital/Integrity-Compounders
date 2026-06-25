"""
alignment.py — Self-Computed Alignment Score (V12)
Integrity Compounders Alpha System V12

V12 (Issues 4, 5, 6): the three component ranks are no longer pre-computed
black-box values from Fiscal AI. They are self-computed from transparent,
reproducible inputs and owned by us.

  FV Rank  (40%) — QGS percentile within universe (quality-growth-valuation).
                   QGS already folds in growth, FCF/EV valuation, ROIC, FCF margin.
  MC Rank  (25%) — weighted price-momentum percentile (momentum confirmation):
                     1M x15% + 3M x25% + 6M x30% + 12M x30%
  ESV Rank (35%) — earnings-surprise composite (absorbs the old standalone PEAD):
                     beat rate x35% + rev surprise x25% + eps surprise x25%
                     + PEAD drift proxy x15%

Alignment = FV x0.40 + MC x0.25 + ESV x0.35   (each rank 0-100)

Buckets:
  ACCUMULATE  >= 65
  HOLD        35-64
  DISTRIBUTE  < 35

Falls back gracefully when enriched columns (QGS, momentum_*) are absent.
"""

import pandas as pd
import numpy as np

# -- Top-level component weights (must sum to 1.0) -----------------------------
WEIGHTS = {
    "fv":  0.40,   # Fundamental Velocity = QGS percentile
    "mc":  0.25,   # Market Conviction = weighted momentum percentile
    "esv": 0.35,   # Earnings Surprise Velocity composite
}

# -- MC sub-weights (weighted momentum percentile) -----------------------------
MC_WEIGHTS = {"momentum_1m": 0.15, "momentum_3m": 0.25,
              "momentum_6m": 0.30, "momentum_12m": 0.30}

# -- ESV sub-weights -----------------------------------------------------------
ESV_WEIGHTS = {"beat_rate": 0.35, "rev_surprise": 0.25,
               "eps_surprise": 0.25, "pead_drift": 0.15}

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


def _weighted_momentum(df: pd.DataFrame) -> pd.Series:
    """Weighted composite of available momentum columns (1M/3M/6M/12M).
    Falls back to (tr_1m, ytd_perf) blend if no momentum_* columns are present."""
    avail = {c: w for c, w in MC_WEIGHTS.items() if c in df.columns}
    if avail:
        wsum = sum(avail.values())
        comp = pd.Series(0.0, index=df.index)
        weight_present = pd.Series(0.0, index=df.index)
        for c, w in avail.items():
            s = pd.to_numeric(df[c], errors="coerce")
            comp = comp.add(s.fillna(0) * w, fill_value=0)
            weight_present = weight_present.add(s.notna().astype(float) * w, fill_value=0)
        # normalize by present weight so partially-missing names aren't deflated
        comp = comp / weight_present.replace(0, np.nan)
        return comp
    # Fallback: legacy price momentum
    cols = [c for c in ("tr_1m", "ytd_perf") if c in df.columns]
    return df[cols].mean(axis=1) if cols else pd.Series(np.nan, index=df.index)


def compute_esv(df: pd.DataFrame) -> pd.DataFrame:
    """
    V12 Earnings Surprise Velocity composite (absorbs standalone PEAD).
      beat rate     35% — share of rev/eps surprises that are positive
      rev surprise  25% — rank of revenue surprise magnitude
      eps surprise  25% — rank of EPS surprise magnitude
      PEAD drift    15% — rank of post-earnings price drift proxy (momentum_1m / tr_1m)
    Returns df with an 'esv' composite column (0-1 scale before rank-normalize).
    """
    df = df.copy()
    rev = pd.to_numeric(df.get("rev_surprise_q"), errors="coerce") if "rev_surprise_q" in df.columns else pd.Series(np.nan, index=df.index)
    eps = pd.to_numeric(df.get("eps_surprise_q"), errors="coerce") if "eps_surprise_q" in df.columns else pd.Series(np.nan, index=df.index)

    beat = ((rev > 0).astype(float) + (eps > 0).astype(float)) / 2.0

    rev_pct = _rank_normalize(rev) / 100.0
    eps_pct = _rank_normalize(eps) / 100.0

    # PEAD drift proxy: most-recent-month drift after the print
    if "momentum_1m" in df.columns:
        drift = pd.to_numeric(df["momentum_1m"], errors="coerce")
    elif "tr_1m" in df.columns:
        drift = pd.to_numeric(df["tr_1m"], errors="coerce")
    else:
        drift = pd.Series(np.nan, index=df.index)
    drift_pct = _rank_normalize(drift) / 100.0

    df["esv"] = (
        ESV_WEIGHTS["beat_rate"]    * beat +
        ESV_WEIGHTS["rev_surprise"] * rev_pct +
        ESV_WEIGHTS["eps_surprise"] * eps_pct +
        ESV_WEIGHTS["pead_drift"]   * drift_pct
    )
    return df


def compute_alignment(df: pd.DataFrame) -> pd.DataFrame:
    """
    V12 self-computed Alignment Score.
      FV  = QGS percentile (fallback: X/Y axis rank average)
      MC  = weighted momentum percentile
      ESV = earnings-surprise composite percentile
    Alignment = FV x0.40 + MC x0.25 + ESV x0.35
    """
    df = df.copy()

    # ── FV: QGS percentile ────────────────────────────────────────────────
    if "quality_growth_score" in df.columns and df["quality_growth_score"].notna().any():
        df["fv_rank"] = _rank_normalize(pd.to_numeric(df["quality_growth_score"], errors="coerce"))
        df["fv_source"] = "qgs"
    else:
        # Fallback to V11 fundamental velocity (X/Y axis rank average)
        x_rank = _rank_normalize(df.get("earnings_mom_roc"))
        y_rank = _rank_normalize(df.get("multiple_roc"))
        df["fv_rank"] = (x_rank + y_rank) / 2
        df["fv_source"] = "axis_fallback"

    # ── MC: weighted momentum percentile ─────────────────────────────────
    df["price_mom"] = _weighted_momentum(df)
    df["mc_rank"]   = _rank_normalize(df["price_mom"])

    # ── ESV: earnings-surprise composite percentile ──────────────────────
    df = compute_esv(df)
    df["esv_rank"] = _rank_normalize(df["esv"])

    # ── Weighted alignment score ─────────────────────────────────────────
    df["alignment_score"] = (
        WEIGHTS["fv"]  * df["fv_rank"]  +
        WEIGHTS["mc"]  * df["mc_rank"]  +
        WEIGHTS["esv"] * df["esv_rank"]
    ).round(2)

    def _bucket(score):
        if pd.isna(score):
            return "HOLD"
        if score >= ACCUMULATE_THRESH:
            return "ACCUMULATE"
        if score < DISTRIBUTE_THRESH:
            return "DISTRIBUTE"
        return "HOLD"

    df["alignment_bucket"] = df["alignment_score"].apply(_bucket)
    df["alignment_rank"]   = df["alignment_score"].rank(ascending=False, method="min").astype(int)

    # V12 canonical aliases (dashboards read *_v2)
    df["alignment_score_v2"]  = df["alignment_score"]
    df["alignment_bucket_v2"] = df["alignment_bucket"]
    df["fv_rank_v2"]  = df["fv_rank"]
    df["mc_rank_v2"]  = df["mc_rank"]
    df["esv_rank_v2"] = df["esv_rank"]

    # Convergence count (FV, MC, ESV all above median)
    df["convergence_count"] = (
        (df["fv_rank"] >= 50).astype(int) +
        (df["mc_rank"] >= 50).astype(int) +
        (df["esv_rank"] >= 50).astype(int)
    )
    df["convergence_label"] = df["convergence_count"].map(CONVERGENCE_LABELS)

    # PEAD now lives inside ESV; retain a derived flag for back-compat displays
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
    V12: PEAD is absorbed into ESV Rank. This derived label is a back-compat
    display only, read off the ESV percentile and momentum confirmation.
      Strong PEAD  — ESV rank >= 80 and momentum confirming (mc_rank >= 50)
      PEAD Confirm — ESV rank >= 65
      PEAD Warn    — ESV rank >= 65 but momentum diverging (mc_rank < 35)
      Reverse PEAD — ESV rank <= 20
    """
    esv_r = row.get("esv_rank", np.nan)
    mc_r  = row.get("mc_rank", np.nan)
    if pd.isna(esv_r):
        return "—"
    if esv_r >= 80 and (not pd.isna(mc_r) and mc_r >= 50):
        return "Strong PEAD"
    if esv_r >= 65 and (not pd.isna(mc_r) and mc_r < 35):
        return "PEAD Warn"
    if esv_r >= 65:
        return "PEAD Confirm"
    if esv_r <= 20:
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
