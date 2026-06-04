"""
trigger_monitor.py
------------------
Daily morning monitor for Integrity Compounders portfolio.
Pulls current state from Supabase and prints a structured briefing.

Usage:
    python scripts/trigger_monitor.py
    python scripts/trigger_monitor.py --html   # also saves HTML to outputs/reports/
"""

import sys
import argparse
from pathlib import Path
from datetime import date, datetime, timedelta

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
from config.settings import settings

NAVY = "#1F3A5F"
GOLD = "#C9A84C"


def get_conn():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    return conn


# ══════════════════════════════════════════════════════════════════════════════
# DATA QUERIES
# ══════════════════════════════════════════════════════════════════════════════

def q_hard_rule_violations(cur) -> list[dict]:
    violations = []

    # IT sector > 28%
    cur.execute("""
        SELECT sector, COUNT(*) as n,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
        FROM companies WHERE in_portfolio=TRUE AND active=TRUE AND sector IS NOT NULL
        GROUP BY sector ORDER BY n DESC
    """)
    for sector, n, pct in cur.fetchall():
        if float(pct) > 28:
            violations.append({
                "type": "SECTOR_CAP",
                "desc": f"{sector} at {pct}% — above 28% cap ({n} holdings)",
                "severity": "HIGH",
            })

    # Discretionary positions missing override_reason — check positions table
    cur.execute("""
        SELECT c.ticker, c.company_name
        FROM companies c
        WHERE c.is_discretionary=TRUE AND c.in_portfolio=TRUE AND c.active=TRUE
    """)
    disc = cur.fetchall()
    # Check positions table for each
    for ticker, name in disc:
        cur.execute("""
            SELECT override_reason FROM positions
            WHERE ticker=%s AND status='ACTIVE'
            ORDER BY created_at DESC LIMIT 1
        """, (ticker,))
        row = cur.fetchone()
        if not row or not row[0]:
            violations.append({
                "type": "MISSING_OVERRIDE",
                "desc": f"{ticker} — discretionary position missing override_reason in positions table",
                "severity": "MEDIUM",
            })

    # Factor snapshot stale (>35 days)
    cur.execute("SELECT MAX(snapshot_date) FROM factor_snapshots")
    last_snap = cur.fetchone()[0]
    if not last_snap or (date.today() - last_snap).days > 35:
        days_since = (date.today() - last_snap).days if last_snap else 999
        violations.append({
            "type": "FACTOR_SNAPSHOT_STALE",
            "desc": f"Factor exposure snapshot is {days_since}d old — run: python scripts/factor_exposure.py --snapshot",
            "severity": "MEDIUM",
        })

    # Active positions past mandatory_review_date
    cur.execute("""
        SELECT ticker, mandatory_review_date FROM positions
        WHERE status='ACTIVE' AND mandatory_review_date IS NOT NULL
          AND mandatory_review_date < CURRENT_DATE
    """)
    for ticker, review_date in cur.fetchall():
        days_past = (date.today() - review_date).days
        violations.append({
            "type": "PAST_REVIEW_DATE",
            "desc": f"{ticker} — mandatory review was {review_date} ({days_past}d overdue)",
            "severity": "MEDIUM",
        })

    return violations


def q_earnings_this_week(cur) -> list[dict]:
    next_week = date.today() + timedelta(days=7)
    cur.execute("""
        SELECT c.ticker, c.company_name, cmd.next_earnings_date
        FROM company_market_data cmd
        JOIN companies c ON c.id = cmd.company_id
        WHERE c.in_portfolio=TRUE AND c.active=TRUE
          AND cmd.next_earnings_date BETWEEN CURRENT_DATE AND %s
          AND cmd.data_date = (
              SELECT MAX(data_date) FROM company_market_data
              WHERE company_id = cmd.company_id
          )
        ORDER BY cmd.next_earnings_date
    """, (next_week,))

    results = []
    for ticker, name, earn_date in cur.fetchall():
        days_away = (earn_date - date.today()).days
        # Check for pre-earnings memo
        quarter = f"Q{((earn_date.month - 1) // 3) + 1} {earn_date.year}"
        cur.execute("""
            SELECT pre_completed FROM earnings_memos
            WHERE ticker=%s AND quarter=%s
            ORDER BY created_at DESC LIMIT 1
        """, (ticker, quarter))
        memo = cur.fetchone()
        has_pre = bool(memo and memo[0])
        results.append({
            "ticker":    ticker,
            "name":      name,
            "date":      earn_date,
            "days_away": days_away,
            "has_pre":   has_pre,
            "quarter":   quarter,
        })
    return results


def q_quad_alerts(cur) -> tuple[list, list]:
    # Provisional (month 1)
    cur.execute("""
        SELECT qml.ticker, qml.from_quad, qml.to_quad,
               qml.consecutive_months, qml.migration_date
        FROM quad_migration_log qml
        JOIN companies c ON c.ticker = qml.ticker
        WHERE qml.confirmed=FALSE AND c.in_portfolio=TRUE
        ORDER BY qml.migration_date DESC
    """)
    provisional = [
        {"ticker": r[0], "from": r[1], "to": r[2], "months": r[3], "date": r[4]}
        for r in cur.fetchall()
    ]

    # Confirmed, pending PM decision
    cur.execute("""
        SELECT qml.ticker, qml.from_quad, qml.to_quad,
               qml.migration_date, qml.pm_decision
        FROM quad_migration_log qml
        JOIN companies c ON c.ticker = qml.ticker
        WHERE qml.confirmed=TRUE AND qml.pm_decision='PENDING'
          AND c.in_portfolio=TRUE
        ORDER BY qml.migration_date DESC
    """)
    confirmed = [
        {"ticker": r[0], "from": r[1], "to": r[2], "date": r[3], "decision": r[4]}
        for r in cur.fetchall()
    ]

    # Q3 holdings — from companies table
    cur.execute("""
        SELECT ticker, company_name FROM companies
        WHERE quad_current='Q3' AND in_portfolio=TRUE AND active=TRUE
    """)
    q3_holdings = [{"ticker": r[0], "name": r[1]} for r in cur.fetchall()]

    return provisional, confirmed, q3_holdings


def q_thesis_alerts(cur) -> list[dict]:
    # Most recent review per company with watch/review/broken status
    cur.execute("""
        SELECT DISTINCT ON (cr.company_id)
            c.ticker, c.company_name, cr.thesis_status,
            cr.review_date, cr.what_has_changed
        FROM company_reviews cr
        JOIN companies c ON c.id = cr.company_id
        WHERE cr.thesis_status IN ('WATCH','REVIEW','BROKEN')
          AND c.in_portfolio=TRUE AND c.active=TRUE
        ORDER BY cr.company_id, cr.review_date DESC
    """)
    thesis = [
        {"ticker": r[0], "name": r[1], "status": r[2],
         "date": r[3], "notes": r[4]}
        for r in cur.fetchall()
    ]

    # Mandatory review approaching (14 days)
    soon = date.today() + timedelta(days=14)
    cur.execute("""
        SELECT ticker, mandatory_review_date FROM positions
        WHERE status='ACTIVE' AND mandatory_review_date IS NOT NULL
          AND mandatory_review_date BETWEEN CURRENT_DATE AND %s
    """, (soon,))
    upcoming = [
        {"ticker": r[0], "date": r[1],
         "days": (r[1] - date.today()).days}
        for r in cur.fetchall()
    ]
    return thesis, upcoming


def q_five_gate_alerts(cur) -> list[dict]:
    cur.execute("""
        SELECT ticker, company_name, five_gate_status, five_gate_last_checked
        FROM companies
        WHERE five_gate_status IN ('WATCH_1','WATCH_2','FAIL')
          AND in_portfolio=TRUE AND active=TRUE
        ORDER BY five_gate_status DESC
    """)
    return [{"ticker": r[0], "name": r[1], "status": r[2], "checked": r[3]}
            for r in cur.fetchall()]


def q_watchlist_alerts(cur) -> list[dict]:
    cur.execute("""
        SELECT ticker, company_name, why_watching, status,
               current_composite_score, target_entry_price, next_earnings_date
        FROM watchlist
        WHERE status IN ('APPROACHING','READY')
        ORDER BY status DESC, current_composite_score DESC NULLS LAST
    """)
    return [{"ticker": r[0], "name": r[1], "why": r[2], "status": r[3],
             "score": r[4], "target_price": r[5], "next_earnings": r[6]}
            for r in cur.fetchall()]


def q_active_triggers(cur) -> list[dict]:
    cur.execute("""
        SELECT t.ticker, t.trigger_type, t.trigger_action,
               t.trigger_condition, t.created_at, p.status
        FROM triggers t
        LEFT JOIN positions p ON p.id = t.position_id
        WHERE t.trigger_status='PENDING'
          AND (p.status='ACTIVE' OR t.position_id IS NULL)
        ORDER BY t.created_at ASC
    """)
    def _days_old(ts):
        if not ts: return 0
        try:
            from datetime import timezone
            now = datetime.now(timezone.utc) if ts.tzinfo else datetime.now()
            return (now - ts).days
        except Exception:
            return 0
    return [{"ticker": r[0], "type": r[1], "action": r[2],
             "condition": r[3], "days_old": _days_old(r[4]), "pos_status": r[5]}
            for r in cur.fetchall()]


def q_allocation_drift(cur) -> list[dict]:
    cur.execute("""
        SELECT COUNT(*) FROM positions WHERE status='ACTIVE'
    """)
    n = cur.fetchone()[0]
    if not n:
        return []
    target = round(1.0 / n, 4) if n > 0 else 0.04

    cur.execute("""
        SELECT ticker, current_allocation_pct, target_allocation_pct
        FROM positions
        WHERE status='ACTIVE' AND current_allocation_pct IS NOT NULL
    """)
    drifts = []
    for ticker, actual, tgt in cur.fetchall():
        actual_f = float(actual or 0)
        tgt_f    = float(tgt or target)
        drift    = actual_f - tgt_f
        if abs(drift) > 0.01:
            drifts.append({"ticker": ticker, "actual": actual_f,
                           "target": tgt_f, "drift": drift})
    return sorted(drifts, key=lambda x: abs(x["drift"]), reverse=True)


def q_portfolio_summary(cur) -> dict:
    cur.execute("""
        SELECT COUNT(*) FROM companies WHERE in_portfolio=TRUE AND active=TRUE
    """)
    n_holdings = cur.fetchone()[0]

    cur.execute("""
        SELECT AVG(COALESCE(cs.composite_score_v2, cs.composite_score))
        FROM company_scores cs
        JOIN companies c ON c.id = cs.company_id
        WHERE c.in_portfolio=TRUE AND c.active=TRUE
          AND cs.score_date = (
              SELECT MAX(score_date) FROM company_scores WHERE company_id = cs.company_id
          )
    """)
    avg_score_row = cur.fetchone()
    avg_score = round(float(avg_score_row[0]), 1) if avg_score_row and avg_score_row[0] else None

    # Latest factor snapshot for header line
    cur.execute("""
        SELECT wtd_avg_roic, wtd_avg_fcf_margin, avg_pairwise_correlation, snapshot_date
        FROM factor_snapshots ORDER BY snapshot_date DESC LIMIT 1
    """)
    fs = cur.fetchone()
    factor_line = None
    if fs:
        def fp(v): return f"{float(v)*100:.1f}%" if v else "—"
        factor_line = (f"Avg ROIC: {fp(fs[0])} | Avg FCF Margin: {fp(fs[1])} | "
                       f"Pairwise Corr: {float(fs[2]):.2f}" if fs[2] else f"Avg ROIC: {fp(fs[0])}")

    return {
        "n_holdings":    n_holdings,
        "target_weight": round(100.0 / n_holdings, 1) if n_holdings else 4.0,
        "avg_score":     avg_score,
        "factor_line":   factor_line,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TERMINAL PRINTER
# ══════════════════════════════════════════════════════════════════════════════

def print_monitor(data: dict):
    summary    = data["summary"]
    today_str  = datetime.now().strftime("%A, %B %d, %Y  %I:%M %p")
    score_str  = f"{data['summary']['avg_score']}" if data["summary"]["avg_score"] else "—"

    print(f"\n{'='*60}")
    print(f"  INTEGRITY COMPOUNDERS  ·  {today_str}")
    print(f"{'='*60}")
    print(f"  Holdings: {summary['n_holdings']}  |  "
          f"Target Weight: {summary['target_weight']:.1f}%  |  "
          f"Avg Score (v2): {score_str}  |  YTD: —")
    if summary.get("factor_line"):
        print(f"  Factors: {summary['factor_line']}")
    print(f"{'='*60}\n")

    # 1. Hard rule violations
    violations = data["violations"]
    print(f"  1. HARD RULE VIOLATIONS ({len(violations)})")
    if not violations:
        print("     ✅ None\n")
    else:
        for v in violations:
            icon = "🚨" if v["severity"] == "HIGH" else "⚠️ "
            print(f"     {icon} [{v['type']}] {v['desc']}")
        print()

    # 2. Earnings this week
    earnings = data["earnings"]
    print(f"  2. EARNINGS THIS WEEK ({len(earnings)})")
    if not earnings:
        print("     ✅ None in next 7 days\n")
    else:
        for e in earnings:
            pre_tag = "✅ pre-note exists" if e["has_pre"] else "⚠️  NO PRE-EARNINGS NOTE"
            print(f"     {e['ticker']:<6} {str(e['date'])} ({e['days_away']}d)  {e['quarter']}  —  {pre_tag}")
        print()

    # 3. Quad alerts
    provisional, confirmed, q3 = data["quad_provisional"], data["quad_confirmed"], data["q3_holdings"]
    total_quad = len(provisional) + len(confirmed) + len(q3)
    print(f"  3. QUAD ALERTS ({total_quad})")
    if confirmed:
        for r in confirmed:
            print(f"     🚨 {r['ticker']:<6} CONFIRMED: {r['from']} → {r['to']}  ({r['date']})  PM DECISION REQUIRED")
    if q3:
        for r in q3:
            print(f"     🔴 {r['ticker']:<6} IN Q3 (Margin Compression) — held position, review required")
    if provisional:
        for r in provisional:
            print(f"     ⚠️  {r['ticker']:<6} Provisional: → {r['to']} month 1/2 (was {r['from'] or 'None'})")
    if total_quad == 0:
        print("     ✅ None\n")
    else:
        print()

    # 4. Thesis alerts
    thesis, upcoming_reviews = data["thesis_alerts"], data["upcoming_reviews"]
    total_thesis = len(thesis) + len(upcoming_reviews)
    print(f"  4. THESIS ALERTS ({total_thesis})")
    for t in thesis:
        icon = "🚨" if t["status"] == "BROKEN" else "⚠️ "
        print(f"     {icon} {t['ticker']:<6} Thesis: {t['status']}  (review: {t['date']})")
    for r in upcoming_reviews:
        print(f"     📅 {r['ticker']:<6} Review due in {r['days']}d ({r['date']})")
    if total_thesis == 0:
        print("     ✅ None\n")
    else:
        print()

    # 5. Five-gate alerts
    gates = data["five_gate_alerts"]
    print(f"  5. FIVE-GATE ALERTS ({len(gates)})")
    if not gates:
        print("     ✅ None\n")
    else:
        for g in gates:
            icon = "🚨" if g["status"] == "FAIL" else "⚠️ "
            checked = f" (last checked: {g['checked']})" if g["checked"] else ""
            print(f"     {icon} {g['ticker']:<6} Status: {g['status']}{checked}")
        print()

    # 6. Watchlist alerts
    wl = data["watchlist_alerts"]
    print(f"  6. WATCHLIST ALERTS ({len(wl)})")
    if not wl:
        print("     ℹ️  No APPROACHING or READY names\n")
    else:
        for w in wl:
            score_s = f"  score: {w['score']:.1f}" if w["score"] else ""
            price_s = f"  target: ${w['target_price']:,.2f}" if w["target_price"] else ""
            print(f"     🎯 {w['ticker']:<6} [{w['status']}]{score_s}{price_s}  {(w['why'] or '')[:50]}")
        print()

    # 7. Active triggers
    triggers = data["triggers"]
    print(f"  7. ACTIVE TRIGGERS ({len(triggers)})")
    if not triggers:
        print("     ✅ None pending\n")
    else:
        for t in triggers:
            print(f"     🔔 {(t['ticker'] or '?'):<6} [{t['action']}] {t['type']}  "
                  f"({t['days_old']}d old)  {(t['condition'] or '')[:45]}")
        print()

    # 8. Allocation drift
    drifts = data["drifts"]
    print(f"  8. ALLOCATION DRIFT (>{1}% from target)")
    if not drifts:
        print("     ✅ All positions within 1% of target\n")
    else:
        for d in drifts:
            icon = "🚨" if abs(d["drift"]) > 0.02 else "⚠️ "
            print(f"     {icon} {d['ticker']:<6} actual {d['actual']*100:.1f}%  "
                  f"target {d['target']*100:.1f}%  drift {d['drift']*100:+.1f}pp")
        print()

    print(f"{'='*60}")
    print(f"  Run data_updater.py to refresh market data")
    print(f"  Run quad_refresher.py to refresh quad assignments")
    print(f"{'='*60}\n")


# ══════════════════════════════════════════════════════════════════════════════
# HTML GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def generate_html(data: dict, output_path: Path) -> None:
    summary   = data["summary"]
    today_str = datetime.now().strftime("%B %d, %Y  %I:%M %p")
    run_ts    = datetime.now().strftime("%B %d, %Y · %I:%M %p")
    score_str = f"{data['summary']['avg_score']}" if data["summary"]["avg_score"] else "—"

    def section(title: str, count: int, content: str, anchor: str = "") -> str:
        color = "#dc2626" if count > 0 and "HARD" in title else NAVY
        return f"""
        <div id="{anchor}" style="background:white;border-radius:14px;padding:24px;
                margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,0.07);border:1px solid #e5e7eb">
          <div style="border-left:4px solid {color};padding-left:14px;margin-bottom:16px;
                      display:flex;justify-content:space-between;align-items:center">
            <h2 style="font-size:15px;font-weight:800;color:{color}">{title}</h2>
            <span style="background:{'#fee2e2' if count > 0 else '#f0fdf4'};
                         color:{'#dc2626' if count > 0 else '#16a34a'};
                         padding:2px 10px;border-radius:10px;font-size:12px;font-weight:700">{count}</span>
          </div>
          {content}
        </div>"""

    def alert_row(icon: str, text: str, severity: str = "medium") -> str:
        bg = {"high":"#fee2e2","medium":"#fef3c7","low":"#f0fdf4","ok":"#f0fdf4"}.get(severity,"#f9fafb")
        return f'<div style="background:{bg};border-radius:8px;padding:10px 14px;margin-bottom:8px;font-size:13px;color:#374151">{icon} {text}</div>'

    def ok_row(text: str) -> str:
        return f'<div style="color:#6b7280;font-style:italic;font-size:13px;padding:8px">{text}</div>'

    # Build section HTML
    # 1. Violations
    viol_html = ""
    for v in data["violations"]:
        icon = "🚨" if v["severity"] == "HIGH" else "⚠️"
        viol_html += alert_row(icon, f"<strong>[{v['type']}]</strong> {v['desc']}",
                               "high" if v["severity"]=="HIGH" else "medium")
    if not viol_html:
        viol_html = ok_row("✅ No violations")

    # 2. Earnings
    earn_html = ""
    for e in data["earnings"]:
        pre = "✅ pre-note exists" if e["has_pre"] else "⚠️ NO PRE-NOTE"
        earn_html += alert_row("📅",
            f"<strong>{e['ticker']}</strong> — {e['date']} ({e['days_away']}d) {e['quarter']} · {pre}",
            "low" if e["has_pre"] else "medium")
    if not earn_html:
        earn_html = ok_row("✅ No earnings in next 7 days")

    # 3. Quad
    quad_html = ""
    for r in data["quad_confirmed"]:
        quad_html += alert_row("🚨", f"<strong>{r['ticker']}</strong> CONFIRMED: {r['from']} → {r['to']} · PM DECISION REQUIRED", "high")
    for r in data["q3_holdings"]:
        quad_html += alert_row("🔴", f"<strong>{r['ticker']}</strong> in Q3 Margin Compression — review required", "high")
    for r in data["quad_provisional"]:
        quad_html += alert_row("⚠️", f"<strong>{r['ticker']}</strong> Provisional → {r['to']} (month 1/2, was {r['from'] or 'None'})", "medium")
    if not quad_html:
        quad_html = ok_row("✅ No quad alerts")

    # 4. Thesis
    thesis_html = ""
    for t in data["thesis_alerts"]:
        icon = "🚨" if t["status"]=="BROKEN" else "⚠️"
        thesis_html += alert_row(icon, f"<strong>{t['ticker']}</strong> Thesis: {t['status']} (reviewed: {t['date']})",
                                 "high" if t["status"]=="BROKEN" else "medium")
    for r in data["upcoming_reviews"]:
        thesis_html += alert_row("📅", f"<strong>{r['ticker']}</strong> Review due in {r['days']}d ({r['date']})", "medium")
    if not thesis_html:
        thesis_html = ok_row("✅ No thesis alerts")

    # 5. Five-gate
    gate_html = ""
    for g in data["five_gate_alerts"]:
        icon = "🚨" if g["status"]=="FAIL" else "⚠️"
        gate_html += alert_row(icon, f"<strong>{g['ticker']}</strong> Gate status: {g['status']}", "high" if g["status"]=="FAIL" else "medium")
    if not gate_html:
        gate_html = ok_row("✅ No gate alerts")

    # 6. Watchlist
    wl_html = ""
    for w in data["watchlist_alerts"]:
        score_s = f" · score {w['score']:.1f}" if w["score"] else ""
        wl_html += alert_row("🎯", f"<strong>{w['ticker']}</strong> [{w['status']}]{score_s} — {(w['why'] or '')[:60]}", "low")
    if not wl_html:
        wl_html = ok_row("ℹ️ No approaching or ready names")

    # 7. Triggers
    trig_html = ""
    for t in data["triggers"]:
        trig_html += alert_row("🔔", f"<strong>{t.get('ticker','?')}</strong> [{t['action']}] {t['type']} · {t['days_old']}d old · {(t['condition'] or '')[:50]}", "medium")
    if not trig_html:
        trig_html = ok_row("✅ No pending triggers")

    # 8. Drift
    drift_html = ""
    for d in data["drifts"]:
        icon = "🚨" if abs(d["drift"]) > 0.02 else "⚠️"
        drift_html += alert_row(icon, f"<strong>{d['ticker']}</strong> actual {d['actual']*100:.1f}% · target {d['target']*100:.1f}% · drift {d['drift']*100:+.1f}pp",
                                "high" if abs(d["drift"])>0.02 else "medium")
    if not drift_html:
        drift_html = ok_row("✅ All positions within 1% of target")

    total_alerts = (len(data["violations"]) + len(data["earnings"]) +
                    len(data["quad_confirmed"]) + len(data["q3_holdings"]) +
                    len(data["thesis_alerts"]) + len(data["five_gate_alerts"]))

    nav = "".join(
        f'<a href="#{a}" style="color:rgba(255,255,255,0.8);text-decoration:none;font-size:12px;padding:5px 12px;border-radius:16px">{l}</a>'
        for a, l in [("v","Rules"),("e","Earnings"),("q","Quads"),("t","Thesis"),
                     ("g","Gates"),("wl","Watchlist"),("tr","Triggers"),("d","Drift")]
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Morning Monitor · {date.today()}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{box-sizing:border-box;margin:0;padding:0}}
  body {{font-family:'Source Sans 3',Calibri,sans-serif;background:#f1f5f9;color:#1e293b;-webkit-font-smoothing:antialiased}}
  @media(max-width:640px) {{
    .grid6 {{grid-template-columns:repeat(2,1fr)!important}}
    .body-pad {{padding:16px!important}}
  }}
</style>
</head>
<body>

<div style="background:linear-gradient(135deg,{NAVY},#2d5282);position:sticky;top:0;z-index:100;box-shadow:0 2px 8px rgba(0,0,0,0.2)">
  <div style="max-width:960px;margin:0 auto;padding:0 20px;display:flex;align-items:center;justify-content:space-between;height:50px">
    <div style="font-family:'Playfair Display',serif;font-size:16px;font-weight:800;color:white">Integrity Compounders</div>
    <nav style="display:flex;gap:2px;flex-wrap:wrap">{nav}</nav>
  </div>
</div>

<div style="background:linear-gradient(135deg,{NAVY},#2d5282);padding:24px 20px 20px">
  <div style="max-width:960px;margin:0 auto">
    <div style="font-family:'Playfair Display',serif;font-size:26px;font-weight:800;color:white;margin-bottom:4px">Morning Monitor</div>
    <div style="font-size:13px;color:rgba(255,255,255,0.55);margin-bottom:20px">{today_str} · Alpha System v10.0</div>
    <div class="grid6" style="display:grid;grid-template-columns:repeat(6,1fr);gap:12px">
      {"".join(f'<div style="background:rgba(255,255,255,0.1);border-radius:10px;padding:12px;text-align:center"><div style="font-size:20px;font-weight:800;color:{"#ef4444" if v=="🚨" else "white"}">{v}</div><div style="font-size:10px;color:rgba(255,255,255,0.55);margin-top:3px;text-transform:uppercase;letter-spacing:0.5px">{l}</div></div>'
        for v,l in [
          (summary["n_holdings"], "Holdings"),
          (f"{summary['target_weight']:.1f}%", "Target Wt"),
          (score_str, "Avg Score"),
          (total_alerts, "Alerts"),
          (len(data["earnings"]), "Earnings Soon"),
          (len(data["quad_confirmed"])+len(data["q3_holdings"]), "Quad Flags"),
        ])}
    </div>
  </div>
</div>

<div class="body-pad" style="max-width:960px;margin:0 auto;padding:24px 20px 40px">
  {section("1. HARD RULE VIOLATIONS", len(data["violations"]), viol_html, "v")}
  {section("2. EARNINGS THIS WEEK", len(data["earnings"]), earn_html, "e")}
  {section("3. QUAD ALERTS", len(data["quad_confirmed"])+len(data["q3_holdings"])+len(data["quad_provisional"]), quad_html, "q")}
  {section("4. THESIS ALERTS", len(data["thesis_alerts"])+len(data["upcoming_reviews"]), thesis_html, "t")}
  {section("5. FIVE-GATE ALERTS", len(data["five_gate_alerts"]), gate_html, "g")}
  {section("6. WATCHLIST ALERTS", len(data["watchlist_alerts"]), wl_html, "wl")}
  {section("7. ACTIVE TRIGGERS", len(data["triggers"]), trig_html, "tr")}
  {section("8. ALLOCATION DRIFT", len(data["drifts"]), drift_html, "d")}
</div>

<div style="background:{NAVY};color:rgba(255,255,255,0.4);text-align:center;padding:16px;font-size:11px">
  Integrity Compounders · Integrity Wealth Partners · {run_ts} · Internal Use Only
</div>
<script>
  document.querySelectorAll('a[href^="#"]').forEach(a=>{{
    a.addEventListener('click',e=>{{e.preventDefault();document.querySelector(a.getAttribute('href'))?.scrollIntoView({{behavior:'smooth',block:'start'}});}});
  }});
</script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  [HTML] Saved: {output_path}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", action="store_true",
                        help="Also save HTML report to outputs/reports/")
    args = parser.parse_args()

    conn = get_conn()
    cur  = conn.cursor()

    data = {
        "summary":         q_portfolio_summary(cur),
        "violations":      q_hard_rule_violations(cur),
        "earnings":        q_earnings_this_week(cur),
        "quad_provisional":[], "quad_confirmed":[], "q3_holdings":[],
        "thesis_alerts":   [], "upcoming_reviews":[],
        "five_gate_alerts":q_five_gate_alerts(cur),
        "watchlist_alerts":q_watchlist_alerts(cur),
        "triggers":        q_active_triggers(cur),
        "drifts":          q_allocation_drift(cur),
    }
    data["quad_provisional"], data["quad_confirmed"], data["q3_holdings"] = q_quad_alerts(cur)
    data["thesis_alerts"], data["upcoming_reviews"] = q_thesis_alerts(cur)

    cur.close()
    conn.close()

    print_monitor(data)

    if args.html:
        out_path = ROOT / "outputs" / "reports" / f"morning_monitor_{date.today()}.html"
        generate_html(data, out_path)
        try:
            import os, webbrowser
            webbrowser.open(f"file:///{str(out_path).replace(os.sep, '/')}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
