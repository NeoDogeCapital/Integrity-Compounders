# Moving Integrity Compounders to your Mac

**The key idea:** your data lives in **Supabase (cloud)**, not on any one machine. The
local SQLite file (`data/universe.db`) is just a cache. So migrating = clone the code +
add your credentials, and the Mac is instantly connected to the same live model your
Windows box uses. Run a refresh on either device and both see it.

You only need to move **two things by hand** (they're gitignored for security):
1. **`.env`** — your Supabase + Anthropic secrets
2. **`data/raw/*.csv`** — your latest Fiscal AI screener exports (the newest ones aren't in git)

Everything else comes from GitHub + Supabase.

---

## Prerequisites (one-time)

Install [Homebrew](https://brew.sh) if you don't have it, then everything else is automated
by `setup_mac.sh`. (It installs Python 3.12 and Node.) **Use Python 3.11 or 3.12 — not 3.14** —
for the best `numpy`/`scipy`/`pandas` wheel support on macOS.

---

## Step 1 — Get the code

```bash
cd ~/  # or wherever you keep your macro model
git clone https://github.com/NeoDogeCapital/Integrity-Compounders.git
cd Integrity-Compounders
```

## Step 2 — Bring over your secrets (`.env`)

The `.env` holds 5 values (Supabase URL/anon/service keys, DATABASE_URL, ANTHROPIC_API_KEY).
It is **not** in git. Options, easiest first:
- **AirDrop** the `.env` file from the Windows folder to the Mac project root, or
- `cp .env.example .env` then paste the real values from your Windows `.env`.

Verify later with: `python -c "from config.settings import settings; print(settings)"`
(prints masked keys; errors loudly if anything's missing).

## Step 3 — Run the setup script

```bash
bash setup_mac.sh
```

This creates a `.venv`, installs Python + Node deps, seeds the local cache from Supabase,
and checks your `.env`. To use the environment in any new terminal:

```bash
source .venv/bin/activate
```

## Step 4 — Bring over the latest screener CSVs

The pipeline reads the newest `data/raw/Screener_Results_YYYY-MM-DD.csv`. The older ones are
in git; the most recent (incl. the V12 gross-profit-column export) may not be. **AirDrop the
`data/raw/` folder** from Windows to the Mac (or at least the latest CSV). Without it,
`run.py refresh` has nothing to load.

## Step 5 — Verify it's live

```bash
source .venv/bin/activate
python -c "from config.settings import settings; print(settings)"     # secrets OK?
python run.py status                                                   # reads Supabase
python run.py who is NVDA                                              # full factor card
```

If those work, you're done — the Mac is on the same model as Windows.

---

## Daily / monthly workflow (identical on both machines)

```bash
source .venv/bin/activate

# daily
python scripts/data_updater.py        # yfinance prices/margins → Supabase
python scripts/quad_refresher.py      # quads + contamination flags, 2-month confirm

# on a new Fiscal AI CSV (drop it in data/raw/ first)
python run.py refresh                 # full V12 pipeline + Supabase sync

# scoring / memos
python scripts/company_scorer.py --review-all      # pillar scores (Claude)
python scripts/company_scorer.py --memo TICKER     # single memo

# monthly
python scripts/factor_exposure.py --snapshot --html
python scripts/publish.py --push      # regenerate dashboards → GitHub Pages
```

## Two-device notes

- **Supabase is shared state.** A refresh/score on the Mac is immediately visible on
  Windows and vice-versa. No syncing needed beyond git for code.
- **Local `universe.db` is disposable.** Rebuild anytime: delete it and run
  `python run.py refresh` (or the pull step in `setup_mac.sh`).
- **Keep code in sync with git.** `git pull` before you start, `git push` when you commit
  changes, so both machines share the same code + committed docs.
- **No Windows-only dependencies** in the app — it's pure Python + Node, all cross-platform
  (`PYTHONIOENCODING=utf-8` is only needed on Windows for emoji output; harmless to omit on Mac).
- Sits happily **next to your macro model** — it's self-contained in its own folder and venv.
