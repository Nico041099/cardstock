"""Orchestrates the daily run: fetch -> store -> analyze -> rules -> email."""
from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import List, Optional

from . import analyze, db, rules, email_report
from .config import Config
from .models import CardRef, Movement, PriceSnapshot
from .sources import get_source

log = logging.getLogger("cardstock.pipeline")


def today_str() -> str:
    return date_cls.today().isoformat()


def fetch_all(cfg: Config, source_name: str) -> tuple:
    """Fetch watchlist + sets. Returns (snapshots, refs_by_id, watchlist_ids)."""
    source = get_source(source_name, cfg)
    snaps: List[PriceSnapshot] = []
    refs_by_id: dict = {}
    watchlist_ids: set = set()

    # Watchlist
    for ref in cfg.watchlist():
        try:
            snap = source.fetch_card(ref)
        except Exception as exc:  # noqa: BLE001
            log.error("fetch failed for %s: %s", ref.describe(), exc)
            continue
        if snap is None:
            continue
        # carry watchlist label/ownership onto the snapshot's ref
        refs_by_id[snap.card_id] = ref
        watchlist_ids.add(snap.card_id)
        snaps.append(snap)
        log.info("watchlist: %s %s = %s", snap.card_id, snap.name, snap.price())

    # Sets
    max_per = cfg.max_cards_per_set()
    for set_id in cfg.sets():
        try:
            set_snaps = source.fetch_set(set_id, max_cards=max_per)
        except Exception as exc:  # noqa: BLE001
            log.error("set scan failed for %s: %s", set_id, exc)
            continue
        log.info("set %s: %d cards", set_id, len(set_snaps))
        snaps.extend(set_snaps)

    return snaps, refs_by_id, watchlist_ids


def run(
    cfg: Config,
    run_date: Optional[str] = None,
    send: bool = True,
    preview_path: Optional[str] = None,
) -> dict:
    run_date = run_date or today_str()
    source_name = cfg.get("pricing.source", "pokemontcg")
    field = cfg.get("pricing.price_field", "market")

    log.info("=== Card Squad run %s (source=%s, field=%s) ===", run_date, source_name, field)

    # 1. Fetch
    snaps, refs_by_id, watchlist_ids = fetch_all(cfg, source_name)

    # 2. Store
    conn = db.connect(cfg.db_path)
    stored = db.store_snapshots(conn, snaps, run_date, refs_by_id)
    log.info("stored %d price rows for %s", stored, run_date)

    # 3. Analyze
    movements = analyze.all_movements(conn, cfg, source_name, run_date, field)
    limit = int(cfg.get("movement.top_movers_limit", 15))
    movers_up = analyze.top_movers(movements, "up", limit, "pct_day")
    movers_down = analyze.top_movers(movements, "down", limit, "pct_day")
    watchlist_moves = [m for m in movements if m.card_id in watchlist_ids]
    watchlist_moves.sort(key=lambda m: m.name.lower())

    # 4. Rules
    signals = rules.evaluate(cfg, movements)
    db.record_signals(conn, signals, run_date)
    counts = {k: len([s for s in signals if s.kind == k]) for k in ("BUY", "AVOID", "SELL")}
    log.info("signals: %s", counts)

    # 5. Email
    html = email_report.build_html(
        cfg, run_date, source_name, signals, movers_up, movers_down, watchlist_moves
    )
    if preview_path:
        p = email_report.write_preview(html, preview_path)
        log.info("wrote HTML preview: %s", p)

    sent = False
    if send and cfg.get("email.enabled", True):
        subject = f"{cfg.get('email.subject_prefix', '[Card Squad] Daily Digest')} — {run_date}"
        sent = email_report.send_email(cfg, subject, html)

    conn.close()
    return {
        "date": run_date,
        "stored": stored,
        "movements": len(movements),
        "signals": counts,
        "emailed": sent,
        "html_len": len(html),
    }
