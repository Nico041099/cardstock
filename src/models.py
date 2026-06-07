"""Shared typed data models passed between layers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CardRef:
    """A reference to a card from the watchlist — either an explicit id or set+number."""

    id: Optional[str] = None
    set: Optional[str] = None
    number: Optional[str] = None
    name: Optional[str] = None
    owned: bool = False
    cost_basis: Optional[float] = None
    qty: Optional[int] = None

    def describe(self) -> str:
        if self.id:
            return self.id
        return f"{self.set}-#{self.number}"


@dataclass
class PriceSnapshot:
    """One day's price reading for one card from one source."""

    card_id: str
    source: str
    name: str = ""
    set_id: str = ""
    number: str = ""
    market: Optional[float] = None
    low: Optional[float] = None
    mid: Optional[float] = None
    high: Optional[float] = None

    def price(self, field_name: str = "market") -> Optional[float]:
        """Return the chosen price field, falling back sensibly if it's missing."""
        order = [field_name, "market", "mid", "low", "high"]
        for f in order:
            v = getattr(self, f, None)
            if v is not None:
                return float(v)
        return None


@dataclass
class Movement:
    """Computed movement stats for one card as of a given run date."""

    card_id: str
    name: str
    current: Optional[float]
    prev: Optional[float] = None
    avg7: Optional[float] = None
    avg30: Optional[float] = None
    pct_day: Optional[float] = None
    pct_7d: Optional[float] = None
    pct_30d: Optional[float] = None
    points: int = 0
    thin: bool = False
    owned: bool = False
    cost_basis: Optional[float] = None


@dataclass
class Signal:
    """A fired rule for one card."""

    card_id: str
    name: str
    kind: str            # BUY | AVOID | SELL
    reason: str
    current: Optional[float] = None
    max_buy: Optional[float] = None
    extra: dict = field(default_factory=dict)
