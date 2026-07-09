#!/usr/bin/env bash
# ============================================================================
# Integrity Compounders — macOS setup
# Run from the project root:  bash setup_mac.sh
# Assumes Homebrew is installed (https://brew.sh). Idempotent — safe to re-run.
# ============================================================================
set -e
echo "▶ Integrity Compounders — macOS setup"

# 1. Toolchain (Python 3.12 + Node) via Homebrew
if ! command -v brew >/dev/null 2>&1; then
  echo "✗ Homebrew not found. Install from https://brew.sh first, then re-run."
  exit 1
fi
echo "▶ Installing python@3.12 and node (skips if present)…"
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
brew list node        >/dev/null 2>&1 || brew install node

PY=$(brew --prefix python@3.12)/bin/python3.12

# 2. Python virtual environment + deps
echo "▶ Creating venv and installing Python deps…"
"$PY" -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# 3. Node deps (Word memo generator)
echo "▶ Installing Node deps (docx)…"
npm install

# 4. .env check
if [ ! -f .env ]; then
  echo "⚠ No .env found. Copy .env.example → .env and fill in your Supabase + Anthropic keys."
  echo "   cp .env.example .env  &&  \$EDITOR .env"
else
  echo "✓ .env present."
fi

# 5. Build the local SQLite cache from the cloud (Supabase is the source of truth)
if [ -f .env ]; then
  echo "▶ Initializing local cache DB and pulling enriched data from Supabase…"
  python - <<'PY'
from engines.database import init_db
init_db()
try:
    from engines.supabase_sync import pull_enriched_to_local
    pull_enriched_to_local()
    print("✓ Local cache seeded from Supabase.")
except Exception as e:
    print(f"⚠ Pull skipped ({e}). Run `python run.py refresh` once you drop a screener CSV in data/raw/.")
PY
fi

echo ""
echo "✓ Setup complete. Activate the env in new terminals with:  source .venv/bin/activate"
echo "  Sanity check:  python -c 'from config.settings import settings; print(settings)'"
