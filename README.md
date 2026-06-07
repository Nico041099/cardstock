# The Card Squad — Price Tracker & Buy/Sell Alert System

A Python app that, once a day, pulls Pokémon card prices (watchlist + whole sets),
stores them in SQLite to build history, detects movers, runs a BUY/AVOID/SELL rules
engine, and emails a daily HTML digest.

See [SPEC.md](SPEC.md) for the full design. Signals are **screening suggestions**,
not guarantees — always confirm condition and authenticity before buying or selling.

## Setup

```bash
cd ~/cardstock
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env        # then fill in your keys/secrets
```

Fill in `.env`:
- `POKEMONTCG_API_KEY` — free at https://pokemontcg.io/dev (optional, raises rate limits).
- `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` — enable 2-Step Verification on the Gmail
  account, then create an **App Password** for "Mail". Do **not** use the normal password.
- `PRICECHARTING_TOKEN` — only needed for the optional paid graded-price source.

Then edit:
- `watchlist.yaml` — the cards you track (by `id`, or `set` + `number`). Tag cards you
  `owned: true` with a `cost_basis` to enable SELL signals.
- `sets.yaml` — set ids to scan for top movers.
- `config.yaml` — all thresholds (drop %, spike %, min price, target ROI, sell gain %).

## Run

```bash
.venv/bin/python run_daily.py                  # full run: fetch, store, analyze, email
.venv/bin/python run_daily.py --no-email       # run without sending (testing)
.venv/bin/python run_daily.py --preview out/digest.html   # save the digest as HTML
.venv/bin/python run_daily.py --date 2026-06-07           # store under a specific date
```

History accrues over runs — movers and most signals need **2+ days** of data
(30-day-based signals get more reliable as history builds). Logs are written to
`logs/cardstock.log`.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

## Scheduling

### macOS / Linux (cron)

Run `crontab -e` and add (runs daily at 8:00 AM; adjust the path to your install):

```cron
0 8 * * * cd /Users/nickdivi/cardstock && /Users/nickdivi/cardstock/.venv/bin/python run_daily.py >> logs/cron.log 2>&1
```

On macOS you may need to grant `cron` Full Disk Access (System Settings → Privacy &
Security → Full Disk Access) for it to read the project files.

### Windows (Task Scheduler)

1. Open **Task Scheduler** → **Create Basic Task**.
2. Trigger: **Daily**, set your time.
3. Action: **Start a program**.
   - Program/script: `C:\path\to\cardstock\.venv\Scripts\python.exe`
   - Add arguments: `run_daily.py`
   - Start in: `C:\path\to\cardstock`
4. Finish. (Tick "Run whether user is logged on or not" if you want it headless.)

## Architecture

```
cardstock/
  config.yaml          # thresholds, sets, email settings (edit without touching code)
  watchlist.yaml       # cards to track (+ owned/cost basis)
  sets.yaml            # sets to scan
  .env                 # secrets (gitignored)
  run_daily.py         # entry point: fetch -> store -> analyze -> rules -> email
  src/
    config.py          # config + secrets loader
    models.py          # typed data models
    db.py              # SQLite schema + read/write
    analyze.py         # % changes, rolling averages, movers
    rules.py           # BUY / AVOID / SELL logic + target-max-buy
    email_report.py    # Jinja2 HTML digest + Gmail SMTP
    sources/           # pluggable price sources
      base.py          # PriceSource interface
      pokemontcg.py    # free backbone (TCGplayer snapshots)
      pricecharting.py # optional paid source (graded prices)
  tests/
```

**Adding a data source** = add one file in `src/sources/` implementing `PriceSource`
(`fetch_card`, `fetch_set`) and register it in `src/sources/__init__.py`. Nothing
else changes — see `pricecharting.py` as the worked example.
