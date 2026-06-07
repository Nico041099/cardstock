"""Pluggable price sources. Add a new source = add one file here implementing PriceSource."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import PriceSource
from .pokemontcg import PokemonTcgSource
from .pricecharting import PriceChartingSource

if TYPE_CHECKING:
    from ..config import Config

# Registry: name -> class. New sources register here.
REGISTRY = {
    "pokemontcg": PokemonTcgSource,
    "pricecharting": PriceChartingSource,
}


def get_source(name: str, config: "Config") -> PriceSource:
    """Instantiate a source module by name."""
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown source '{name}'. Known: {', '.join(sorted(REGISTRY))}"
        )
    return cls(config)


__all__ = [
    "PriceSource",
    "PokemonTcgSource",
    "PriceChartingSource",
    "REGISTRY",
    "get_source",
]
