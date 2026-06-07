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
- `EBAY_CLIENT_ID` + `EBAY_CLIENT_SECRET` — free at https://developer.ebay.com (create a
  production keyset). Powers active-listing comps and reading price from a pasted eBay link.
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

## Should I buy THIS one? (link / card evaluator)

Paste a Collectr, eBay, or TCGplayer link (or just a card name) and get a clear
**BUY / FAIR / PASS** verdict against your target ROI:

```bash
.venv/bin/python evaluate_link.py "<paste any link>"            # auto-reads price if the page allows
.venv/bin/python evaluate_link.py "<link>" --price 450          # judge a specific asking price
.venv/bin/python evaluate_link.py "Charizard" --set base1 --number 4 --price 450
.venv/bin/python evaluate_link.py "<link>" --roi 0.3            # judge for 30% ROI instead of 50%
.venv/bin/python evaluate_link.py "<link>" --no-fetch           # slug only, don't touch the page
```

How it works (and its honest limits):
- The **card identity** is read from the URL slug (e.g. TCGplayer URLs contain
  `charizard-base-set-4`). eBay item URLs often have no slug — pass `--name`/`--set`/`--number`.
- The **asking price** is grabbed from the page's meta tags when possible. eBay,
  TCGplayer, and Collectr block bots and render with JS, so this often fails —
  when it does, pass `--price`. (We never hard-scrape; it's best-effort + ToS-safe.)
- The **market price** always comes from the official Pokémon TCG API.
- Verdict: `BUY` if asking ≤ your max buy, `FAIR` if below market but above max buy,
  `PASS` if above market. If you've been running `run_daily.py`, it also shows a
  dip/overheated timing note from your local history.

The matched card is always printed — if it's the wrong one, re-run with
`--set`/`--number`/`--name`.

**eBay + budget overlays** (shown automatically when configured):
- With eBay keys set, paste an eBay `/itm/...` link and the asking price + title are
  read **via the official Browse API** (no scraping). The verdict also shows
  `eBay now: low / median (N active listings)` next to TCGplayer market.
- With the inventory sheet connected, the verdict adds a budget line and warns if a
  buy would exceed your remaining budget (`⚠ exceeds remaining budget (CA$X left)`).

## Inventory & budget (Google Sheet)

The app reads your workbook **read-only** to show spend / savings / budget and to make
buy decisions budget-aware. All figures are **CAD**; USD market prices are converted
with `economics.usd_to_cad` in `config.yaml`.

**Setup:**
1. Share the sheet: **File → Share → General access → "Anyone with the link" (Viewer).**
   (The app uses the CSV export URL; the sheet must be link-readable.)
2. In `config.yaml` under `inventory:`, set `sheet_id` and `inventory_gid` (the Inventory
   tab's gid — open that tab and copy the `gid=` from the browser URL). Optionally set
   `settings_gid` so the app reads **starting capital** from the Settings tab; otherwise
   set `starting_capital_cad`.
3. Set `economics.usd_to_cad` to a current-ish rate.

**Snapshot command:**

```bash
.venv/bin/python inventory_report.py          # spent / saved / budget left (values holdings vs market)
.venv/bin/python inventory_report.py --fast   # skip the live holdings valuation
```

The same snapshot is added to the top of the daily email digest.

What the numbers mean:
- **Spent** = Σ cost basis · **Realized profit** = Σ profit on sold rows · **Proceeds** = Σ net proceeds
- **Budget left** = starting capital + proceeds − spent
- **Holdings value** = held cards priced at current market (USD→CAD) ·
  **Below-market** = Σ(market − cost) on held cards (your "bought smart" savings)

**Sold comps note:** true eBay *sold* prices need the Marketplace Insights API, which is
gated (partner-only). The app is wired for it but uses **active** listings unless your
keyset is approved.

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
