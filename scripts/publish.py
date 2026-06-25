"""
publish.py
----------
Regenerates all static dashboards and optionally pushes to GitHub Pages.

Usage:
    python scripts/publish.py           # regenerate docs/ only
    python scripts/publish.py --push    # regenerate + git add/commit/push
"""

import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DOCS    = ROOT / "docs"
REPORTS = ROOT / "outputs" / "reports"
DOCS.mkdir(parents=True, exist_ok=True)


def run(cmd: str, cwd: Path = ROOT) -> tuple[int, str]:
    env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        cmd, shell=True, capture_output=True, cwd=str(cwd), env=env
    )
    stdout = (result.stdout or b"").decode("utf-8", errors="replace")
    stderr = (result.stderr or b"").decode("utf-8", errors="replace")
    return result.returncode, (stdout + stderr).strip()


def generate_all():
    """Run all dashboard generators and copy outputs to docs/."""
    import os
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    steps = [
        ("Portfolio dashboard",  "python outputs/reports/portfolio_dashboard.py"),
        ("Watchlist dashboard",  "python outputs/reports/watchlist_dashboard.py"),
        ("Factor exposure HTML", "python scripts/factor_exposure.py --html"),
    ]

    for label, cmd in steps:
        print(f"  [{label}]...", end=" ", flush=True)
        rc, out = run(cmd)
        print("✅" if rc == 0 else f"⚠️  {out[:80]}")

    # Copy generated HTML files to docs/
    copy_pairs = [
        (REPORTS / "portfolio-dashboard.html",   DOCS / "portfolio-dashboard.html"),
        (REPORTS / "watchlist-dashboard.html",   DOCS / "watchlist-dashboard.html"),
        (REPORTS / f"factor_exposure_{datetime.today().strftime('%Y-%m-%d')}.html",
                                                  DOCS / "factor_exposure.html"),
    ]
    for src, dst in copy_pairs:
        if src.exists():
            dst.write_bytes(src.read_bytes())
            print(f"  Copied → docs/{dst.name}")

    # Regenerate index
    _write_index()
    print(f"  Generated → docs/index.html")


def _write_index():
    today  = datetime.today().strftime("%Y-%m-%d")
    run_ts = datetime.now().strftime("%B %d, %Y · %I:%M %p")

    links = [
        ("Portfolio Dashboard",  "portfolio-dashboard.html",  "Live portfolio — holdings, quads, scores, alerts"),
        ("Watchlist Dashboard",  "watchlist-dashboard.html",  "Research pipeline and approaching names"),
        ("Factor Exposure",      "factor_exposure.html",      "Monthly factor report — quality, valuation, risk"),
    ]

    link_cards = "".join(f"""
    <a href="{href}" style="display:block;background:#161b22;border:1px solid #30363d;
       border-radius:8px;padding:20px;text-decoration:none;transition:border-color .2s"
       onmouseover="this.style.borderColor='#C9A84C'" onmouseout="this.style.borderColor='#30363d'">
      <div style="color:#C9A84C;font-size:14px;font-weight:700;margin-bottom:6px">{title}</div>
      <div style="color:#8b949e;font-size:12px">{desc}</div>
    </a>""" for title, href, desc in links)

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Integrity Compounders OS</title>
<style>
  body{{font-family:Calibri,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:0;min-height:100vh}}
  .hdr{{background:#1F3A5F;border-bottom:3px solid #C9A84C;padding:24px 32px}}
  .hdr h1{{color:#fff;font-size:22px;margin:0;font-weight:800}}
  .hdr .sub{{color:#C9A84C;font-size:13px;margin-top:6px}}
  .body{{max-width:700px;margin:0 auto;padding:40px 24px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:28px}}
  .badge{{display:inline-block;background:#1b2d3d;color:#C9A84C;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;margin-bottom:8px}}
  @media(max-width:500px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body>
<div class="hdr">
  <h1>Integrity Compounders OS</h1>
  <div class="sub">Concentrated Quality-Compounder Strategy · Integrity Wealth Partners · LPL Financial Affiliate</div>
</div>
<div class="body">
  <div class="badge">Alpha System v12</div>
  <p style="font-size:14px;color:#8b949e;line-height:1.6">
    Internal dashboards for the Integrity Compounders concentrated equity strategy.
    3-Pillar Scoring · Quad Framework · Factor Exposure Analytics.
  </p>
  <div class="grid">
    {link_cards}
    <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px">
      <div style="color:#C9A84C;font-size:14px;font-weight:700;margin-bottom:6px">System Status</div>
      <div style="color:#8b949e;font-size:12px">Last generated: {run_ts}</div>
      <div style="color:#8b949e;font-size:12px;margin-top:4px">Data as of: {today}</div>
    </div>
  </div>
</div>
</body></html>"""

    (DOCS / "index.html").write_text(html, encoding="utf-8")


def git_push(message: str = None) -> bool:
    """Stage, commit, and push to GitHub."""
    if message is None:
        message = f"IC OS v12 — dashboard update {datetime.today().strftime('%Y-%m-%d %H:%M')}"

    # Check git is initialised
    rc, _ = run("git rev-parse --git-dir")
    if rc != 0:
        print("  ⚠️  Not a git repo. Run: git init && git remote add origin <url>")
        return False

    steps = [
        ("git add docs/ outputs/", "Stage docs and outputs"),
        (f'git commit -m "{message} [skip ci]"', "Commit"),
        ("git push origin HEAD:main", "Push to origin/main"),
    ]
    for cmd, label in steps:
        rc, out = run(cmd)
        if rc == 0:
            print(f"  ✅ {label}")
        else:
            # "nothing to commit" is not an error
            if "nothing to commit" in out or "nothing added" in out:
                print(f"  ℹ️  {label}: nothing new to commit")
            else:
                print(f"  ⚠️  {label}: {out[:120]}")
                if "push" in cmd:
                    return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--push",    action="store_true", help="Push to GitHub after generating")
    parser.add_argument("--message", type=str, default=None, help="Custom commit message")
    args = parser.parse_args()

    print(f"\n  PUBLISH — {datetime.now().strftime('%B %d, %Y · %I:%M %p')}")
    print(f"  {'='*48}")

    generate_all()

    if args.push:
        print(f"\n  Pushing to GitHub...")
        git_push(args.message)
    else:
        print(f"\n  docs/ updated. Run with --push to deploy to GitHub Pages.")

    print(f"\n  Done.\n")


if __name__ == "__main__":
    main()
