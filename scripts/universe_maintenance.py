"""
universe_maintenance.py — the two-strike universe removal rule (rulebook §4)

    "One fail = watch-only. Two consecutive monthly fails ... = removed from
     universe."

Until now nothing implemented this: companies.active was 304/304 TRUE and no
code path ever set it FALSE, so "active" carried no information and every
`WHERE active = TRUE` filter really meant "everything we have ever seen".

WHAT COUNTS AS A FAIL
V12 retired the eliminatory five-gate language — Quality Indicators are
explicitly diagnostic and "do NOT remove names". So the fail that matters is
absence from the Fiscal AI screen: the screener defines the universe.

WHAT COUNTS AS A MONTH
The screener exports in data/raw/ are the ground truth of screen membership;
ic_signal_rankings.rank_date is the *run* date, not the screen date (the same
07-09 export ranked again on 07-13 produces two rank_dates from one screen).
Screens are therefore grouped by calendar month and the latest export in each
month is that month's observation — otherwise two ad-hoc uploads three days
apart (06-01, 06-04) would count as two "monthly" strikes and evict a name in
a week.

THREE GUARDS, each load-bearing
  • Holdings are never removed. Deactivating a name we own stops its price
    refresh, which strands the return series and every factor regression — the
    exact failure that froze SPY for five weeks.
  • Names never observed in any on-disk screen have INSUFFICIENT HISTORY and are
    left alone. Absence of evidence is not two strikes: the exports only reach
    back to 2026-05-29, and LEU / PLTR / SEI are live positions that predate
    them.
  • Re-entering the screen reactivates a name, so removal is never a one-way
    door.

Dry run by default; --apply mutates. Removals are journalled (rulebook §12
makes "name added to or removed from universe" a material event).

    python scripts/universe_maintenance.py            # report only
    python scripts/universe_maintenance.py --apply    # apply + journal
    python run.py universe review [--apply]
"""
import sys
import csv
import glob
import re
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
from config.settings import settings

MIN_MONTHS = 2   # rulebook: two consecutive monthly fails


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
    """Classify every tracked name against the two-strike rule."""
    screens = monthly_screens()
    if len(screens) < MIN_MONTHS:
        return {"error": f"need {MIN_MONTHS} monthly screens, have {len(screens)}"}

    months = list(screens)
    recent = months[-MIN_MONTHS:]                     # the two most recent months
    recent_sets = [screens[m][1] for m in recent]
    newest = recent_sets[-1]
    ever = set().union(*(s for _, s in screens.values()))

    conn = psycopg2.connect(settings.DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT ticker, active FROM companies")
    cloud = {r[0].upper(): r[1] for r in cur.fetchall()}
    cur.close(); conn.close()

    held = _holdings()
    remove, watch, reactivate, insufficient, protected = [], [], [], [], []

    for tk, active in cloud.items():
        if tk in newest:
            if not active:
                reactivate.append(tk)                 # back in the screen
            continue
        if tk not in ever:
            insufficient.append(tk)                   # never observed — no evidence
            continue
        strikes = sum(1 for s in recent_sets if tk not in s)
        if strikes >= MIN_MONTHS:
            (protected if tk in held else remove).append(tk)
        else:
            watch.append(tk)                          # one strike — watch only

    return {"screens": screens, "recent": recent, "remove": sorted(remove),
            "watch": sorted(watch), "reactivate": sorted(reactivate),
            "insufficient": sorted(insufficient), "protected": sorted(protected)}


def apply_changes(res: dict) -> None:
    """Set companies.active / universe_status and journal each removal."""
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    for tk in res["remove"]:
        cur.execute("UPDATE companies SET active = FALSE WHERE ticker = %s", (tk,))
    for tk in res["reactivate"]:
        cur.execute("UPDATE companies SET active = TRUE WHERE ticker = %s", (tk,))
    cur.close(); conn.close()

    db = ROOT / "data" / "universe.db"
    if db.exists():
        l = sqlite3.connect(db)
        for tk in res["remove"]:
            l.execute("UPDATE universe SET universe_status='inactive' WHERE ticker=?", (tk,))
        for tk in res["reactivate"]:
            l.execute("UPDATE universe SET universe_status='active' WHERE ticker=?", (tk,))
        l.commit(); l.close()

    if res["remove"]:
        from engines.database import log_decision
        last = res["screens"][res["recent"][-1]][0]
        for tk in res["remove"]:
            log_decision(
                note=(f"UNIVERSE REMOVAL — {tk} absent from the last {MIN_MONTHS} monthly "
                      f"screens ({', '.join(res['recent'])}); rulebook §4 two-strike rule. "
                      f"Latest screen {last}. Not held. Re-entry reactivates."),
                ticker=tk, event_type="UNIVERSE_REMOVAL",
            )
        from engines.supabase_sync import sync_trade_tables_to_supabase
        sync_trade_tables_to_supabase()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="apply changes (default: dry run)")
    a = ap.parse_args()

    res = evaluate()
    if res.get("error"):
        print(f"\n  ⚠️  {res['error']}\n")
        return 1

    print("\n" + "=" * 66)
    print(f"  UNIVERSE REVIEW — two-strike rule ({'APPLY' if a.apply else 'DRY RUN'})")
    print("=" * 66)
    print("  monthly screens: " + " · ".join(f"{m} ({d}, {len(s)})"
                                             for m, (d, s) in res["screens"].items()))
    print(f"  strike window:   {' + '.join(res['recent'])}")
    print("-" * 66)
    print(f"  ❌ REMOVE ({len(res['remove'])})       absent from both monthly screens")
    for t in res["remove"]:
        print(f"       {t}")
    print(f"  ⚠️  WATCH ({len(res['watch'])})        one strike — stay active")
    if res["watch"]:
        print(f"       {', '.join(res['watch'])}")
    if res["protected"]:
        print(f"  ★  HELD, EXEMPT ({len(res['protected'])})  two strikes but we own them")
        print(f"       {', '.join(res['protected'])}")
    if res["reactivate"]:
        print(f"  ✅ REACTIVATE ({len(res['reactivate'])})   back in the newest screen")
        print(f"       {', '.join(res['reactivate'])}")
    print(f"  ·  insufficient history ({len(res['insufficient'])})  never in an on-disk screen — untouched")
    if res["insufficient"]:
        print(f"       {', '.join(res['insufficient'])}")
    print("-" * 66)

    if a.apply:
        apply_changes(res)
        print(f"  Applied: {len(res['remove'])} removed, {len(res['reactivate'])} reactivated.")
    else:
        print("  Dry run — nothing changed. Re-run with --apply to commit.")
    print("=" * 66 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
