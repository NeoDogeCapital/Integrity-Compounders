"""
universe_maintenance.py — screen-absence review (DIAGNOSTIC — never removes)

Reports how long each tracked name has been absent from the Fiscal AI screen.
It does NOT deactivate anything. Nothing in this system auto-removes a name:
`engines.screener.update_universe_status` is a deliberate no-op, and per V12 the
Quality Indicators are diagnostic — "Indicators do NOT remove names". This script
follows the same rule, by Niko's decision (2026-07-15): the tracked universe does
not shrink on its own. Surfacing a name is useful; evicting it is not, because
deactivating a name stops its price refresh and strands its history — and a name
out of the screen this month is often back in it the next.

Read the output as a watchlist, not a to-do list. Acting on it is a human call.

STRIKES
A "strike" is absence from one monthly screen. The exports in data/raw/ are the
ground truth of screen membership; ic_signal_rankings.rank_date is the *run*
date, not the screen date (the 07-09 export re-ranked on 07-13 yields two
rank_dates from one screen), so it cannot be used here. Screens are grouped by
calendar month and the latest export in each month is that month's observation —
otherwise two ad-hoc uploads three days apart (06-01, 06-04) would read as two
separate monthly strikes.

Names never seen in an on-disk screen are reported as INSUFFICIENT HISTORY, not
as strikes: the exports only reach back to 2026-05-29, and LEU / PLTR / SEI are
live positions that predate them. Absence of evidence is not evidence of absence.

    python scripts/universe_maintenance.py
    python run.py universe review
"""
import sys
import csv
import glob
import re
import argparse
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
from config.settings import settings

STRIKE_WINDOW = 2   # months of screen history to report against


def monthly_screens(raw_dir: Path = None) -> dict:
    """{YYYY-MM: (screen_date, {tickers})} — the latest export in each month."""
    raw_dir = raw_dir or (ROOT / "data" / "raw")
    by_month = defaultdict(list)
    for f in glob.glob(str(raw_dir / "Screener_Results_*.csv")):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", f)
        if m:
            by_month[m.group(1)[:7]].append((m.group(1), f))
    out = {}
    for month, entries in by_month.items():
        date, path = max(entries)
        with open(path) as fh:
            tk = {(r.get("Ticker") or r.get("ticker") or "").strip().upper()
                  for r in csv.DictReader(fh)} - {""}
        out[month] = (date, tk)
    return dict(sorted(out.items()))


def _holdings() -> set:
    p = ROOT / "data" / "raw" / "portfolio.csv"
    if not p.exists():
        return set()
    with open(p) as f:
        return {r["ticker"].strip().upper() for r in csv.DictReader(f) if r.get("ticker")}


def evaluate() -> dict:
    """Classify tracked names by consecutive monthly screen absence. Read-only."""
    screens = monthly_screens()
    if len(screens) < STRIKE_WINDOW:
        return {"error": f"need {STRIKE_WINDOW} monthly screens, have {len(screens)}"}

    months = list(screens)
    recent = months[-STRIKE_WINDOW:]
    recent_sets = [screens[m][1] for m in recent]
    newest = recent_sets[-1]
    ever = set().union(*(s for _, s in screens.values()))

    conn = psycopg2.connect(settings.DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT ticker, active FROM companies")
    cloud = {r[0].upper(): r[1] for r in cur.fetchall()}
    cur.close(); conn.close()

    held = _holdings()
    two_strike, watch, insufficient, in_screen = [], [], [], []

    for tk in cloud:
        if tk in newest:
            in_screen.append(tk)
            continue
        if tk not in ever:
            insufficient.append(tk)
            continue
        strikes = sum(1 for s in recent_sets if tk not in s)
        (two_strike if strikes >= STRIKE_WINDOW else watch).append(tk)

    ann = lambda ts: sorted(f"{t}★" if t in held else t for t in ts)
    return {"screens": screens, "recent": recent, "in_screen": sorted(in_screen),
            "two_strike": ann(two_strike), "watch": ann(watch),
            "insufficient": ann(insufficient),
            "inactive": sorted(t for t, a in cloud.items() if not a)}


def main():
    ap = argparse.ArgumentParser(description="Screen-absence review (read-only)")
    ap.parse_args()

    res = evaluate()
    if res.get("error"):
        print(f"\n  ⚠️  {res['error']}\n")
        return 1

    print("\n" + "=" * 68)
    print("  UNIVERSE REVIEW — screen absence (diagnostic · nothing is removed)")
    print("=" * 68)
    print("  monthly screens: " + " · ".join(f"{m} ({d}, {len(s)})"
                                             for m, (d, s) in res["screens"].items()))
    print(f"  window:          {' + '.join(res['recent'])}      ★ = we hold it")
    print("-" * 68)
    print(f"  ✅ in newest screen ({len(res['in_screen'])})")
    print(f"  ⚠️  absent {STRIKE_WINDOW}+ months ({len(res['two_strike'])})  — worth a look, still tracked")
    if res["two_strike"]:
        print(f"       {', '.join(res['two_strike'])}")
    print(f"  ·  absent 1 month ({len(res['watch'])})")
    if res["watch"]:
        print(f"       {', '.join(res['watch'])}")
    print(f"  ·  insufficient history ({len(res['insufficient'])})  — never in an on-disk screen")
    if res["insufficient"]:
        print(f"       {', '.join(res['insufficient'])}")
    if res["inactive"]:
        print(f"  ❗ currently inactive ({len(res['inactive'])})  — deactivated by hand at some point")
        print(f"       {', '.join(res['inactive'])}")
    print("-" * 68)
    print("  Read-only. Names are never auto-removed; deactivation is a human decision.")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
