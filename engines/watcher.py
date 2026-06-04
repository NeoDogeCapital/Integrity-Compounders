"""
watcher.py — Drop-and-Analyze Folder Watcher
Integrity Compounders Alpha System v10.0

Watches Clippings/ and PDFs/ for newly dropped files.
When a PDF or image lands, automatically:
  1. Analyzes it with Claude vision
  2. Identifies ticker + content type from the analysis
  3. Routes the Obsidian note to the right folder
  4. Saves HTML to outputs/reports/
  5. Opens the result in the browser

Run:
    python run.py watch            — start watching (Ctrl+C to stop)
    python run.py watch --no-browser   — watch silently (no auto-open)

Watched folders:    Clippings/   PDFs/
Routed output to:   Clippings/   Earnings/   Management/   Investor-Letters/
                    Companies/[TICKER]/   Quarterly-Reviews/
"""

import sys
import re
import time
import threading
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from engines.vision import (
    analyze_file, _result_to_markdown, _result_to_html,
    _write_to_supabase,
    PDF_EXTENSIONS, IMAGE_EXTENSIONS, ALL_SUPPORTED,
)

# ── Folders to watch ───────────────────────────────────────────────────────────
WATCH_FOLDERS = [
    ROOT / "Clippings",
    ROOT / "PDFs",
]

# ── Routing rules ──────────────────────────────────────────────────────────────
# Maps content-type keywords Claude might identify → destination folder
CONTENT_ROUTE_MAP = [
    (["earnings_call", "earnings call", "earnings release", "quarterly result"],
     "Earnings"),
    (["10-k", "10k", "annual report", "annual filing"],
     "Clippings"),
    (["10-q", "10q", "quarterly filing", "quarterly report"],
     "Clippings"),
    (["management interview", "interview", "podcast", "conference presentation",
      "investor day", "management discussion"],
     "Management"),
    (["shareholder letter", "investor letter", "annual letter", "partnership letter",
      "nomad", "fundsmith", "constellation"],
     "Investor-Letters"),
    (["thesis review", "portfolio review", "quarterly review"],
     "Quarterly-Reviews"),
    (["price chart", "stock chart", "technical analysis", "chart"],
     None),   # → Companies/TICKER/ if ticker known, else Clippings/
    (["sec filing", "proxy", "8-k", "form 4", "insider"],
     "Clippings"),
]

# Cooldown: ignore repeated events for the same file within N seconds
_processed: dict[str, float] = {}
COOLDOWN_SECS = 15


# ── Ticker extractor ───────────────────────────────────────────────────────────

def _extract_ticker_from_filename(name: str) -> str:
    """Try to pull a ticker from the filename. Returns '' if not found."""
    # Common patterns: AAPL_10K.pdf, viav-earnings.pdf, Q3_NVDA_2025.png
    name_upper = name.upper()
    match = re.search(r'\b([A-Z]{2,6})\b', name_upper)
    if match:
        candidate = match.group(1)
        # Exclude common non-ticker words
        skip = {"PDF","PNG","JPG","JPEG","CHART","REPORT","ANNUAL","FILING",
                "SEC","THE","AND","FOR","FROM","WITH","FORM"}
        if candidate not in skip and len(candidate) <= 5:
            return candidate
    return ""


def _extract_ticker_from_analysis(analysis_text: str) -> str:
    """
    Ask Claude to identify the ticker in its own analysis text.
    Quick regex pass first — only calls API if needed.
    """
    # Look for explicit ticker mentions like "VIAV", "AAPL", "$NVDA"
    matches = re.findall(
        r'\b\$?([A-Z]{2,5})\b(?:\s*[-–]\s*(?:Inc|Corp|plc|Ltd|LLC|Holdings|Group))?',
        analysis_text
    )
    counts: dict[str, int] = {}
    skip = {"THE","AND","FOR","FROM","WITH","THAT","THIS","WILL","HAVE","BEEN",
            "ROIC","CAGR","EBIT","EBITDA","FCF","EPS","YOY","QOQ","CEO","CFO",
            "PASS","FAIL","HOLD","TRIM","EXIT","HIGH","LOW","BUY","SELL","ADD",
            "INTACT","WATCH","BROKEN","NEUTRAL","POSITIVE","NEGATIVE","STRONG",
            "WEAKNESS","REVENUE","MARGIN","GROWTH","EXPANDING","STABLE","RISING"}
    for m in matches:
        if m not in skip and 2 <= len(m) <= 5:
            counts[m] = counts.get(m, 0) + 1
    if counts:
        return max(counts, key=lambda k: counts[k])
    return ""


def _route_output_folder(result: dict) -> Path:
    """
    Decide which Obsidian folder the note should go in based on
    the analysis content. Returns absolute Path.
    """
    analysis = result.get("analysis", "").lower()
    ticker   = result.get("ticker", "")

    # Check routing rules
    for keywords, folder_name in CONTENT_ROUTE_MAP:
        if any(kw in analysis for kw in keywords):
            if folder_name is None:
                # Chart — route to Companies/TICKER/ if ticker known
                if ticker:
                    dest = ROOT / "Companies" / ticker
                    dest.mkdir(parents=True, exist_ok=True)
                    return dest
                return ROOT / "Clippings"
            return ROOT / folder_name

    # Default: if we have a ticker, put it in Companies/TICKER/
    if ticker:
        dest = ROOT / "Companies" / ticker
        dest.mkdir(parents=True, exist_ok=True)
        return dest

    return ROOT / "Clippings"


# ── Save to routed folder ──────────────────────────────────────────────────────

def _save_routed(result: dict, open_browser: bool = True) -> dict:
    """Save analysis note to the correct Obsidian folder + HTML to reports/."""
    import os, webbrowser

    today    = datetime.today().strftime("%Y-%m-%d")
    ticker   = result.get("ticker", "")
    ftype    = result.get("file_type", "pdf")
    stem     = Path(result.get("filename", "analysis")).stem
    label    = "pdf" if ftype == "pdf" else "chart"

    dest_folder = _route_output_folder(result)
    dest_folder.mkdir(parents=True, exist_ok=True)

    # Markdown note → routed Obsidian folder
    md_name = f"{today}_{ticker + '_' if ticker else ''}{stem}_{label}.md"
    md_path = dest_folder / md_name
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_result_to_markdown(result))

    # HTML report → outputs/reports/
    out_dir = ROOT / "outputs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_name = f"{ticker + '_' if ticker else ''}{stem}_{label}_{today}.html"
    html_path = out_dir / html_name
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_result_to_html(result))

    print(f"  [Saved] Note  → {md_path.relative_to(ROOT)}")
    print(f"  [Saved] HTML  → {html_path.relative_to(ROOT)}")

    # Write to Supabase (non-fatal)
    _write_to_supabase(result, ticker or None, label, str(md_path))

    if open_browser:
        webbrowser.open(f"file:///{str(html_path).replace(os.sep, '/')}")

    return {"markdown": md_path, "html": html_path}


# ── Event handler ──────────────────────────────────────────────────────────────

class DropHandler(FileSystemEventHandler):

    def __init__(self, open_browser: bool = True):
        self.open_browser = open_browser
        super().__init__()

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle(Path(event.src_path))

    def on_moved(self, event):
        """Catch files moved/renamed into the watched folder."""
        if event.is_directory:
            return
        self._handle(Path(event.dest_path))

    def _handle(self, path: Path):
        suffix = path.suffix.lower()
        if suffix not in ALL_SUPPORTED:
            return   # Not a supported file type — ignore silently

        # Deduplicate: ignore if we processed this file recently
        key = str(path)
        now = time.time()
        if key in _processed and (now - _processed[key]) < COOLDOWN_SECS:
            return
        _processed[key] = now

        # Small delay to let the file finish writing before we read it
        time.sleep(1.5)
        if not path.exists() or path.stat().st_size == 0:
            return

        # Run analysis in a background thread so the watcher stays responsive
        t = threading.Thread(target=self._analyze, args=(path,), daemon=True)
        t.start()

    def _analyze(self, path: Path):
        print(f"\n{'='*60}")
        print(f"  DROP DETECTED: {path.name}")
        print(f"  {datetime.now().strftime('%B %d, %Y · %I:%M %p')}")
        print(f"{'='*60}")

        # Try to identify ticker from filename first
        ticker = _extract_ticker_from_filename(path.stem)
        if ticker:
            print(f"  Ticker from filename: {ticker}")

        try:
            result = analyze_file(path, ticker=ticker)

            # Refine ticker from analysis if filename didn't give one
            if not result.get("ticker"):
                found = _extract_ticker_from_analysis(result["analysis"])
                if found:
                    print(f"  Ticker from analysis: {found}")
                    result["ticker"] = found

            dest = _route_output_folder(result)
            print(f"  Routing note to: {dest.relative_to(ROOT)}/")

            _save_routed(result, open_browser=self.open_browser)

            print(f"\n  Done. File: {path.name}")
            print(f"{'='*60}\n")

        except Exception as e:
            print(f"\n  !! ERROR analyzing {path.name}: {e}")
            print(f"{'='*60}\n")


# ── Main watcher loop ──────────────────────────────────────────────────────────

def run_watcher(open_browser: bool = True):
    """Start watching Clippings/ and PDFs/ for dropped files."""

    # Ensure watched folders exist
    for folder in WATCH_FOLDERS:
        folder.mkdir(parents=True, exist_ok=True)

    handler  = DropHandler(open_browser=open_browser)
    observer = Observer()

    for folder in WATCH_FOLDERS:
        observer.schedule(handler, str(folder), recursive=False)
        print(f"  Watching: {folder.relative_to(ROOT)}/")

    observer.start()

    print(f"""
{'='*60}
  DROP-AND-ANALYZE WATCHER ACTIVE
  {datetime.now().strftime('%B %d, %Y · %I:%M %p')}
{'='*60}

  Drop any PDF or image into:
    Clippings/     ← research, filings, charts, screenshots
    PDFs/          ← annotated documents

  Supported: .pdf  .png  .jpg  .jpeg  .gif  .webp  .tiff

  Analysis auto-routes to:
    Clippings/              (SEC filings, general research)
    Earnings/               (earnings calls, releases)
    Management/             (interviews, podcasts)
    Investor-Letters/       (shareholder letters)
    Companies/[TICKER]/     (company-specific charts)
    Quarterly-Reviews/      (portfolio reviews)

  Press Ctrl+C to stop.
{'='*60}
""")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  Watcher stopped.")
        observer.stop()

    observer.join()
