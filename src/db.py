"""SQLite schema + read/write for price history."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .models import CardRef, PriceSnapshot, Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    card_id     TEXT PRIMARY KEY,
    name        TEXT,
    set_id      TEXT,
    number      TEXT,
    owned       INTEGER DEFAULT 0,
    cost_basis  REAL,
    qty         INTEGER
);

CREATE TABLE IF NOT EXISTS prices (
    card_id  TEXT NOT NULL,
    date     TEXT NOT NULL,          -- YYYY-MM-DD
    source   TEXT NOT NULL,
    market   REAL,
    low      REAL,
    mid      REAL,
    high     REAL,
    PRIMARY KEY (card_id, date, source)
);
CREATE INDEX IF NOT EXISTS idx_prices_card_date ON prices(card_id, date);

CREATE TABLE IF NOT EXISTS signals (
    date     TEXT NOT NULL,
    card_id  TEXT NOT NULL,
    name     TEXT,
    kind     TEXT NOT NULL,          -- BUY | AVOID | SELL
    reason   TEXT,
    current  REAL,
    max_buy  REAL,
    extra    TEXT                     -- JSON blob
);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(date);
"""


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def upsert_card(conn: sqlite3.Connection, snap: PriceSnapshot, ref: Optional[CardRef] = None) -> None:
    """Insert/update card metadata. ref carries owned/cost_basis from the watchlist."""
    owned = int(ref.owned) if ref else 0
    cost_basis = ref.cost_basis if ref else None
    qty = ref.qty if ref else None
    name = snap.name or (ref.name if ref else "") or ""
    # Prefer a human label from the watchlist if the API name is blank.
    if ref and ref.name and not snap.name:
        name = ref.name
    conn.execute(
        """
        INSERT INTO cards (card_id, name, set_id, number, owned, cost_basis, qty)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(card_id) DO UPDATE SET
            name=COALESCE(NULLIF(excluded.name,''), cards.name),
            set_id=COALESCE(NULLIF(excluded.set_id,''), cards.set_id),
            number=COALESCE(NULLIF(excluded.number,''), cards.number),
            owned=excluded.owned,
            cost_basis=COALESCE(excluded.cost_basis, cards.cost_basis),
            qty=COALESCE(excluded.qty, cards.qty)
        """,
        (snap.card_id, name, snap.set_id, snap.number, owned, cost_basis, qty),
    )


def record_price(conn: sqlite3.Connection, snap: PriceSnapshot, date: str) -> None:
    """Store one day's price. Re-running the same day overwrites (idempotent)."""
    conn.execute(
        """
        INSERT INTO prices (card_id, date, source, market, low, mid, high)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(card_id, date, source) DO UPDATE SET
            market=excluded.market, low=excluded.low,
            mid=excluded.mid, high=excluded.high
        """,
        (snap.card_id, date, snap.source, snap.market, snap.low, snap.mid, snap.high),
    )


def store_snapshots(
    conn: sqlite3.Connection,
    snaps: Iterable[PriceSnapshot],
    date: str,
    refs_by_id: Optional[dict] = None,
) -> int:
    refs_by_id = refs_by_id or {}
    n = 0
    for snap in snaps:
        if not snap.card_id:
            continue
        upsert_card(conn, snap, refs_by_id.get(snap.card_id))
        record_price(conn, snap, date)
        n += 1
    conn.commit()
    return n


def price_history(
    conn: sqlite3.Connection,
    card_id: str,
    source: str,
    field: str = "market",
    limit_days: int = 60,
) -> List[Tuple[str, Optional[float]]]:
    """Return [(date, price)] newest-last, using the chosen price field."""
    if field not in ("market", "low", "mid", "high"):
        field = "market"
    rows = conn.execute(
        f"""
        SELECT date, {field} AS price
        FROM prices
        WHERE card_id=? AND source=?
        ORDER BY date DESC
        LIMIT ?
        """,
        (card_id, source, limit_days),
    ).fetchall()
    return [(r["date"], r["price"]) for r in reversed(rows)]


def all_card_ids(conn: sqlite3.Connection, source: str, date: str) -> List[str]:
    """Card ids that have a price for the given run date."""
    rows = conn.execute(
        "SELECT DISTINCT card_id FROM prices WHERE source=? AND date=?",
        (source, date),
    ).fetchall()
    return [r["card_id"] for r in rows]


def card_meta(conn: sqlite3.Connection, card_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM cards WHERE card_id=?", (card_id,)).fetchone()


def record_signals(conn: sqlite3.Connection, signals: Iterable[Signal], date: str) -> None:
    # Clear today's signals first so re-runs don't pile up duplicates.
    conn.execute("DELETE FROM signals WHERE date=?", (date,))
    for s in signals:
        conn.execute(
            """
            INSERT INTO signals (date, card_id, name, kind, reason, current, max_buy, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (date, s.card_id, s.name, s.kind, s.reason, s.current, s.max_buy,
             json.dumps(s.extra)),
        )
    conn.commit()
