"""
trade_log.py — Trade logging engine
Integrity Compounders Alpha System v10.0

Handles interactive trade entry, model state auto-population,
journal entry generation, and trade confirmation output.
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engines.database import (
    get_universe, get_conn, log_trade, log_decision,
    get_last_snapshot_date,
)
from engines.screener  import run_gates
from engines.quad      import compute_axes, assign_quadrants
from engines.alignment import compute_alignment
from engines.fcf_flip  import compute_flip_scores
from engines.pods      import assign_pods

ACTIONS      = ["BUY", "ADD", "TRIM", "SELL", "CLOSE"]
SLEEVES      = ["Core Compounders", "Catalyst Momentum",
                "Relative Value Pairs", "High Conviction Speculative"]
TRIGGER_TYPES = [
    "Q1 Confirmation", "Q2 Earnings Resilience Entry", "Momentum Entry",
    "Rebalance / Reweight", "Conviction Add", "Quad Migration",
    "Earnings Catalyst", "Valuation Reset", "Portfolio Construction",
]


# ── Model state lookup ────────────────────────────────────────────────────────

def get_model_state(ticker: str) -> dict:
    """
    Pull and compute current model state for a ticker.
    Returns dict of model fields or empty dict if not found.
    """
    ticker = ticker.upper()
    df = get_universe("all")
    if df.empty:
        return {}

    from engines.screener import run_gates
    df = run_gates(df)
    df = compute_axes(df)
    df = assign_quadrants(df)
    df = assign_pods(df)
    df = compute_alignment(df)
    df = compute_flip_scores(df)

    row = df[df["ticker"] == ticker]
    if row.empty:
        return {}

    r = row.iloc[0]
    return {
        "company":           str(r.get("company", "")),
        "quadrant":          str(r.get("quadrant", "N/A")),
        "quad_provisional":  int(r.get("quad_provisional", 1) or 1),
        "ev_rank":           int(r.get("ev_rank", 99) or 99),
        "alignment_score":   float(r.get("alignment_score", 0) or 0),
        "alignment_bucket":  str(r.get("alignment_bucket", "Neutral")),
        "pead_flag":         str(r.get("pead_flag", "—")),
        "x_axis":            float(r.get("earnings_mom_roc", 0) or 0),
        "y_axis":            float(r.get("multiple_roc", 0) or 0),
        "fcf_spread_tag":    str(r.get("fcf_spread_tag", "—")),
        "convergence_signals": int(r.get("convergence_count", 0) or 0),
        "stock_price":       float(r.get("stock_price", 0) or 0),
    }


# ── Prompt helpers ────────────────────────────────────────────────────────────

def _prompt(label: str, default: str = "", required: bool = False) -> str:
    """Prompt user for input with optional default."""
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"  {label}{suffix}: ").strip()
        if not val and default:
            return default
        if not val and required:
            print(f"    !! Required. Please enter a value.")
            continue
        return val or ""


def _prompt_float(label: str, default: float | None = None) -> float | None:
    suffix = f" [{default}]" if default is not None else " [skip]"
    while True:
        val = input(f"  {label}{suffix}: ").strip()
        if not val and default is not None:
            return default
        if not val:
            return None
        try:
            return float(val.replace(",", "").replace("$", ""))
        except ValueError:
            print("    !! Enter a number (e.g. 48.56)")


def _prompt_choice(label: str, choices: list[str], default: str = "") -> str:
    print(f"\n  {label}:")
    for i, c in enumerate(choices, 1):
        marker = " <-- default" if c == default else ""
        print(f"    {i}) {c}{marker}")
    while True:
        val = input(f"  Enter number or text [{default}]: ").strip()
        if not val and default:
            return default
        try:
            idx = int(val) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError:
            if val.upper() in [c.upper() for c in choices]:
                return val.upper()
        print(f"    !! Enter 1-{len(choices)} or type the value.")


def _prompt_date(label: str, default: str | None = None) -> str:
    today = datetime.today().strftime("%Y-%m-%d")
    default = default or today
    while True:
        val = input(f"  {label} [{default}]: ").strip()
        if not val:
            return default
        try:
            datetime.strptime(val, "%Y-%m-%d")
            return val
        except ValueError:
            print("    !! Format: YYYY-MM-DD")


# ── Interactive entry ─────────────────────────────────────────────────────────

def interactive_log_trade(ticker: str = "", action: str = "",
                           price: float | None = None,
                           shares: float | None = None) -> int | None:
    """
    Walk through all trade fields interactively.
    Pre-fills ticker/action/price/shares if passed from CLI args.
    Returns the new trade_id or None if aborted.
    """
    print("\n" + "=" * 62)
    print("  INTEGRITY COMPOUNDERS — LOG TRADE  v10.0")
    print("=" * 62)

    # ── Core fields ───────────────────────────────────────────────
    if not ticker:
        ticker = _prompt("Ticker", required=True).upper()
    else:
        ticker = ticker.upper()
        print(f"  Ticker: {ticker}")

    # Pull model state
    print(f"\n  [Loading model state for {ticker}...]")
    state = get_model_state(ticker)
    if not state:
        print(f"  !! {ticker} not found in universe. You can still log the trade manually.")

    company = state.get("company", _prompt("Company name"))

    if not action:
        action = _prompt_choice("Action", ACTIONS, default="BUY")
    else:
        action = action.upper()
        print(f"  Action: {action}")

    trade_date = _prompt_date("Trade date")

    if price is None:
        suggested = state.get("stock_price")
        price = _prompt_float("Entry price ($)", default=suggested)
    else:
        print(f"  Price: ${price:,.2f}")

    if shares is None:
        shares = _prompt_float("Shares")
    else:
        print(f"  Shares: {shares:,.4f}")

    dollar_amount = round(price * shares, 2) if price and shares else None
    if dollar_amount:
        print(f"  Dollar amount: ${dollar_amount:,.2f}")

    weight_before = _prompt_float("Weight before trade (% of portfolio)", default=0.0)
    weight_after  = _prompt_float("Weight after trade (% of portfolio)")
    target_weight = _prompt_float("Target weight (%)")
    max_weight    = _prompt_float("Max weight (%)", default=7.0)

    sleeve = _prompt_choice("Sleeve", SLEEVES, default="Core Compounders")

    # ── Model state display + override ───────────────────────────
    print("\n" + "-" * 62)
    print("  MODEL STATE (auto-populated from current screening)")
    print("-" * 62)
    if state:
        print(f"  Quadrant:         {state.get('quadrant')} "
              f"{'[PROVISIONAL]' if state.get('quad_provisional') else '[CONFIRMED]'}")
        print(f"  EV Rank:          {state.get('ev_rank')}")
        print(f"  Alignment Score:  {state.get('alignment_score'):.1f} "
              f"({state.get('alignment_bucket')})")
        print(f"  PEAD Flag:        {state.get('pead_flag')}")
        print(f"  Rev Momentum (X): {state.get('x_axis', 0):+.2f}%")
        print(f"  EPS Momentum (Y): {state.get('y_axis', 0):+.2f}%")
        print(f"  FCF Spread Tag:   {state.get('fcf_spread_tag')}")
        print(f"  Convergence:      {state.get('convergence_signals')}/3 signals")
    else:
        print("  (no model state available — enter manually below)")

    # Allow manual override
    override = input("\n  Override model state? (y/N): ").strip().lower()
    if override == "y":
        state["quadrant"]          = _prompt("Quadrant", default=state.get("quadrant","N/A"))
        state["ev_rank"]           = int(_prompt("EV Rank", default=str(state.get("ev_rank",99))) or 99)
        state["alignment_score"]   = float(_prompt("Alignment Score", default=str(state.get("alignment_score",0))) or 0)
        state["alignment_bucket"]  = _prompt("Bucket", default=state.get("alignment_bucket","Neutral"))
        state["pead_flag"]         = _prompt("PEAD Flag", default=state.get("pead_flag","—"))
        state["convergence_signals"] = int(_prompt("Convergence signals (0-3)", default=str(state.get("convergence_signals",0))) or 0)

    # ── Decision rationale ────────────────────────────────────────
    print("\n" + "-" * 62)
    print("  DECISION RATIONALE")
    print("-" * 62)

    trigger_type = _prompt_choice("Trigger type", TRIGGER_TYPES, default="Q1 Confirmation")
    print()
    why_now   = _prompt("Why now (1-2 sentences)", required=True)
    thesis    = _prompt("Full thesis")
    bear_case = _prompt("Bear case (what breaks the thesis)")

    # ── Trigger prices ────────────────────────────────────────────
    print("\n" + "-" * 62)
    print("  TRIGGER PRICES & REVIEW")
    print("-" * 62)

    add_trigger  = _prompt("Add trigger (price or condition, e.g. '<$45 on any pullback')")
    trim_trigger = _prompt("Trim trigger (price or condition)")
    exit_trigger = _prompt("Exit trigger (hard stop / thesis break condition)")
    quad_flip    = _prompt_float("Quad flip price estimate ($)", default=None)
    default_review = (datetime.today() + timedelta(days=30)).strftime("%Y-%m-%d")
    review_date  = _prompt_date("Next review date", default=default_review)

    # ── Confirm and save ──────────────────────────────────────────
    print("\n" + "=" * 62)
    print(f"  TRADE SUMMARY — {action} {ticker} @ ${price:,.2f} x {shares} shares")
    print("=" * 62)
    print(f"  Date:       {trade_date}")
    print(f"  Amount:     ${dollar_amount:,.2f}" if dollar_amount else "  Amount:     —")
    print(f"  Weight:     {weight_before}% -> {weight_after}% (target {target_weight}%)")
    print(f"  Quad:       {state.get('quadrant')} | Score: {state.get('alignment_score'):.1f} | {state.get('alignment_bucket')}")
    print(f"  PEAD:       {state.get('pead_flag')} | Conv: {state.get('convergence_signals')}/3")
    print(f"  Why now:    {why_now}")
    print(f"  Add at:     {add_trigger or '—'}")
    print(f"  Trim at:    {trim_trigger or '—'}")
    print(f"  Exit if:    {exit_trigger or '—'}")
    print(f"  Review:     {review_date}")

    confirm = input("\n  Save this trade? (Y/n): ").strip().lower()
    if confirm == "n":
        print("  [Aborted — nothing saved.]")
        return None

    record = {
        "logged_at":          datetime.utcnow().isoformat(),
        "trade_date":         trade_date,
        "ticker":             ticker,
        "company":            company,
        "action":             action,
        "shares":             shares,
        "price":              price,
        "dollar_amount":      dollar_amount,
        "weight_before":      weight_before,
        "weight_after":       weight_after,
        "sleeve":             sleeve,
        "quadrant":           state.get("quadrant"),
        "quad_provisional":   state.get("quad_provisional", 1),
        "ev_rank":            state.get("ev_rank"),
        "alignment_score":    state.get("alignment_score"),
        "alignment_bucket":   state.get("alignment_bucket"),
        "pead_flag":          state.get("pead_flag"),
        "x_axis":             state.get("x_axis"),
        "y_axis":             state.get("y_axis"),
        "fcf_spread_tag":     state.get("fcf_spread_tag"),
        "convergence_signals":state.get("convergence_signals"),
        "trigger_type":       trigger_type,
        "why_now":            why_now,
        "thesis":             thesis,
        "bear_case":          bear_case,
        "quad_flip_price":    quad_flip,
        "add_trigger":        add_trigger,
        "trim_trigger":       trim_trigger,
        "exit_trigger":       exit_trigger,
        "target_weight":      target_weight,
        "max_weight":         max_weight,
        "review_date":        review_date,
        "status":             "Open",
    }

    trade_id = log_trade(record)

    # Auto-generate journal entry
    _write_journal_entry(trade_id, record)

    # Print confirmation
    _print_confirmation(trade_id, record)
    return trade_id


def quick_log_trade(ticker: str, action: str, price: float, shares: float,
                    why_now: str, thesis: str = "", bear_case: str = "",
                    trigger_type: str = "Q1 Confirmation",
                    add_trigger: str = "", trim_trigger: str = "",
                    exit_trigger: str = "") -> int:
    """
    Non-interactive log for scripted/test usage.
    Auto-populates all model state fields.
    """
    ticker = ticker.upper()
    action = action.upper()
    state  = get_model_state(ticker)

    dollar_amount  = round(price * shares, 2)
    default_review = (datetime.today() + timedelta(days=30)).strftime("%Y-%m-%d")

    record = {
        "logged_at":          datetime.utcnow().isoformat(),
        "trade_date":         datetime.today().strftime("%Y-%m-%d"),
        "ticker":             ticker,
        "company":            state.get("company", ticker),
        "action":             action,
        "shares":             shares,
        "price":              price,
        "dollar_amount":      dollar_amount,
        "weight_before":      0.0,
        "weight_after":       None,
        "sleeve":             "Core Compounders",
        "quadrant":           state.get("quadrant", "N/A"),
        "quad_provisional":   state.get("quad_provisional", 1),
        "ev_rank":            state.get("ev_rank"),
        "alignment_score":    state.get("alignment_score"),
        "alignment_bucket":   state.get("alignment_bucket"),
        "pead_flag":          state.get("pead_flag"),
        "x_axis":             state.get("x_axis"),
        "y_axis":             state.get("y_axis"),
        "fcf_spread_tag":     state.get("fcf_spread_tag"),
        "convergence_signals":state.get("convergence_signals"),
        "trigger_type":       trigger_type,
        "why_now":            why_now,
        "thesis":             thesis,
        "bear_case":          bear_case,
        "add_trigger":        add_trigger,
        "trim_trigger":       trim_trigger,
        "exit_trigger":       exit_trigger,
        "target_weight":      4.0,
        "max_weight":         7.0,
        "review_date":        default_review,
        "status":             "Open",
    }

    trade_id = log_trade(record)
    _write_journal_entry(trade_id, record)
    _print_confirmation(trade_id, record)
    return trade_id


# ── Journal entry writer ──────────────────────────────────────────────────────

def _write_journal_entry(trade_id: int, record: dict):
    """Write a markdown journal entry to journal/decisions/."""
    journal_dir = ROOT / "journal" / "decisions"
    journal_dir.mkdir(parents=True, exist_ok=True)

    ts    = datetime.now().strftime("%Y-%m-%d %H:%M")
    fname = f"{datetime.today().strftime('%Y-%m-%d')}_{record['ticker']}_{record['action']}.md"
    path  = journal_dir / fname

    x_val = record.get("x_axis") or 0
    y_val = record.get("y_axis") or 0

    content = f"""## [{ts}] — {record['ticker']} — {record['action']}  (Trade ID #{trade_id})

**Company:** {record.get('company','')}
**Action:** {record['action']} {record.get('shares','')} shares @ ${record.get('price',0):,.2f}
**Dollar Amount:** ${record.get('dollar_amount',0):,.2f}
**Date:** {record['trade_date']}
**Sleeve:** {record.get('sleeve','')}

---

### Model State at Entry

| Field | Value |
|-------|-------|
| Quadrant | {record.get('quadrant','—')} {'[PROVISIONAL]' if record.get('quad_provisional') else '[CONFIRMED]'} |
| EV Rank | {record.get('ev_rank','—')} |
| Alignment Score | {f"{record.get('alignment_score') or 0:.1f}" if record.get('alignment_score') is not None else '—'} ({record.get('alignment_bucket','—')}) |
| PEAD Flag | {record.get('pead_flag','—')} |
| Rev Momentum (X) | {x_val:+.2f}% |
| EPS Momentum (Y) | {y_val:+.2f}% |
| FCF Spread Tag | {record.get('fcf_spread_tag','—')} |
| Convergence | {record.get('convergence_signals','—')}/3 signals |

---

### Decision Rationale

**Trigger Type:** {record.get('trigger_type','—')}

**Why Now:**
{record.get('why_now','—')}

**Thesis:**
{record.get('thesis','—')}

**Bear Case:**
{record.get('bear_case','—')}

---

### Position Management

| Field | Value |
|-------|-------|
| Weight Before | {record.get('weight_before',0)}% |
| Weight After | {record.get('weight_after','—')}% |
| Target Weight | {record.get('target_weight','—')}% |
| Max Weight | {record.get('max_weight',7.0)}% |
| Add Trigger | {record.get('add_trigger','—')} |
| Trim Trigger | {record.get('trim_trigger','—')} |
| Exit Trigger | {record.get('exit_trigger','—')} |
| Review Date | {record.get('review_date','—')} |

---
*Auto-generated by Integrity Compounders Alpha System v10.0*
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    # Also log to decision_journal DB table
    log_decision(
        note=f"{record['action']} {record['ticker']} @ ${record.get('price',0):,.2f} — {record.get('why_now','')[:100]}",
        ticker=record["ticker"],
        event_type=f"TRADE_{record['action']}"
    )
    print(f"  [Journal] Entry saved: {path.name}")


# ── Confirmation printer ──────────────────────────────────────────────────────

def _print_confirmation(trade_id: int, record: dict):
    x_pct = record.get("x_axis") or 0
    y_pct = record.get("y_axis") or 0
    print(f"""
{"=" * 62}
  TRADE LOGGED SUCCESSFULLY — ID #{trade_id}
{"=" * 62}
  Ticker      : {record['ticker']} — {record.get('company','')}
  Action      : {record['action']}
  Date        : {record['trade_date']}
  Price       : ${record.get('price',0):,.2f}
  Shares      : {record.get('shares',0):,.4f}
  Amount      : ${record.get('dollar_amount',0):,.2f}
  Sleeve      : {record.get('sleeve','—')}

  MODEL STATE AT ENTRY
  Quadrant    : {record.get('quadrant','—')} {'[PROVISIONAL]' if record.get('quad_provisional') else '[CONFIRMED]'}
  EV Rank     : {record.get('ev_rank','—')}
  Align Score : {f"{record.get('alignment_score') or 0:.1f}" if record.get('alignment_score') is not None else '—'} ({record.get('alignment_bucket','—')})
  PEAD Flag   : {record.get('pead_flag','—')}
  X-Axis      : {x_pct:+.2f}%  |  Y-Axis: {y_pct:+.2f}%
  FCF Tag     : {record.get('fcf_spread_tag','—')}
  Convergence : {record.get('convergence_signals','—')}/3

  RATIONALE
  Trigger     : {record.get('trigger_type','—')}
  Why Now     : {record.get('why_now','—')}

  TRIGGERS
  Add at      : {record.get('add_trigger','—')}
  Trim at     : {record.get('trim_trigger','—')}
  Exit if     : {record.get('exit_trigger','—')}
  Review by   : {record.get('review_date','—')}
{"=" * 62}
""")
