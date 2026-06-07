"""Common interface every price source implements.

To add a source (PriceCharting, eBay, ...): subclass PriceSource, implement
fetch_card / fetch_set, and register it in sources/__init__.py REGISTRY.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

from ..models import CardRef, PriceSnapshot

if TYPE_CHECKING:
    from ..config import Config


class PriceSource(ABC):
    name: str = "base"

    def __init__(self, config: "Config"):
        self.config = config

    @abstractmethod
    def fetch_card(self, ref: CardRef) -> "PriceSnapshot | None":
        """Return a price snapshot for a single card, or None if not found."""
        raise NotImplementedError

    @abstractmethod
    def fetch_set(self, set_id: str, max_cards: int = 0) -> List[PriceSnapshot]:
        """Return price snapshots for every card in a set (optionally capped)."""
        raise NotImplementedError
