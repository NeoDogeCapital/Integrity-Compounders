"""
watchlist_dashboard.py
Generate watchlist-dashboard.html from live Supabase data.
Usage: python outputs/reports/watchlist_dashboard.py
"""
import sys
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
from config.settings import settings

NAVY = "#1F3A5F"
GOLD = "#C9A84C"

def get_conn():
    return psycopg2.connect(settings.DATABASE_URL)

def badge(text, color, bg):
    return f'<span style="background:{bg};color:{color};padding:2px 8px;border-radius:8px;font-size:11px;font-weight:600">{text}</span>'

def main():
    conn = get_conn()
    cur  = conn.cursor()
    run_ts = datetime.now().strftime("%B %d, %Y · %I:%M %p")

    cur.execute("""
        SELECT w.ticker, w.company_name, w.status, w.current_composite_score,
               w.target_entry_score, w.target_entry_price, w.next_earnings_date,
               w.why_watching, w.source_of_idea, w.notes, w.date_added
        FROM watchlist w ORDER BY
          CASE w.status WHEN 'READY' THEN 1 WHEN 'APPROACHING' THEN 2
                        WHEN 'RESEARCHING' THEN 3 ELSE 4 END,
          w.current_composite_score DESC NULLS LAST
    """)
    all_wl = cur.fetchall()
    cols   = ["ticker","name","status","score","target_score","target_price",
               "next_earnings","why","source","notes","date_added"]
    all_wl = [dict(zip(cols, r)) for r in all_wl]

    ready       = [w for w in all_wl if w["status"] == "READY"]
    approaching = [w for w in all_wl if w["status"] == "APPROACHING"]
    researching = [w for w in all_wl if w["status"] == "RESEARCHING"]
    passed      = [w for w in all_wl if w["status"] == "PASSED"]

    status_colors = {
        "READY":      ("#166534","#dcfce7"),
        "APPROACHING":("#1e40af","#dbeafe"),
        "RESEARCHING":("#374151","#f3f4f6"),
        "PASSED":     ("#6b7280","#f3f4f6"),
    }

    def wl_card(w) -> str:
        s = str(w.get("status",""))
        fc, bc = status_colors.get(s,("#374151","#f9fafb"))
        sc = w.get("score")
        sc_str   = f"{float(sc):.1f}" if sc else "—"
        sc_color = "#16a34a" if sc and float(sc)>=7.5 else "#d97706" if sc and float(sc)>=6 else "#dc2626"
        ts = w.get("target_score")
        ts_str = f"{float(ts):.1f}" if ts else "—"
        tp = w.get("target_price")
        tp_str = f"${float(tp):,.2f}" if tp else "—"
        earn = w.get("next_earnings")
        earn_str = str(earn) if earn else "—"

        return f"""
        <div style="background:white;border-radius:12px;border-left:4px solid {fc};
                    padding:16px 18px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,0.06)">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
            <div>
              <span style="font-size:18px;font-weight:800;color:{NAVY}">{w.get('ticker','')}</span>
              <span style="font-size:13px;color:#374151;margin-left:10px">{str(w.get('name',''))[:30]}</span>
              <div style="margin-top:5px">{badge(s,fc,bc)}</div>
            </div>
            <div style="text-align:right">
              <div style="font-size:20px;font-weight:800;color:{sc_color}">{sc_str}</div>
              <div style="font-size:10px;color:#6b7280;text-transform:uppercase">Score</div>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px">
            {"".join(f'<div style="background:#f8fafc;border-radius:6px;padding:7px 10px"><div style="font-size:10px;color:#6b7280;text-transform:uppercase">{l}</div><div style="font-size:13px;font-weight:600;color:#374151;margin-top:2px">{v}</div></div>'
              for l,v in [("Target Score",ts_str),("Target Price",tp_str),("Next Earnings",earn_str)])}
          </div>
          {"" if not w.get('why') else f'<div style="font-size:12px;color:#6b7280;line-height:1.5"><strong>Why watching:</strong> {str(w["why"])[:120]}</div>'}
          {"" if not w.get('notes') else f'<div style="font-size:11px;color:#9ca3af;margin-top:5px">{str(w["notes"])[:80]}</div>'}
        </div>"""

    def section(title, items, empty_msg="Nothing in this category.") -> str:
        content = "".join(wl_card(w) for w in items) if items else f'<p style="color:#6b7280;font-style:italic;padding:12px">{empty_msg}</p>'
        return f"""
        <div style="background:white;border-radius:14px;padding:22px;margin-bottom:20px;
                    box-shadow:0 1px 4px rgba(0,0,0,0.07);border:1px solid #e5e7eb">
          <div style="border-left:4px solid {NAVY};padding-left:12px;margin-bottom:16px">
            <h2 style="font-size:15px;font-weight:800;color:{NAVY}">{title}</h2>
          </div>
          {content}
        </div>"""

    # Researching — gap analysis
    research_rows = ""
    for w in researching:
        sc = float(w.get("score") or 0)
        ts = float(w.get("target_score") or 7.5)
        gap = ts - sc
        gap_color = "#dc2626" if gap > 2 else "#d97706" if gap > 1 else "#16a34a"
        research_rows += f"""
        <tr>
          <td style="padding:8px 12px;font-weight:700;color:{NAVY}">{w.get('ticker','')}</td>
          <td style="padding:8px 12px;font-size:12px;color:#374151">{str(w.get('name',''))[:22]}</td>
          <td style="padding:8px 12px;text-align:center;font-weight:700;color:#374151">{f"{sc:.1f}" if sc else "—"}</td>
          <td style="padding:8px 12px;text-align:center;color:#374151">{f"{ts:.1f}" if ts else "—"}</td>
          <td style="padding:8px 12px;text-align:center;font-weight:700;color:{gap_color}">{f"+{gap:.1f} needed" if gap > 0 else "READY"}</td>
          <td style="padding:8px 12px;font-size:11px;color:#6b7280">{str(w.get('why',''))[:50]}</td>
        </tr>"""

    if not research_rows:
        research_rows = '<tr><td colspan="6" style="padding:12px;color:#6b7280;text-align:center;font-style:italic">No companies being researched.</td></tr>'

    passed_rows = ""
    for w in passed:
        passed_rows += f"""
        <tr>
          <td style="padding:8px 12px;font-weight:700;color:#6b7280">{w.get('ticker','')}</td>
          <td style="padding:8px 12px;font-size:12px;color:#6b7280">{str(w.get('name',''))[:24]}</td>
          <td style="padding:8px 12px;font-size:12px;color:#6b7280">{str(w.get('date_added',''))}</td>
          <td style="padding:8px 12px;font-size:12px;color:#6b7280">{str(w.get('notes',''))[:60]}</td>
        </tr>"""
    if not passed_rows:
        passed_rows = '<tr><td colspan="4" style="padding:12px;color:#6b7280;text-align:center;font-style:italic">None passed on yet.</td></tr>'

    tbl_hdr = lambda cols: f'<tr style="background:{NAVY};color:white">{"".join(f"<th style=\'padding:8px 12px;text-align:left;font-size:12px\'>{c}</th>" for c in cols)}</tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Watchlist Dashboard · {date.today()}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:'Source Sans 3',Calibri,sans-serif;background:#f1f5f9;color:#1e293b}}</style>
</head><body>
<div style="background:linear-gradient(135deg,{NAVY},#2d5282);padding:24px 32px 20px">
  <div style="max-width:1000px;margin:0 auto">
    <div style="font-family:'Playfair Display',serif;font-size:24px;font-weight:800;color:white;margin-bottom:4px">Watchlist Dashboard</div>
    <div style="font-size:12px;color:rgba(255,255,255,0.5);margin-bottom:18px">{run_ts}</div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px">
      {"".join(f'<div style="background:rgba(255,255,255,0.1);border-radius:10px;padding:12px;text-align:center"><div style="font-size:22px;font-weight:800;color:white">{v}</div><div style="font-size:10px;color:rgba(255,255,255,0.5);margin-top:3px;text-transform:uppercase">{l}</div></div>'
        for v,l in [(len(ready),"Ready"),(len(approaching),"Approaching"),
                    (len(researching),"Researching"),(len(passed),"Passed")])}
    </div>
  </div>
</div>
<div style="max-width:1000px;margin:0 auto;padding:24px 32px 40px">
  {section(f"🎯 Ready to Initiate ({len(ready)})", ready, "No names at READY status.")}
  {section(f"📈 Approaching ({len(approaching)})", approaching, "No names approaching conditions.")}
  <div style="background:white;border-radius:14px;padding:22px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,0.07);border:1px solid #e5e7eb">
    <div style="border-left:4px solid {NAVY};padding-left:12px;margin-bottom:16px">
      <h2 style="font-size:15px;font-weight:800;color:{NAVY}">Researching ({len(researching)}) — Score Gap to Initiation</h2>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>{tbl_hdr(["Ticker","Company","Score","Target","Gap","Why Watching"])}</thead>
      <tbody>{research_rows}</tbody>
    </table>
  </div>
  <div style="background:white;border-radius:14px;padding:22px;box-shadow:0 1px 4px rgba(0,0,0,0.07);border:1px solid #e5e7eb">
    <div style="border-left:4px solid #6b7280;padding-left:12px;margin-bottom:16px">
      <h2 style="font-size:15px;font-weight:800;color:#6b7280">Passed On ({len(passed)})</h2>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>{tbl_hdr(["Ticker","Company","Date","Reason"])}</thead>
      <tbody>{passed_rows}</tbody>
    </table>
  </div>
</div>
<div style="background:{NAVY};color:rgba(255,255,255,0.4);text-align:center;padding:14px;font-size:11px">
  Integrity Compounders · Alpha System V12 · {run_ts} · Internal Use Only<br>
  <span style="font-size:10px">Refresh: python outputs/reports/watchlist_dashboard.py</span>
</div></body></html>"""

    out_path = Path(__file__).parent / "watchlist-dashboard.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    cur.close()
    conn.close()
    print(f"  [Dashboard] Saved: {out_path}")

if __name__ == "__main__":
    main()
