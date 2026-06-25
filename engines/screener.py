"""
screener.py — Quality Indicators (Diagnostic) — Integrity Compounders V12

V12 change (Issues 2, 3, 8): the old "five gates" were eliminatory in name but
non-binding in practice. They are now six DIAGNOSTIC Quality Indicators that
describe a business but do not by themselves exclude a name. Action decisions
come from the Alignment Score and the pillar scores.

Six indicators (each PASS / FAIL / DATA_INCOMPLETE):
  Capital Efficiency      ROIC >= 10%
  Pricing Power           Gross Margin >= 30%      (split out from old margin test)
  Operational Efficiency  Operating Margin >= 15%  (split out from old margin test)
  Cash Conversion         FCF Margin >= 7%         (Fiscal AI CSV → yfinance backup)
  Growth Durability       Revenue 3Y CAGR >= 5%
  Balance Sheet           Net Debt/EBITDA <= 3.0x

Quality Profile: 5-6 pass = FULL_COMPOUNDER, 3-4 = QUALITY_WATCH,
                 1-2 = DEVELOPING, 0 = QUALITY_CONCERN.

Missing data yields DATA_INCOMPLETE for that indicator (never a false FAIL).
Legacy gate_* / gates_pass columns are still emitted as aliases for back-compat.
"""

import pandas as pd
import numpy as np
import json
from datetime import datetime

# ── V12 Quality Indicators (thresholds in PLAIN %, matching stored data) ─────
INDICATORS = {
    "capital_efficiency":     ("roic",            ">=", 10.0),
    "pricing_power":          ("gross_margin",    ">=", 30.0),
    "operational_efficiency": ("op_margin",       ">=", 15.0),
    "cash_conversion":        ("fcf_margin",      ">=",  7.0),
    "growth_durability":      ("rev_3y_cagr",     ">=",  5.0),
    "balance_sheet":          ("net_debt_ebitda", "<=",  3.0),
}

# Legacy gate name → V12 indicator name (for back-compat alias columns)
LEGACY_GATE_ALIASES = {
    "gate_quality":        "capital_efficiency",
    "gate_durability":     "operational_efficiency",
    "gate_cash_conv":      "cash_conversion",
    "gate_reinvestment":   "growth_durability",
    "gate_balance_sheet":  "balance_sheet",
    "gate_pricing_power":  "pricing_power",
}

# Back-compat: some callers still import GATES
GATES = INDICATORS

QUALITY_PROFILE = {
    "FULL_COMPOUNDER":  "5-6 indicators pass",
    "QUALITY_WATCH":    "3-4 indicators pass",
    "DEVELOPING":       "1-2 indicators pass",
    "QUALITY_CONCERN":  "0 indicators pass",
}

PROXY_FLAGS = {}

EPS_CAGR_CAP = 25.0   # cap forward EPS CAGR at 25% (data stored as plain %, e.g. 12.5 = 12.5%)


def _quality_profile(n_pass: int) -> str:
    if n_pass >= 5:
        return "FULL_COMPOUNDER"
    if n_pass >= 3:
        return "QUALITY_WATCH"
    if n_pass >= 1:
        return "DEVELOPING"
    return "QUALITY_CONCERN"


def _eval_gate(series: pd.Series, op: str, threshold: float) -> pd.Series:
    if op == ">=":
        return (series >= threshold).astype(int)
    elif op == "<=":
        return (series <= threshold).astype(int)
    raise ValueError(f"Unknown operator: {op}")


def run_gates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Evaluate the six V12 Quality Indicators (diagnostic, non-eliminatory).

    Adds:
      ind_<name>              1=pass, 0=fail, NaN=DATA_INCOMPLETE  (per indicator)
      indicators_pass         count of passing indicators (0-6)
      quality_profile         FULL_COMPOUNDER / QUALITY_WATCH / DEVELOPING / QUALITY_CONCERN
      data_incomplete_flags   JSON list of indicators with missing data
      watch_flags             JSON list of failing indicators
      universe_status         always 'active' (V12: indicators are diagnostic)
      gate_* / gates_pass     legacy aliases for back-compat
      fwd_eps_cagr_capped     EPS cap (base-effect protection)
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

    # Evaluate each indicator. Missing field/value → DATA_INCOMPLETE (NaN), not FAIL.
    for name, (field, op, thresh) in INDICATORS.items():
        col = f"ind_{name}"
        if field in df.columns:
            series = pd.to_numeric(df[field], errors="coerce")
            present = series.notna()
            result = pd.Series(np.nan, index=df.index, dtype="float")
            if op == ">=":
                result[present] = (series[present] >= thresh).astype(float)
            else:  # "<="
                result[present] = (series[present] <= thresh).astype(float)
            df[col] = result
        else:
            df[col] = np.nan
            print(f"[Indicators] field '{field}' missing — '{name}' = DATA_INCOMPLETE")

    ind_cols = [f"ind_{n}" for n in INDICATORS]
    df["indicators_pass"] = df[ind_cols].apply(lambda r: int((r == 1.0).sum()), axis=1)
    df["quality_profile"] = df["indicators_pass"].apply(_quality_profile)

    def _flags(row, kind):
        out = []
        for n in INDICATORS:
            v = row.get(f"ind_{n}")
            if kind == "fail" and v == 0.0:
                out.append(n)
            elif kind == "incomplete" and (v is None or (isinstance(v, float) and pd.isna(v))):
                out.append(n)
        return json.dumps(out)

    df["watch_flags"]           = df.apply(lambda r: _flags(r, "fail"), axis=1)
    df["data_incomplete_flags"] = df.apply(lambda r: _flags(r, "incomplete"), axis=1)

    # V12: indicators are diagnostic — they never remove a name from the universe.
    df["universe_status"] = "active"

    # ── Legacy aliases (back-compat for callers expecting gate_* / gates_pass) ──
    for legacy_col, ind_name in LEGACY_GATE_ALIASES.items():
        src = f"ind_{ind_name}"
        if src in df.columns:
            df[legacy_col] = (df[src] == 1.0).astype(int)
    df["gates_pass"] = df["indicators_pass"]

    return df


def update_universe_status(current: pd.DataFrame, previous: pd.DataFrame | None) -> pd.DataFrame:
    """
    V12: Quality Indicators are diagnostic, not eliminatory. Names are no longer
    removed from the universe on indicator fails. The quality_profile carries the
    diagnostic signal; exit decisions come from Alignment + pillar scores.

    Retained as a no-op (status stays 'active') for pipeline back-compat.
    """
    current = current.copy()
    current["universe_status"] = "active"
    return current


def screen_summary(df: pd.DataFrame) -> dict:
    """Return a summary dict of V12 quality-indicator results."""
    capped = df[df.get("eps_cagr_was_capped", pd.Series(0, index=df.index)) == 1]

    indicator_pass_rates = {}
    for name in INDICATORS:
        col = f"ind_{name}"
        if col in df.columns:
            valid = df[col].dropna()
            rate = valid.mean() if len(valid) else float("nan")
            indicator_pass_rates[name] = round(rate, 3) if pd.notna(rate) else None

    profile_counts = df["quality_profile"].value_counts().to_dict() if "quality_profile" in df.columns else {}

    summary = {
        "total_names":          len(df),
        "profile_counts":       profile_counts,
        "eps_cagr_capped":      len(capped),
        "indicator_pass_rates": indicator_pass_rates,
        "run_timestamp":        datetime.utcnow().isoformat(),
    }
    return summary


def print_screen_summary(df: pd.DataFrame):
    s = screen_summary(df)
    print("\n" + "=" * 60)
    print("  INTEGRITY COMPOUNDERS — QUALITY INDICATORS (V12, DIAGNOSTIC)")
    print("=" * 60)
    print(f"  Universe scanned:   {s['total_names']:>4}")
    print("\n  Quality profile distribution:")
    for prof in ("FULL_COMPOUNDER", "QUALITY_WATCH", "DEVELOPING", "QUALITY_CONCERN"):
        print(f"    {prof:<18} {s['profile_counts'].get(prof, 0):>4}")
    print(f"\n  EPS CAGR capped:    {s['eps_cagr_capped']:>4}  (>{EPS_CAGR_CAP:.0f}% cap applied)")
    print("\n  Indicator pass rates (of names with data):")
    for name, rate in s["indicator_pass_rates"].items():
        rate_str = f"{rate:.1%}" if rate is not None else " DATA_INCOMPLETE"
        print(f"    {name:<24} {rate_str}")
    print("=" * 60 + "\n")


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
