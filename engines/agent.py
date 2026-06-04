"""
agent.py — AI Research Brief Agent
Integrity Compounders Alpha System v10.0

Generates a two-page internal research brief for any ticker:
  Step 1  Pull all model data from universe.db
  Step 2  Web research via DuckDuckGo (earnings + business model)
  Step 3  Call Claude API to write the structured brief
  Step 4  Save as Markdown (wiki/) + styled HTML (outputs/reports/)
  Step 5  Called via: python run.py brief TICKER
"""

import sys
import re
import time
import textwrap
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values
from engines.database import get_universe, get_conn
from engines.screener import run_gates
from engines.quad import compute_axes, assign_quadrants, QUAD_NAME
from engines.alignment import compute_alignment
from engines.fcf_flip import compute_flip_scores
from engines.pods import assign_pods


# ── Config ─────────────────────────────────────────────────────────────────────
MODEL   = "claude-sonnet-4-5"
NAVY    = "#1F3A5F"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ── Step 1: Pull model data ───────────────────────────────────────────────────

def get_model_data(ticker: str) -> dict:
    """Pull and compute full model state for ticker."""
    print(f"  [Step 1] Pulling model data for {ticker}...")

    df = get_universe("all")
    df = run_gates(df)
    df = compute_axes(df)
    df = assign_quadrants(df)
    df = assign_pods(df)
    df = compute_alignment(df)
    df = compute_flip_scores(df)

    row = df[df["ticker"] == ticker]
    if row.empty:
        raise ValueError(f"{ticker} not found in universe. Run `python run.py refresh` first.")

    r = row.iloc[0]

    def g(field, default=None):
        v = r.get(field, default)
        return None if (v is None or (isinstance(v, float) and __import__("math").isnan(v))) else v

    data = {
        "ticker":           ticker,
        "company":          g("company", ticker),
        "industry":         g("industry", ""),
        "quadrant":         g("quadrant", "N/A"),
        "quad_name":        QUAD_NAME.get(str(g("quadrant","N/A")), "N/A"),
        "ev_rank":          g("ev_rank"),
        "alignment_score":  g("alignment_score"),
        "alignment_bucket": g("alignment_bucket"),
        "pead_flag":        g("pead_flag"),
        "fv_rank":          g("fv_rank"),
        "mc_rank":          g("mc_rank"),
        "esv_rank":         g("esv_rank"),
        "x_axis":           g("earnings_mom_roc"),   # Rev Momentum
        "y_axis":           g("multiple_roc"),        # EPS Momentum
        "roic":             g("roic"),
        "op_margin":        g("op_margin"),
        "fcf_yield":        g("fcf_yield"),
        "fwd_fcf_yield":    g("fwd_fcf_yield"),
        "rev_3y_cagr":      g("rev_3y_cagr"),
        "fwd_rev_cagr":     g("fwd_rev_cagr"),
        "eps_3y_cagr":      g("eps_3y_cagr"),
        "fwd_eps_cagr":     g("fwd_eps_cagr"),
        "net_debt_ebitda":  g("net_debt_ebitda"),
        "beta":             g("beta"),
        "peg":              g("peg"),
        "stock_price":      g("stock_price"),
        "market_cap":       g("market_cap"),
        "tr_1m":            g("tr_1m"),
        "ytd_perf":         g("ytd_perf"),
        "pod":              g("pod"),
        "pod_count":        g("pod_count"),
        "flip_price":       g("flip_price"),
        "flip_setup_type":  g("flip_setup_type"),
        "fcf_spread_tag":   g("fcf_spread_tag"),
        "convergence_count":g("convergence_count"),
    }

    print(f"  [Step 1] ✓ {ticker} — {data['company']} | {data['quadrant']} {data['quad_name']} | Score {data['alignment_score']:.1f}")
    return data


# ── Step 2: Web research ───────────────────────────────────────────────────────

def _ddg_search(query: str, max_results: int = 3) -> list[dict]:
    """Search DuckDuckGo HTML and return list of {title, url, snippet}."""
    url = "https://html.duckduckgo.com/html/"
    try:
        resp = requests.post(url, data={"q": query}, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        for result in soup.select(".result")[:max_results * 2]:
            title_el = result.select_one(".result__title a")
            snippet_el = result.select_one(".result__snippet")
            if not title_el:
                continue
            href = title_el.get("href", "")
            # DuckDuckGo wraps URLs — extract the real one
            if "uddg=" in href:
                from urllib.parse import unquote, parse_qs, urlparse
                qs = parse_qs(urlparse(href).query)
                href = unquote(qs.get("uddg", [href])[0])
            # Skip DDG internal or ad links
            if "duckduckgo.com" in href or not href.startswith("http"):
                continue
            results.append({
                "title":   title_el.get_text(strip=True),
                "url":     href,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            })
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"    [Search] Warning: DDG search failed ({e})")
        return []


def _fetch_page_text(url: str, max_words: int = 150) -> str:
    """Fetch a URL and return plain-text extract (max_words)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove scripts, styles, navs
        for tag in soup(["script","style","nav","header","footer","aside","form"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        words = text.split()
        return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")
    except Exception as e:
        return f"[Could not fetch page: {e}]"


def web_research(ticker: str, company: str) -> dict:
    """Run two searches, fetch top results, return structured research dict."""
    print(f"  [Step 2] Running web research for {ticker}...")

    searches = {
        "earnings": f"{ticker} {company} earnings results 2026",
        "business": f"{ticker} {company} business model competitive advantage",
    }

    research = {}
    for key, query in searches.items():
        print(f"    Searching: \"{query}\"")
        results = _ddg_search(query, max_results=3)
        sources = []
        for i, r in enumerate(results):
            print(f"      [{i+1}] {r['title'][:60]} — {r['url'][:60]}")
            text = _fetch_page_text(r["url"])
            sources.append({
                "title":   r["title"],
                "url":     r["url"],
                "snippet": r["snippet"],
                "extract": text,
            })
            time.sleep(0.5)   # polite delay
        research[key] = sources

    print(f"  [Step 2] ✓ Found {sum(len(v) for v in research.values())} sources")
    return research


def _format_research_for_prompt(research: dict) -> str:
    """Format web research into a clean prompt block."""
    lines = []
    for section, sources in research.items():
        heading = "RECENT EARNINGS & NEWS" if section == "earnings" else "BUSINESS MODEL & COMPETITIVE ADVANTAGE"
        lines.append(f"\n## {heading}")
        if not sources:
            lines.append("No sources retrieved.")
            continue
        for i, s in enumerate(sources, 1):
            lines.append(f"\nSource {i}: {s['title']}")
            lines.append(f"URL: {s['url']}")
            if s["snippet"]:
                lines.append(f"Snippet: {s['snippet']}")
            lines.append(f"Extract: {s['extract']}")
    return "\n".join(lines)


def _format_model_data_for_prompt(d: dict) -> str:
    """Format model data into a structured prompt block."""
    def pct(v):  return f"{v:.1f}%"  if v is not None else "N/A"
    def val(v):  return f"{v:.2f}"   if v is not None else "N/A"
    def ival(v): return str(int(v))  if v is not None else "N/A"
    def mul(v):  return f"{v:.1f}x"  if v is not None else "N/A"

    x = d.get("x_axis", 0) or 0
    y = d.get("y_axis", 0) or 0

    return f"""
## IC MODEL STATE — {d['ticker']} ({d['company']})
Industry: {d.get('industry','N/A')}
Pod: {d.get('pod','N/A')} (Pod Count: {d.get('pod_count','N/A')})

### Quad Framework
- Quadrant: {d['quadrant']} — {d['quad_name']}
- EV Rank: {ival(d.get('ev_rank'))} (1=Best Full Compounder, 4=Worst Full Deterioration)
- Revenue Momentum (X-Axis): {x:+.2f}% (Fwd Rev CAGR minus Trailing — positive = accelerating)
- Earnings Momentum (Y-Axis): {y:+.2f}% (Fwd EPS CAGR minus Trailing — positive = accelerating)

### Alignment Score
- Score: {val(d.get('alignment_score'))} / 100  |  Bucket: {d.get('alignment_bucket','N/A')}
- PEAD Flag: {d.get('pead_flag','—')}
- Convergence Signals: {d.get('convergence_count','N/A')}/3
- FV Rank: {val(d.get('fv_rank'))}  |  MC Rank: {val(d.get('mc_rank'))}  |  ESV Rank: {val(d.get('esv_rank'))}
- FCF Spread Tag: {d.get('fcf_spread_tag','—')}

### Quality Gates
- ROIC: {pct(d.get('roic'))}
- Operating Margin: {pct(d.get('op_margin'))}
- FCF Yield: {pct(d.get('fcf_yield'))}  |  Fwd FCF Yield: {pct(d.get('fwd_fcf_yield'))}
- Net Debt / EBITDA: {mul(d.get('net_debt_ebitda'))}

### Growth
- Revenue 3Y CAGR: {pct(d.get('rev_3y_cagr'))}  |  Fwd Rev CAGR: {pct(d.get('fwd_rev_cagr'))}
- EPS 3Y CAGR: {pct(d.get('eps_3y_cagr'))}  |  Fwd EPS CAGR: {pct(d.get('fwd_eps_cagr'))}

### Market Data
- Price: ${d.get('stock_price',0):,.2f}  |  Market Cap: ${d.get('market_cap',0):,.0f}M
- Beta: {val(d.get('beta'))}  |  PEG: {val(d.get('peg'))}
- 1M Return: {pct(d.get('tr_1m'))}  |  YTD Return: {pct(d.get('ytd_perf'))}

### FCF Flip Screen
- Flip Price: ${f"{d.get('flip_price'):.2f}" if d.get('flip_price') else 'N/A'}
- Setup Type: {d.get('flip_setup_type','N/A')}
"""


# ── Step 3: Call Claude API ────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a senior equity analyst at Integrity Wealth Partners writing an internal "
    "two-page research brief. Write in a direct analytical voice. Reference the specific "
    "model metrics naturally. Be honest about uncertainty. No filler."
)

BRIEF_STRUCTURE = """
Write a two-page internal research brief with EXACTLY this structure. Use markdown headers.

---
# PAGE 1

## The Business
Two paragraphs: what this company actually does, how it makes money, and its competitive position.

## The Story Right Now
Two paragraphs: what is the key narrative driving this stock today. Reference the quad position,
revenue momentum, and earnings momentum specifically.

## Recent Earnings
One paragraph summarizing the most recent earnings results and what they mean for the thesis.
Use the web research. Be specific about beats/misses if available.

## Bull Case
- [Bullet 1]
- [Bullet 2]
- [Bullet 3]

## Bear Case
- [Bullet 1]
- [Bullet 2]
- [Bullet 3]

---
# PAGE 2

## Model Snapshot
A concise table-style summary of the key model metrics. Reference alignment score, quad,
PEAD flag, convergence signals, ROIC, FCF yield, and both axis values.

## Price Action
One paragraph on recent price behavior (1M return, YTD), FCF spread tag, and what the
flip price implies about valuation sensitivity.

## Scenario Analysis
Three scenarios — base case, bull case, bear case — each with a brief description of
what would need to happen and what quad migration would signal each scenario playing out.

## Thesis Confirmation Checklist
Five checklist items specific to this business and thesis. For each, assign a status:
🟢 GREEN = confirmed and tracking, 🟡 YELLOW = mixed or uncertain, 🔴 RED = concern or broken.

Format each as:
- [Status emoji] **[Item]**: [One sentence assessment]

## Bottom Line
Three to four sentences. Direct verdict: should a position be initiated, held, added to, or trimmed.
Reference the specific triggers. No hedge words unless the uncertainty is real.

---
"""


def call_claude(ticker: str, model_data: dict, research: dict) -> str:
    """Send context to Claude and return the brief text."""
    print(f"  [Step 3] Calling Claude API ({MODEL})...")

    env = dotenv_values(ROOT / ".env")
    api_key = env.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not found in .env")

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    model_block   = _format_model_data_for_prompt(model_data)
    research_block = _format_research_for_prompt(research)

    user_message = f"""
Write a two-page internal research brief for {ticker} ({model_data.get('company','')}).

{model_block}

{research_block}

{BRIEF_STRUCTURE}

Today's date: {datetime.today().strftime('%B %d, %Y')}
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )

    brief_text = response.content[0].text
    print(f"  [Step 3] ✓ Brief generated ({len(brief_text.split())} words)")
    return brief_text


# ── Step 4: Save outputs ───────────────────────────────────────────────────────

def _md_to_html_sections(md: str) -> str:
    """Convert the markdown brief to styled HTML sections."""
    html = []
    current_page = 1

    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Page divider
        if line.strip().startswith("# PAGE"):
            page_num = "1" if "1" in line else "2"
            color = "#1F3A5F" if page_num == "1" else "#166534"
            label = "Page 1 — Fundamental Analysis" if page_num == "1" else "Page 2 — Model & Positioning"
            html.append(f'<div style="background:{color};color:white;padding:8px 20px;border-radius:8px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin:28px 0 20px">{label}</div>')
            i += 1
            continue

        # H2 section headers
        if line.startswith("## "):
            title = line[3:].strip()
            html.append(f'<h2 style="font-size:16px;font-weight:800;color:#1F3A5F;margin:24px 0 10px;padding-bottom:6px;border-bottom:2px solid #e5e7eb">{title}</h2>')
            i += 1
            continue

        # H3 sub-headers
        if line.startswith("### "):
            title = line[4:].strip()
            html.append(f'<h3 style="font-size:13px;font-weight:700;color:#374151;margin:16px 0 8px;text-transform:uppercase;letter-spacing:0.5px">{title}</h3>')
            i += 1
            continue

        # H1
        if line.startswith("# "):
            i += 1
            continue

        # Horizontal rule
        if line.strip() == "---":
            html.append('<hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0">')
            i += 1
            continue

        # Bullet points — collect a group
        if line.strip().startswith("- "):
            bullets = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                content = lines[i].strip()[2:]
                # Bold **text**
                content = re.sub(r"\*\*(.+?)\*\*", r'<strong>\1</strong>', content)
                # Status emojis with color
                for emoji, color in [("🟢","#16a34a"),("🟡","#d97706"),("🔴","#dc2626")]:
                    if emoji in content:
                        content = content.replace(emoji, f'<span style="font-size:14px">{emoji}</span>')
                bullets.append(f'<li style="margin-bottom:6px;line-height:1.6">{content}</li>')
                i += 1
            html.append(f'<ul style="margin:8px 0 12px 20px;color:#374151;font-size:13px">{"".join(bullets)}</ul>')
            continue

        # Regular paragraph
        stripped = line.strip()
        if stripped:
            # Bold **text**
            stripped = re.sub(r"\*\*(.+?)\*\*", r'<strong>\1</strong>', stripped)
            html.append(f'<p style="font-size:13px;color:#374151;line-height:1.7;margin-bottom:10px">{stripped}</p>')

        i += 1

    return "\n".join(html)


def save_outputs(ticker: str, model_data: dict, brief_text: str) -> tuple[Path, Path]:
    """Save brief as Markdown + HTML. Returns (md_path, html_path)."""
    today     = datetime.today().strftime("%Y-%m-%d")
    run_ts    = datetime.now().strftime("%B %d, %Y · %I:%M %p")
    company   = model_data.get("company", ticker)
    quadrant  = model_data.get("quadrant","N/A")
    score_val = model_data.get("alignment_score")
    score_str = f"{score_val:.1f}" if score_val else "N/A"
    bucket    = model_data.get("alignment_bucket","N/A")

    # ── Markdown ──────────────────────────────────────────────────────────────
    wiki_dir = ROOT / "wiki" / ticker
    wiki_dir.mkdir(parents=True, exist_ok=True)
    md_path = wiki_dir / f"{today}_{ticker}_brief.md"

    md_header = f"""---
ticker: {ticker}
company: {company}
date: {today}
quadrant: {quadrant}
alignment_score: {score_str}
alignment_bucket: {bucket}
generated_by: Integrity Compounders Alpha System v10.0
---

"""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_header + brief_text)
    print(f"  [Step 4] Markdown saved: {md_path}")

    # ── HTML ──────────────────────────────────────────────────────────────────
    out_dir = ROOT / "outputs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{ticker}_brief_{today}.html"

    brief_html = _md_to_html_sections(brief_text)

    # Quad color
    quad_colors = {"Q1":"#2563eb","Q2":"#16a34a","Q3":"#dc2626","Q4":"#d97706","N/A":"#6b7280"}
    q_color = quad_colors.get(quadrant, "#6b7280")
    score_color = "#16a34a" if (score_val and score_val >= 65) else "#d97706" if (score_val and score_val >= 35) else "#dc2626"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{ticker} Research Brief · {today}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{box-sizing:border-box;margin:0;padding:0}}
  body {{font-family:'Source Sans 3',Calibri,sans-serif;background:#f1f5f9;color:#1e293b;-webkit-font-smoothing:antialiased}}
  @media print {{body{{background:white}} .no-print{{display:none}}}}
</style>
</head>
<body>

<!-- Header -->
<div style="background:linear-gradient(135deg,#1F3A5F,#2d5282);padding:0">
  <div style="max-width:900px;margin:0 auto;padding:32px 40px 28px">
    <div style="font-size:11px;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:2px;margin-bottom:8px">
      Integrity Wealth Partners · Internal Research Brief
    </div>
    <div style="display:flex;justify-content:space-between;align-items:flex-start">
      <div>
        <div style="font-family:'Playfair Display',serif;font-size:40px;font-weight:800;color:white;letter-spacing:-1px;line-height:1">{ticker}</div>
        <div style="font-size:16px;color:rgba(255,255,255,0.7);margin-top:6px;font-weight:500">{company}</div>
        <div style="font-size:12px;color:rgba(255,255,255,0.45);margin-top:4px">{model_data.get('industry','')}</div>
      </div>
      <div style="text-align:right">
        <!-- Quad badge -->
        <div style="background:{q_color};color:white;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:700;display:inline-block;margin-bottom:8px">
          {quadrant} · {model_data.get('quad_name','N/A')}
        </div>
        <br>
        <!-- Score -->
        <div style="display:inline-block;text-align:center">
          <div style="font-size:36px;font-weight:800;color:{score_color};line-height:1">{score_str}</div>
          <div style="font-size:10px;color:rgba(255,255,255,0.5);text-transform:uppercase;margin-top:2px">{bucket}</div>
        </div>
      </div>
    </div>
    <!-- Stat strip -->
    <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-top:24px">
      {"".join(f'<div style="background:rgba(255,255,255,0.08);border-radius:8px;padding:10px;text-align:center"><div style="font-size:14px;font-weight:700;color:white">{v}</div><div style="font-size:10px;color:rgba(255,255,255,0.5);margin-top:2px;text-transform:uppercase">{l}</div></div>'
        for v,l in [
          (f"${model_data.get('stock_price',0):,.2f}", "Price"),
          (f"${model_data.get('market_cap',0)/1000:.1f}B" if (model_data.get('market_cap') or 0) >= 1000 else f"${model_data.get('market_cap',0):.0f}M", "Mkt Cap"),
          (f"{model_data.get('roic',0):.1f}%" if model_data.get('roic') else "N/A", "ROIC"),
          (f"{model_data.get('fcf_yield',0):.1f}%" if model_data.get('fcf_yield') else "N/A", "FCF Yield"),
          (f"{model_data.get('tr_1m',0):+.1f}%" if model_data.get('tr_1m') else "N/A", "1M Return"),
          (f"{model_data.get('ytd_perf',0):+.1f}%" if model_data.get('ytd_perf') else "N/A", "YTD"),
        ])}
    </div>
    <div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:16px">Generated {run_ts} · Alpha System v10.0 · Fiscal AI {today} · Internal Use Only</div>
  </div>
</div>

<!-- Brief content -->
<div style="max-width:900px;margin:0 auto;padding:32px 40px 48px">
  <div style="background:white;border-radius:16px;padding:36px;box-shadow:0 2px 12px rgba(0,0,0,0.08);border:1px solid #e5e7eb">
    {brief_html}
  </div>
</div>

<!-- Footer -->
<div style="background:#1F3A5F;color:rgba(255,255,255,0.4);text-align:center;padding:20px;font-size:11px">
  <div style="font-family:'Playfair Display',serif;font-size:14px;color:rgba(255,255,255,0.7);margin-bottom:4px">
    Integrity Compounders · Integrity Wealth Partners · LPL Financial Affiliate
  </div>
  Alpha System v10.0 · {run_ts} · Internal Use Only · Not for distribution
</div>

</body>
</html>"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  [Step 4] HTML saved: {html_path}")

    return md_path, html_path


# ── Step 5: Main entry point ───────────────────────────────────────────────────

def run_brief(ticker: str) -> str:
    """Full pipeline: model data → web research → Claude brief → save → return html path."""
    ticker = ticker.upper()
    today  = datetime.today().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"  RESEARCH BRIEF AGENT — {ticker}")
    print(f"  {datetime.now().strftime('%B %d, %Y · %I:%M %p')}")
    print(f"{'='*60}\n")

    model_data          = get_model_data(ticker)
    research            = web_research(ticker, model_data.get("company", ticker))
    brief_text          = call_claude(ticker, model_data, research)
    md_path, html_path  = save_outputs(ticker, model_data, brief_text)

    print(f"\n{'='*60}")
    print(f"  BRIEF COMPLETE — {ticker}")
    print(f"  Markdown : {md_path}")
    print(f"  HTML     : {html_path}")
    print(f"{'='*60}\n")

    return str(html_path)


# ══════════════════════════════════════════════════════════════════════════════
# BATCH RUNNER — run briefs for all portfolio names in universe
# ══════════════════════════════════════════════════════════════════════════════

def run_all_portfolio_briefs(delay_secs: float = 4.0) -> list[dict]:
    """
    Run individual research briefs for every portfolio holding that exists
    in the IC universe. Skips out-of-universe names gracefully.
    Returns list of {ticker, status, html_path, error}.
    """
    from engines.database import get_portfolio, get_universe

    port = get_portfolio()
    if port.empty:
        print("[Batch] No portfolio loaded. Run: python run.py load portfolio")
        return []

    uni_tickers = set(get_universe("all")["ticker"].tolist())
    results     = []
    tickers     = port["ticker"].tolist()
    n           = len(tickers)

    # Separate in/out of universe
    to_run = [t for t in tickers if t in uni_tickers]
    skipped = [t for t in tickers if t not in uni_tickers]

    print(f"\n{'='*62}")
    print(f"  BATCH BRIEF RUN — {len(to_run)} briefs  ({len(skipped)} skipped)")
    print(f"  Delay between calls: {delay_secs}s")
    if skipped:
        print(f"  Skipping (not in universe): {', '.join(skipped)}")
    print(f"{'='*62}\n")

    for i, ticker in enumerate(to_run, 1):
        print(f"[{i:02d}/{len(to_run):02d}] Starting brief for {ticker}...")
        try:
            html_path = run_brief(ticker)
            results.append({"ticker": ticker, "status": "OK", "html_path": html_path, "error": None})
        except Exception as e:
            print(f"  !! ERROR on {ticker}: {e}")
            results.append({"ticker": ticker, "status": "ERROR", "html_path": None, "error": str(e)})

        if i < len(to_run):
            print(f"  [Pause {delay_secs}s before next call...]\n")
            time.sleep(delay_secs)

    # Summary
    ok  = [r for r in results if r["status"] == "OK"]
    err = [r for r in results if r["status"] == "ERROR"]
    print(f"\n{'='*62}")
    print(f"  BATCH COMPLETE — {len(ok)} succeeded, {len(err)} failed, {len(skipped)} skipped")
    for r in err:
        print(f"  !! {r['ticker']}: {r['error']}")
    for t in skipped:
        print(f"  -- {t}: not in Fiscal AI universe (discretionary / not covered)")
    print(f"{'='*62}\n")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO BRIEF — macro-level analytical view of the whole portfolio
# ══════════════════════════════════════════════════════════════════════════════

PORTFOLIO_SYSTEM_PROMPT = (
    "You are a senior portfolio manager and equity analyst at Integrity Wealth Partners "
    "writing an internal portfolio review memo. Write with precision and conviction. "
    "Reference specific model metrics, company names, and weights throughout. "
    "Surface non-obvious cross-portfolio risks and opportunities. "
    "Be honest about what you don't know. No filler, no hedging for the sake of hedging."
)

PORTFOLIO_BRIEF_STRUCTURE = """
Write a comprehensive internal portfolio review memo with EXACTLY this structure.
Use markdown headers. Be analytical, specific, and concise in each section.

---
# PORTFOLIO OVERVIEW

## Snapshot
One paragraph: total value, number of holdings, weighted average alignment score,
quad distribution, how many IC-model vs discretionary positions, and the key
structural characteristic of this portfolio right now.

## Key Themes
Identify the 4-5 dominant investment themes running through this portfolio.
For each theme, name the specific holdings that express it and explain why
the theme is compelling or at risk right now.

Format each as:
### [Theme Name]
Holdings: [tickers]
[Two to three sentences on the theme, current status, and what would confirm or break it]

---
# FUNDAMENTAL ANALYSIS

## Portfolio Quality Assessment
Assess the quality of the aggregate portfolio using the weighted model metrics.
Cover: weighted average ROIC, FCF yield, operating margins, leverage (ND/EBITDA),
and revenue growth. How does this portfolio compare against a typical large-cap benchmark
on these metrics? Is quality improving or deteriorating vs prior periods?

## Factor Exposures
What systematic factors is this portfolio long? Consider: growth vs value, cyclicality,
interest rate sensitivity (via leverage and duration of earnings), geographic concentration,
sector caps, and any factor crowding risks. Be specific about which positions drive each exposure.

## Sector Concentration & Risk
Name the two or three sectors with heaviest concentration. Assess whether that
concentration is intentional signal or accidental overlap. Flag any sector at or near
the 28% portfolio cap.

---
# MARKET & MACRO CONTEXT

## Recent Earnings & Events
Based on available research, summarize key earnings results, guidance changes, or
material events for the major holdings. Identify which positions had positive
earnings surprise vs which had disappointing results. Be explicit about what is
confirmed vs inferred.

## Potential Catalysts (Next 30-90 Days)
List the 5-7 most important upcoming catalysts for this portfolio — earnings, Fed decisions,
sector data releases, M&A speculation, regulatory events. For each, note which holdings
are most affected and whether the catalyst is a tailwind or headwind.

Format as:
- **[Catalyst]** — [affected tickers] — [tailwind/headwind/binary]

## M&A & Structural Themes
Any holdings where M&A activity, spin-offs, or structural change is a live thesis?
Any sectors undergoing consolidation that could benefit or threaten positions?

---
# RISK ASSESSMENT

## Top 5 Portfolio Risks
The five most important risks to this portfolio right now, ranked by severity × probability.
For each: name the risk, which holdings it hits hardest, and what would signal it materializing.

Format as:
### Risk [N]: [Risk Name]
Holdings most exposed: [tickers]
Signal to watch: [one specific metric or event]
[Two sentences on the risk]

## Cross-Portfolio Correlations
Are there hidden correlation risks — positions that look diversified but would move
together in a specific stress scenario (e.g., a USD shock, China slowdown, rate spike)?
Name the specific correlation clusters.

## Model vs Discretionary Divergence
Comment on the 6 discretionary positions (MU, PLTR, NOC, SEI, DGX, LEU). Where does
the manager's conviction diverge from what the model signals? Is that divergence
currently adding or subtracting value?

---
# PORTFOLIO POSITIONING

## Strongest Conviction Positions
The top 5 holdings by combined model signal strength and fundamental quality.
For each, give one sentence on why it deserves its weight.

## Positions Requiring Attention
Any holdings where the model signal, price action, or fundamental data is
sending a warning. Include the 2 Q3/Q4 holdings specifically (NVDA, STRL, LLY, DGX).
Should any be reduced?

## Rebalance Recommendations
Three specific actions the model would recommend for next month's rebalance.
Be direct: add X, trim Y, watch Z. Reference specific alignment scores and quad positions.

---
# BOTTOM LINE

## Portfolio Verdict
Four to five sentences. Characterize the portfolio: is it well-positioned for the
current environment? What is the primary risk vs the primary opportunity?
What is the one thing that would materially change the outlook?

## One Year Outlook
If the IC model signals are correct and the key themes play out, where does this
portfolio stand in 12 months? What would outperformance look like? What would
underperformance look like?

---
"""


def _format_portfolio_context(port_df, uni_df) -> str:
    """Build the full portfolio context block for Claude."""
    from engines.quad import QUAD_NAME

    def pct(v): return f"{v:.1f}%" if (v is not None and not __import__('math').isnan(float(v or 0))) else "N/A"
    def val(v): return f"{v:.1f}"  if (v is not None and not __import__('math').isnan(float(v or 0))) else "N/A"

    # Merge model data into portfolio
    uni_idx = uni_df.set_index("ticker")

    lines = [f"## PORTFOLIO HOLDINGS — {len(port_df)} POSITIONS\n"]
    lines.append(f"{'Ticker':<7} {'Company':<28} {'Quad':<5} {'Score':>6} {'Bucket':<11} {'PEAD':<14} "
                 f"{'X%':>7} {'Y%':>7} {'Weight':>7} {'Disc':>5} {'ROIC':>6} {'RevMom':>8} {'EPSMom':>8}")
    lines.append("-" * 120)

    total_value = port_df["current_value"].sum()
    sector_wts  = {}
    sleeve_wts  = {}

    for _, row in port_df.iterrows():
        t      = row["ticker"]
        wt     = row.get("weight_actual", 0) or 0
        disc   = "Y" if row.get("is_discretionary") else "N"
        sleeve = str(row.get("sleeve",""))

        # From universe
        if t in uni_idx.index:
            u  = uni_idx.loc[t]
            q  = str(u.get("quadrant","N/A"))
            sc = u.get("alignment_score")
            bk = str(u.get("alignment_bucket","—"))
            pf = str(u.get("pead_flag","—"))
            x  = u.get("earnings_mom_roc", 0) or 0
            y  = u.get("multiple_roc", 0) or 0
            ro = u.get("roic", 0) or 0
            co = str(u.get("company", t))[:26]
            ind = str(u.get("industry",""))
        else:
            q="N/A"; sc=None; bk="—"; pf="—"; x=0; y=0; ro=0; co=t; ind=""

        sc_str = f"{sc:.1f}" if sc else "—"
        lines.append(f"{t:<7} {co:<28} {q:<5} {sc_str:>6} {bk:<11} {pf:<14} "
                     f"{x*100:>+6.1f}% {y*100:>+6.1f}% {wt:>6.1f}% {disc:>5} {ro:>5.1f}% "
                     f"{x*100:>+7.1f}% {y*100:>+7.1f}%")

        # Sector/sleeve aggregation
        if ind:
            sector_wts[ind] = sector_wts.get(ind, 0) + wt
        sleeve_wts[sleeve] = sleeve_wts.get(sleeve, 0) + wt

    lines.append("\n## SECTOR WEIGHTS")
    for sec, wt in sorted(sector_wts.items(), key=lambda x: -x[1]):
        cap_flag = " !! OVER 28% CAP" if wt > 28 else ""
        lines.append(f"  {sec:<45} {wt:.1f}%{cap_flag}")

    lines.append("\n## SLEEVE WEIGHTS (Target: Core 45% | Catalyst 30% | Rel Value 15% | Spec 10%)")
    for slv, wt in sorted(sleeve_wts.items(), key=lambda x: -x[1]):
        lines.append(f"  {slv:<40} {wt:.1f}%")

    # Weighted averages
    in_uni = port_df[port_df["ticker"].isin(uni_idx.index)]
    if not in_uni.empty and not uni_df.empty:
        merged = in_uni.merge(uni_df[["ticker","alignment_score","roic","op_margin",
                                       "fcf_yield","net_debt_ebitda","rev_3y_cagr",
                                       "fwd_rev_cagr","eps_3y_cagr","fwd_eps_cagr",
                                       "quadrant"]], on="ticker", how="left", suffixes=("","_u"))
        wa = lambda col: (merged[col] * merged["weight_actual"]).sum() / merged["weight_actual"].sum()
        lines.append(f"\n## WEIGHTED AVERAGE MODEL METRICS")
        try:
            lines.append(f"  Alignment Score:   {wa('alignment_score_u'):.1f}")
            lines.append(f"  ROIC:              {wa('roic'):.1f}%")
            lines.append(f"  Op Margin:         {wa('op_margin'):.1f}%")
            lines.append(f"  FCF Yield:         {wa('fcf_yield'):.1f}%")
            lines.append(f"  ND/EBITDA:         {wa('net_debt_ebitda'):.1f}x")
            lines.append(f"  Rev 3Y CAGR:       {wa('rev_3y_cagr'):.1f}%")
            lines.append(f"  Fwd Rev CAGR:      {wa('fwd_rev_cagr'):.1f}%")
            lines.append(f"  EPS 3Y CAGR:       {wa('eps_3y_cagr'):.1f}%")
            lines.append(f"  Fwd EPS CAGR:      {wa('fwd_eps_cagr'):.1f}%")
        except Exception:
            lines.append("  (weighted avg calculation unavailable)")

        q_counts = merged.groupby("quadrant_u")["weight_actual"].sum().to_dict()
        lines.append(f"\n## QUAD WEIGHT DISTRIBUTION")
        for q, label in [("Q1","Full Compounders"),("Q2","Earnings Resilience"),
                          ("Q3","Margin Compression"),("Q4","Full Deterioration"),("N/A","Not in model")]:
            w = q_counts.get(q, 0)
            n = int((merged["quadrant_u"] == q).sum())
            lines.append(f"  {q} {label:<25} {n:>2} names   {w:.1f}%")

    return "\n".join(lines)


def _portfolio_brief_to_html(brief_text: str, port_df, uni_df, run_ts: str, today: str) -> str:
    """Convert portfolio brief markdown to styled HTML."""
    from engines.reports import _quad_color, _quad_bg

    # Quick stats
    total_value = port_df["current_value"].sum()
    avg_score   = port_df["alignment_score"].mean() if "alignment_score" in port_df.columns else 0
    n           = len(port_df)
    q1n = int((port_df["quadrant"]=="Q1").sum()) if "quadrant" in port_df.columns else 0
    q2n = int((port_df["quadrant"]=="Q2").sum()) if "quadrant" in port_df.columns else 0

    # Convert markdown to HTML
    html_body = []
    lines = brief_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("# "):
            title = line[2:].strip()
            html_body.append(f'<div style="background:#1F3A5F;color:white;padding:10px 20px;border-radius:10px;font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin:28px 0 18px">{title}</div>')
        elif line.startswith("## "):
            title = line[3:].strip()
            html_body.append(f'<h2 style="font-size:17px;font-weight:800;color:#1F3A5F;margin:24px 0 10px;padding-bottom:6px;border-bottom:2px solid #e5e7eb">{title}</h2>')
        elif line.startswith("### "):
            title = line[4:].strip()
            # Risk/theme sub-heading
            if title.startswith("Risk ") or title.startswith("Theme"):
                html_body.append(f'<h3 style="font-size:13px;font-weight:700;color:#dc2626;margin:16px 0 6px">{title}</h3>')
            else:
                html_body.append(f'<h3 style="font-size:13px;font-weight:700;color:#374151;margin:16px 0 6px;border-left:3px solid #1F3A5F;padding-left:10px">{title}</h3>')
        elif line.strip() == "---":
            html_body.append('<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">')
        elif line.strip().startswith("- "):
            # Collect bullet group
            bullets = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                content = lines[i].strip()[2:]
                content = re.sub(r"\*\*(.+?)\*\*", r'<strong>\1</strong>', content)
                for emoji in ["🟢","🟡","🔴"]:
                    content = content.replace(emoji, f'<span style="font-size:14px">{emoji}</span>')
                bullets.append(f'<li style="margin-bottom:7px;line-height:1.6;font-size:13px;color:#374151">{content}</li>')
                i += 1
            html_body.append(f'<ul style="margin:8px 0 14px 20px">{"".join(bullets)}</ul>')
            continue
        elif line.strip():
            content = re.sub(r"\*\*(.+?)\*\*", r'<strong>\1</strong>', line.strip())
            html_body.append(f'<p style="font-size:13px;color:#374151;line-height:1.75;margin-bottom:10px">{content}</p>')
        i += 1

    brief_html = "\n".join(html_body)

    score_color = "#16a34a" if avg_score >= 65 else "#d97706"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Portfolio Brief · {today}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>* {{box-sizing:border-box;margin:0;padding:0}} body {{font-family:'Source Sans 3',Calibri,sans-serif;background:#f1f5f9;color:#1e293b;-webkit-font-smoothing:antialiased}}</style>
</head>
<body>

<div style="background:linear-gradient(135deg,#1F3A5F,#2d5282);padding:36px 40px 28px">
  <div style="max-width:1000px;margin:0 auto">
    <div style="font-size:11px;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:2px;margin-bottom:8px">Integrity Wealth Partners · Internal Memo</div>
    <div style="font-family:'Playfair Display',serif;font-size:34px;font-weight:800;color:white;margin-bottom:4px">Portfolio Review Brief</div>
    <div style="font-size:14px;color:rgba(255,255,255,0.55);margin-bottom:24px">Generated {run_ts} · Alpha System v10.0 · Internal Use Only</div>
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:14px">
      {"".join(f'<div style="background:rgba(255,255,255,0.1);border-radius:10px;padding:14px;text-align:center"><div style="font-size:22px;font-weight:800;color:white">{v}</div><div style="font-size:10px;color:rgba(255,255,255,0.5);margin-top:3px;text-transform:uppercase;letter-spacing:0.5px">{l}</div></div>'
        for v,l in [
          (n, "Holdings"),
          (f"${total_value/1e6:.1f}M" if total_value >= 1e6 else f"${total_value:,.0f}", "Portfolio Value"),
          (f"{avg_score:.1f}", "Avg Score"),
          (f"{q1n}Q1 / {q2n}Q2", "Core Quads"),
          (today, "As Of"),
        ])}
    </div>
  </div>
</div>

<div style="max-width:1000px;margin:0 auto;padding:32px 40px 48px">
  <div style="background:white;border-radius:16px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,0.08);border:1px solid #e5e7eb">
    {brief_html}
  </div>
</div>

<div style="background:#1F3A5F;color:rgba(255,255,255,0.4);text-align:center;padding:20px;font-size:11px">
  <div style="font-family:'Playfair Display',serif;font-size:14px;color:rgba(255,255,255,0.7);margin-bottom:4px">Integrity Compounders · Integrity Wealth Partners · LPL Financial Affiliate</div>
  Alpha System v10.0 · {run_ts} · Internal Use Only · Not for distribution
</div>
</body></html>"""


def run_portfolio_brief() -> str:
    """
    Full pipeline for a portfolio-level analytical brief.
    Returns path to saved HTML.
    """
    from engines.database import get_portfolio, get_universe
    import pandas as pd

    today  = datetime.today().strftime("%Y-%m-%d")
    run_ts = datetime.now().strftime("%B %d, %Y · %I:%M %p")

    print(f"\n{'='*62}")
    print(f"  PORTFOLIO BRIEF AGENT")
    print(f"  {run_ts}")
    print(f"{'='*62}\n")

    # ── Pull data ─────────────────────────────────────────────────────────────
    print("  [Step 1] Loading portfolio + universe pipeline...")
    port = get_portfolio()
    if port.empty:
        raise ValueError("No portfolio loaded. Run: python run.py load portfolio")

    uni = get_universe("all")
    from engines.screener import run_gates
    from engines.quad import compute_axes, assign_quadrants
    from engines.alignment import compute_alignment
    from engines.fcf_flip import compute_flip_scores
    from engines.pods import assign_pods
    uni = run_gates(uni)
    uni = compute_axes(uni)
    uni = assign_quadrants(uni)
    uni = assign_pods(uni)
    uni = compute_alignment(uni)
    uni = compute_flip_scores(uni)
    print(f"  [Step 1] ✓ {len(port)} holdings loaded")

    # ── Web research — sector themes ─────────────────────────────────────────
    print("  [Step 2] Running sector-level web research...")
    theme_searches = [
        ("semis_cycle",   "semiconductor equipment industry earnings outlook 2026"),
        ("industrial",    "industrial machinery capex cycle earnings 2026"),
        ("copper_metals", "copper mining demand electrification outlook 2026"),
        ("defense",       "defense aerospace spending budget 2026"),
        ("macro",         "S&P 500 earnings growth outlook June 2026 economic"),
    ]

    all_research = {}
    for key, query in theme_searches:
        print(f"    Searching: \"{query}\"")
        results = _ddg_search(query, max_results=2)
        sources = []
        for r in results:
            print(f"      -> {r['title'][:55]}")
            text = _fetch_page_text(r["url"], max_words=120)
            sources.append({
                "title":   r["title"],
                "url":     r["url"],
                "snippet": r.get("snippet",""),
                "extract": text,
            })
            time.sleep(0.4)
        all_research[key] = sources
        time.sleep(0.3)

    total_sources = sum(len(v) for v in all_research.values())
    print(f"  [Step 2] ✓ {total_sources} web sources collected")

    # ── Format context ────────────────────────────────────────────────────────
    print("  [Step 3] Calling Claude API for portfolio brief...")
    port_context  = _format_portfolio_context(port, uni)
    web_context   = _format_research_for_prompt(all_research)

    env     = dotenv_values(ROOT / ".env")
    api_key = env.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not found in .env")

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    user_msg = f"""
Write a comprehensive internal portfolio review brief for the Integrity Compounders portfolio.

{port_context}

## WEB RESEARCH — SECTOR THEMES & MACRO CONTEXT
{web_context}

{PORTFOLIO_BRIEF_STRUCTURE}

Today's date: {datetime.today().strftime('%B %d, %Y')}
Portfolio context: This is a 25-name concentrated equity portfolio run within an RIA
(Integrity Wealth Partners, LPL affiliate). 21 positions are IC-model-driven (based on
quad framework and alignment score). 4 are discretionary: MU, PLTR, SEI, LEU.
The quad framework uses Revenue Momentum (X-axis) and EPS Momentum (Y-axis) to place
names in Q1 Full Compounders (both positive), Q2 Earnings Resilience (revenue negative,
earnings positive), Q3 Margin Compression (revenue positive, earnings negative),
Q4 Full Deterioration (both negative).
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=6000,
        system=PORTFOLIO_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}]
    )

    brief_text = response.content[0].text
    print(f"  [Step 3] ✓ Portfolio brief generated ({len(brief_text.split())} words)")

    # ── Save ──────────────────────────────────────────────────────────────────
    print("  [Step 4] Saving outputs...")

    # Markdown
    wiki_dir = ROOT / "wiki" / "_portfolio"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    md_path = wiki_dir / f"{today}_portfolio_brief.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"---\ntype: portfolio_brief\ndate: {today}\nholdings: {len(port)}\n---\n\n")
        f.write(brief_text)
    print(f"  [Step 4] Markdown: {md_path}")

    # HTML
    out_dir  = ROOT / "outputs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"portfolio_brief_{today}.html"
    html = _portfolio_brief_to_html(brief_text, port, uni, run_ts, today)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  [Step 4] HTML: {html_path}")

    print(f"\n{'='*62}")
    print(f"  PORTFOLIO BRIEF COMPLETE")
    print(f"  {html_path}")
    print(f"{'='*62}\n")

    return str(html_path)
