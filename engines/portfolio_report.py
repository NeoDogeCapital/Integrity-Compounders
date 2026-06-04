"""
portfolio_report.py — Portfolio memo HTML generator
Integrity Compounders Alpha System v10.0

Generates the one-page portfolio memo with:
  S1  Quad distribution of held names
  S2  Sector exposure vs 28% cap
  S3  Sleeve allocation vs targets
  S4  Holdings detail table
  S5  Alerts panel
  S6  Month-over-month changes (if prior snapshot exists)
"""

import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engines.reports import _pead_badge, _quad_color, _quad_bg, _score, _mcap, _section
from engines.portfolio import SLEEVE_TARGETS, SECTOR_CAP
from engines.database import get_portfolio_history_dates, get_portfolio

NAVY = "#1F3A5F"


# ── Small badge helpers ───────────────────────────────────────────────────────

def _action_badge(action: str) -> str:
    c = {"BUY":"#16a34a","ADD":"#1e40af","TRIM":"#92400e","SELL":"#991b1b"}.get(action,"#374151")
    bg = {"BUY":"#dcfce7","ADD":"#dbeafe","TRIM":"#fef3c7","SELL":"#fee2e2"}.get(action,"#f3f4f6")
    return f'<span style="background:{bg};color:{c};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:700">{action}</span>'

def _vs_badge(v: str) -> str:
    c  = {"Above":"#16a34a","In Line":"#1e40af","Below":"#dc2626"}.get(v,"#6b7280")
    bg = {"Above":"#dcfce7","In Line":"#dbeafe","Below":"#fee2e2"}.get(v,"#f3f4f6")
    return f'<span style="background:{bg};color:{c};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:600">{v}</span>'

def _bucket_badge(b: str) -> str:
    c  = {"Accumulate":"#16a34a","Neutral":"#d97706","Distribute":"#dc2626"}.get(b,"#6b7280")
    bg = {"Accumulate":"#dcfce7","Neutral":"#fef3c7","Distribute":"#fee2e2"}.get(b,"#f3f4f6")
    return f'<span style="background:{bg};color:{c};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:600">{b}</span>'

def _drift_color(v) -> str:
    try:
        f = float(v)
        return "#dc2626" if abs(f) > 2 else "#d97706" if abs(f) > 1 else "#374151"
    except Exception:
        return "#374151"

def _pnl_color(v) -> str:
    try:
        return "#16a34a" if float(v) >= 0 else "#dc2626"
    except Exception:
        return "#374151"

def _bar(pct: float, total: float, color: str, cap: float = 28.0) -> str:
    w = min(pct / max(total, 1) * 200, 200)
    over = pct > cap
    c = "#dc2626" if over else color
    return (f'<div style="background:#e5e7eb;border-radius:3px;height:8px;width:200px;display:inline-block">'
            f'<div style="background:{c};width:{w:.0f}px;height:8px;border-radius:3px"></div></div>')


# ── Section builders ──────────────────────────────────────────────────────────

def _s1_quad_distribution(port: pd.DataFrame) -> str:
    total_value = port["current_value"].sum()
    cards = []
    for q, label, color, bg in [
        ("Q1", "Full Compounders",    "#2563eb", "#eff6ff"),
        ("Q2", "Earnings Resilience", "#16a34a", "#f0fdf4"),
        ("Q3", "Margin Compression",  "#dc2626", "#fef2f2"),
        ("Q4", "Full Deterioration",  "#d97706", "#fffbeb"),
    ]:
        grp = port[port["quadrant"] == q] if "quadrant" in port.columns else pd.DataFrame()
        n   = len(grp)
        wt  = grp["weight_actual"].sum() if not grp.empty else 0
        tickers = ", ".join(grp["ticker"].tolist()) if not grp.empty else "—"
        warn = ""
        if q == "Q4" and n > 0:
            warn = f'<div style="margin-top:6px;font-size:10px;font-weight:700;color:#dc2626">⚠ REVIEW REQUIRED</div>'
        cards.append(f"""
        <div style="background:{bg};border:1.5px solid {color}30;border-radius:12px;padding:18px">
          <div style="font-size:11px;font-weight:700;color:{color};text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">{q} · {label}</div>
          <div style="font-size:32px;font-weight:800;color:{color};line-height:1">{n}</div>
          <div style="font-size:12px;color:#6b7280;margin-top:4px">{wt:.1f}% of portfolio</div>
          <div style="font-size:11px;color:#374151;margin-top:6px;font-weight:500">{tickers[:60]}</div>
          {warn}
        </div>""")
    return f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px">{"".join(cards)}</div>'


def _s2_sector_exposure(port: pd.DataFrame) -> str:
    if "industry" not in port.columns:
        return "<p style='color:#6b7280'>No industry data.</p>"
    rows = ""
    total_wt = port["weight_actual"].sum()
    by_sector = port.groupby("industry").agg(
        count=("ticker","count"),
        weight=("weight_actual","sum"),
        tickers=("ticker", lambda x: ", ".join(x.tolist()))
    ).sort_values("weight", ascending=False)

    for i, (sector, r) in enumerate(by_sector.iterrows()):
        bg    = "#f9fafb" if i % 2 == 0 else "white"
        over  = r["weight"] > SECTOR_CAP
        wt_color = "#dc2626" if over else "#374151"
        flag  = '<span style="color:#dc2626;font-weight:700;font-size:11px"> !! OVER CAP</span>' if over else ""
        rows += f"""
        <tr style="background:{bg}">
          <td style="padding:9px 14px;color:#374151;font-size:13px">{sector}</td>
          <td style="padding:9px 14px;text-align:center;color:#374151;font-size:12px">{r['count']}</td>
          <td style="padding:9px 14px">{_bar(r['weight'], 100, "#2563eb")}</td>
          <td style="padding:9px 14px;font-weight:700;color:{wt_color}">{r['weight']:.1f}%{flag}</td>
          <td style="padding:9px 14px;font-size:11px;color:#6b7280">{str(r['tickers'])[:50]}</td>
        </tr>"""
    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:{NAVY};color:white">
        <th style="padding:9px 14px;text-align:left">Sector</th>
        <th style="padding:9px 14px;text-align:center">Count</th>
        <th style="padding:9px 14px;text-align:left">Weight</th>
        <th style="padding:9px 14px;text-align:left">Actual %</th>
        <th style="padding:9px 14px;text-align:left">Holdings</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _s3_sleeve_allocation(port: pd.DataFrame) -> str:
    rows = ""
    for i, (sleeve, target) in enumerate(SLEEVE_TARGETS.items()):
        bg     = "#f9fafb" if i % 2 == 0 else "white"
        grp    = port[port["sleeve"] == sleeve] if "sleeve" in port.columns else pd.DataFrame()
        actual = grp["weight_actual"].sum() if not grp.empty else 0
        drift  = actual - target
        over   = abs(drift) > 5
        flag   = '<span style="color:#dc2626;font-weight:700;font-size:11px"> !! >5pp off</span>' if over else ""
        drift_c = "#dc2626" if over else "#d97706" if abs(drift) > 2 else "#374151"
        n = len(grp)
        tickers = ", ".join(grp["ticker"].tolist()) if not grp.empty else "—"
        rows += f"""
        <tr style="background:{bg}">
          <td style="padding:9px 14px;font-weight:600;color:#374151">{sleeve}</td>
          <td style="padding:9px 14px;text-align:center;color:#374151">{n}</td>
          <td style="padding:9px 14px;text-align:right;color:#6b7280">{target:.1f}%</td>
          <td style="padding:9px 14px;text-align:right;font-weight:700;color:#374151">{actual:.1f}%</td>
          <td style="padding:9px 14px;text-align:right;font-weight:700;color:{drift_c}">{drift:+.1f}%{flag}</td>
          <td style="padding:9px 14px;font-size:11px;color:#6b7280">{tickers[:60]}</td>
        </tr>"""
    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:{NAVY};color:white">
        <th style="padding:9px 14px;text-align:left">Sleeve</th>
        <th style="padding:9px 14px;text-align:center">N</th>
        <th style="padding:9px 14px;text-align:right">Target</th>
        <th style="padding:9px 14px;text-align:right">Actual</th>
        <th style="padding:9px 14px;text-align:right">Drift</th>
        <th style="padding:9px 14px;text-align:left">Holdings</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _s4_holdings_detail(port: pd.DataFrame) -> str:
    sorted_port = port.sort_values(
        ["ev_rank","alignment_score"], ascending=[True, False]
    )
    rows = ""
    for i, (_, r) in enumerate(sorted_port.iterrows()):
        q      = str(r.get("quadrant") or "N/A")
        bg     = _quad_bg(q)
        score  = r.get("alignment_score")
        sc_str = f"{score:.1f}" if pd.notna(score) else "—"
        sc_c   = "#16a34a" if (score and score >= 65) else "#d97706" if (score and score >= 35) else "#dc2626"
        warn   = r.get("migration_warning", 0)
        warn_html = '<span style="color:#dc2626;font-weight:700;font-size:11px"> ⚠</span>' if warn else ""
        pnl_pct = r.get("unrealized_pnl_pct", 0)
        pnl_c   = "#16a34a" if (pnl_pct and pnl_pct >= 0) else "#dc2626"
        drift   = r.get("weight_drift", 0)
        drift_c = _drift_color(drift)

        rows += f"""
        <tr style="background:{'#f9fafb' if i%2==0 else 'white'}">
          <td style="padding:9px 12px;font-weight:700;color:{NAVY[1:]}">{r.get('ticker','')}{warn_html}</td>
          <td style="padding:9px 12px;text-align:center">
            <span style="background:{_quad_bg(q)};color:{_quad_color(q)};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:700">{q}</span>
          </td>
          <td style="padding:9px 12px;text-align:center;color:#374151">{r.get('ev_rank','—')}</td>
          <td style="padding:9px 12px;text-align:center;font-weight:700;color:{sc_c}">{sc_str}</td>
          <td style="padding:9px 12px;text-align:center">{_bucket_badge(str(r.get('alignment_bucket','—')))}</td>
          <td style="padding:9px 12px;text-align:right;font-weight:600;color:#374151">{r.get('weight_actual',0):.1f}%</td>
          <td style="padding:9px 12px;text-align:right;color:#6b7280">{r.get('weight_target',0):.1f}%</td>
          <td style="padding:9px 12px;text-align:right;font-weight:600;color:{drift_c}">{drift:+.1f}%</td>
          <td style="padding:9px 12px;text-align:right;font-weight:600;color:{pnl_c}">{pnl_pct:+.1f}%</td>
          <td style="padding:9px 12px;text-align:right;color:#374151">${r.get('current_price',0):,.2f}</td>
          <td style="padding:9px 12px;text-align:right;color:#374151">${r.get('current_value',0):,.0f}</td>
          <td style="padding:9px 12px;text-align:center">{_vs_badge(str(r.get('vs_base_case','—')))}</td>
          <td style="padding:9px 12px;text-align:center">{_pead_badge(str(r.get('pead_flag','—')))}</td>
        </tr>"""

    return f"""
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:12px;min-width:900px">
      <thead><tr style="background:{NAVY};color:white">
        <th style="padding:9px 12px;text-align:left">Ticker</th>
        <th style="padding:9px 12px;text-align:center">Quad</th>
        <th style="padding:9px 12px;text-align:center">EV</th>
        <th style="padding:9px 12px;text-align:center">Score</th>
        <th style="padding:9px 12px;text-align:center">Bucket</th>
        <th style="padding:9px 12px;text-align:right">Actual%</th>
        <th style="padding:9px 12px;text-align:right">Target%</th>
        <th style="padding:9px 12px;text-align:right">Drift</th>
        <th style="padding:9px 12px;text-align:right">P&amp;L%</th>
        <th style="padding:9px 12px;text-align:right">Price</th>
        <th style="padding:9px 12px;text-align:right">Value</th>
        <th style="padding:9px 12px;text-align:center">vs Cost</th>
        <th style="padding:9px 12px;text-align:center">PEAD</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table></div>"""


def _s5_alerts(port: pd.DataFrame) -> str:
    warns    = port[port["migration_warning"] == 1] if "migration_warning" in port.columns else pd.DataFrame()
    distribs = port[port["alignment_bucket"] == "Distribute"] if "alignment_bucket" in port.columns else pd.DataFrame()
    drifts   = port[port["weight_drift"].abs() > 2] if "weight_drift" in port.columns else pd.DataFrame()

    def _cards(df, color, bg, label_fn):
        if df.empty:
            return f'<div style="color:#6b7280;font-style:italic;font-size:12px;padding:8px">None</div>'
        cards = ""
        for _, r in df.iterrows():
            cards += f"""
            <div style="background:{bg};border:1px solid {color}40;border-radius:10px;padding:12px;margin-bottom:8px">
              <div style="font-weight:700;color:{color};font-size:14px">{r.get('ticker','')}</div>
              <div style="font-size:12px;color:#374151;margin-top:3px">${r.get('current_value',0):,.0f} &nbsp;·&nbsp; {label_fn(r)}</div>
            </div>"""
        return cards

    warn_cards = _cards(warns,    "#dc2626", "#fee2e2",
        lambda r: f"Q{r.get('quadrant','?')} | Score {r.get('alignment_score',0):.1f} | Price within 10% of flip")
    dist_cards = _cards(distribs, "#991b1b", "#fee2e2",
        lambda r: f"Score {r.get('alignment_score',0):.1f} | P&L {r.get('unrealized_pnl_pct',0):+.1f}%")
    drift_cards = _cards(drifts,  "#d97706", "#fef3c7",
        lambda r: f"Drift {r.get('weight_drift',0):+.1f}% | Actual {r.get('weight_actual',0):.1f}% vs target {r.get('weight_target',0):.1f}%")

    return f"""
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:24px">
      <div>
        <div style="font-size:12px;font-weight:700;color:#dc2626;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px">
          Migration Warnings ({len(warns)})
        </div>
        {warn_cards}
      </div>
      <div>
        <div style="font-size:12px;font-weight:700;color:#991b1b;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px">
          Distribute Signals ({len(distribs)})
        </div>
        {dist_cards}
      </div>
      <div>
        <div style="font-size:12px;font-weight:700;color:#d97706;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px">
          Weight Drift >2% ({len(drifts)})
        </div>
        {drift_cards}
      </div>
    </div>"""


def _s6_mom_changes(port: pd.DataFrame, snapshot_date: str) -> str:
    """Compare current snapshot to most recent prior snapshot."""
    dates = get_portfolio_history_dates()
    prior_dates = [d for d in dates if d < snapshot_date]
    if not prior_dates:
        return '<p style="color:#6b7280;font-style:italic">No prior snapshot available for comparison.</p>'

    prior = get_portfolio(snapshot_date=prior_dates[0])
    if prior.empty:
        return '<p style="color:#6b7280;font-style:italic">Prior snapshot is empty.</p>'

    curr_tickers  = set(port["ticker"].tolist())
    prior_tickers = set(prior["ticker"].tolist())
    new_pos    = curr_tickers - prior_tickers
    closed_pos = prior_tickers - curr_tickers

    # Quad migrations
    curr_quads  = port.set_index("ticker")["quadrant"].to_dict()
    prior_quads = prior.set_index("ticker")["quadrant"].to_dict() if "quadrant" in prior.columns else {}
    migrations  = {t: (prior_quads[t], curr_quads[t])
                   for t in curr_quads
                   if t in prior_quads and prior_quads[t] != curr_quads[t]}

    # Weight changes
    curr_wts  = port.set_index("ticker")["weight_actual"].to_dict()
    prior_wts = prior.set_index("ticker")["weight_actual"].to_dict() if "weight_actual" in prior.columns else {}
    wt_changes = {t: (prior_wts[t], curr_wts[t])
                  for t in curr_wts
                  if t in prior_wts and abs(curr_wts[t] - prior_wts[t]) > 0.5}

    items = []
    for t in sorted(new_pos):
        items.append(f'<div style="padding:6px 12px;background:#dcfce7;border-radius:8px;margin-bottom:6px;font-size:12px"><strong style="color:#166534">NEW: {t}</strong></div>')
    for t in sorted(closed_pos):
        items.append(f'<div style="padding:6px 12px;background:#fee2e2;border-radius:8px;margin-bottom:6px;font-size:12px"><strong style="color:#991b1b">CLOSED: {t}</strong></div>')
    for t, (frm, to) in sorted(migrations.items()):
        q_c = _quad_color(to)
        items.append(f'<div style="padding:6px 12px;background:#f3f4f6;border-radius:8px;margin-bottom:6px;font-size:12px"><strong style="color:{q_c}">{t}</strong>: {frm} → {to}</div>')
    for t, (frm, to) in sorted(wt_changes.items(), key=lambda x: abs(x[1][1]-x[1][0]), reverse=True)[:10]:
        drift = to - frm
        c = "#16a34a" if drift > 0 else "#dc2626"
        items.append(f'<div style="padding:6px 12px;background:#f8fafc;border-radius:8px;margin-bottom:6px;font-size:12px">{t}: weight {frm:.1f}% → <strong style="color:{c}">{to:.1f}%</strong> ({drift:+.1f}pp)</div>')

    if not items:
        return '<p style="color:#6b7280;font-style:italic">No material changes since {prior_dates[0]}.</p>'

    return f"""
    <div style="font-size:12px;color:#6b7280;margin-bottom:12px">vs snapshot: {prior_dates[0]}</div>
    <div style="column-count:2;column-gap:20px">{"".join(items)}</div>"""


# ── Main generator ────────────────────────────────────────────────────────────

def generate_portfolio_memo(port: pd.DataFrame,
                             snapshot_date: str | None = None,
                             output_path: str | None = None) -> str:

    snapshot_date = snapshot_date or datetime.today().strftime("%Y-%m-%d")
    run_ts        = datetime.now().strftime("%B %d, %Y · %I:%M %p")

    total_value = port["current_value"].sum()
    avg_score   = port["alignment_score"].mean() if "alignment_score" in port.columns else 0
    avg_ev      = port["ev_rank"].mean() if "ev_rank" in port.columns else 0
    n           = len(port)
    warns_n     = int(port["migration_warning"].sum()) if "migration_warning" in port.columns else 0
    dist_n      = int((port["alignment_bucket"] == "Distribute").sum()) if "alignment_bucket" in port.columns else 0
    drift_n     = int((port["weight_drift"].abs() > 2).sum()) if "weight_drift" in port.columns else 0
    alerts_n    = warns_n + dist_n + drift_n
    total_pnl   = port["unrealized_pnl_dollar"].sum() if "unrealized_pnl_dollar" in port.columns else 0
    pnl_c       = "#16a34a" if total_pnl >= 0 else "#dc2626"

    hero_stats = [
        (n,                                    "Holdings"),
        (f"${total_value:,.0f}",               "Total Value"),
        (f"{avg_score:.1f}",                   "Avg Score"),
        (f"{avg_ev:.1f}",                      "Avg EV Rank"),
        (f'<span style="color:{pnl_c}">${total_pnl:,.0f}</span>', "Unrealized P&L"),
        (f'<span style="color:{"#dc2626" if alerts_n else "#16a34a"}">{alerts_n}</span>', "Alerts"),
    ]
    hero_html = "".join(f"""
    <div style="background:rgba(255,255,255,0.1);border-radius:12px;padding:16px;text-align:center">
      <div style="font-size:24px;font-weight:800;color:white;line-height:1">{v}</div>
      <div style="font-size:11px;color:rgba(255,255,255,0.6);margin-top:4px;text-transform:uppercase;letter-spacing:0.5px">{l}</div>
    </div>""" for v, l in hero_stats)

    nav_links = "".join(
        f'<a href="#{a}" style="color:rgba(255,255,255,0.8);text-decoration:none;font-size:13px;padding:6px 14px;border-radius:20px">{l}</a>'
        for a, l in [("quad","Quads"),("sector","Sectors"),("sleeve","Sleeves"),
                     ("holdings","Holdings"),("alerts","Alerts"),("mom","MoM")]
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Portfolio Memo · {snapshot_date}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>* {{box-sizing:border-box;margin:0;padding:0}} body {{font-family:'Source Sans 3',Calibri,sans-serif;background:#f1f5f9;color:#1e293b;-webkit-font-smoothing:antialiased}}</style>
</head>
<body>

<!-- NAV -->
<div style="background:linear-gradient(135deg,#1F3A5F,#2d5282);position:sticky;top:0;z-index:100;box-shadow:0 2px 12px rgba(0,0,0,0.2)">
  <div style="max-width:1300px;margin:0 auto;padding:0 32px;display:flex;align-items:center;justify-content:space-between;height:56px">
    <div style="display:flex;align-items:center;gap:14px">
      <div style="font-family:'Playfair Display',serif;font-size:17px;font-weight:800;color:white">Integrity Compounders</div>
      <div style="font-size:11px;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:1px">Portfolio Memo</div>
    </div>
    <nav style="display:flex;gap:2px">{nav_links}</nav>
    <div style="font-size:12px;color:rgba(255,255,255,0.7)">{snapshot_date}</div>
  </div>
</div>

<!-- HERO -->
<div style="background:linear-gradient(135deg,#1F3A5F,#2d5282);padding:28px 32px 24px">
  <div style="max-width:1300px;margin:0 auto">
    <div style="font-family:'Playfair Display',serif;font-size:28px;font-weight:800;color:white;margin-bottom:4px">Portfolio Memo</div>
    <div style="font-size:13px;color:rgba(255,255,255,0.6);margin-bottom:20px">
      {n} holdings · ${total_value:,.0f} · Avg Score {avg_score:.1f} · {alerts_n} alert(s) · Generated {run_ts}
    </div>
    <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:14px">{hero_html}</div>
  </div>
</div>

<!-- BODY -->
<div style="max-width:1300px;margin:0 auto;padding:28px 32px">

  {_section("Quad Distribution — Held Names",
    "Breakdown of portfolio positions by quadrant",
    _s1_quad_distribution(port), "quad")}

  {_section("Sector Exposure",
    f"28% sector cap · flag if over · {port['industry'].nunique() if 'industry' in port.columns else 0} sectors represented",
    _s2_sector_exposure(port), "sector")}

  {_section("Sleeve Allocation",
    "Target: Core 45% · Catalyst 30% · Rel Value 15% · Speculative 10% · Flag if >5pp off",
    _s3_sleeve_allocation(port), "sleeve")}

  {_section("Holdings Detail",
    f"All {n} positions · sorted by EV rank then Alignment Score · ⚠ = migration warning",
    _s4_holdings_detail(port), "holdings")}

  {_section("Alerts",
    f"{alerts_n} total alert(s): {warns_n} migration warning(s) · {dist_n} distribute signal(s) · {drift_n} drift(s)",
    _s5_alerts(port), "alerts")}

  {_section("Month-over-Month Changes",
    "Quad migrations · new/closed positions · weight changes vs prior snapshot",
    _s6_mom_changes(port, snapshot_date), "mom")}

</div>

<!-- FOOTER -->
<div style="background:#1F3A5F;color:rgba(255,255,255,0.5);text-align:center;padding:20px;font-size:12px;margin-top:8px">
  <div style="font-family:'Playfair Display',serif;font-size:15px;color:rgba(255,255,255,0.8);margin-bottom:4px">
    Integrity Compounders · Integrity Wealth Partners
  </div>
  <div>Alpha System v10.0 · {run_ts} · Internal Use Only</div>
</div>

<script>
  document.querySelectorAll('a[href^="#"]').forEach(a => {{
    a.addEventListener('click', e => {{
      e.preventDefault();
      const el = document.querySelector(a.getAttribute('href'));
      if (el) el.scrollIntoView({{behavior:'smooth',block:'start'}});
    }});
  }});
</script>
</body>
</html>"""

    if output_path is None:
        out_dir = ROOT / "outputs" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / f"portfolio_{snapshot_date}.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[Report] Saved: {output_path}")
    return output_path
