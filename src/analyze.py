"""Compute per-card movement vs. yesterday / 7-day / 30-day, and rank movers."""
from __future__ import annotations

import sqlite3
from typing import List, Optional

from . import db
from .config import Config
from .models import Movement


def _mean(vals: List[float]) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _pct(current: Optional[float], base: Optional[float]) -> Optional[float]:
    if current is None or base in (None, 0):
        return None
    return (current - base) / base


def movement_for_card(
    conn: sqlite3.Connection,
    cfg: Config,
    card_id: str,
    source: str,
    field: str,
) -> Optional[Movement]:
    history = db.price_history(conn, card_id, source, field, limit_days=60)
    prices = [(d, p) for d, p in history if p is not None]
    if not prices:
        return None

    series = [p for _, p in prices]
    current = series[-1]
    prev = series[-2] if len(series) >= 2 else None
    avg7 = _mean(series[-7:])
    avg30 = _mean(series[-30:])

    meta = db.card_meta(conn, card_id)
    name = (meta["name"] if meta and meta["name"] else card_id)
    owned = bool(meta["owned"]) if meta else False
    cost_basis = meta["cost_basis"] if meta else None

    thin = len(series) < int(cfg.get("movement.thin_min_points", 5))

    return Movement(
        card_id=card_id,
        name=name,
        current=current,
        prev=prev,
        avg7=avg7,
        avg30=avg30,
        pct_day=_pct(current, prev),
        pct_7d=_pct(current, avg7),
        pct_30d=_pct(current, avg30),
        points=len(series),
        thin=thin,
        owned=owned,
        cost_basis=cost_basis,
    )


def all_movements(
    conn: sqlite3.Connection,
    cfg: Config,
    source: str,
    date: str,
    field: str,
) -> List[Movement]:
    out: List[Movement] = []
    for card_id in db.all_card_ids(conn, source, date):
        m = movement_for_card(conn, cfg, card_id, source, field)
        if m:
            out.append(m)
    return out


def top_movers(
    movements: List[Movement],
    direction: str = "up",
    limit: int = 15,
    metric: str = "pct_day",
) -> List[Movement]:
    """Rank by a pct metric. direction='up' = biggest gainers, 'down' = biggest droppers."""
    have = [m for m in movements if getattr(m, metric) is not None]
    reverse = direction == "up"
    have.sort(key=lambda m: getattr(m, metric), reverse=reverse)
    if direction == "up":
        have = [m for m in have if getattr(m, metric) > 0]
    else:
        have = [m for m in have if getattr(m, metric) < 0]
    return have[:limit]
