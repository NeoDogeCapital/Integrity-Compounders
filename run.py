"""
run.py — Integrity Compounders Alpha System v10.0
Main entry point and plain-English command dispatcher.

Usage:
    python run.py update                          *** FULL 5-LAYER REFRESH *** Upload a screener,
                                                  run this. Runs all layers, syncs Supabase,
                                                  scores all companies, logs every change.
    python run.py refresh                         Load newest CSV from data/raw/, recompute all
    python run.py quad snapshot                   Current quadrant distribution + top names
    python run.py q1 list                         Q1 Full Compounders sorted by Alignment Score
    python run.py q2 list                         Q2 Earnings Resilience sorted by Alignment Score
    python run.py q3 watch                        Q3 Margin Compression names (flag for review)
    python run.py flip screen                     FCF Yield Flip top 20
    python run.py alignment report                Full Alignment Score table
    python run.py weekly report                   HTML report: scatter + alignment + migrations
    python run.py q1q2 report                     Focused Q1+Q2 HTML report
    python run.py monthly rebalance               Monthly rebalance memo with trade summary
    python run.py migration log                   All quad migrations since last snapshot
    python run.py watch                                   Watch Clippings/ + PDFs/ — auto-analyze on drop
    python run.py analyze PATH [TICKER]                   Analyze a PDF or chart image with Claude vision
    python run.py load portfolio                           Load portfolio.csv, enrich + save
    python run.py portfolio                               Print portfolio status to terminal
    python run.py portfolio snapshot                      Full snapshot: CSV + HTML memo + journal
    python run.py log trade [TICKER ACTION PRICE SHARES]  Log a trade (interactive if no args)
    python run.py trade log                       Generate trade log HTML report
    python run.py journal [note]                  Log a decision note
    python run.py audit                           Compare current vs last month
    python run.py who is [TICKER]                 Full factor card for one name
    python run.py status                          Quick health check
"""

import sys
import os
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from pathlib import Path
from datetime import datetime

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from engines.database import (
    init_db, load_csv, upsert_universe, get_universe,
    get_last_snapshot_date, log_decision, save_quad_history,
    log_migration, get_conn,
)
from engines.trade_log import interactive_log_trade, quick_log_trade
from engines.portfolio import cmd_load_portfolio, cmd_portfolio_status, cmd_portfolio_snapshot
from engines.screener  import run_gates, print_screen_summary, update_universe_status
from engines.quad      import (compute_axes, assign_quadrants, compute_migrations,
                                print_quad_distribution, top_by_quad, dangerous_migrations)
from engines.alignment import compute_alignment, print_alignment_report
from engines.fcf_flip  import compute_flip_scores, print_flip_screen

import pandas as pd


# ── Full pipeline (V12) ───────────────────────────────────────────────────────
# Order: quality indicators → quad + contamination flags → signals (enriched on
# pull) → alignment → flip. POD retired in V12 (replaced by quality_profile).

def run_full_pipeline(df_raw: pd.DataFrame, previous: pd.DataFrame | None = None) -> pd.DataFrame:
    """Execute all engines in dependency order and return enriched DataFrame."""
    df = run_gates(df_raw)                       # V12 diagnostic Quality Indicators
    df = update_universe_status(df, previous)
    df = compute_axes(df)
    df = assign_quadrants(df)                     # includes earnings-quality contamination flag
    df = compute_migrations(df, previous)
    df = compute_alignment(df)                    # V12 self-computed alignment
    df = compute_flip_scores(df)
    df["last_updated"] = datetime.utcnow().isoformat()
    return df


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_status():
    last = get_last_snapshot_date()
    df = get_universe(status="all")
    if df.empty:
        print("\n[Status] Universe is EMPTY. Drop a Fiscal AI CSV into data/raw/ and run `refresh`.\n")
        return
    counts = df["quadrant"].value_counts().to_dict() if "quadrant" in df.columns else {}
    print(f"""
╔══════════════════════════════════════════════════════╗
║   INTEGRITY COMPOUNDERS — SYSTEM STATUS              ║
╠══════════════════════════════════════════════════════╣
║   Last data date:   {str(last):<33}║
║   Universe size:    {len(df):<33}║
║   Q2 (Best):        {counts.get('Q2', 0):<33}║
║   Q1 (Good):        {counts.get('Q1', 0):<33}║
║   Q4 (Reset):       {counts.get('Q4', 0):<33}║
║   Q3 (Danger):      {counts.get('Q3', 0):<33}║
╚══════════════════════════════════════════════════════╝
""")


def cmd_refresh():
    """Load newest CSV from data/raw/, run full pipeline, persist to DB."""
    raw_dir = ROOT / "data" / "raw"
    csvs = sorted(raw_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not csvs:
        print(f"[Refresh] No CSV found in {raw_dir}/")
        print("  Drop a Fiscal AI screener export (26 columns, v9 format) there and rerun.")
        return

    latest = csvs[0]
    print(f"[Refresh] Loading: {latest.name}")

    previous = get_universe()
    if previous.empty:
        previous = None

    df_raw = load_csv(latest)

    # V12: pull QGS (and fcf_ev_yield) from Supabase so Alignment FV = QGS percentile.
    # data_updater computes QGS into company_market_data; merge the latest per ticker.
    try:
        import psycopg2
        from config.settings import settings
        pg = psycopg2.connect(settings.DATABASE_URL)
        qgs_df = pd.read_sql("""
            SELECT DISTINCT ON (ticker) ticker, quality_growth_score, fcf_ev_yield
            FROM company_market_data
            WHERE quality_growth_score IS NOT NULL
            ORDER BY ticker, data_date DESC
        """, pg)
        pg.close()
        if not qgs_df.empty:
            qgs_df["ticker"] = qgs_df["ticker"].str.upper()
            df_raw = df_raw.merge(qgs_df, on="ticker", how="left")
            print(f"[Refresh] Merged QGS for {qgs_df['quality_growth_score'].notna().sum()} names (Alignment FV = QGS pct)")
    except Exception as e:
        print(f"[Refresh] QGS merge skipped (FV falls back to axis rank): {e}")

    df = run_full_pipeline(df_raw, previous)

    # Detect and log migrations
    data_date = df["data_date"].iloc[0]
    if "migration_severity" in df.columns and previous is not None:
        migs = df[df["migration_severity"].notna()]
        for _, r in migs.iterrows():
            log_migration(
                ticker=r["ticker"], company=r.get("company",""),
                from_quad=r.get("from_quad",""), to_quad=r["quadrant"],
                severity=r["migration_severity"].split("—")[0].strip(),
                alignment_score=r.get("alignment_score", 0),
                pead_flag=r.get("pead_flag", ""),
                x_delta=r.get("earnings_mom_roc", 0),
                y_delta=r.get("multiple_roc", 0),
                data_date=data_date,
            )
            # Auto-journal DANGEROUS migrations
            if "DANGEROUS" in str(r.get("migration_severity", "")):
                log_decision(
                    note=f"AUTO: DANGEROUS migration {r.get('from_quad','')} → {r['quadrant']} | "
                         f"Alignment: {r.get('alignment_score',0):.1f} | PEAD: {r.get('pead_flag','')}",
                    ticker=r["ticker"],
                    event_type="dangerous_migration",
                )

    upsert_universe(df)
    save_quad_history(df, data_date)
    print_screen_summary(df)
    print_quad_distribution(df)

    # ── Sync to Supabase (non-fatal) ──────────────────────────────────────────
    try:
        from engines.supabase_sync import sync_universe_to_supabase, pull_enriched_to_local
        sync_universe_to_supabase(df, data_date)
        pull_enriched_to_local(data_date)
    except Exception as e:
        print(f"[Supabase] Sync skipped: {e}")

    # Highlight dangerous migrations immediately
    danger = dangerous_migrations(df)
    if not danger.empty:
        print(f"\n  ⚠️  {len(danger)} DANGEROUS MIGRATION(S) DETECTED — IMMEDIATE REVIEW REQUIRED:\n")
        print(danger.to_string(index=False))
        print()


def cmd_quad_snapshot():
    df = get_universe(status="all")
    if df.empty:
        print("[Error] Universe empty. Run `refresh` first."); return
    df = run_full_pipeline(df)
    print_quad_distribution(df)
    for q in ["Q2", "Q1", "Q4", "Q3"]:
        top = top_by_quad(df, q, n=5)
        if not top.empty:
            print(f"  Top 5 {q} by Alignment Score:")
            print(top.to_string(index=False))
            print()


def cmd_q2_list():
    df = get_universe(status="all")
    if df.empty:
        print("[Error] Universe empty. Run `refresh` first."); return
    df = run_full_pipeline(df)
    q2 = df[df["quadrant"] == "Q2"].sort_values("alignment_score", ascending=False)
    cols = ["ticker", "company", "industry", "alignment_score", "alignment_bucket",
            "pead_flag", "ev_rank", "earnings_mom_roc", "multiple_roc",
            "flip_setup_type", "flip_score_pct", "stock_price"]
    present = [c for c in cols if c in q2.columns]
    print(f"\n  Q2 HIDDEN VALUE / GARP — {len(q2)} names (sorted by Alignment Score)\n")
    print(q2[present].to_string(index=False))
    strong = q2[q2["pead_flag"] == "Strong PEAD"]
    if not strong.empty:
        print(f"\n  ★ Strong PEAD in Q2: {', '.join(strong['ticker'].tolist())}")
    print()


def cmd_q3_watch():
    df = get_universe(status="all")
    if df.empty:
        print("[Error] Universe empty. Run `refresh` first."); return
    df = run_full_pipeline(df)
    q3 = df[df["quadrant"] == "Q3"].sort_values("alignment_score")
    cols = ["ticker", "company", "alignment_score", "alignment_bucket",
            "pead_flag", "migration_severity", "earnings_mom_roc", "multiple_roc",
            "ev_rank", "stock_price"]
    present = [c for c in cols if c in q3.columns]
    print(f"\n  ⚠️  Q3 NARRATIVE RALLY — {len(q3)} names (EV Rank 4 — WORST)\n")
    print(q3[present].to_string(index=False))
    print("\n  ACTION: Do NOT add to any Q3 name. Review any held Q3 positions for exit.\n")


def cmd_flip_screen():
    df = get_universe(status="all")
    if df.empty:
        print("[Error] Universe empty. Run `refresh` first."); return
    df = run_full_pipeline(df)
    print_flip_screen(df)


def cmd_alignment_report():
    df = get_universe(status="all")
    if df.empty:
        print("[Error] Universe empty. Run `refresh` first."); return
    df = run_full_pipeline(df)
    print_alignment_report(df)


def cmd_migration_log(n: int = 30):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT logged_at, ticker, company, from_quad, to_quad,
                      severity, alignment_score, pead_flag, note
               FROM migration_log
               ORDER BY logged_at DESC LIMIT ?""", [n]
        ).fetchall()
    if not rows:
        print("[Migration Log] No migrations recorded yet.")
        return
    print(f"\n  MIGRATION LOG (last {n} events)\n")
    print(f"  {'Date':<12} {'Ticker':<7} {'From':<4} {'To':<4} {'Severity':<14} {'Align':>6}  {'PEAD'}")
    print("  " + "─" * 70)
    for r in rows:
        sev = str(r["severity"])[:13]
        print(f"  {r['logged_at'][:10]:<12} {r['ticker']:<7} {str(r['from_quad']):<4} "
              f"{str(r['to_quad']):<4} {sev:<14} {r['alignment_score']:>6.1f}  {r['pead_flag']}")
    print()


def cmd_journal(note: str):
    log_decision(note, event_type="manual")
    print(f"[Journal] ✓ Logged: {note}")


def cmd_who_is(ticker: str):
    ticker = ticker.upper()
    df = get_universe(status="all")
    if df.empty:
        print("[Error] Universe empty. Run `refresh` first."); return
    df = run_full_pipeline(df)
    row = df[df["ticker"] == ticker]
    if row.empty:
        print(f"[Who Is] {ticker} not found in universe.")
        return

    r = row.iloc[0]
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  FACTOR CARD: {ticker:<47}║
╠══════════════════════════════════════════════════════════════╣
║  {r.get('company',''):<60}║
║  {r.get('industry',''):<60}║
╠══════════════════════════════════════════════════════════════╣
║  QUADRANT:    {str(r.get('quadrant','')):<10}  FCF/EV Rank: {str(r.get('fcf_ev_rank','') if r.get('fcf_ev_rank') is not None else '—'):<6}  Profile: {str(r.get('quality_profile','—')):<16}║
║  X-Axis (Rev Momentum):     {r.get('earnings_mom_roc', float('nan')):>+8.3f}                     ║
║  Y-Axis (EPS Momentum):     {r.get('multiple_roc', float('nan')):>+8.3f}                     ║
║  Earnings Quality: {str(r.get('earnings_quality_flag','—')):<43}║
╠══════════════════════════════════════════════════════════════╣
║  Alignment Score: {r.get('alignment_score', 0):>5.1f}   Bucket: {str(r.get('alignment_bucket','')):<12}              ║
║  FV {r.get('fv_rank', float('nan')):>4.0f}  MC {r.get('mc_rank', float('nan')):>4.0f}  ESV {r.get('esv_rank', float('nan')):>4.0f}   (40/25/35)                  ║
║  Flip Score: {r.get('flip_score_pct', 0):>5.1f}    Setup: {str(r.get('flip_setup_type','')):<35}║
╠══════════════════════════════════════════════════════════════╣
║  QUALITY INDICATORS (V12 · diagnostic)                      ║
║  Capital Eff  (ROIC ≥10%):    {str(r.get('roic', float('nan')))[:6]:<8} {'PASS' if r.get('ind_capital_efficiency')==1 else 'fail' if r.get('ind_capital_efficiency')==0 else 'n/a '}          ║
║  Pricing Pwr  (GM ≥30%):      {str(r.get('gross_margin', float('nan')))[:6]:<8} {'PASS' if r.get('ind_pricing_power')==1 else 'fail' if r.get('ind_pricing_power')==0 else 'n/a '}          ║
║  Operational  (OpMgn ≥15%):   {str(r.get('op_margin', float('nan')))[:6]:<8} {'PASS' if r.get('ind_operational_efficiency')==1 else 'fail' if r.get('ind_operational_efficiency')==0 else 'n/a '}          ║
║  Cash Conv    (FCF Mgn ≥7%):  {str(r.get('fcf_margin', float('nan')))[:6]:<8} {'PASS' if r.get('ind_cash_conversion')==1 else 'fail' if r.get('ind_cash_conversion')==0 else 'n/a '}          ║
║  Growth Dur   (Rev CAGR ≥5%): {str(r.get('rev_3y_cagr', float('nan')))[:6]:<8} {'PASS' if r.get('ind_growth_durability')==1 else 'fail' if r.get('ind_growth_durability')==0 else 'n/a '}          ║
║  Bal Sheet    (ND/EBITDA ≤3): {str(r.get('net_debt_ebitda', float('nan')))[:6]:<8} {'PASS' if r.get('ind_balance_sheet')==1 else 'fail' if r.get('ind_balance_sheet')==0 else 'n/a '}          ║
║  Profile: {str(r.get('quality_profile','')):<8} ({int(r.get('indicators_pass',0))}/6 pass)                              ║
╠══════════════════════════════════════════════════════════════╣
║  Stock Price:  ${r.get('stock_price', 0):>8.2f}    Market Cap: ${r.get('market_cap', 0):>10,.0f}M      ║
║  FCF Margin:  {r.get('fcf_margin_trailing', r.get('fcf_margin', float('nan'))):>6.1f}%    FCF Yield:     {r.get('fcf_yield', float('nan')):>6.1f}%              ║
║  Rev 3Y CAGR: {r.get('rev_3y_cagr', float('nan')):>6.1f}%    Fwd Rev CAGR:  {r.get('fwd_rev_cagr', float('nan')):>6.1f}%              ║
║  EPS 3Y CAGR: {r.get('eps_3y_cagr', float('nan')):>6.1f}%    Fwd EPS CAGR:  {r.get('fwd_eps_cagr', float('nan')):>6.1f}%              ║
║  ROIC:        {r.get('roic', float('nan')):>6.1f}%    Beta:          {r.get('beta', float('nan')):>7.2f}              ║
║  Rev Surp Q:  {r.get('rev_surprise_q', float('nan')):>+6.1f}%    EPS Surp Q:    {r.get('eps_surprise_q', float('nan')):>+6.1f}%              ║
╚══════════════════════════════════════════════════════════════╝
""")


def cmd_audit():
    """Compare current universe to prior snapshot — additions, removals, migrations."""
    with get_conn() as conn:
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT data_date FROM quad_history ORDER BY data_date DESC LIMIT 2"
        ).fetchall()]

    if len(dates) < 2:
        print("[Audit] Need at least 2 snapshots. Run `refresh` again after next month's data.")
        return

    curr_date, prev_date = dates[0], dates[1]
    with get_conn() as conn:
        curr = pd.read_sql(
            "SELECT * FROM quad_history WHERE data_date = ?", conn, params=[curr_date])
        prev = pd.read_sql(
            "SELECT * FROM quad_history WHERE data_date = ?", conn, params=[prev_date])

    curr_tickers = set(curr["ticker"])
    prev_tickers = set(prev["ticker"])
    added   = curr_tickers - prev_tickers
    removed = prev_tickers - curr_tickers

    print(f"\n  AUDIT: {prev_date} → {curr_date}")
    print(f"  Added to universe:   {len(added)}  {sorted(added)}")
    print(f"  Removed from universe: {len(removed)}  {sorted(removed)}")

    # Quad migrations
    merged = curr.merge(prev[["ticker","quadrant"]], on="ticker", suffixes=("_curr","_prev"))
    changed = merged[merged["quadrant_curr"] != merged["quadrant_prev"]]
    print(f"\n  Quad migrations: {len(changed)}")
    if not changed.empty:
        for _, r in changed.iterrows():
            print(f"    {r['ticker']:<7} {r['quadrant_prev']} → {r['quadrant_curr']}")
    print()


# ── Full 5-layer update ───────────────────────────────────────────────────────

def cmd_full_update():
    """
    Run all 5 IC layers in order, sync to Supabase, score everything,
    detect changes vs prior snapshot, log to journal.

    Layer 1 — Quality Indicators     (via refresh)
    Layer 2 — Quad + contamination   (via refresh)
    Layer 3 — Alignment Score (V12)  (via refresh)
    Layer 4 — Pillar Scores          (company_scorer --review-all)
    + Supabase sync                  (automatic in refresh)
    + Change detection + journal     (this function)
    (POD retired in V12 — replaced by quality_profile + factor model)
    """
    import subprocess, json
    from pathlib import Path as P
    from datetime import datetime as dt

    RUN_TS  = dt.now().strftime("%Y-%m-%d %H:%M")
    SEP     = "=" * 62

    print(f"\n{SEP}")
    print(f"  INTEGRITY COMPOUNDERS — FULL 5-LAYER UPDATE")
    print(f"  {RUN_TS}")
    print(f"{SEP}\n")

    # ── Snapshot BEFORE ────────────────────────────────────────────────────────
    df_before = get_universe("all")
    before_quads   = df_before.set_index("ticker")["quadrant"].to_dict()       if not df_before.empty else {}
    before_buckets = df_before.set_index("ticker")["alignment_bucket"].to_dict() if not df_before.empty else {}
    before_tickers = set(df_before["ticker"].tolist())                          if not df_before.empty else set()

    # ── LAYER 1-3 + Supabase sync: refresh ─────────────────────────────────────
    print(f"  [1/4] Running layers 1–3 (indicators → quad+flags → alignment + Supabase sync)...")
    cmd_refresh()

    # ── Snapshot AFTER ─────────────────────────────────────────────────────────
    df_after = get_universe("all")

    from engines.screener import run_gates
    from engines.quad import compute_axes, assign_quadrants, QUAD_NAME
    from engines.alignment import compute_alignment
    from engines.fcf_flip import compute_flip_scores

    df_after = run_gates(df_after)
    df_after = compute_axes(df_after)
    df_after = assign_quadrants(df_after)
    df_after = compute_alignment(df_after)
    df_after = compute_flip_scores(df_after)

    after_quads   = df_after.set_index("ticker")["quadrant"].to_dict()
    after_buckets = df_after.set_index("ticker")["alignment_bucket"].to_dict()
    after_scores  = df_after.set_index("ticker")["alignment_score"].to_dict()
    after_tickers = set(df_after["ticker"].tolist())

    # ── LAYER 4: Pillar scores — fast batch (score_only, no memo/web) ────────
    print(f"\n  [2/4] Layer 4 — pillar scoring {len(after_tickers)} companies (scores only, no memos)...")
    import warnings, sys as _sys
    from scripts.company_scorer import score_ticker, get_conn as scorer_conn
    sc_conn = scorer_conn()
    scored_ok = scored_skip = scored_fail = 0

    # Suppress yfinance deprecation warnings that flood batch output
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)

        for i, ticker in enumerate(sorted(after_tickers), 1):
            try:
                result = score_ticker(
                    ticker, sc_conn,
                    interactive=False, force=False,
                    score_only=True   # ← skips memo + web research
                )
                if result is True:
                    scored_ok += 1
                    if scored_ok % 25 == 0:
                        print(f"     {scored_ok} scored so far...")
                else:
                    scored_skip += 1
            except Exception as e:
                scored_fail += 1

    sc_conn.close()
    print(f"  [2/4] Pillar scoring: {scored_ok} scored · {scored_skip} skipped (recent) · {scored_fail} failed")

    # ── Data updater (yfinance prices) ─────────────────────────────────────────
    print(f"\n  [3/4] Updating live prices via yfinance for all {len(after_tickers)} names...")
    try:
        from scripts.data_updater import fetch_ticker_data, upsert_market_data, get_conn as du_conn
        from datetime import date
        du_c = du_conn(); du_c.autocommit = False
        du_cur = du_c.cursor()
        du_cur.execute("SELECT id, ticker FROM companies WHERE active=TRUE ORDER BY ticker")
        company_rows = du_cur.fetchall()
        du_cur.close()
        du_ok = du_fail = 0
        for company_id, ticker in company_rows:
            data, missing = fetch_ticker_data(ticker)
            if not data:
                du_fail += 1
                continue
            try:
                upsert_market_data(str(company_id), ticker, data, du_c)
                du_c.commit()
                du_ok += 1
            except Exception:
                du_c.rollback()
                du_fail += 1
        du_c.close()
        print(f"  [3/4] yfinance update: {du_ok} updated · {du_fail} failed")
    except Exception as e:
        print(f"  [3/4] yfinance update skipped: {e}")

    # ── Quad refresher (2-month confirmation in Supabase) ──────────────────────
    print(f"\n  [4/4] Running quad refresher (Supabase 2-month confirmation)...")
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "quad_refresher.py")],
            capture_output=True, text=True, cwd=str(ROOT)
        )
        # Print just the summary line
        for line in result.stdout.split("\n"):
            if "SUMMARY" in line or "confirmed" in line.lower() or "MIGRATION" in line:
                print(f"  {line.strip()}")
    except Exception as e:
        print(f"  [4/4] Quad refresher skipped: {e}")

    # ── Change detection ───────────────────────────────────────────────────────
    changes = []

    # New tickers added to universe
    new_tickers = after_tickers - before_tickers
    for t in sorted(new_tickers):
        changes.append({"type": "NEW_NAME", "ticker": t,
                         "detail": f"Added to universe · quad: {after_quads.get(t,'?')}"})

    # Tickers removed from universe
    dropped = before_tickers - after_tickers
    for t in sorted(dropped):
        changes.append({"type": "REMOVED", "ticker": t,
                         "detail": "No longer in screener universe"})

    # Quad changes (only for names that existed before)
    for ticker, new_quad in after_quads.items():
        old_quad = before_quads.get(ticker)
        if old_quad and old_quad != new_quad and old_quad not in ("N/A","") and new_quad not in ("N/A",""):
            changes.append({"type": "QUAD_CHANGE", "ticker": ticker,
                             "detail": f"{old_quad} → {new_quad}  score: {after_scores.get(ticker,0):.1f}"})

    # Alignment bucket changes (Accumulate ↔ Neutral ↔ Distribute)
    for ticker, new_bucket in after_buckets.items():
        old_bucket = before_buckets.get(ticker)
        if old_bucket and old_bucket != new_bucket:
            direction = "⬆" if new_bucket == "Accumulate" else ("⬇" if new_bucket == "Distribute" else "~")
            changes.append({"type": "BUCKET_CHANGE", "ticker": ticker,
                             "detail": f"{old_bucket} → {new_bucket} {direction}  score: {after_scores.get(ticker,0):.1f}"})

    # ── Print changelog ────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  CHANGE LOG — {RUN_TS}")
    print(f"{SEP}")

    type_order = ["NEW_NAME","REMOVED","QUAD_CHANGE","BUCKET_CHANGE"]
    type_icons = {"NEW_NAME":"🆕","REMOVED":"🗑 ","QUAD_CHANGE":"🔀","BUCKET_CHANGE":"📊"}
    type_labels = {"NEW_NAME":"New names","REMOVED":"Removed","QUAD_CHANGE":"Quad migrations","BUCKET_CHANGE":"Bucket changes"}

    total_changes = len(changes)
    if not changes:
        print(f"  ✅ No changes detected vs prior snapshot")
    else:
        for ctype in type_order:
            group = [c for c in changes if c["type"] == ctype]
            if group:
                print(f"\n  {type_icons[ctype]} {type_labels[ctype]} ({len(group)}):")
                for c in group:
                    print(f"     {c['ticker']:<7}  {c['detail']}")

    # Quad distribution summary
    q_counts = df_after["quadrant"].value_counts().to_dict()
    print(f"\n  UNIVERSE SNAPSHOT: {len(after_tickers)} names")
    for q, label in [("Q1","Full Compounders"),("Q2","Earnings Resilience"),
                      ("Q3","Margin Compression"),("Q4","Full Deterioration")]:
        n = q_counts.get(q, 0)
        pct = n / len(after_tickers) * 100
        bar = "█" * int(pct / 3)
        print(f"     {q} {label:<22} {n:>3}  {pct:.0f}%  {bar}")

    # ── Write to journal ───────────────────────────────────────────────────────
    journal_dir = ROOT / "journal" / "decisions"
    journal_dir.mkdir(parents=True, exist_ok=True)
    today_str = datetime.today().strftime("%Y-%m-%d")
    journal_path = journal_dir / f"{today_str}_full_update_changelog.md"

    with open(journal_path, "w", encoding="utf-8") as f:
        f.write(f"# Full Update Changelog — {RUN_TS}\n\n")
        f.write(f"**Universe:** {len(after_tickers)} names · {total_changes} changes detected\n\n")
        f.write(f"## Quad Distribution\n")
        for q in ["Q1","Q2","Q3","Q4"]:
            f.write(f"- {q}: {q_counts.get(q,0)}\n")
        f.write(f"\n## Changes\n")
        if not changes:
            f.write("No changes vs prior snapshot.\n")
        else:
            for ctype in type_order:
                group = [c for c in changes if c["type"] == ctype]
                if group:
                    f.write(f"\n### {type_labels[ctype]} ({len(group)})\n")
                    for c in group:
                        f.write(f"- **{c['ticker']}**: {c['detail']}\n")
        f.write(f"\n## Scoring\n")
        f.write(f"- Pillar scores: {scored_ok} written · {scored_skip} skipped · {scored_fail} failed\n")
        f.write(f"\n*Generated by Alpha System v10.0*\n")

    # Log to Supabase decision_journal
    log_decision(
        note=(f"Full 5-layer update complete — {len(after_tickers)} names · "
              f"{total_changes} changes · {scored_ok} pillar scores written"),
        event_type="FULL_UPDATE"
    )

    print(f"\n  [Journal] Saved: {journal_path.name}")
    print(f"\n{SEP}")
    print(f"  UPDATE COMPLETE — {total_changes} changes logged")
    print(f"{SEP}\n")


# ── Dispatcher ────────────────────────────────────────────────────────────────

def main():
    init_db()
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        cmd_status()
        return

    cmd = " ".join(args[:2]).lower()

    if args[0] == "update":
        cmd_full_update()
    elif args[0] == "refresh":
        cmd_refresh()
    elif cmd in ("quad snapshot", "quad"):
        cmd_quad_snapshot()
    elif cmd in ("q2 list", "q2"):
        cmd_q2_list()
    elif cmd in ("q3 watch", "q3"):
        cmd_q3_watch()
    elif cmd in ("flip screen", "flip"):
        cmd_flip_screen()
    elif cmd in ("alignment report", "alignment"):
        cmd_alignment_report()
    elif cmd in ("migration log", "migrations"):
        cmd_migration_log()
    elif cmd in ("weekly report", "weekly"):
        from engines.reports import generate_report
        generate_report()
    elif cmd in ("q1q2 report", "q1q2", "focus report"):
        from engines.reports import generate_q1q2_report
        generate_q1q2_report()
    elif cmd in ("monthly rebalance", "monthly"):
        from engines.reports import generate_monthly_rebalance_report
        path = generate_monthly_rebalance_report()
        try:
            import webbrowser
            webbrowser.open(f"file:///{path.replace(os.sep, '/')}")
        except Exception:
            pass
    elif cmd in ("trade log",):
        from engines.reports import generate_trade_log_report
        path = generate_trade_log_report()
        try:
            import webbrowser
            webbrowser.open(f"file:///{path.replace(os.sep, '/')}")
        except Exception:
            pass
    elif cmd in ("load portfolio", "load port"):
        cmd_load_portfolio()
    elif args[0] == "portfolio" and len(args) == 1:
        cmd_portfolio_status()
    elif cmd in ("portfolio snapshot", "port snapshot"):
        cmd_portfolio_snapshot()
    elif cmd in ("log trade", "log"):
        # python run.py log trade [TICKER ACTION PRICE SHARES]
        extra = args[2:]  # everything after "log trade"
        ticker = extra[0].upper() if len(extra) > 0 else ""
        action = extra[1].upper() if len(extra) > 1 else ""
        price  = float(extra[2]) if len(extra) > 2 else None
        shares = float(extra[3]) if len(extra) > 3 else None
        interactive_log_trade(ticker=ticker, action=action,
                              price=price, shares=shares)
    elif args[0] == "audit":
        cmd_audit()
    elif args[0] == "status":
        cmd_status()
    elif args[0] == "journal" and len(args) > 1:
        cmd_journal(" ".join(args[1:]))
    elif args[0] in ("who", "whois") and len(args) >= 2:
        ticker = args[-1]
        cmd_who_is(ticker)
    elif args[0] == "brief" and len(args) >= 2:
        ticker = args[1].upper()
        from engines.agent import run_brief
        html_path = run_brief(ticker)
        try:
            import webbrowser
            webbrowser.open(f"file:///{html_path.replace(os.sep, '/')}")
        except Exception:
            pass
    elif args[0] == "watch":
        no_browser = "--no-browser" in args
        from engines.watcher import run_watcher
        run_watcher(open_browser=not no_browser)
    elif args[0] == "analyze" and len(args) >= 2:
        # python run.py analyze FILE [TICKER] [--context "extra context"]
        filepath = args[1]
        ticker   = args[2].upper() if len(args) > 2 and not args[2].startswith("--") else ""
        context  = ""
        if "--context" in args:
            ci = args.index("--context")
            context = args[ci + 1] if ci + 1 < len(args) else ""
        from engines.vision import run_analyze
        run_analyze(filepath, ticker=ticker, extra_context=context,
                    save=True, open_browser=True)
    elif cmd in ("brief all", "briefs"):
        from engines.agent import run_all_portfolio_briefs
        run_all_portfolio_briefs()
    elif cmd in ("portfolio brief", "port brief"):
        from engines.agent import run_portfolio_brief
        html_path = run_portfolio_brief()
        try:
            import webbrowser
            webbrowser.open(f"file:///{html_path.replace(os.sep, '/')}")
        except Exception:
            pass
    else:
        print(f"[Error] Unknown command: '{' '.join(args)}'")
        print(__doc__)


if __name__ == "__main__":
    main()
