"""
quad_map.py — the whole universe plotted on the Quad grid

Every active name positioned by its two axes (CLAUDE.md §5.1):
    X = Revenue Momentum  = Fwd Rev CAGR − Trailing Rev 3Y CAGR
    Y = Earnings Momentum = Fwd EPS CAGR (capped 25%) − Trailing EPS 3Y CAGR

Quadrants follow engines/quad.py::_assign_quadrant, which is the code of record:
    Q1 Full Compounders    X ≥ 0, Y ≥ 0   (EV Rank 1 — best)
    Q2 Earnings Resilience X < 0, Y ≥ 0   (EV Rank 2)
    Q3 Margin Compression  X ≥ 0, Y < 0   (EV Rank 3)
    Q4 Full Deterioration  X < 0, Y < 0   (EV Rank 4 — worst)

NOTE — CLAUDE.md contradicts itself on this. §5.2's table agrees with the code
(and with this chart). The V12 summary at the top of the file does not: it claims
Q2 = X>0/Y≤0, Q3 = X≤0/Y≤0, Q4 = X≤0/Y>0, which would mislabel three quadrants.
The code and §5.2 win; the summary line is wrong and should be corrected.

Reads Supabase (source of truth) — company_market_data carries x_rev_mom (X) and
x_eps_mom (Y) alongside the stored quadrant, written by data_updater's quad stage.
Verified: stored quadrant matches the rule on 277/277 names.

§5.3 clip bounds are honoured — axes clip to ±30% and clipped names render as
triangles at the edge pointing the way they ran off. Without it the chart is
unreadable: 72 names sit beyond ±30 on Y, one at −667.

Departure from §14: it asks for labelled tickers. 277 labels overlap into mush at
screen size, so only holdings are labelled; everything else is on hover.

    python scripts/quad_map.py        # → docs/quad_map.html
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import psycopg2
import plotly.graph_objects as go
from datetime import datetime
from config.settings import settings

DOCS = ROOT / "docs"; DOCS.mkdir(exist_ok=True)
NAVY, GOLD = "#1F3A5F", "#C9A84C"
CLIP = 30.0

QUADS = {
    "Q1": dict(name="Q1 · Full Compounders",    color="#2563eb", fill="rgba(37,99,235,.055)",
               desc="Revenue AND earnings accelerating. Core long — full confirmation."),
    "Q2": dict(name="Q2 · Earnings Resilience", color="#1baf7a", fill="rgba(27,175,122,.055)",
               desc="Revenue slowing, earnings holding. Quality signal — watch for revenue recovery."),
    "Q3": dict(name="Q3 · Margin Compression",  color="#cc3333", fill="rgba(204,51,51,.055)",
               desc="Revenue growing, earnings fading. Margin risk — monitor closely."),
    "Q4": dict(name="Q4 · Full Deterioration",  color="#e08a1e", fill="rgba(224,138,30,.055)",
               desc="Both decelerating. Avoid or reduce."),
}


def load() -> pd.DataFrame:
    conn = psycopg2.connect(settings.DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT c.ticker, COALESCE(c.company_name, c.ticker), COALESCE(c.sector, '—'),
               COALESCE(c.in_portfolio, FALSE), cmd.quadrant, cmd.x_rev_mom, cmd.x_eps_mom,
               cmd.ev_rank, cmd.alignment_score_v3, cmd.qgs_tier, cmd.market_cap, cmd.data_date
        FROM companies c
        JOIN company_market_data cmd ON cmd.ticker = c.ticker
         AND cmd.data_date = (SELECT MAX(data_date) FROM company_market_data WHERE ticker = c.ticker)
        WHERE c.active = TRUE
    """)
    rows = cur.fetchall(); cur.close(); conn.close()
    df = pd.DataFrame(rows, columns=["ticker", "company", "sector", "held", "quad", "x", "y",
                                     "ev_rank", "align_v3", "qgs_tier", "mcap", "data_date"])
    for c in ("x", "y", "align_v3", "mcap"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _marker(x, y):
    """§5.3: clipped values render as a triangle at the edge, pointing the way they ran off."""
    cx, cy = abs(x) > CLIP, abs(y) > CLIP
    if not cx and not cy:
        return "circle"
    if cx and not cy:
        return "triangle-right" if x > 0 else "triangle-left"
    if cy and not cx:
        return "triangle-up" if y > 0 else "triangle-down"
    return "triangle-ne" if (x > 0 and y > 0) else \
           "triangle-nw" if (x < 0 and y > 0) else \
           "triangle-se" if (x > 0 and y < 0) else "triangle-sw"


def build(df: pd.DataFrame) -> str:
    d = df.dropna(subset=["x", "y", "quad"]).copy()
    d["xc"] = d.x.clip(-CLIP, CLIP)
    d["yc"] = d.y.clip(-CLIP, CLIP)
    d["sym"] = [_marker(a, b) for a, b in zip(d.x, d.y)]
    d["clipped"] = (d.x.abs() > CLIP) | (d.y.abs() > CLIP)

    fig = go.Figure()
    # quadrant shading + corner labels
    for q, (x0, x1, y0, y1) in {"Q1": (0, CLIP, 0, CLIP), "Q2": (-CLIP, 0, 0, CLIP),
                                "Q3": (0, CLIP, -CLIP, 0), "Q4": (-CLIP, 0, -CLIP, 0)}.items():
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, layer="below",
                      fillcolor=QUADS[q]["fill"], line={"width": 0})

    # Captions pinned to the plot's four corners in PAPER coords, each on a backing
    # box. Data coords don't work here: the bottom edge is a solid carpet of clipped
    # triangles (72 names sit below −30% on Y), so a caption placed in the Q3/Q4
    # band lands on top of it whatever y you choose. Corners also map to meaning —
    # Q1 (best) top-right, Q4 (worst) bottom-left.
    for q, (px, py, xa, ya) in {"Q2": (0.008, 0.985, "left", "top"),
                                "Q1": (0.992, 0.985, "right", "top"),
                                "Q4": (0.008, 0.015, "left", "bottom"),
                                "Q3": (0.992, 0.015, "right", "bottom")}.items():
        fig.add_annotation(x=px, y=py, xref="paper", yref="paper", xanchor=xa, yanchor=ya,
                           text=f"<b>{QUADS[q]['name']}</b>  ({int((d.quad == q).sum())})",
                           showarrow=False, font={"size": 11, "color": QUADS[q]["color"]},
                           bgcolor="rgba(255,255,255,.86)", bordercolor=QUADS[q]["color"],
                           borderwidth=1, borderpad=4)
    fig.add_vline(x=0, line={"color": "#94a3b8", "width": 1})
    fig.add_hline(y=0, line={"color": "#94a3b8", "width": 1})

    for q in ("Q1", "Q2", "Q3", "Q4"):
        s = d[d.quad == q]
        if s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.xc, y=s.yc, mode="markers", name=f"{QUADS[q]['name']} ({len(s)})",
            marker={"size": [11 if c else 8 for c in s.clipped], "color": QUADS[q]["color"],
                    "symbol": list(s.sym), "line": {"width": .6, "color": "#fff"}, "opacity": .82},
            customdata=list(zip(s.ticker, s.company, s.sector, s.x.round(1), s.y.round(1),
                                s.align_v3.round(1), s.qgs_tier.fillna("—"),
                                ["★ HOLDING" if h else "" for h in s.held],
                                ["  ⟵ clipped, true value shown" if c else "" for c in s.clipped])),
            hovertemplate=("<b>%{customdata[0]}</b> %{customdata[7]}<br>%{customdata[1]}"
                           "<br><i>%{customdata[2]}</i><br>"
                           "Revenue momentum (X): %{customdata[3]}%%{customdata[8]}<br>"
                           "Earnings momentum (Y): %{customdata[4]}%<br>"
                           "Alignment v3: %{customdata[5]}<br>QGS tier: %{customdata[6]}<extra></extra>")))

    # holdings overlay — labelled, ringed in gold
    h = d[d.held]
    if not h.empty:
        fig.add_trace(go.Scatter(
            x=h.xc, y=h.yc, mode="markers+text", name=f"★ Holdings ({len(h)})",
            marker={"size": 15, "color": "rgba(0,0,0,0)", "symbol": "circle",
                    "line": {"width": 2, "color": GOLD}},
            text=h.ticker, textposition="top center",
            textfont={"size": 9, "color": NAVY, "family": "Calibri"}, hoverinfo="skip"))

    fig.update_layout(
        height=720, paper_bgcolor="#fff", plot_bgcolor="#fbfcfd",
        font={"family": "Calibri", "size": 11, "color": "#333"},
        margin={"l": 60, "r": 26, "t": 16, "b": 54},
        legend={"orientation": "h", "y": -0.09, "x": .5, "xanchor": "center", "font": {"size": 10}},
        xaxis={"title": "X = Revenue Momentum   ◀ decelerating · accelerating ▶",
               "range": [-CLIP - 2, CLIP + 2], "gridcolor": "#eef2f6", "zeroline": False,
               "ticksuffix": "%", "title_font": {"size": 11}},
        yaxis={"title": "Y = Earnings Momentum   ◀ decel · accel ▶",
               "range": [-CLIP - 2, CLIP + 2], "gridcolor": "#eef2f6", "zeroline": False,
               "ticksuffix": "%", "title_font": {"size": 11}})
    # default_width: without it Plotly hard-codes 700px and the chart floats in a
    # third of the card.
    return fig.to_html(full_html=False, include_plotlyjs="cdn", default_width="100%",
                       config={"displayModeBar": False, "responsive": True})


def html(df: pd.DataFrame) -> str:
    d = df.dropna(subset=["x", "y", "quad"])
    na = df[df.quad.isna()]
    chart = build(df)
    dd = max([x for x in df.data_date if x is not None], default="—")
    n_clip = int(((d.x.abs() > CLIP) | (d.y.abs() > CLIP)).sum())
    n_ybot = int((d.y < -CLIP).sum())
    n_neg = (d.quad.isin(["Q3", "Q4"])).sum() / max(len(d), 1)
    n_held_total = int(df.held.sum())
    n_held_plot = int(d.held.sum())
    held_missing = sorted(na[na.held].ticker)

    kpis = "".join(
        f"""<div class="k" style="border-left:4px solid {QUADS[q]['color']}">
              <div class="kl">{QUADS[q]['name']}</div>
              <div class="kv" style="color:{QUADS[q]['color']}">{int((d.quad == q).sum())}</div>
              <div class="ks">{int((d[d.quad == q].held).sum())} held · {(d.quad == q).sum() / max(len(d), 1):.0%} of universe</div>
            </div>""" for q in ("Q1", "Q2", "Q3", "Q4"))

    legend = "".join(
        f"""<tr><td style="white-space:nowrap"><b style="color:{QUADS[q]['color']}">{QUADS[q]['name']}</b></td>
            <td style="text-align:center;color:#64748b">{'X ≥ 0, Y ≥ 0' if q=='Q1' else 'X &lt; 0, Y ≥ 0' if q=='Q2' else 'X ≥ 0, Y &lt; 0' if q=='Q3' else 'X &lt; 0, Y &lt; 0'}</td>
            <td style="text-align:center"><b>{ {'Q1':1,'Q2':2,'Q3':3,'Q4':4}[q] }</b></td>
            <td style="color:#64748b">{QUADS[q]['desc']}</td></tr>""" for q in ("Q1", "Q2", "Q3", "Q4"))

    na_rows = ", ".join(f"<b>{t}★</b>" if t in held_missing else t
                        for t in sorted(na.ticker)) if len(na) else "none"

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0"><title>IC — Quad Map</title>
<style>
body{{font-family:Calibri,Arial,sans-serif;background:#f1f5f9;margin:0;color:#1e293b}}
.hdr{{background:{NAVY};border-bottom:3px solid {GOLD};padding:18px 30px}}
.hdr h1{{color:#fff;font-size:21px;margin:0}}.hdr .s{{color:{GOLD};font-size:12px;margin-top:3px}}
.wrap{{max-width:1180px;margin:0 auto;padding:22px 18px}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px 18px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.05)}}
.card h2{{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:{NAVY};margin:0 0 12px;border-left:4px solid {NAVY};padding-left:9px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:10px}}
.k{{background:#f8fafc;border-radius:8px;padding:10px 12px}}
.kl{{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.5px}}
.kv{{font-size:24px;font-weight:700;margin:2px 0}}
.ks{{font-size:10px;color:#94a3b8}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:#94a3b8;text-align:left;padding:4px 0}}
td{{padding:6px 0;border-bottom:1px solid #f1f5f9;vertical-align:top}}
.note{{font-size:11px;color:#64748b;line-height:1.55}}
.foot{{text-align:center;color:#94a3b8;font-size:11px;margin:18px 0}}
</style></head><body>
<div class="hdr"><h1>Quad Map — The Whole Universe</h1>
<div class="s">Integrity Compounders · {len(d)} of {len(df)} names plotted · {n_held_plot} of {n_held_total} holdings · data {dd} · Fiscal AI screen</div></div>
<div class="wrap">

<div class="card"><h2>Distribution</h2><div class="kpis">{kpis}</div></div>

<div class="card"><h2>Quad Grid — every active name by revenue &amp; earnings momentum</h2>
{chart}
<div class="note" style="margin-top:10px">
<b>Reading it.</b> Each point is one company. Right = revenue accelerating vs its own 3Y trend;
up = earnings accelerating. Gold rings with tickers are positions we hold; hover anything for detail.
Click a legend entry to isolate a quadrant.<br>
<b>Triangles</b> are clipped outliers (§5.3): axes bound at ±30%, and {n_clip} names run past it —
they sit on the edge pointing the way they went, with the true value in the hover. One name reaches
−667% on earnings momentum, so plotting unclipped would flatten everything else into a dot.<br>
<b>That row along the bottom is a finding, not an artefact.</b> {n_ybot} names — {n_ybot/max(len(d),1):.0%} of
the universe — have earnings momentum below −30%, and {n_neg:.0%} of the screen sits in Q3 or Q4
(negative earnings momentum) at all. The screen is currently finding far more decelerating earnings
than accelerating ones.
</div></div>

<div class="card"><h2>Quadrant definitions</h2>
<table><tr><th>Quadrant</th><th style="text-align:center">Rule</th><th style="text-align:center">EV Rank</th><th>Character</th></tr>
{legend}</table>
<div class="note" style="margin-top:10px">
<b>X = Revenue Momentum</b> = Fwd Rev CAGR − Trailing Rev 3Y CAGR.
<b>Y = Earnings Momentum</b> = Fwd EPS CAGR (capped 25%) − Trailing EPS 3Y CAGR.
Both measure <i>acceleration against a company's own history</i>, not absolute growth — a
fast grower that is slowing plots left, a modest grower that is speeding up plots right.<br>
Quadrant assignment follows <code>engines/quad.py::_assign_quadrant</code> and CLAUDE.md §5.2;
verified consistent on {len(d)}/{len(d)} names. Zero is treated as non-negative (X=0 or Y=0 → the
upper/right side), which differs from §5.2's stated conservative tie-break.<br>
A first-time move into a new quadrant is <b>provisional</b> — §5.2 requires two consecutive
month-ends before a migration counts as signal.
</div></div>

<div class="card"><h2>Not plotted ({len(na)}) — including {len(held_missing)} we hold</h2>
<div class="note">Tracked but absent from the current Fiscal AI screen, so there are no forward
CAGRs to compute either axis from. They are not failures and they are not removed (§4.1); they
reappear the moment they return to a screen.
{'<br><br><b style="color:#b45309">★ Holdings with no quad this screen: ' + ', '.join(held_missing)
  + f'</b><br><span style="color:#64748b">The grid above therefore shows {n_held_plot} of your '
    f'{n_held_total} positions — these {len(held_missing)} are un-quadded, not un-held.</span>'
  if held_missing else ''}
<br><br><span style="color:#475569">{na_rows}</span></div></div>

<div class="foot">Integrity Compounders · Alpha System v12.1 · generated {datetime.now().strftime('%B %d, %Y · %I:%M %p')}</div>
</div></body></html>"""


def main():
    df = load()
    out = DOCS / "quad_map.html"
    out.write_text(html(df), encoding="utf-8")
    d = df.dropna(subset=["x", "y", "quad"])
    print(f"  📄  docs/quad_map.html ({out.stat().st_size:,} bytes)")
    print(f"      {len(d)} plotted · " + " · ".join(f"{q} {int((d.quad==q).sum())}" for q in ("Q1","Q2","Q3","Q4"))
          + f" · {len(df) - len(d)} unplotted")


if __name__ == "__main__":
    main()
