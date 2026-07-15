"""
health_check.py — pipeline health / staleness assertions

Motivation: every serious defect found in this system has been SILENT — an engine
that was never committed, a table nothing writes, a benchmark quietly frozen, a
column that stopped being persisted. Nothing ever asserted "this should be fresh"
or "this should not be null", so the failures only surfaced when someone looked.

This checks the things that have actually broken:
  • price history / benchmark freshness   (SPY was stale 5+ weeks, silently
    corrupting the return series and every factor regression)
  • return-series + analytics freshness   (engine was missing; returns froze)
  • engine outputs populated              (quad went blank on daily runs;
    upsert_universe persisted nothing computed)
  • book in sync across csv / cloud / flags
  • decision-journal fragmentation

    python scripts/health_check.py        (or: python run.py health)
Exit code 1 if any FAIL.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import csv
import sqlite3
import psycopg2
from datetime import date, timedelta
from config.settings import settings

OK, WARN, FAIL = "✅", "⚠️ ", "❌"
_results = []


def _add(status, name, detail):
    _results.append((status, name, detail))


def _age(d):
    if d is None:
        return None
    if hasattr(d, "date"):
        d = d.date()
    return (date.today() - d).days


def _fresh(name, d, warn=4, fail=10, note=""):
    a = _age(d)
    if a is None:
        _add(FAIL, name, "no data")
    elif a > fail:
        _add(FAIL, name, f"{d} — {a}d stale {note}")
    elif a > warn:
        _add(WARN, name, f"{d} — {a}d old {note}")
    else:
        _add(OK, name, f"{d} ({a}d) {note}")


def run():
    c = psycopg2.connect(settings.DATABASE_URL); cur = c.cursor()

    # ── freshness ────────────────────────────────────────────────────────────
    cur.execute("SELECT MAX(price_date) FROM ic_price_history")
    _fresh("price history", cur.fetchone()[0])

    for etf in ("SPY", "QQQ", "MTUM", "QUAL"):
        cur.execute("SELECT MAX(price_date) FROM ic_price_history WHERE ticker=%s", (etf,))
        _fresh(f"benchmark {etf}", cur.fetchone()[0])

    cur.execute("SELECT MAX(data_date) FROM company_market_data")
    _fresh("company_market_data", cur.fetchone()[0])

    cur.execute("SELECT MAX(return_date) FROM ic_daily_returns")
    _fresh("return series", cur.fetchone()[0], warn=4, fail=14)

    cur.execute("SELECT MAX(run_date) FROM ic_analytics_history")
    _fresh("analytics snapshot", cur.fetchone()[0], warn=8, fail=40)

    cur.execute("SELECT MAX(data_date) FROM factor_scores")
    _fresh("factor scores", cur.fetchone()[0])

    # ── engine outputs populated on the latest snapshot ──────────────────────
    # Denominator matters. quad and QGS are computed FROM the Fiscal AI screener
    # CSV, so a tracked name outside the current screen structurally cannot have
    # one — scoring them against all 304 active names reads a permanent 91% and
    # quietly normalises the shortfall, which is how a real engine failure would
    # slip through. Those two are scored against screen membership (reachable
    # 100%); momentum and alignment run off price history / cloud data, so every
    # active name is genuinely in scope for them.
    # Ground truth for "in the current screen" is the screener export itself —
    # not universe_status, which by design also keeps held names active after
    # they drop out of the screen (those genuinely have no quad/QGS inputs and
    # would otherwise read as engine failures).
    try:
        _csvs = sorted((ROOT / "data/raw").glob("Screener_Results_*.csv"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        with open(_csvs[0]) as _f:
            in_screen = {(r.get("Ticker") or r.get("ticker") or "").strip().upper()
                         for r in csv.DictReader(_f)} - {""}
    except Exception:
        in_screen = set()

    cur.execute("""SELECT c.ticker, cmd.quadrant, cmd.trend_status, cmd.alignment_score_v3,
                          cmd.quality_growth_score
        FROM companies c JOIN company_market_data cmd ON cmd.ticker=c.ticker
        AND cmd.data_date=(SELECT MAX(data_date) FROM company_market_data WHERE ticker=c.ticker)
        WHERE c.active=TRUE""")
    rows = cur.fetchall()
    active = len(rows) or 1

    for label, i, scoped in [("quad", 1, True), ("momentum", 2, False),
                             ("alignment v3", 3, False), ("QGS", 4, True)]:
        pool = [r for r in rows if (not scoped or not in_screen or r[0].upper() in in_screen)]
        den  = len(pool) or 1
        n    = sum(1 for r in pool if r[i] is not None)
        pct  = n / den
        st   = OK if pct >= 0.97 else (WARN if pct >= 0.85 else FAIL)
        scope = "in-screen" if scoped and in_screen else "active"
        _add(st, f"{label} populated", f"{n}/{den} {scope} names ({pct:.0%})")

    # ── book in sync ─────────────────────────────────────────────────────────
    book = [r["ticker"].strip().upper() for r in csv.DictReader(open(ROOT / "data/raw/portfolio.csv"))]
    cur.execute("SELECT COUNT(*) FROM companies WHERE in_portfolio=TRUE"); flagged = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT ticker) FROM ic_portfolio_holdings"); held = cur.fetchone()[0]
    if len(book) == flagged == held:
        _add(OK, "book in sync", f"{len(book)} = portfolio.csv = in_portfolio = ic_portfolio_holdings")
    else:
        _add(FAIL, "book in sync", f"portfolio.csv {len(book)} · in_portfolio {flagged} · holdings {held}")

    cur.execute("""SELECT ticker FROM companies WHERE in_portfolio=TRUE""")
    flagged_t = {r[0] for r in cur.fetchall()}
    drift = set(book) ^ flagged_t
    if drift:
        _add(FAIL, "book membership", f"mismatch: {sorted(drift)[:6]}")

    # ── local vs cloud ───────────────────────────────────────────────────────
    try:
        l = sqlite3.connect(ROOT / "data/universe.db"); lc = l.cursor()
        n_local = lc.execute("SELECT COUNT(*) FROM universe WHERE quadrant IS NOT NULL").fetchone()[0]
        tot = lc.execute("SELECT COUNT(*) FROM universe").fetchone()[0] or 1
        st = OK if n_local / tot >= 0.8 else WARN
        _add(st, "local universe computed", f"{n_local}/{tot} rows have quadrant persisted")
        lj = lc.execute("SELECT COUNT(*) FROM decision_journal").fetchone()[0]
        l.close()
        cur.execute("SELECT COUNT(*) FROM ic_decision_journal"); sj = cur.fetchone()[0]
        if lj and sj and abs(lj - sj) > 3:
            _add(WARN, "decision journal", f"local {lj} vs cloud {sj} — entries not fully mirrored")
        else:
            _add(OK, "decision journal", f"local {lj} · cloud {sj}")
    except Exception as e:
        _add(WARN, "local universe.db", str(e)[:50])

    c.close()

    # ── report ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 66)
    print("  INTEGRITY COMPOUNDERS — PIPELINE HEALTH")
    print("=" * 66)
    for st, name, detail in _results:
        print(f"  {st} {name:<26} {detail}")
    nf = sum(1 for s, _, _ in _results if s == FAIL)
    nw = sum(1 for s, _, _ in _results if s == WARN)
    print("-" * 66)
    print(f"  {len(_results)} checks · {nf} failed · {nw} warnings")
    print("=" * 66 + "\n")
    return 1 if nf else 0


if __name__ == "__main__":
    sys.exit(run())
