"""
reports.py — HTML Report Generator
Integrity Compounders Alpha System v9.1
Branding: Navy #1F3A5F | Calibri | US Letter proportions
"""

import sys
import json
import math
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

from engines.database import get_universe, get_last_snapshot_date, get_conn
from engines.screener import run_gates, screen_summary
from engines.quad import compute_axes, assign_quadrants, compute_migrations
from engines.pods import assign_pods, pod_distribution
from engines.alignment import compute_alignment, alignment_summary
from engines.fcf_flip import compute_flip_scores


def _pct(v, decimals=1):
    if pd.isna(v): return "—"
    return f"{v:.{decimals}f}%"

def _num(v, decimals=1):
    if pd.isna(v): return "—"
    return f"{v:.{decimals}f}"

def _price(v):
    if pd.isna(v): return "—"
    return f"${v:,.2f}"

def _mcap(v):
    if pd.isna(v): return "—"
    if v >= 1000: return f"${v/1000:.1f}T" if v >= 1000000 else f"${v/1000:.1f}B"
    return f"${v:.0f}M"

def _score(v):
    if pd.isna(v): return "—"
    return f"{v:.1f}"

def _quad_color(q):
    return {"Q1": "#2563eb", "Q2": "#16a34a", "Q3": "#dc2626", "Q4": "#d97706", "N/A": "#6b7280"}.get(q, "#6b7280")

def _quad_bg(q):
    return {"Q1": "#eff6ff", "Q2": "#f0fdf4", "Q3": "#fef2f2", "Q4": "#fffbeb", "N/A": "#f9fafb"}.get(q, "#f9fafb")

def _bucket_color(b):
    return {"Accumulate": "#16a34a", "Neutral": "#d97706", "Distribute": "#dc2626"}.get(b, "#6b7280")

def _pead_badge(p):
    colors = {
        "Strong PEAD":   ("#166534", "#dcfce7"),
        "PEAD Confirm":  ("#1e40af", "#dbeafe"),
        "PEAD Warn":     ("#92400e", "#fef3c7"),
        "Reverse PEAD":  ("#6b21a8", "#f3e8ff"),
        "—":             ("#6b7280", "#f3f4f6"),
    }
    fg, bg = colors.get(p, ("#6b7280", "#f3f4f6"))
    return f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap">{p}</span>'


def _build_scatter_svg(df: pd.DataFrame) -> str:
    """Generate inline SVG quad scatter chart."""
    W, H = 700, 480
    PAD = {"l": 60, "r": 20, "t": 40, "b": 50}
    IW = W - PAD["l"] - PAD["r"]
    IH = H - PAD["t"] - PAD["b"]

    X_MIN, X_MAX = -30, 15
    Y_MIN, Y_MAX = -5, 5

    def to_svg_x(x):
        x = max(X_MIN, min(X_MAX, x))
        return PAD["l"] + (x - X_MIN) / (X_MAX - X_MIN) * IW

    def to_svg_y(y):
        y = max(Y_MIN, min(Y_MAX, y))
        return PAD["t"] + (1 - (y - Y_MIN) / (Y_MAX - Y_MIN)) * IH

    cx = to_svg_x(0)
    cy = to_svg_y(0)

    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;font-family:Calibri,sans-serif">']

    # Quadrant fills
    quads = [
        (PAD["l"], PAD["t"], cx - PAD["l"], cy - PAD["t"], "#eff6ff", "Q1"),
        (cx, PAD["t"], W - PAD["r"] - cx, cy - PAD["t"], "#f0fdf4", "Q2"),
        (PAD["l"], cy, cx - PAD["l"], H - PAD["b"] - cy, "#fef2f2", "Q3"),
        (cx, cy, W - PAD["r"] - cx, H - PAD["b"] - cy, "#fffbeb", "Q4"),
    ]
    for x, y, w, h, fill, label in quads:
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" opacity="0.7"/>')

    # Quad labels
    quad_labels = [
        (PAD["l"] + 6, PAD["t"] + 16, "Q1 Trending Quality", "#2563eb"),
        (cx + 6, PAD["t"] + 16, "Q2 Hidden Value / GARP", "#16a34a"),
        (PAD["l"] + 6, cy + 16, "Q3 Narrative Rally", "#dc2626"),
        (cx + 6, cy + 16, "Q4 Reset / Drawdown", "#d97706"),
    ]
    for x, y, text, color in quad_labels:
        parts.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="11" font-weight="700" opacity="0.8">{text}</text>')

    # Grid lines
    for xv in [-20, -10, 0, 5, 10]:
        sx = to_svg_x(xv)
        parts.append(f'<line x1="{sx}" y1="{PAD["t"]}" x2="{sx}" y2="{H-PAD["b"]}" stroke="#d1d5db" stroke-width="0.5" stroke-dasharray="3,3"/>')
    for yv in [-4, -2, 0, 2, 4]:
        sy = to_svg_y(yv)
        parts.append(f'<line x1="{PAD["l"]}" y1="{sy}" x2="{W-PAD["r"]}" y2="{sy}" stroke="#d1d5db" stroke-width="0.5" stroke-dasharray="3,3"/>')

    # Axes
    parts.append(f'<line x1="{PAD["l"]}" y1="{cy}" x2="{W-PAD["r"]}" y2="{cy}" stroke="#1F3A5F" stroke-width="1.5"/>')
    parts.append(f'<line x1="{cx}" y1="{PAD["t"]}" x2="{cx}" y2="{H-PAD["b"]}" stroke="#1F3A5F" stroke-width="1.5"/>')

    # Axis labels
    parts.append(f'<text x="{W//2}" y="{H-8}" text-anchor="middle" fill="#374151" font-size="12" font-weight="600">Earnings Momentum ROC →</text>')
    parts.append(f'<text x="14" y="{H//2}" text-anchor="middle" fill="#374151" font-size="12" font-weight="600" transform="rotate(-90,14,{H//2})">Multiple ROC →</text>')

    # Tick labels X
    for xv in [-20, -10, 0, 5, 10]:
        sx = to_svg_x(xv)
        parts.append(f'<text x="{sx}" y="{H-PAD["b"]+14}" text-anchor="middle" fill="#6b7280" font-size="9">{xv}%</text>')
    for yv in [-4, -2, 0, 2, 4]:
        sy = to_svg_y(yv)
        parts.append(f'<text x="{PAD["l"]-4}" y="{sy+4}" text-anchor="end" fill="#6b7280" font-size="9">{yv}%</text>')

    # Plot points
    plotted = df[df["quadrant"].isin(["Q1", "Q2", "Q3", "Q4"])].copy()
    plotted = plotted[plotted["earnings_mom_roc"].notna() & plotted["multiple_roc"].notna()]

    # Scale dot size by alignment score
    for _, row in plotted.iterrows():
        x_raw = row["earnings_mom_roc"] * 100
        y_raw = row["multiple_roc"] * 100
        is_clipped = x_raw < X_MIN or x_raw > X_MAX or y_raw < Y_MIN or y_raw > Y_MAX
        sx = to_svg_x(x_raw)
        sy = to_svg_y(y_raw)
        color = _quad_color(row["quadrant"])
        score = row.get("alignment_score", 50) or 50
        r = 3 + (score / 100) * 4

        ticker = row["ticker"]
        quad = row["quadrant"]
        align = f"{score:.0f}"

        if is_clipped:
            # Triangle marker for outliers
            size = 6
            pts = f"{sx},{sy-size} {sx-size},{sy+size} {sx+size},{sy+size}"
            parts.append(f'<polygon points="{pts}" fill="{color}" opacity="0.75"><title>{ticker} ({quad}) Align:{align}</title></polygon>')
        else:
            parts.append(f'<circle cx="{sx}" cy="{sy}" r="{r:.1f}" fill="{color}" opacity="0.75" stroke="white" stroke-width="0.5"><title>{ticker} ({quad}) Align:{align}</title></circle>')

        # Label top names only (Q2 Accumulate + Q1 Accumulate)
        if row.get("alignment_bucket") == "Accumulate" and row["quadrant"] in ("Q1", "Q2"):
            parts.append(f'<text x="{sx+r+2}" y="{sy+4}" fill="{color}" font-size="9" font-weight="700">{ticker}</text>')

    parts.append('</svg>')
    return "\n".join(parts)


def _quad_summary_cards(df: pd.DataFrame) -> str:
    counts = df["quadrant"].value_counts().to_dict()
    total = len(df)
    cards = [
        ("Q2", "Hidden Value / GARP", "Best EV", "#16a34a", "#f0fdf4"),
        ("Q1", "Trending Quality", "Good EV", "#2563eb", "#eff6ff"),
        ("Q4", "Reset / Drawdown", "Watch", "#d97706", "#fffbeb"),
        ("Q3", "Narrative Rally", "Avoid", "#dc2626", "#fef2f2"),
    ]
    html = '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px">'
    for q, label, tag, color, bg in cards:
        n = counts.get(q, 0)
        pct = n / max(total, 1) * 100
        html += f"""
        <div style="background:{bg};border:1.5px solid {color}30;border-radius:12px;padding:20px;text-align:center">
            <div style="font-size:11px;font-weight:700;color:{color};text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">{q} · {tag}</div>
            <div style="font-size:36px;font-weight:800;color:{color};line-height:1">{n}</div>
            <div style="font-size:12px;color:#6b7280;margin-top:4px">{label}</div>
            <div style="font-size:11px;color:{color};margin-top:6px;font-weight:600">{pct:.1f}% of universe</div>
        </div>"""
    html += '</div>'
    return html


def _gate_bars(summary: dict) -> str:
    gates = [
        ("Quality", "ROIC ≥ 12", summary["gate_pass_rates"].get("quality", 0), False),
        ("Durability", "Op Margin ≥ 25 ⚑", summary["gate_pass_rates"].get("durability", 0), True),
        ("Cash Conv", "FCF Yield ≥ 3 ⚑", summary["gate_pass_rates"].get("cash_conv", 0), True),
        ("Reinvestment", "Rev 3Y CAGR ≥ 6", summary["gate_pass_rates"].get("reinvestment", 0), False),
        ("Balance Sheet", "ND/EBITDA ≤ 2.5", summary["gate_pass_rates"].get("balance_sheet", 0), False),
    ]
    html = ""
    for name, rule, rate, is_proxy in gates:
        pct = rate * 100
        color = "#16a34a" if pct >= 60 else "#d97706" if pct >= 40 else "#dc2626"
        proxy_tag = '<span style="font-size:10px;color:#d97706;margin-left:4px">proxy</span>' if is_proxy else ""
        html += f"""
        <div style="margin-bottom:12px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
                <span style="font-size:13px;font-weight:600;color:#1F3A5F">{name}{proxy_tag}</span>
                <span style="font-size:12px;color:#6b7280">{rule}</span>
                <span style="font-size:14px;font-weight:700;color:{color}">{pct:.1f}%</span>
            </div>
            <div style="background:#e5e7eb;border-radius:4px;height:6px">
                <div style="background:{color};width:{pct:.1f}%;height:6px;border-radius:4px;transition:width 0.3s"></div>
            </div>
        </div>"""
    return html


def _q2_table(df: pd.DataFrame) -> str:
    q2 = df[df["quadrant"] == "Q2"].sort_values("alignment_score", ascending=False)
    if q2.empty:
        return '<p style="color:#6b7280;font-style:italic">No Q2 names in current universe.</p>'

    rows = ""
    for i, (_, r) in enumerate(q2.iterrows()):
        bg = "#f9fafb" if i % 2 == 0 else "white"
        score = r.get("alignment_score", 0)
        score_color = "#16a34a" if score >= 65 else "#d97706" if score >= 35 else "#dc2626"
        rows += f"""
        <tr style="background:{bg}">
            <td style="padding:10px 12px;font-weight:700;color:#1F3A5F">{r['ticker']}</td>
            <td style="padding:10px 12px;color:#374151;font-size:12px">{str(r.get('company',''))[:28]}</td>
            <td style="padding:10px 12px;color:#374151;font-size:11px">{str(r.get('industry',''))[:22]}</td>
            <td style="padding:10px 12px;text-align:center;font-weight:700;color:{score_color}">{_score(score)}</td>
            <td style="padding:10px 12px;text-align:center">{_pead_badge(r.get('pead_flag','—'))}</td>
            <td style="padding:10px 12px;text-align:right;color:#374151">{_num(r.get('earnings_mom_roc',0)*100)}</td>
            <td style="padding:10px 12px;text-align:right;color:#374151">{_num(r.get('multiple_roc',0)*100)}</td>
            <td style="padding:10px 12px;text-align:right;color:#374151">{_price(r.get('stock_price'))}</td>
            <td style="padding:10px 12px;text-align:right;color:#374151">{_mcap(r.get('market_cap'))}</td>
            <td style="padding:10px 12px;text-align:center;font-size:12px;color:#6b7280">{_score(r.get('flip_score_pct',0))}</td>
        </tr>"""

    return f"""
    <table style="width:100%;border-collapse:collapse;font-family:Calibri,sans-serif;font-size:13px">
        <thead>
            <tr style="background:#1F3A5F;color:white">
                <th style="padding:10px 12px;text-align:left;font-weight:600">Ticker</th>
                <th style="padding:10px 12px;text-align:left;font-weight:600">Company</th>
                <th style="padding:10px 12px;text-align:left;font-weight:600">Industry</th>
                <th style="padding:10px 12px;text-align:center;font-weight:600">Align</th>
                <th style="padding:10px 12px;text-align:center;font-weight:600">PEAD</th>
                <th style="padding:10px 12px;text-align:right;font-weight:600">X-Axis</th>
                <th style="padding:10px 12px;text-align:right;font-weight:600">Y-Axis</th>
                <th style="padding:10px 12px;text-align:right;font-weight:600">Price</th>
                <th style="padding:10px 12px;text-align:right;font-weight:600">Mkt Cap</th>
                <th style="padding:10px 12px;text-align:center;font-weight:600">Flip%</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>"""


def _alignment_table(df: pd.DataFrame) -> str:
    buckets = [("Accumulate", "#16a34a", "#f0fdf4"), ("Neutral", "#d97706", "#fffbeb"), ("Distribute", "#dc2626", "#fef2f2")]
    sections = ""
    for bucket, color, bg in buckets:
        sub = df[df["alignment_bucket"] == bucket].sort_values("alignment_score", ascending=(bucket == "Distribute"))
        if sub.empty: continue
        rows = ""
        for i, (_, r) in enumerate(sub.iterrows()):
            rbg = "#f9fafb" if i % 2 == 0 else "white"
            rows += f"""
            <tr style="background:{rbg}">
                <td style="padding:8px 12px;font-weight:700;color:#1F3A5F">{r['ticker']}</td>
                <td style="padding:8px 12px;font-size:12px;color:#374151">{str(r.get('company',''))[:24]}</td>
                <td style="padding:8px 12px;text-align:center">
                    <span style="background:{_quad_bg(r['quadrant'])};color:{_quad_color(r['quadrant'])};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:700">{r['quadrant']}</span>
                </td>
                <td style="padding:8px 12px;text-align:center;font-weight:700;color:{color}">{_score(r.get('alignment_score'))}</td>
                <td style="padding:8px 12px;text-align:center">{_pead_badge(r.get('pead_flag','—'))}</td>
                <td style="padding:8px 12px;text-align:right;font-size:12px;color:#6b7280">{_num(r.get('fv_rank'))}</td>
                <td style="padding:8px 12px;text-align:right;font-size:12px;color:#6b7280">{_num(r.get('mc_rank'))}</td>
                <td style="padding:8px 12px;text-align:right;font-size:12px;color:#6b7280">{_num(r.get('vc_rank'))}</td>
                <td style="padding:8px 12px;text-align:right;font-size:12px;color:#6b7280">{_num(r.get('esv_rank'))}</td>
            </tr>"""
        sections += f"""
        <div style="margin-bottom:24px">
            <div style="background:{color};color:white;padding:8px 16px;border-radius:8px 8px 0 0;font-weight:700;font-size:13px;display:flex;justify-content:space-between">
                <span>{bucket}</span><span>{len(sub)} names</span>
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:12px">
                <thead><tr style="background:{bg}">
                    <th style="padding:8px 12px;text-align:left;color:{color}">Ticker</th>
                    <th style="padding:8px 12px;text-align:left;color:{color}">Company</th>
                    <th style="padding:8px 12px;text-align:center;color:{color}">Quad</th>
                    <th style="padding:8px 12px;text-align:center;color:{color}">Score</th>
                    <th style="padding:8px 12px;text-align:center;color:{color}">PEAD</th>
                    <th style="padding:8px 12px;text-align:right;color:{color}">FV</th>
                    <th style="padding:8px 12px;text-align:right;color:{color}">MC</th>
                    <th style="padding:8px 12px;text-align:right;color:{color}">VC</th>
                    <th style="padding:8px 12px;text-align:right;color:{color}">ESV</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>"""
    return sections


def _flip_table(df: pd.DataFrame, top_n: int = 20) -> str:
    top = df.sort_values("flip_score", ascending=False).head(top_n)
    rows = ""
    for i, (_, r) in enumerate(top.iterrows()):
        bg = "#f9fafb" if i % 2 == 0 else "white"
        setup = r.get("flip_setup_type", "—")
        setup_color = "#16a34a" if setup == "Value Re-rate Underway" else "#d97706" if "Watch" in str(setup) else "#6b7280"
        rows += f"""
        <tr style="background:{bg}">
            <td style="padding:9px 12px;font-weight:700;color:#1F3A5F">{r['ticker']}</td>
            <td style="padding:9px 12px;font-size:12px;color:#374151">{str(r.get('company',''))[:22]}</td>
            <td style="padding:9px 12px;text-align:center">
                <span style="background:{_quad_bg(r['quadrant'])};color:{_quad_color(r['quadrant'])};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:700">{r['quadrant']}</span>
            </td>
            <td style="padding:9px 12px;text-align:center;font-weight:700;color:#1F3A5F">{_score(r.get('flip_score_pct'))}</td>
            <td style="padding:9px 12px;text-align:right;color:#374151">{_pct(r.get('fcf_yield',0))}</td>
            <td style="padding:9px 12px;text-align:right;color:#374151">{_pct(r.get('fwd_fcf_yield',0))}</td>
            <td style="padding:9px 12px;text-align:right;color:#374151">{_pct(r.get('tr_1m',0))}</td>
            <td style="padding:9px 12px;font-size:11px;color:{setup_color};font-weight:600">{setup}</td>
            <td style="padding:9px 12px;font-size:11px;color:#6b7280">{r.get('options_structure','—')}</td>
        </tr>"""
    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:12px">
        <thead><tr style="background:#1F3A5F;color:white">
            <th style="padding:9px 12px;text-align:left">Ticker</th>
            <th style="padding:9px 12px;text-align:left">Company</th>
            <th style="padding:9px 12px;text-align:center">Quad</th>
            <th style="padding:9px 12px;text-align:center">Score</th>
            <th style="padding:9px 12px;text-align:right">FCF Yld</th>
            <th style="padding:9px 12px;text-align:right">Fwd Yld</th>
            <th style="padding:9px 12px;text-align:right">1M Ret</th>
            <th style="padding:9px 12px;text-align:left">Setup</th>
            <th style="padding:9px 12px;text-align:left">Structure</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def _pod_table(df: pd.DataFrame) -> str:
    dist = pod_distribution(df)
    rows = ""
    for i, (_, r) in enumerate(dist.iterrows()):
        bg = "#f9fafb" if i % 2 == 0 else "white"
        bar_w = int(r["pct"] * 200)
        rows += f"""
        <tr style="background:{bg}">
            <td style="padding:9px 12px;font-weight:600;color:#1F3A5F">{r['pod']}</td>
            <td style="padding:9px 12px;text-align:center;font-weight:700;color:#374151">{r['count']}</td>
            <td style="padding:9px 12px;text-align:center;color:#6b7280">{r['pct']*100:.1f}%</td>
            <td style="padding:9px 12px">
                <div style="background:#e5e7eb;border-radius:3px;height:8px;width:200px">
                    <div style="background:#1F3A5F;width:{bar_w}px;height:8px;border-radius:3px"></div>
                </div>
            </td>
            <td style="padding:9px 12px;text-align:right;color:#374151">{_pct(r.get('avg_roic',0)*100) if pd.notna(r.get('avg_roic')) else '—'}</td>
            <td style="padding:9px 12px;text-align:right;color:#374151">{_pct(r.get('avg_fcf_yield',0)*100) if pd.notna(r.get('avg_fcf_yield')) else '—'}</td>
        </tr>"""
    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:#1F3A5F;color:white">
            <th style="padding:9px 12px;text-align:left">Pod</th>
            <th style="padding:9px 12px;text-align:center">Count</th>
            <th style="padding:9px 12px;text-align:center">% Universe</th>
            <th style="padding:9px 12px;text-align:left">Distribution</th>
            <th style="padding:9px 12px;text-align:right">Avg ROIC</th>
            <th style="padding:9px 12px;text-align:right">Avg FCF Yld</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def _migration_section() -> str:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT logged_at, ticker, company, from_quad, to_quad,
                      severity, alignment_score, pead_flag
               FROM migration_log ORDER BY logged_at DESC LIMIT 20"""
        ).fetchall()
    if not rows:
        return '<p style="color:#6b7280;font-style:italic;padding:20px">No migrations recorded yet. Run refresh again next month to begin tracking changes.</p>'

    html_rows = ""
    for i, r in enumerate(rows):
        bg = "#f9fafb" if i % 2 == 0 else "white"
        sev = str(r["severity"] or "")
        sev_color = "#dc2626" if "DANGEROUS" in sev else "#16a34a" if "FAVORABLE" in sev else "#d97706" if "CONSTRUCTIVE" in sev else "#6b7280"
        from_q = str(r["from_quad"] or "—")
        to_q = str(r["to_quad"] or "—")
        html_rows += f"""
        <tr style="background:{bg}">
            <td style="padding:9px 12px;color:#6b7280;font-size:12px">{str(r['logged_at'])[:10]}</td>
            <td style="padding:9px 12px;font-weight:700;color:#1F3A5F">{r['ticker']}</td>
            <td style="padding:9px 12px;font-size:12px;color:#374151">{str(r['company'] or '')[:24]}</td>
            <td style="padding:9px 12px;text-align:center">
                <span style="color:{_quad_color(from_q)};font-weight:700">{from_q}</span>
                <span style="color:#9ca3af;margin:0 4px">→</span>
                <span style="color:{_quad_color(to_q)};font-weight:700">{to_q}</span>
            </td>
            <td style="padding:9px 12px;font-weight:700;color:{sev_color};font-size:12px">{sev.split('—')[0].strip()}</td>
            <td style="padding:9px 12px;text-align:center;color:#374151">{f"{r['alignment_score']:.1f}" if r['alignment_score'] else '—'}</td>
            <td style="padding:9px 12px;text-align:center">{_pead_badge(r['pead_flag'] or '—')}</td>
        </tr>"""

    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:#1F3A5F;color:white">
            <th style="padding:9px 12px;text-align:left">Date</th>
            <th style="padding:9px 12px;text-align:left">Ticker</th>
            <th style="padding:9px 12px;text-align:left">Company</th>
            <th style="padding:9px 12px;text-align:center">Migration</th>
            <th style="padding:9px 12px;text-align:left">Severity</th>
            <th style="padding:9px 12px;text-align:center">Align</th>
            <th style="padding:9px 12px;text-align:center">PEAD</th>
        </tr></thead>
        <tbody>{html_rows}</tbody>
    </table>"""


def _section(title: str, subtitle: str, content: str, anchor: str = "") -> str:
    return f"""
    <div id="{anchor}" style="background:white;border-radius:16px;padding:32px;margin-bottom:28px;box-shadow:0 1px 3px rgba(0,0,0,0.08);border:1px solid #e5e7eb">
        <div style="border-left:4px solid #1F3A5F;padding-left:16px;margin-bottom:24px">
            <h2 style="margin:0;font-size:20px;font-weight:800;color:#1F3A5F;letter-spacing:-0.3px">{title}</h2>
            <p style="margin:4px 0 0;font-size:13px;color:#6b7280">{subtitle}</p>
        </div>
        {content}
    </div>"""


def generate_report(output_path: str | None = None) -> str:
    """Generate the full HTML report and return the path."""

    # ── Load and compute ──────────────────────────────────────────────────────
    df = get_universe("all")
    df = run_gates(df)
    df = compute_axes(df)
    df = assign_quadrants(df)
    df = assign_pods(df)
    df = compute_alignment(df)
    df = compute_flip_scores(df)

    data_date = get_last_snapshot_date() or datetime.today().strftime("%Y-%m-%d")
    run_ts = datetime.now().strftime("%B %d, %Y · %I:%M %p")
    universe_n = len(df)
    screen = screen_summary(df)
    align = alignment_summary(df)
    quad_counts = df["quadrant"].value_counts().to_dict()

    # ── Build HTML ────────────────────────────────────────────────────────────
    scatter_svg = _build_scatter_svg(df)

    # Nav items
    nav_items = [
        ("#overview", "Overview"),
        ("#scatter", "Quad Chart"),
        ("#q2", "Q2 Names"),
        ("#alignment", "Alignment"),
        ("#flip", "Flip Screen"),
        ("#pods", "Pods"),
        ("#migrations", "Migrations"),
    ]
    nav_html = "".join(
        f'<a href="{href}" style="color:rgba(255,255,255,0.8);text-decoration:none;font-size:13px;font-weight:500;padding:6px 14px;border-radius:20px;transition:background 0.2s" '
        f'onmouseover="this.style.background=\'rgba(255,255,255,0.15)\'" onmouseout="this.style.background=\'transparent\'">{label}</a>'
        for href, label in nav_items
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Integrity Compounders · Alpha Report · {data_date}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Source Sans 3', Calibri, sans-serif; background: #f1f5f9; color: #1e293b; -webkit-font-smoothing: antialiased; }}
  @media print {{ body {{ background: white; }} .no-print {{ display: none; }} }}
</style>
</head>
<body>

<!-- HEADER / NAV -->
<div style="background:linear-gradient(135deg,#1F3A5F 0%,#2d5282 60%,#1a365d 100%);padding:0;position:sticky;top:0;z-index:100;box-shadow:0 2px 12px rgba(0,0,0,0.2)">
  <div style="max-width:1200px;margin:0 auto;padding:0 32px">
    <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 0">
      <div style="display:flex;align-items:center;gap:16px">
        <div style="width:36px;height:36px;background:rgba(255,255,255,0.15);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px">⬡</div>
        <div>
          <div style="font-family:'Playfair Display',serif;font-size:18px;font-weight:800;color:white;letter-spacing:-0.3px">Integrity Compounders</div>
          <div style="font-size:11px;color:rgba(255,255,255,0.6);letter-spacing:1px;text-transform:uppercase">Alpha System v9.1</div>
        </div>
      </div>
      <nav style="display:flex;gap:4px;align-items:center">{nav_html}</nav>
      <div style="text-align:right">
        <div style="font-size:12px;color:rgba(255,255,255,0.5)">Data: Fiscal AI</div>
        <div style="font-size:12px;color:rgba(255,255,255,0.8);font-weight:600">{data_date}</div>
      </div>
    </div>
  </div>
</div>

<!-- HERO BAND -->
<div style="background:linear-gradient(135deg,#1F3A5F,#2d5282);padding:40px 32px 32px">
  <div style="max-width:1200px;margin:0 auto">
    <div style="font-family:'Playfair Display',serif;font-size:32px;font-weight:800;color:white;margin-bottom:6px;letter-spacing:-0.5px">
      Monthly Alpha Report
    </div>
    <div style="font-size:14px;color:rgba(255,255,255,0.6);margin-bottom:28px">
      Generated {run_ts} · Universe: {universe_n} names · Integrity Wealth Partners
    </div>
    <!-- Hero stat strip -->
    <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:16px">
      {"".join(f'''
      <div style="background:rgba(255,255,255,0.1);border-radius:12px;padding:16px;text-align:center;backdrop-filter:blur(4px)">
        <div style="font-size:28px;font-weight:800;color:white;line-height:1">{val}</div>
        <div style="font-size:11px;color:rgba(255,255,255,0.6);margin-top:4px;text-transform:uppercase;letter-spacing:0.5px">{label}</div>
      </div>''' for val, label in [
        (universe_n, "Universe"),
        (quad_counts.get('Q2',0), "Q2 Names"),
        (quad_counts.get('Q1',0), "Q1 Names"),
        (align['accumulate'], "Accumulate"),
        (align['strong_pead'], "Strong PEAD"),
        (f"{screen['survival_rate']*100:.0f}%", "5-Gate Pass"),
      ])}
    </div>
  </div>
</div>

<!-- MAIN CONTENT -->
<div style="max-width:1200px;margin:0 auto;padding:32px">

  <!-- OVERVIEW -->
  {_section("Universe Overview", f"Five-gate quality screen · {data_date} snapshot",
    f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:32px">
      <div>
        <h3 style="font-size:14px;font-weight:700;color:#1F3A5F;margin-bottom:16px;text-transform:uppercase;letter-spacing:0.5px">Five-Gate Screen Results</h3>
        {_gate_bars(screen)}
        <div style="margin-top:16px;padding:12px 16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0">
          <div style="display:flex;justify-content:space-between;margin-bottom:6px">
            <span style="font-size:13px;color:#6b7280">Active (all 5 pass)</span>
            <span style="font-weight:700;color:#16a34a">{screen['active']} ({screen['survival_rate']*100:.1f}%)</span>
          </div>
          <div style="display:flex;justify-content:space-between;margin-bottom:6px">
            <span style="font-size:13px;color:#6b7280">Watch (1 gate fails)</span>
            <span style="font-weight:700;color:#d97706">{screen['watch']}</span>
          </div>
          <div style="display:flex;justify-content:space-between">
            <span style="font-size:13px;color:#6b7280">EPS CAGR capped (&gt;25%)</span>
            <span style="font-weight:700;color:#6b7280">{screen['eps_cagr_capped']}</span>
          </div>
        </div>
        <p style="font-size:11px;color:#9ca3af;margin-top:8px">⚑ Proxy: Op Margin used for Gross Margin; FCF Yield used for FCF Margin (not in Fiscal AI export)</p>
      </div>
      <div>
        <h3 style="font-size:14px;font-weight:700;color:#1F3A5F;margin-bottom:16px;text-transform:uppercase;letter-spacing:0.5px">Quadrant Distribution</h3>
        {_quad_summary_cards(df)}
        <div style="padding:12px 16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0">
          <div style="font-size:12px;color:#6b7280;margin-bottom:8px;font-weight:600">Alignment Score Distribution</div>
          <div style="display:flex;gap:16px">
            <div style="text-align:center"><div style="font-size:22px;font-weight:800;color:#16a34a">{align['accumulate']}</div><div style="font-size:11px;color:#6b7280">Accumulate</div></div>
            <div style="text-align:center"><div style="font-size:22px;font-weight:800;color:#d97706">{align['neutral']}</div><div style="font-size:11px;color:#6b7280">Neutral</div></div>
            <div style="text-align:center"><div style="font-size:22px;font-weight:800;color:#dc2626">{align['distribute']}</div><div style="font-size:11px;color:#6b7280">Distribute</div></div>
            <div style="text-align:center"><div style="font-size:22px;font-weight:800;color:#166534">{align['strong_pead']}</div><div style="font-size:11px;color:#6b7280">Strong PEAD</div></div>
          </div>
        </div>
      </div>
    </div>""", "overview")}

  <!-- SCATTER CHART -->
  {_section("Stock-Level Quad Chart",
    "X-Axis: Earnings Momentum ROC · Y-Axis: Multiple ROC · Size: Alignment Score · Labels: Q1/Q2 Accumulate names",
    f'<div style="background:#fafafa;border-radius:12px;padding:16px;border:1px solid #e5e7eb">{scatter_svg}</div>'
    + f"""
    <div style="display:flex;gap:24px;margin-top:16px;flex-wrap:wrap">
      {"".join(f'<div style="display:flex;align-items:center;gap:8px"><div style="width:12px;height:12px;border-radius:50%;background:{color}"></div><span style="font-size:12px;color:#374151">{label}</span></div>'
        for color, label in [("#2563eb","Q1 Trending Quality"),("#16a34a","Q2 Hidden Value / GARP"),("#dc2626","Q3 Narrative Rally"),("#d97706","Q4 Reset / Drawdown")])}
      <div style="display:flex;align-items:center;gap:8px"><div style="width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;border-bottom:10px solid #6b7280"></div><span style="font-size:12px;color:#374151">Clipped outlier</span></div>
    </div>""", "scatter")}

  <!-- Q2 LIST -->
  {_section("Q2 · Hidden Value / GARP",
    f"Earnings accelerating + multiple de-rating · EV Rank 1 (Best) · {quad_counts.get('Q2',0)} names · Sorted by Alignment Score",
    _q2_table(df), "q2")}

  <!-- ALIGNMENT SCORE -->
  {_section("Compounders Alignment Score",
    "4-Signal convergence: Fundamental Velocity 35% · Market Conviction 30% · Valuation Confirmation 20% · ESV 15%",
    _alignment_table(df), "alignment")}

  <!-- FCF FLIP -->
  {_section("FCF Yield Flip Screen · Options Candidates",
    "Satellite framework · Composite: FCF Yield 40% + Yield Decline 35% + Reverse Price Momentum 25% · Defined-risk structures only",
    _flip_table(df), "flip")}

  <!-- PODS -->
  {_section("Business-Model Pod Distribution",
    "Deterministic waterfall · First-match wins · Preserves factor exposure context at portfolio construction layer",
    _pod_table(df), "pods")}

  <!-- MIGRATIONS -->
  {_section("Quad Migration Log",
    "Auto-logged on every refresh · DANGEROUS = Q4→Q3 (narrative trap) · Requires two consecutive months to confirm",
    _migration_section(), "migrations")}

</div>

<!-- FOOTER -->
<div style="background:#1F3A5F;color:rgba(255,255,255,0.5);text-align:center;padding:24px;font-size:12px;margin-top:16px">
  <div style="font-family:'Playfair Display',serif;font-size:16px;color:rgba(255,255,255,0.8);margin-bottom:6px">Integrity Compounders · Integrity Wealth Partners</div>
  <div>Alpha System v9.1 · Generated {run_ts} · Data: Fiscal AI · Internal Use Only</div>
  <div style="margin-top:8px;font-size:11px">Q2 (EV Rank 1) → Q1 (2) → Q4 (3) → Q3 (4) · Two consecutive months required to confirm quad migrations</div>
</div>

<script>
  // Smooth scroll for nav links
  document.querySelectorAll('a[href^="#"]').forEach(a => {{
    a.addEventListener('click', e => {{
      e.preventDefault();
      const el = document.querySelector(a.getAttribute('href'));
      if (el) el.scrollIntoView({{behavior:'smooth', block:'start'}});
    }});
  }});
</script>
</body>
</html>"""

    # ── Save ──────────────────────────────────────────────────────────────────
    if output_path is None:
        out_dir = ROOT / "outputs" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / f"integrity_compounders_{data_date}.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[Report] Saved: {output_path}")
    return output_path


def _q1q2_combined_table(df: pd.DataFrame) -> str:
    """Combined Q1 + Q2 table sorted by alignment score desc, then PEAD priority."""
    pead_order = {"Strong PEAD": 0, "PEAD Confirm": 1, "PEAD Warn": 2, "Reverse PEAD": 3, "—": 4}
    sub = df[df["quadrant"].isin(["Q1", "Q2"])].copy()
    sub["_pead_rank"] = sub["pead_flag"].map(lambda x: pead_order.get(x, 9))
    sub = sub.sort_values(["alignment_score", "_pead_rank"], ascending=[False, True])

    if sub.empty:
        return '<p style="color:#6b7280;font-style:italic">No Q1 or Q2 names in current universe.</p>'

    rows = ""
    for i, (_, r) in enumerate(sub.iterrows()):
        bg = "#f9fafb" if i % 2 == 0 else "white"
        score = r.get("alignment_score", 0)
        score_color = "#16a34a" if score >= 65 else "#d97706" if score >= 35 else "#dc2626"
        q = r["quadrant"]
        rows += f"""
        <tr style="background:{bg}">
            <td style="padding:10px 12px;font-weight:700;color:#1F3A5F">{r['ticker']}</td>
            <td style="padding:10px 12px;color:#374151;font-size:12px">{str(r.get('company',''))[:28]}</td>
            <td style="padding:10px 12px;font-size:11px;color:#6b7280">{str(r.get('industry',''))[:22]}</td>
            <td style="padding:10px 12px;text-align:center">
                <span style="background:{_quad_bg(q)};color:{_quad_color(q)};padding:2px 10px;border-radius:10px;font-size:11px;font-weight:700">{q}</span>
            </td>
            <td style="padding:10px 12px;text-align:center;font-weight:700;color:{score_color}">{_score(score)}</td>
            <td style="padding:10px 12px;text-align:center">{_pead_badge(r.get('pead_flag','—'))}</td>
            <td style="padding:10px 12px;text-align:center;font-size:12px;color:#6b7280">{r.get('alignment_bucket','—')}</td>
            <td style="padding:10px 12px;text-align:right;color:#374151">{_num(r.get('earnings_mom_roc',0)*100)}</td>
            <td style="padding:10px 12px;text-align:right;color:#374151">{_num(r.get('multiple_roc',0)*100)}</td>
            <td style="padding:10px 12px;text-align:center;font-size:11px;color:#374151">{r.get('ev_rank','—')}</td>
            <td style="padding:10px 12px;text-align:right;color:#374151">{_price(r.get('stock_price'))}</td>
            <td style="padding:10px 12px;text-align:right;color:#374151">{_mcap(r.get('market_cap'))}</td>
            <td style="padding:10px 12px;text-align:center;font-size:12px;color:#6b7280">{_score(r.get('flip_score_pct',0))}</td>
        </tr>"""

    return f"""
    <table style="width:100%;border-collapse:collapse;font-family:Calibri,sans-serif;font-size:13px">
        <thead>
            <tr style="background:#1F3A5F;color:white">
                <th style="padding:10px 12px;text-align:left;font-weight:600">Ticker</th>
                <th style="padding:10px 12px;text-align:left;font-weight:600">Company</th>
                <th style="padding:10px 12px;text-align:left;font-weight:600">Industry</th>
                <th style="padding:10px 12px;text-align:center;font-weight:600">Quad</th>
                <th style="padding:10px 12px;text-align:center;font-weight:600">Align</th>
                <th style="padding:10px 12px;text-align:center;font-weight:600">PEAD</th>
                <th style="padding:10px 12px;text-align:center;font-weight:600">Bucket</th>
                <th style="padding:10px 12px;text-align:right;font-weight:600">X-Axis</th>
                <th style="padding:10px 12px;text-align:right;font-weight:600">Y-Axis</th>
                <th style="padding:10px 12px;text-align:center;font-weight:600">EV Rank</th>
                <th style="padding:10px 12px;text-align:right;font-weight:600">Price</th>
                <th style="padding:10px 12px;text-align:right;font-weight:600">Mkt Cap</th>
                <th style="padding:10px 12px;text-align:center;font-weight:600">Flip%</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>"""


def generate_q1q2_report(output_path: str | None = None) -> str:
    """Generate a focused Q1 + Q2 only HTML report."""

    df = get_universe("all")
    df = run_gates(df)
    df = compute_axes(df)
    df = assign_quadrants(df)
    df = assign_pods(df)
    df = compute_alignment(df)
    df = compute_flip_scores(df)

    data_date = get_last_snapshot_date() or datetime.today().strftime("%Y-%m-%d")
    run_ts = datetime.now().strftime("%B %d, %Y · %I:%M %p")
    screen = screen_summary(df)
    align = alignment_summary(df)

    filt = df[df["quadrant"].isin(["Q1", "Q2"])].copy()
    q1_n = int((filt["quadrant"] == "Q1").sum())
    q2_n = int((filt["quadrant"] == "Q2").sum())
    total_n = len(filt)

    pead_order = {"Strong PEAD": 0, "PEAD Confirm": 1, "PEAD Warn": 2, "Reverse PEAD": 3, "—": 4}
    filt["_pead_rank"] = filt["pead_flag"].map(lambda x: pead_order.get(x, 9))
    strong_pead_n = int((filt["pead_flag"] == "Strong PEAD").sum())
    accum_n = int((filt["alignment_bucket"] == "Accumulate").sum())

    # Scatter restricted to Q1/Q2 only
    scatter_svg = _build_scatter_svg(filt)

    nav_items = [
        ("#summary", "Summary"),
        ("#chart", "Chart"),
        ("#names", "All Names"),
    ]
    nav_html = "".join(
        f'<a href="{href}" style="color:rgba(255,255,255,0.8);text-decoration:none;font-size:13px;font-weight:500;padding:6px 14px;border-radius:20px;transition:background 0.2s" '
        f'onmouseover="this.style.background=\'rgba(255,255,255,0.15)\'" onmouseout="this.style.background=\'transparent\'">{label}</a>'
        for href, label in nav_items
    )

    # Summary cards for Q1 and Q2
    cards_html = '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px">'
    for val, label, color, bg in [
        (q2_n, "Q2 · Hidden Value / GARP", "#16a34a", "#f0fdf4"),
        (q1_n, "Q1 · Trending Quality", "#2563eb", "#eff6ff"),
        (strong_pead_n, "Strong PEAD", "#166534", "#dcfce7"),
        (accum_n, "Accumulate", "#16a34a", "#f0fdf4"),
    ]:
        cards_html += f"""
        <div style="background:{bg};border:1.5px solid {color}30;border-radius:12px;padding:20px;text-align:center">
            <div style="font-size:36px;font-weight:800;color:{color};line-height:1">{val}</div>
            <div style="font-size:12px;color:#6b7280;margin-top:6px;font-weight:600">{label}</div>
        </div>"""
    cards_html += '</div>'

    # Strong PEAD callout
    strong_names = filt[filt["pead_flag"] == "Strong PEAD"].sort_values("alignment_score", ascending=False)["ticker"].tolist()
    strong_callout = ""
    if strong_names:
        badges = "".join(
            f'<span style="background:#dcfce7;color:#166534;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:700;margin:2px">{t}</span>'
            for t in strong_names
        )
        strong_callout = f'<div style="margin-top:20px;padding:16px;background:#f0fdf4;border:1px solid #86efac;border-radius:10px"><div style="font-size:12px;font-weight:700;color:#166534;margin-bottom:8px">STRONG PEAD ({len(strong_names)} names)</div><div style="display:flex;flex-wrap:wrap;gap:4px">{badges}</div></div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Integrity Compounders · Q1 &amp; Q2 Report · {data_date}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Source Sans 3', Calibri, sans-serif; background: #f1f5f9; color: #1e293b; -webkit-font-smoothing: antialiased; }}
  @media print {{ body {{ background: white; }} .no-print {{ display: none; }} }}
</style>
</head>
<body>

<!-- NAV -->
<div style="background:linear-gradient(135deg,#1F3A5F 0%,#2d5282 60%,#1a365d 100%);padding:0;position:sticky;top:0;z-index:100;box-shadow:0 2px 12px rgba(0,0,0,0.2)">
  <div style="max-width:1200px;margin:0 auto;padding:0 32px">
    <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 0">
      <div style="display:flex;align-items:center;gap:16px">
        <div style="width:36px;height:36px;background:rgba(255,255,255,0.15);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px">⬡</div>
        <div>
          <div style="font-family:'Playfair Display',serif;font-size:18px;font-weight:800;color:white;letter-spacing:-0.3px">Integrity Compounders</div>
          <div style="font-size:11px;color:rgba(255,255,255,0.6);letter-spacing:1px;text-transform:uppercase">Alpha System v9.1 · Q1 &amp; Q2 Focus</div>
        </div>
      </div>
      <nav style="display:flex;gap:4px;align-items:center">{nav_html}</nav>
      <div style="text-align:right">
        <div style="font-size:12px;color:rgba(255,255,255,0.5)">Data: Fiscal AI</div>
        <div style="font-size:12px;color:rgba(255,255,255,0.8);font-weight:600">{data_date}</div>
      </div>
    </div>
  </div>
</div>

<!-- HERO -->
<div style="background:linear-gradient(135deg,#1F3A5F,#2d5282);padding:40px 32px 32px">
  <div style="max-width:1200px;margin:0 auto">
    <div style="font-family:'Playfair Display',serif;font-size:32px;font-weight:800;color:white;margin-bottom:6px;letter-spacing:-0.5px">
      Q1 &amp; Q2 Focus Report
    </div>
    <div style="font-size:14px;color:rgba(255,255,255,0.6);margin-bottom:28px">
      Generated {run_ts} · {total_n} qualifying names · Integrity Wealth Partners
    </div>
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:16px">
      {"".join(f'''<div style="background:rgba(255,255,255,0.1);border-radius:12px;padding:16px;text-align:center;backdrop-filter:blur(4px)">
        <div style="font-size:28px;font-weight:800;color:white;line-height:1">{val}</div>
        <div style="font-size:11px;color:rgba(255,255,255,0.6);margin-top:4px;text-transform:uppercase;letter-spacing:0.5px">{label}</div>
      </div>''' for val, label in [
        (total_n, "Total Names"),
        (q2_n, "Q2 Names"),
        (q1_n, "Q1 Names"),
        (strong_pead_n, "Strong PEAD"),
        (accum_n, "Accumulate"),
      ])}
    </div>
  </div>
</div>

<!-- MAIN -->
<div style="max-width:1200px;margin:0 auto;padding:32px">

  <!-- SUMMARY -->
  {_section("Q1 &amp; Q2 Summary", f"Best quadrants by EV rank and earnings momentum · {data_date} snapshot",
    cards_html + strong_callout, "summary")}

  <!-- CHART -->
  {_section("Q1 &amp; Q2 Quad Chart",
    "X-Axis: Earnings Momentum ROC · Y-Axis: Multiple ROC · Size: Alignment Score · Q1 = Blue · Q2 = Green",
    f'<div style="background:#fafafa;border-radius:12px;padding:16px;border:1px solid #e5e7eb">{scatter_svg}</div>'
    + f"""<div style="display:flex;gap:24px;margin-top:16px;flex-wrap:wrap">
      {"".join(f'<div style="display:flex;align-items:center;gap:8px"><div style="width:12px;height:12px;border-radius:50%;background:{color}"></div><span style="font-size:12px;color:#374151">{label}</span></div>'
        for color, label in [("#2563eb","Q1 Trending Quality"),("#16a34a","Q2 Hidden Value / GARP")])}
    </div>""", "chart")}

  <!-- COMBINED TABLE -->
  {_section("All Q1 &amp; Q2 Names",
    f"Sorted by Alignment Score (desc) then PEAD signal strength · {total_n} names",
    _q1q2_combined_table(df), "names")}

</div>

<!-- FOOTER -->
<div style="background:#1F3A5F;color:rgba(255,255,255,0.5);text-align:center;padding:24px;font-size:12px;margin-top:16px">
  <div style="font-family:'Playfair Display',serif;font-size:16px;color:rgba(255,255,255,0.8);margin-bottom:6px">Integrity Compounders · Integrity Wealth Partners</div>
  <div>Alpha System v9.1 · Generated {run_ts} · Data: Fiscal AI · Internal Use Only</div>
  <div style="margin-top:8px;font-size:11px">Q2 (EV Rank 1 — Best) → Q1 (EV Rank 2) · Two consecutive months required to confirm quad migrations</div>
</div>

<script>
  document.querySelectorAll('a[href^="#"]').forEach(a => {{
    a.addEventListener('click', e => {{
      e.preventDefault();
      const el = document.querySelector(a.getAttribute('href'));
      if (el) el.scrollIntoView({{behavior:'smooth', block:'start'}});
    }});
  }});
</script>
</body>
</html>"""

    if output_path is None:
        out_dir = ROOT / "outputs" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / f"integrity_compounders_q1q2_{data_date}.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[Report] Saved: {output_path}")
    return output_path


def _trade_status_badge(status: str) -> str:
    colors = {
        "Open":    ("#166534", "#dcfce7"),
        "Partial": ("#1e40af", "#dbeafe"),
        "Closed":  ("#374151", "#f3f4f6"),
    }
    fg, bg = colors.get(status, ("#374151", "#f3f4f6"))
    return f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600">{status}</span>'


def _action_badge(action: str) -> str:
    colors = {
        "BUY":   ("#166534", "#dcfce7"),
        "ADD":   ("#1e40af", "#dbeafe"),
        "TRIM":  ("#92400e", "#fef3c7"),
        "SELL":  ("#991b1b", "#fee2e2"),
        "CLOSE": ("#374151", "#f3f4f6"),
    }
    fg, bg = colors.get(action, ("#374151", "#f3f4f6"))
    return f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700">{action}</span>'


def _outcome_badge(outcome: str) -> str:
    if not outcome or outcome == "None":
        return "—"
    colors = {
        "Confirmed":    ("#166534", "#dcfce7"),
        "Invalidated":  ("#991b1b", "#fee2e2"),
        "Inconclusive": ("#92400e", "#fef3c7"),
    }
    fg, bg = colors.get(outcome, ("#374151", "#f3f4f6"))
    return f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600">{outcome}</span>'


def _return_color(v) -> str:
    if v is None or str(v) == "None":
        return "#374151"
    try:
        return "#16a34a" if float(v) >= 0 else "#dc2626"
    except (TypeError, ValueError):
        return "#374151"


def generate_trade_log_report(output_path: str | None = None) -> str:
    """Generate the trade log HTML report — open/closed positions + statistics."""
    from engines.database import get_trade_log, get_last_snapshot_date

    data_date = get_last_snapshot_date() or datetime.today().strftime("%Y-%m-%d")
    run_ts    = datetime.now().strftime("%B %d, %Y · %I:%M %p")

    all_trades = get_trade_log()
    open_trades   = all_trades[all_trades["status"].isin(["Open","Partial"])].copy() if not all_trades.empty else pd.DataFrame()
    closed_trades = all_trades[all_trades["status"] == "Closed"].copy() if not all_trades.empty else pd.DataFrame()

    # ── Statistics ────────────────────────────────────────────────────────────
    total_n       = len(all_trades)
    open_n        = len(open_trades)
    closed_n      = len(closed_trades)

    confirmed_n = 0
    avg_return  = None
    win_rate    = None
    avg_score   = None

    if not closed_trades.empty:
        confirmed_n = int((closed_trades["thesis_outcome"] == "Confirmed").sum())
        win_rate    = confirmed_n / closed_n * 100 if closed_n else 0
        returns     = pd.to_numeric(closed_trades["total_return"], errors="coerce").dropna()
        avg_return  = returns.mean() if len(returns) else None

    if not all_trades.empty:
        scores    = pd.to_numeric(all_trades["alignment_score"], errors="coerce").dropna()
        avg_score = scores.mean() if len(scores) else None

    most_common_trigger = (
        all_trades["trigger_type"].value_counts().index[0]
        if not all_trades.empty and "trigger_type" in all_trades.columns
        else "—"
    )
    most_common_quad = (
        all_trades["quadrant"].value_counts().index[0]
        if not all_trades.empty and "quadrant" in all_trades.columns
        else "—"
    )

    # ── Open positions table ──────────────────────────────────────────────────
    def open_rows(df):
        if df.empty:
            return '<tr><td colspan="13" style="padding:20px;text-align:center;color:#6b7280;font-style:italic">No open positions logged yet.</td></tr>'
        rows = ""
        for i, (_, r) in enumerate(df.iterrows()):
            bg = "#f9fafb" if i % 2 == 0 else "white"
            q  = str(r.get("quadrant") or "—")
            sc = r.get("alignment_score")
            sc_color = "#16a34a" if (sc and sc >= 65) else "#d97706" if (sc and sc >= 35) else "#dc2626"
            thesis_short = str(r.get("thesis") or r.get("why_now") or "—")[:60] + ("…" if len(str(r.get("thesis") or "")) > 60 else "")
            rows += f"""
            <tr style="background:{bg}">
              <td style="padding:9px 12px;color:#6b7280;font-size:12px">{str(r.get('trade_date',''))[:10]}</td>
              <td style="padding:9px 12px;font-weight:700;color:#1F3A5F">{r.get('ticker','')}</td>
              <td style="padding:9px 12px;text-align:center">{_action_badge(str(r.get('action','')))}</td>
              <td style="padding:9px 12px;text-align:right;color:#374151">${float(r.get('price') or 0):,.2f}</td>
              <td style="padding:9px 12px;text-align:right;color:#374151">{f"{float(r.get('weight_after') or 0):.1f}%" if r.get('weight_after') else "—"}</td>
              <td style="padding:9px 12px;text-align:center">
                <span style="background:{_quad_bg(q)};color:{_quad_color(q)};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:700">{q}</span>
              </td>
              <td style="padding:9px 12px;text-align:center;font-weight:700;color:{sc_color}">{f"{sc:.1f}" if sc else "—"}</td>
              <td style="padding:9px 12px;text-align:center">{_bucket_color_badge(str(r.get('alignment_bucket') or '—'))}</td>
              <td style="padding:9px 12px;font-size:11px;color:#374151;max-width:200px">{thesis_short}</td>
              <td style="padding:9px 12px;font-size:11px;color:#16a34a">{r.get('add_trigger') or '—'}</td>
              <td style="padding:9px 12px;font-size:11px;color:#d97706">{r.get('trim_trigger') or '—'}</td>
              <td style="padding:9px 12px;font-size:11px;color:#dc2626">{r.get('exit_trigger') or '—'}</td>
              <td style="padding:9px 12px;text-align:center">{_trade_status_badge(str(r.get('status','Open')))}</td>
            </tr>"""
        return rows

    def _bucket_color_badge(b):
        c = "#16a34a" if b == "Accumulate" else "#dc2626" if b == "Distribute" else "#d97706"
        return f'<span style="color:{c};font-weight:600;font-size:12px">{b}</span>'

    # ── Closed positions table ────────────────────────────────────────────────
    def closed_rows(df):
        if df.empty:
            return '<tr><td colspan="9" style="padding:20px;text-align:center;color:#6b7280;font-style:italic">No closed positions yet.</td></tr>'
        rows = ""
        for i, (_, r) in enumerate(df.iterrows()):
            bg = "#f9fafb" if i % 2 == 0 else "white"
            ret = r.get("total_return")
            ret_str = f"{float(ret):+.1f}%" if ret and str(ret) != "None" else "—"
            ret_color = _return_color(ret)
            rows += f"""
            <tr style="background:{bg}">
              <td style="padding:9px 12px;color:#6b7280;font-size:12px">{str(r.get('trade_date',''))[:10]}</td>
              <td style="padding:9px 12px;font-weight:700;color:#1F3A5F">{r.get('ticker','')}</td>
              <td style="padding:9px 12px;text-align:center">{_action_badge(str(r.get('action','')))}</td>
              <td style="padding:9px 12px;text-align:right;color:#374151">${float(r.get('price') or 0):,.2f}</td>
              <td style="padding:9px 12px;text-align:right;color:#374151">{f"${float(r.get('close_price') or 0):,.2f}" if r.get('close_price') else "—"}</td>
              <td style="padding:9px 12px;text-align:right;font-weight:700;color:{ret_color}">{ret_str}</td>
              <td style="padding:9px 12px;text-align:center;font-size:12px;color:#374151">{r.get('vs_base_case') or '—'}</td>
              <td style="padding:9px 12px;text-align:center">{_outcome_badge(str(r.get('thesis_outcome') or '—'))}</td>
              <td style="padding:9px 12px;font-size:11px;color:#6b7280;max-width:220px">{str(r.get('what_we_learned') or '—')[:80]}</td>
            </tr>"""
        return rows

    # ── Stats section ─────────────────────────────────────────────────────────
    stat_cards = [
        (total_n,  "Total Trades",    "#1F3A5F"),
        (open_n,   "Open",            "#16a34a"),
        (closed_n, "Closed",          "#374151"),
        (f"{win_rate:.0f}%" if win_rate is not None else "—", "Win Rate", "#16a34a" if (win_rate or 0) >= 50 else "#dc2626"),
        (f"{avg_return:+.1f}%" if avg_return is not None else "—", "Avg Return",
         "#16a34a" if (avg_return or 0) >= 0 else "#dc2626"),
        (f"{avg_score:.1f}" if avg_score is not None else "—", "Avg Score at Entry", "#1F3A5F"),
    ]
    stat_html = '<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:16px;margin-bottom:24px">'
    for val, label, color in stat_cards:
        stat_html += f"""
        <div style="background:white;border-radius:12px;padding:18px;text-align:center;border:1.5px solid #e5e7eb;box-shadow:0 1px 3px rgba(0,0,0,0.06)">
          <div style="font-size:28px;font-weight:800;color:{color};line-height:1">{val}</div>
          <div style="font-size:11px;color:#6b7280;margin-top:6px;text-transform:uppercase;letter-spacing:0.5px">{label}</div>
        </div>"""
    stat_html += "</div>"
    stat_html += f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:8px">
      <div style="padding:12px 16px;background:#f8fafc;border-radius:10px;border:1px solid #e2e8f0">
        <span style="font-size:12px;color:#6b7280">Most common trigger: </span>
        <span style="font-size:13px;font-weight:600;color:#1F3A5F">{most_common_trigger}</span>
      </div>
      <div style="padding:12px 16px;background:#f8fafc;border-radius:10px;border:1px solid #e2e8f0">
        <span style="font-size:12px;color:#6b7280">Most common quad at entry: </span>
        <span style="font-size:13px;font-weight:700;color:{_quad_color(most_common_quad)}">{most_common_quad}</span>
      </div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trade Log · {data_date}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>* {{box-sizing:border-box;margin:0;padding:0}} body {{font-family:'Source Sans 3',Calibri,sans-serif;background:#f1f5f9;color:#1e293b;-webkit-font-smoothing:antialiased}}</style>
</head>
<body>

<div style="background:linear-gradient(135deg,#1F3A5F,#2d5282);padding:0;position:sticky;top:0;z-index:100;box-shadow:0 2px 12px rgba(0,0,0,0.2)">
  <div style="max-width:1300px;margin:0 auto;padding:0 32px;display:flex;align-items:center;justify-content:space-between;height:56px">
    <div style="display:flex;align-items:center;gap:16px">
      <div style="font-family:'Playfair Display',serif;font-size:18px;font-weight:800;color:white">Integrity Compounders</div>
      <div style="font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:1px;text-transform:uppercase">Trade Log</div>
    </div>
    <nav style="display:flex;gap:4px">
      {"".join(f'<a href="#{a}" style="color:rgba(255,255,255,0.8);text-decoration:none;font-size:13px;padding:6px 14px;border-radius:20px">{l}</a>' for a,l in [("stats","Stats"),("open","Open"),("closed","Closed")])}
    </nav>
    <div style="font-size:12px;color:rgba(255,255,255,0.7)">{data_date}</div>
  </div>
</div>

<div style="background:linear-gradient(135deg,#1F3A5F,#2d5282);padding:28px 32px">
  <div style="max-width:1300px;margin:0 auto">
    <div style="font-family:'Playfair Display',serif;font-size:28px;font-weight:800;color:white;margin-bottom:6px">Trade Log</div>
    <div style="font-size:13px;color:rgba(255,255,255,0.6)">Generated {run_ts} · Integrity Wealth Partners</div>
  </div>
</div>

<div style="max-width:1300px;margin:0 auto;padding:28px 32px">

  {_section("Trade Statistics", f"Equal-weighted performance · {total_n} total trades logged", stat_html, "stats")}

  {_section(f"Open Positions ({open_n})",
    "Sorted by trade date · all active and partial positions",
    f"""<div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:12px;min-width:900px">
      <thead><tr style="background:#1F3A5F;color:white">
        <th style="padding:9px 12px;text-align:left">Date</th>
        <th style="padding:9px 12px;text-align:left">Ticker</th>
        <th style="padding:9px 12px;text-align:center">Action</th>
        <th style="padding:9px 12px;text-align:right">Price</th>
        <th style="padding:9px 12px;text-align:right">Weight</th>
        <th style="padding:9px 12px;text-align:center">Quad</th>
        <th style="padding:9px 12px;text-align:center">Score</th>
        <th style="padding:9px 12px;text-align:center">Bucket</th>
        <th style="padding:9px 12px;text-align:left">Thesis</th>
        <th style="padding:9px 12px;text-align:left">Add Trigger</th>
        <th style="padding:9px 12px;text-align:left">Trim Trigger</th>
        <th style="padding:9px 12px;text-align:left">Exit Trigger</th>
        <th style="padding:9px 12px;text-align:center">Status</th>
      </tr></thead>
      <tbody>{open_rows(open_trades)}</tbody>
    </table></div>""", "open")}

  {_section(f"Closed Positions ({closed_n})",
    "All closed trades with outcomes",
    f"""<div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:12px;min-width:800px">
      <thead><tr style="background:#1F3A5F;color:white">
        <th style="padding:9px 12px;text-align:left">Date</th>
        <th style="padding:9px 12px;text-align:left">Ticker</th>
        <th style="padding:9px 12px;text-align:center">Action</th>
        <th style="padding:9px 12px;text-align:right">Entry</th>
        <th style="padding:9px 12px;text-align:right">Exit</th>
        <th style="padding:9px 12px;text-align:right">Return</th>
        <th style="padding:9px 12px;text-align:center">vs Base</th>
        <th style="padding:9px 12px;text-align:center">Outcome</th>
        <th style="padding:9px 12px;text-align:left">What We Learned</th>
      </tr></thead>
      <tbody>{closed_rows(closed_trades)}</tbody>
    </table></div>""", "closed")}

</div>

<div style="background:#1F3A5F;color:rgba(255,255,255,0.5);text-align:center;padding:20px;font-size:12px;margin-top:8px">
  <div style="font-family:'Playfair Display',serif;font-size:15px;color:rgba(255,255,255,0.8);margin-bottom:4px">Integrity Compounders · Integrity Wealth Partners</div>
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
</body></html>"""

    if output_path is None:
        out_dir = ROOT / "outputs" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / f"trade_log_{datetime.today().strftime('%Y-%m-%d')}.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[Report] Saved: {output_path}")
    return output_path


def generate_monthly_rebalance_report(output_path: str | None = None) -> str:
    """
    Generate monthly rebalance memo.
    Includes: universe snapshot, portfolio vs model divergence,
    model recommendations, monthly trade summary.
    """
    from engines.database import (
        get_universe, get_last_snapshot_date, get_trades_this_month, get_portfolio
    )
    from engines.screener  import run_gates, screen_summary
    from engines.quad      import compute_axes, assign_quadrants
    from engines.pods      import assign_pods
    from engines.alignment import compute_alignment, alignment_summary
    from engines.fcf_flip  import compute_flip_scores

    # ── Universe pipeline ─────────────────────────────────────────────────────
    df = get_universe("all")
    df = run_gates(df)
    df = compute_axes(df)
    df = assign_quadrants(df)
    df = assign_pods(df)
    df = compute_alignment(df)
    df = compute_flip_scores(df)

    data_date = get_last_snapshot_date() or datetime.today().strftime("%Y-%m-%d")
    run_ts    = datetime.now().strftime("%B %d, %Y · %I:%M %p")
    month_str = datetime.today().strftime("%B %Y")

    screen   = screen_summary(df)
    align    = alignment_summary(df)
    q_counts = df["quadrant"].value_counts().to_dict()

    # ── Portfolio vs model divergence ─────────────────────────────────────────
    port = get_portfolio()
    has_portfolio = not port.empty

    def _portfolio_divergence_html():
        if not has_portfolio:
            return '<p style="color:#6b7280;font-style:italic;padding:16px">No portfolio loaded. Run: python run.py load portfolio</p>'

        port_tickers = set(port["ticker"].tolist())
        model_q1q2   = set(df[df["quadrant"].isin(["Q1","Q2"])]["ticker"].tolist())
        model_accum  = set(df[df["alignment_bucket"] == "Accumulate"]["ticker"].tolist())

        # Held names not in Q1/Q2 — consider trimming
        held_not_q1q2 = port[~port["ticker"].isin(model_q1q2)].sort_values(
            "alignment_score" if "alignment_score" in port.columns else "weight_actual"
        )
        # Q1/Q2 Accumulate names not held — model would add
        model_add = df[
            df["quadrant"].isin(["Q1","Q2"]) &
            (df["alignment_bucket"] == "Accumulate") &
            ~df["ticker"].isin(port_tickers)
        ].sort_values("alignment_score", ascending=False).head(10)
        # Held names now in Distribute
        held_distribute = port[port["alignment_bucket"] == "Distribute"] if "alignment_bucket" in port.columns else pd.DataFrame()

        rows_trim = ""
        for i,(_, r) in enumerate(held_not_q1q2.iterrows()):
            q   = str(r.get("quadrant","—"))
            sc  = r.get("alignment_score",0)
            bg  = "#f9fafb" if i%2==0 else "white"
            rec = "EXIT" if q == "Q4" else "TRIM" if (sc or 0) < 35 else "WATCH"
            rc  = "#dc2626" if rec=="EXIT" else "#d97706" if rec=="TRIM" else "#374151"
            rows_trim += f"""<tr style="background:{bg}">
              <td style="padding:8px 12px;font-weight:700;color:#1F3A5F">{r.get('ticker','')}</td>
              <td style="padding:8px 12px;text-align:center"><span style="background:{_quad_bg(q)};color:{_quad_color(q)};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:700">{q}</span></td>
              <td style="padding:8px 12px;text-align:center;font-weight:700;color:{'#16a34a' if sc>=65 else '#d97706' if sc>=35 else '#dc2626'}">{f"{sc:.1f}" if sc else "—"}</td>
              <td style="padding:8px 12px;text-align:center">{_pead_badge(str(r.get('pead_flag','—')))}</td>
              <td style="padding:8px 12px;text-align:right;color:#374151">{r.get('weight_actual',0):.1f}%</td>
              <td style="padding:8px 12px;font-weight:700;color:{rc}">{rec}</td>
            </tr>"""

        rows_add = ""
        for i,(_, r) in enumerate(model_add.iterrows()):
            q  = str(r.get("quadrant","—"))
            sc = r.get("alignment_score",0)
            bg = "#f9fafb" if i%2==0 else "white"
            rows_add += f"""<tr style="background:{bg}">
              <td style="padding:8px 12px;font-weight:700;color:#1F3A5F">{r.get('ticker','')}</td>
              <td style="padding:8px 12px;font-size:12px;color:#374151">{str(r.get('company',''))[:24]}</td>
              <td style="padding:8px 12px;text-align:center"><span style="background:{_quad_bg(q)};color:{_quad_color(q)};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:700">{q}</span></td>
              <td style="padding:8px 12px;text-align:center;font-weight:700;color:{'#16a34a' if sc>=65 else '#d97706'}">{f"{sc:.1f}" if sc else "—"}</td>
              <td style="padding:8px 12px;text-align:center">{_pead_badge(str(r.get('pead_flag','—')))}</td>
              <td style="padding:8px 12px;text-align:right;font-weight:600;color:#374151">${r.get('stock_price',0):,.2f}</td>
            </tr>"""

        tbl_header = lambda cols: f'<tr style="background:#1F3A5F;color:white">{"".join(f"<th style=\"padding:8px 12px;text-align:left;font-size:12px\">{c}</th>" for c in cols)}</tr>'

        section = f"""
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px">
          <div>
            <div style="font-size:12px;font-weight:700;color:#d97706;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px">
              Held names NOT in Q1/Q2 — review for trim/exit ({len(held_not_q1q2)})
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:12px">
              <thead>{tbl_header(["Ticker","Quad","Score","PEAD","Weight","Action"])}</thead>
              <tbody>{"" if rows_trim else "<tr><td colspan='6' style='padding:12px;color:#6b7280;font-style:italic;text-align:center'>All held names are in Q1/Q2</td></tr>"}{rows_trim}</tbody>
            </table>
          </div>
          <div>
            <div style="font-size:12px;font-weight:700;color:#16a34a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px">
              Model would ADD — Q1/Q2 Accumulate not held ({len(model_add)})
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:12px">
              <thead>{tbl_header(["Ticker","Company","Quad","Score","PEAD","Price"])}</thead>
              <tbody>{"" if rows_add else "<tr><td colspan='6' style='padding:12px;color:#6b7280;font-style:italic;text-align:center'>All Q1/Q2 Accumulate names are held</td></tr>"}{rows_add}</tbody>
            </table>
          </div>
        </div>"""

        if not held_distribute.empty:
            section += f"""
            <div style="margin-top:16px;padding:12px 16px;background:#fee2e2;border-radius:10px;border:1px solid #fca5a5">
              <strong style="color:#991b1b">Distribute signals in portfolio ({len(held_distribute)}):</strong>
              <span style="color:#374151;font-size:13px;margin-left:8px">{", ".join(held_distribute["ticker"].tolist())}</span>
            </div>"""

        return section

    # ── Trade summary ─────────────────────────────────────────────────────────
    trades_this_month = get_trades_this_month()

    def _trade_summary_rows(trades):
        if trades.empty:
            return '<tr><td colspan="7" style="padding:16px;text-align:center;color:#6b7280;font-style:italic">No trades logged this month.</td></tr>'
        rows = ""
        for i, (_, r) in enumerate(trades.iterrows()):
            bg = "#f9fafb" if i % 2 == 0 else "white"
            q  = str(r.get("quadrant") or "—")
            rows += f"""
            <tr style="background:{bg}">
              <td style="padding:10px 14px;color:#6b7280;font-size:12px">{str(r.get('trade_date',''))[:10]}</td>
              <td style="padding:10px 14px;font-weight:700;color:#1F3A5F">{r.get('ticker','')}</td>
              <td style="padding:10px 14px;text-align:center">{_action_badge(str(r.get('action','')))}</td>
              <td style="padding:10px 14px;text-align:right;color:#374151">${float(r.get('price') or 0):,.2f}</td>
              <td style="padding:10px 14px;text-align:center">
                <span style="background:{_quad_bg(q)};color:{_quad_color(q)};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:700">{q}</span>
              </td>
              <td style="padding:10px 14px;text-align:center;font-weight:700;color:#1F3A5F">{r.get('alignment_score') or '—'}</td>
              <td style="padding:10px 14px;font-size:12px;color:#374151;max-width:260px">{str(r.get('why_now') or '—')[:80]}</td>
            </tr>"""
        return rows

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Monthly Rebalance · {month_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>* {{box-sizing:border-box;margin:0;padding:0}} body {{font-family:'Source Sans 3',Calibri,sans-serif;background:#f1f5f9;color:#1e293b;-webkit-font-smoothing:antialiased}}</style>
</head>
<body>
<div style="background:linear-gradient(135deg,#1F3A5F,#2d5282);padding:32px 32px 28px">
  <div style="max-width:1200px;margin:0 auto">
    <div style="font-family:'Playfair Display',serif;font-size:30px;font-weight:800;color:white;margin-bottom:6px">Monthly Rebalance Memo — {month_str}</div>
    <div style="font-size:13px;color:rgba(255,255,255,0.6)">Generated {run_ts} · Integrity Wealth Partners · Alpha System v10.0</div>
  </div>
</div>
<div style="max-width:1200px;margin:0 auto;padding:28px 32px">

  {_section("Universe Snapshot", f"Five-gate screen · {data_date}",
    f"""<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px">
      {"".join(f'<div style="background:#f8fafc;border-radius:10px;padding:16px;text-align:center;border:1px solid #e2e8f0"><div style="font-size:24px;font-weight:800;color:#1F3A5F">{v}</div><div style="font-size:11px;color:#6b7280;margin-top:4px;text-transform:uppercase">{l}</div></div>'
        for v,l in [(len(df),"Universe"),(q_counts.get("Q1",0),"Q1 Full Comp."),(q_counts.get("Q2",0),"Q2 Earn. Resil."),(align["accumulate"],"Accumulate")])}
    </div>""")}

  {_section("Portfolio vs Model — Rebalance Recommendations",
    f"Current portfolio ({len(port)} names) vs what the model recommends today",
    _portfolio_divergence_html())}

  <div style="background:white;border-radius:14px;padding:28px;margin-top:28px;box-shadow:0 1px 4px rgba(0,0,0,0.07);border:1px solid #e5e7eb">
    <div style="border-left:4px solid #1F3A5F;padding-left:14px;margin-bottom:20px">
      <h2 style="font-size:17px;font-weight:800;color:#1F3A5F">Monthly Trade Summary — {month_str}</h2>
      <p style="font-size:12px;color:#6b7280">{len(trades_this_month)} trade(s) logged this month</p>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:#1F3A5F;color:white">
        <th style="padding:10px 14px;text-align:left">Date</th>
        <th style="padding:10px 14px;text-align:left">Ticker</th>
        <th style="padding:10px 14px;text-align:center">Action</th>
        <th style="padding:10px 14px;text-align:right">Price</th>
        <th style="padding:10px 14px;text-align:center">Quad</th>
        <th style="padding:10px 14px;text-align:center">Score</th>
        <th style="padding:10px 14px;text-align:left">Rationale</th>
      </tr></thead>
      <tbody>{_trade_summary_rows(trades_this_month)}</tbody>
    </table>
  </div>

</div>
<div style="background:#1F3A5F;color:rgba(255,255,255,0.5);text-align:center;padding:20px;font-size:12px;margin-top:8px">
  Integrity Compounders · Integrity Wealth Partners · Alpha System v10.0 · {run_ts} · Internal Use Only
</div>
</body></html>"""

    if output_path is None:
        out_dir = ROOT / "outputs" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / f"monthly_rebalance_{datetime.today().strftime('%Y-%m')}.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[Report] Saved: {output_path}")
    return output_path


if __name__ == "__main__":
    path = generate_report()
    print(f"Open in browser: {path}")
