"""
vision.py — PDF & Chart/Image Analysis Engine
Integrity Compounders Alpha System v10.0

Gives Claude eyes on your research materials:
  - PDFs:   SEC filings, annual reports, earnings releases, investor letters
  - Images: Price charts, financial charts, screenshots, handwritten notes, tables

Usage:
    from engines.vision import analyze_file, analyze_pdf, analyze_chart

CLI:
    python run.py analyze PATH/TO/FILE.pdf [TICKER]
    python run.py analyze PATH/TO/CHART.png [TICKER]
    python run.py analyze PATH/TO/FILE.pdf AAPL --save   (save Obsidian note)
"""

import sys
import base64
import mimetypes
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
from config.settings import settings

# ── Supported types ────────────────────────────────────────────────────────────
PDF_EXTENSIONS   = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
ALL_SUPPORTED    = PDF_EXTENSIONS | IMAGE_EXTENSIONS

MODEL = "claude-opus-4-5"   # Use Opus for vision — highest accuracy on documents/charts

# ── System prompts ─────────────────────────────────────────────────────────────
PDF_SYSTEM = """You are a senior equity analyst at Integrity Wealth Partners analyzing a document.
Your job is to extract every piece of financially relevant information and assess its impact
on the investment thesis for the company involved.

Be specific with numbers. Quote directly when relevant. Flag anything unusual.
Structure your output using the exact section headers requested. No filler."""

CHART_SYSTEM = """You are a senior equity analyst at Integrity Wealth Partners with deep experience
in both technical analysis and fundamental investing. You are looking at a chart or visual.

Describe exactly what you see. Extract every data point visible. Identify patterns, trends,
anomalies, and inflections. Relate what you see to fundamental thesis confirmation or risk.
If the chart contains financial data (income statement, balance sheet, ratios), extract every number.
If it is a price chart, assess price structure, momentum, support/resistance, and volume trends.
No filler. Be direct."""

# ── PDF analysis prompt ────────────────────────────────────────────────────────
PDF_ANALYSIS_PROMPT = """Analyze this document as a senior equity analyst. Structure your response exactly as follows:

## Document Overview
Type of document, company, period covered, and any unusual context.

## Key Financial Metrics Extracted
List every specific number you can find — revenue, margins, ROIC, FCF, debt, growth rates.
Format as a table where possible.

## Five-Gate Check
Assess against these thresholds (mark ✅ PASS / ⚠️ WATCH / ❌ FAIL / — NOT AVAILABLE):
- ROIC ≥ 12%
- Gross Margin ≥ 35%
- FCF Margin ≥ 10%
- Revenue 3Y CAGR ≥ 6%
- Net Debt/EBITDA ≤ 2.5×

## Management Commentary
What did management say? Tone, forward guidance, capital allocation signals, anything unusual.
Direct quotes in blockquotes.

## Competitive & Moat Signals
Evidence of pricing power, market share changes, competitive threats, moat strengthening or weakening.

## Risk Factors
New or changed risks. Flag anything that could invalidate an investment thesis.

## Pillar Impact Assessment
How does this document affect each of the 5 pillars:
- P1 Business Quality: [STRENGTHENS / NEUTRAL / WEAKENS] — reason
- P2 Management Integrity: [STRENGTHENS / NEUTRAL / WEAKENS] — reason
- P3 Financial Strength: [STRENGTHENS / NEUTRAL / WEAKENS] — reason
- P4 Reinvestment Opportunity: [STRENGTHENS / NEUTRAL / WEAKENS] — reason
- P5 Valuation Discipline: [STRENGTHENS / NEUTRAL / WEAKENS] — reason

## Red Flags
Bullet list — be blunt.

## Green Flags
Bullet list — be specific.

## Thesis Impact
**STRENGTHENS / NEUTRAL / WEAKENS** — two paragraphs of direct analytical verdict.

## Action Implication
**ADD / HOLD / TRIM / REVIEW / EXIT** — one paragraph with specific reasoning.
"""

# ── Chart analysis prompt ──────────────────────────────────────────────────────
CHART_ANALYSIS_PROMPT = """Analyze this chart or image as a senior equity analyst. Structure your response exactly as follows:

## What I'm Looking At
Describe the chart type, time period, data series, and any labels visible.

## Data Extraction
Extract every specific number, date, or data point visible. If it's a financial chart,
list all the figures. If it's a price chart, note key price levels, dates, and volumes.

## Pattern & Trend Analysis
What patterns do you see? Uptrend, downtrend, consolidation, breakout, breakdown?
Support and resistance levels? Volume confirmation or divergence?
For financial charts: acceleration, deceleration, inflection points, comparisons.

## Technical Assessment (price charts)
- Trend direction and strength
- Key support / resistance levels
- Momentum signals (if visible — RSI, MACD, etc.)
- Volume analysis
- Pattern formations (if any)
- Where price is relative to moving averages

## Fundamental Signals (financial data charts)
- Revenue / earnings trajectory
- Margin trends
- Return metrics direction
- Balance sheet changes
- Any accelerating or decelerating trends

## Thesis Confirmation Check
Does what you see in this chart STRENGTHEN, remain NEUTRAL, or WEAKEN an investment thesis?
Be specific about which aspect of the business this chart speaks to.

## Red Flags
Anything concerning visible in this chart.

## Green Flags
Anything constructive visible in this chart.

## Analyst Verdict
Two to three sentences. Direct assessment of what this chart tells you and what action it implies.
"""


# ── DB value maps ─────────────────────────────────────────────────────────────
# Map vision engine free-text → constrained DB enum values

_THESIS_MAP = {
    "strengthens": "STRENGTHENS",
    "strengthen":  "STRENGTHENS",
    "strengthen":  "STRENGTHENS",
    "neutral":     "NEUTRAL",
    "weakens":     "WEAKENS",
    "weaken":      "WEAKENS",
}
_ACTION_VALID = {"ADD", "HOLD", "TRIM", "REVIEW", "EXIT", "MONITOR", "NONE"}

def _map_thesis(raw: str) -> str:
    return _THESIS_MAP.get(str(raw or "").lower().strip(), "NEUTRAL")

def _map_action(raw: str) -> str:
    val = str(raw or "").upper().strip()
    return val if val in _ACTION_VALID else "NONE"


# ── Supabase writer ────────────────────────────────────────────────────────────

def _write_to_supabase(result: dict, ticker: str | None, content_type: str,
                        md_path: str) -> None:
    """
    Insert analysis result into research_inputs table.
    Non-fatal — logs warning on failure but never blocks outputs.
    """
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        cur  = conn.cursor()

        # Resolve company_id from ticker
        company_id = None
        if ticker:
            cur.execute("SELECT id FROM companies WHERE ticker = %s", (ticker.upper(),))
            row = cur.fetchone()
            if row:
                company_id = row[0]

        # Extract structured fields from analysis text where possible
        analysis    = result.get("analysis", "")
        thesis_raw  = result.get("thesis_impact", "NEUTRAL")
        action_raw  = result.get("action_implication", "NONE")

        # Parse thesis / action from analysis text if result dict doesn't carry them
        if "strengthens" in analysis.lower():
            thesis_raw = "STRENGTHENS"
        elif "weakens" in analysis.lower():
            thesis_raw = "WEAKENS"

        for word in ["ADD", "EXIT", "TRIM", "REVIEW", "MONITOR", "HOLD"]:
            if f"**{word}**" in analysis or f"## Action Implication\n**{word}" in analysis:
                action_raw = word
                break

        cur.execute("""
            INSERT INTO research_inputs (
                company_id, ticker, source_id, content_type, research_date,
                obsidian_path, raw_content, thesis_impact, signal_strength,
                ai_summary, ai_action_implication, ai_processed_at
            ) VALUES (
                %s, %s, %s, %s,
                CURRENT_DATE,
                %s, %s, %s, %s, %s, %s,
                NOW()
            )
        """, (
            company_id,
            ticker.upper() if ticker else None,
            "internal_research",
            content_type,
            str(md_path),
            analysis[:5000],                        # raw_content (first 5k chars)
            _map_thesis(thesis_raw),                # STRENGTHENS / NEUTRAL / WEAKENS
            result.get("signal_strength", "HIGH"),  # HIGH for vision-analyzed docs
            analysis[:2000],                        # ai_summary (first 2k chars)
            _map_action(action_raw),                # ADD/HOLD/TRIM/REVIEW/EXIT/MONITOR/NONE
        ))

        conn.commit()
        cur.close()
        conn.close()
        print(f"  [Supabase] research_inputs row written ({ticker or 'no ticker'})")

    except Exception as e:
        print(f"  [Supabase] Write failed (non-fatal): {e}")


# ── Client factory ─────────────────────────────────────────────────────────────

def _get_client():
    import anthropic
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


# ── File loader ────────────────────────────────────────────────────────────────

def _load_file(path: Path) -> tuple[str, str]:
    """
    Load a file and return (base64_data, media_type).
    Raises ValueError for unsupported types.
    """
    suffix = path.suffix.lower()
    if suffix not in ALL_SUPPORTED:
        raise ValueError(
            f"Unsupported file type: {suffix}\n"
            f"Supported: {', '.join(sorted(ALL_SUPPORTED))}"
        )
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")

    if suffix == ".pdf":
        return data, "application/pdf"
    # Images
    mime_map = {
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif":  "image/gif",
        ".webp": "image/webp",
        ".bmp":  "image/png",    # convert in Claude
        ".tiff": "image/png",
        ".tif":  "image/png",
    }
    return data, mime_map.get(suffix, "image/png")


# ── Core analysis functions ────────────────────────────────────────────────────

def analyze_pdf(path: str | Path, ticker: str = "", extra_context: str = "") -> dict:
    """
    Send a PDF to Claude for full document analysis.
    Returns dict with keys: analysis, ticker, filename, timestamp, file_type
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    print(f"  [PDF] Loading {path.name} ({path.stat().st_size / 1024:.0f} KB)...")
    b64_data, media_type = _load_file(path)

    client = _get_client()

    context_block = f"\nCompany/Ticker context: {ticker.upper()}\n" if ticker else ""
    if extra_context:
        context_block += f"\nAdditional context: {extra_context}\n"

    print(f"  [PDF] Sending to Claude ({MODEL}) for analysis...")

    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=PDF_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64_data,
                    },
                },
                {
                    "type": "text",
                    "text": context_block + PDF_ANALYSIS_PROMPT,
                },
            ],
        }],
    )

    analysis = message.content[0].text
    print(f"  [PDF] Analysis complete ({len(analysis.split())} words)")

    return {
        "analysis":   analysis,
        "ticker":     ticker.upper() if ticker else "",
        "filename":   path.name,
        "filepath":   str(path),
        "file_type":  "pdf",
        "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M"),
        "model":      MODEL,
        "tokens_in":  message.usage.input_tokens,
        "tokens_out": message.usage.output_tokens,
    }


def analyze_chart(path: str | Path, ticker: str = "", extra_context: str = "") -> dict:
    """
    Send a chart/image to Claude for visual analysis.
    Returns dict with keys: analysis, ticker, filename, timestamp, file_type
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    print(f"  [Chart] Loading {path.name} ({path.stat().st_size / 1024:.0f} KB)...")
    b64_data, media_type = _load_file(path)

    client = _get_client()

    context_block = f"\nCompany/Ticker context: {ticker.upper()}\n" if ticker else ""
    if extra_context:
        context_block += f"\nAdditional context: {extra_context}\n"

    print(f"  [Chart] Sending to Claude ({MODEL}) for visual analysis...")

    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=CHART_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64_data,
                    },
                },
                {
                    "type": "text",
                    "text": context_block + CHART_ANALYSIS_PROMPT,
                },
            ],
        }],
    )

    analysis = message.content[0].text
    print(f"  [Chart] Analysis complete ({len(analysis.split())} words)")

    return {
        "analysis":   analysis,
        "ticker":     ticker.upper() if ticker else "",
        "filename":   path.name,
        "filepath":   str(path),
        "file_type":  "chart",
        "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M"),
        "model":      MODEL,
        "tokens_in":  message.usage.input_tokens,
        "tokens_out": message.usage.output_tokens,
    }


def analyze_file(path: str | Path, ticker: str = "", extra_context: str = "") -> dict:
    """
    Auto-detect file type and route to analyze_pdf or analyze_chart.
    This is the main entry point for the CLI command.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in PDF_EXTENSIONS:
        return analyze_pdf(path, ticker, extra_context)
    elif suffix in IMAGE_EXTENSIONS:
        return analyze_chart(path, ticker, extra_context)
    else:
        raise ValueError(
            f"Cannot analyze '{path.name}'. "
            f"Supported: PDFs ({', '.join(sorted(PDF_EXTENSIONS))}) "
            f"and images ({', '.join(sorted(IMAGE_EXTENSIONS))})"
        )


# ── Output formatters ──────────────────────────────────────────────────────────

def _result_to_markdown(result: dict) -> str:
    """Format analysis result as an Obsidian-ready markdown note."""
    ticker   = result.get("ticker", "")
    filename = result.get("filename", "")
    ftype    = result.get("file_type", "")
    ts       = result.get("timestamp", "")

    source_id = "sec_filings" if ftype == "pdf" else "internal_research"
    content_type = "document" if ftype == "pdf" else "chart"

    header = f"""---
ticker: "{ticker}"
company: ""
source_id: "{source_id}"
content_type: "{content_type}"
file_type: "{ftype}"
source_file: "{filename}"
date: {ts[:10]}
analyzed_by: "Claude {result.get('model','')}"
thesis_impact: ""
signal_strength: "high"
tags: [ai-analysis, {ftype}, {ticker.lower() if ticker else 'untagged'}]
---

> **AI Analysis** — {filename} — {ts}
> Analyzed by {result.get('model','')} · {result.get('tokens_in',0):,} tokens in · {result.get('tokens_out',0):,} tokens out

"""
    return header + result["analysis"]


def _result_to_html(result: dict, nav_back: bool = True) -> str:
    """Format analysis result as styled HTML matching IC branding."""
    import re

    ticker   = result.get("ticker", "")
    filename = result.get("filename", "")
    ftype    = result.get("file_type", "")
    ts       = result.get("timestamp", "")
    analysis = result.get("analysis", "")

    icon = "📄" if ftype == "pdf" else "📊"
    title = f"{icon} {'PDF Analysis' if ftype == 'pdf' else 'Chart Analysis'}"
    subtitle = f"{filename}"
    if ticker:
        subtitle = f"{ticker} · {subtitle}"

    NAVY = "#1F3A5F"

    # Convert markdown to basic HTML
    lines = analysis.split("\n")
    html_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            html_lines.append(
                f'<h2 style="font-size:16px;font-weight:800;color:{NAVY};margin:24px 0 10px;'
                f'padding-bottom:6px;border-bottom:2px solid #e5e7eb">{line[3:]}</h2>'
            )
        elif line.startswith("### "):
            html_lines.append(
                f'<h3 style="font-size:13px;font-weight:700;color:#374151;margin:16px 0 6px;'
                f'border-left:3px solid {NAVY};padding-left:10px">{line[4:]}</h3>'
            )
        elif line.startswith("> "):
            quote = line[2:]
            # Collect multi-line blockquote
            while i + 1 < len(lines) and lines[i+1].startswith("> "):
                i += 1
                quote += "<br>" + lines[i][2:]
            html_lines.append(
                f'<blockquote style="border-left:4px solid #2563eb;margin:10px 0;padding:8px 16px;'
                f'background:#eff6ff;color:#1e40af;font-style:italic;border-radius:0 8px 8px 0">'
                f'{quote}</blockquote>'
            )
        elif line.startswith("- ") or line.startswith("* "):
            bullets = []
            while i < len(lines) and (lines[i].startswith("- ") or lines[i].startswith("* ")):
                content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", lines[i][2:])
                for emoji, color in [("✅","#16a34a"),("⚠️","#d97706"),("❌","#dc2626")]:
                    content = content.replace(emoji, f'<span style="color:{color}">{emoji}</span>')
                bullets.append(f'<li style="margin-bottom:5px;line-height:1.6">{content}</li>')
                i += 1
            html_lines.append(
                f'<ul style="margin:6px 0 12px 20px;color:#374151;font-size:13px">{"".join(bullets)}</ul>'
            )
            continue
        elif line.startswith("| "):
            # Table
            table_lines = []
            while i < len(lines) and lines[i].startswith("| "):
                table_lines.append(lines[i])
                i += 1
            if len(table_lines) >= 2:
                headers = [h.strip() for h in table_lines[0].split("|")[1:-1]]
                th = "".join(f'<th style="padding:8px 12px;text-align:left;font-size:12px">{h}</th>' for h in headers)
                rows = ""
                for j, tl in enumerate(table_lines[2:]):  # skip separator
                    cells = [c.strip() for c in tl.split("|")[1:-1]]
                    bg = "#f9fafb" if j % 2 == 0 else "white"
                    td = "".join(f'<td style="padding:7px 12px;font-size:12px;color:#374151">{c}</td>' for c in cells)
                    rows += f'<tr style="background:{bg}">{td}</tr>'
                html_lines.append(
                    f'<table style="width:100%;border-collapse:collapse;margin:10px 0 16px">'
                    f'<thead><tr style="background:{NAVY};color:white">{th}</tr></thead>'
                    f'<tbody>{rows}</tbody></table>'
                )
            continue
        elif line.strip() == "---":
            html_lines.append('<hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0">')
        elif line.strip():
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line.strip())
            # Color-code STRENGTHENS/NEUTRAL/WEAKENS
            content = content.replace("STRENGTHENS", '<span style="color:#16a34a;font-weight:700">STRENGTHENS</span>')
            content = content.replace("WEAKENS",     '<span style="color:#dc2626;font-weight:700">WEAKENS</span>')
            content = content.replace("NEUTRAL",     '<span style="color:#d97706;font-weight:700">NEUTRAL</span>')
            html_lines.append(
                f'<p style="font-size:13px;color:#374151;line-height:1.75;margin-bottom:10px">{content}</p>'
            )
        i += 1

    body = "\n".join(html_lines)
    run_ts = datetime.now().strftime("%B %d, %Y · %I:%M %p")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{subtitle}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>* {{box-sizing:border-box;margin:0;padding:0}} body {{font-family:'Source Sans 3',Calibri,sans-serif;background:#f1f5f9;color:#1e293b;-webkit-font-smoothing:antialiased}}</style>
</head>
<body>

<div style="background:linear-gradient(135deg,{NAVY},#2d5282);padding:28px 40px 24px">
  <div style="max-width:900px;margin:0 auto">
    <div style="font-size:11px;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:2px;margin-bottom:8px">
      Integrity Wealth Partners · AI Document Analysis
    </div>
    <div style="font-family:'Playfair Display',serif;font-size:28px;font-weight:800;color:white;margin-bottom:4px">
      {title}
    </div>
    <div style="font-size:14px;color:rgba(255,255,255,0.65);margin-bottom:16px">{subtitle}</div>
    <div style="display:flex;gap:16px;flex-wrap:wrap">
      {"".join(f'<div style="background:rgba(255,255,255,0.1);border-radius:8px;padding:8px 14px;font-size:12px;color:rgba(255,255,255,0.8)">{v}</div>'
        for v in [
          f"📅 {ts}",
          f"🤖 {result.get('model','')}",
          f"📥 {result.get('tokens_in',0):,} tokens in",
          f"📤 {result.get('tokens_out',0):,} tokens out",
          f"📁 {filename}",
        ] if v)}
    </div>
  </div>
</div>

<div style="max-width:900px;margin:0 auto;padding:28px 40px 48px">
  <div style="background:white;border-radius:16px;padding:36px;box-shadow:0 2px 12px rgba(0,0,0,0.08);border:1px solid #e5e7eb">
    {body}
  </div>
</div>

<div style="background:{NAVY};color:rgba(255,255,255,0.4);text-align:center;padding:16px;font-size:11px">
  Integrity Compounders · Alpha System v10.0 · {run_ts} · Internal Use Only
</div>
</body>
</html>"""


# ── Save outputs ───────────────────────────────────────────────────────────────

def save_analysis(result: dict, save_obsidian: bool = True) -> dict[str, Path]:
    """
    Save analysis as:
      - HTML report in outputs/reports/
      - Markdown note in Clippings/ (or Companies/TICKER/ if ticker provided)
    Returns dict of saved paths.
    """
    today    = datetime.today().strftime("%Y-%m-%d")
    ticker   = result.get("ticker", "")
    ftype    = result.get("file_type", "pdf")
    stem     = Path(result.get("filename", "analysis")).stem
    saved    = {}

    # HTML
    out_dir = ROOT / "outputs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    label    = "pdf" if ftype == "pdf" else "chart"
    html_name = f"{ticker + '_' if ticker else ''}{stem}_{label}_{today}.html"
    html_path = out_dir / html_name
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_result_to_html(result))
    print(f"  [Save] HTML  → {html_path}")
    saved["html"] = html_path

    # Obsidian Markdown — route to correct folder (mirrors watcher logic)
    if save_obsidian:
        md_dir = _route_output_folder(result)   # fixed: was always Clippings/
        md_dir.mkdir(parents=True, exist_ok=True)
        md_name = f"{today}_{ticker + '_' if ticker else ''}{stem}_{label}.md"
        md_path = md_dir / md_name
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(_result_to_markdown(result))
        print(f"  [Save] Note  → {md_path}")
        saved["markdown"] = md_path

        # Write to Supabase (non-fatal)
        _write_to_supabase(result, ticker or None, label, str(md_path))

    return saved


# ── CLI entry point ────────────────────────────────────────────────────────────

def run_analyze(filepath: str, ticker: str = "", extra_context: str = "",
                save: bool = True, open_browser: bool = True) -> dict:
    """
    Full pipeline: detect → analyze → save → optionally open in browser.
    Returns the result dict including saved paths.
    """
    path = Path(filepath)

    print(f"\n{'='*60}")
    print(f"  VISION ANALYSIS — {path.name}")
    print(f"  {datetime.now().strftime('%B %d, %Y · %I:%M %p')}")
    if ticker:
        print(f"  Ticker: {ticker.upper()}")
    print(f"{'='*60}\n")

    result = analyze_file(path, ticker=ticker, extra_context=extra_context)

    if save:
        saved = save_analysis(result, save_obsidian=True)
        result["saved"] = saved

        if open_browser and "html" in saved:
            import os, webbrowser
            webbrowser.open(f"file:///{str(saved['html']).replace(os.sep, '/')}")

    print(f"\n{'='*60}")
    print(f"  ANALYSIS COMPLETE — {path.name}")
    print(f"{'='*60}\n")

    return result
