# The Card Squad — Price Tracker & Buy/Sell Alert System

Handoff spec for Claude Code. Build the project phase by phase, testing each phase
against real API calls before moving on.

## 1. What we're building

A Python app that, once a day:

1. Pulls current Pokémon card prices for (a) a **watchlist** of cards we care about
   and (b) **whole sets** we want to scan.
2. Stores prices in a local database so we build price **history**.
3. Detects **movers** — what went up and down vs. yesterday, 7-day, and 30-day averages.
4. Runs a **rules engine** that flags **BUY candidates**, **AVOID/overheated** cards,
   and **SELL/take-profit** cards we own.
5. **Emails a daily digest** to thecardsquadco@gmail.com.

Context: We're a two-person Pokémon card resale business (The Card Squad) selling
singles on eBay and at card shows. This tool helps us source smart — buy cards that
are dipping, avoid ones that are overheated, and know when to sell what we hold.

## 2. Honest constraints (read first — they shape the design)

- **No free real-time feed exists.** Most accessible data is **daily snapshots**, so
  alerts are once-daily, and "going up/down" means day-over-day (and vs. rolling averages).
- **Signals are a screen, not an oracle.** They flag candidates. A human still confirms
  condition and authenticity before buying — market price ≠ the specific card's condition.
- **Respect ToS & rate limits.** Use official APIs only. Do **not** scrape TCGplayer or
  eBay (against their terms). Cache results; back off on rate limits.
- Prices are **ungraded market** unless a graded source is used. Match condition when
  interpreting.

## 3. Data sources

- **Primary (free): Pokémon TCG API — pokemontcg.io.** Card metadata + daily TCGplayer
  and Cardmarket price snapshots per card. Free API key (pokemontcg.io/dev) for higher
  rate limits. This is the backbone.
- **Add (paid): PriceCharting API.** Broader coverage including graded prices and
  historical data. Use it to enrich watchlist cards and for graded signals.
- **Optional (if access granted): eBay APIs.** Browse API for active listings;
  Marketplace Insights for sold comps (partner/gated). Treat as a future module.
- Design data access as **pluggable source modules** (a common interface) so we can
  add/swap sources without rewriting the app.

## 4. Core features & behavior

1. **Config-driven watchlist** — watchlist.yaml listing cards by Pokémon TCG API id
   (preferred) or set + number. Optionally tag cards we **own** with our **cost basis**
   so SELL signals compare to what we paid.
2. **Set scan list** — sets.yaml listing set IDs to scan daily for top gainers/droppers.
3. **Daily fetch** — pull current prices for watchlist + scanned sets; write to SQLite
   with a date stamp.
4. **History & movement** — compute, per card: % change vs. yesterday, vs. 7-day avg,
   vs. 30-day avg; flag cards with too little data as "thin / low confidence."
5. **Rules engine** (all thresholds in config):
   - **BUY candidate:** current ≤ (30-day avg × buy_drop_pct, default 0.85) AND
     30-day avg ≥ min_price (default $5) AND enough data points. Also compute our
     **target max buy** and flag whether market leaves flip room:
     `max_buy = (market × 0.864 − 0.40 − ship) ÷ (1 + target_roi)`
     (0.864 = after eBay ~13.6% fee; 0.40 = eBay per-order fee; default target_roi 0.5).
   - **AVOID / overheated:** up ≥ spike_pct (default 30%) over 7 days → likely to revert.
   - **SELL / take-profit (owned only):** current ≥ cost_basis × (1 + sell_gain_pct,
     default 0.20), or ≥ 30-day avg × 1.15 → flag to list.
6. **Email digest** — daily HTML email with sections: Top Movers Up, Top Movers Down,
   BUY candidates (with target max buy), AVOID, SELL/take-profit, watchlist summary.
   Gmail SMTP with an App Password.
7. **Scheduling** — run daily via cron (mac/Linux) or Task Scheduler (Windows).
   run_daily.py entry point.

## 6. Build phases

1. Scaffold + first fetch.
2. Storage + watchlist.
3. Set scan + movement math.
4. Rules engine.
5. Email digest.
6. Schedule + harden.
7. (Optional) Enrich with PriceCharting + inventory cost basis.

## 8. Acceptance criteria

- `python run_daily.py` runs end to end with no errors.
- All thresholds editable in config.yaml without touching code.
- Adding a new source = adding one file in src/sources/ implementing the shared interface.
- Handles API failures and rate limits without crashing; logs what it did.

## 9. Guardrails

- Official APIs only; never scrape sites that prohibit it.
- Cache responses, respect rate limits.
- Signals are screening suggestions — disclaimer at bottom of every email.
- Secrets in .env, never committed.
