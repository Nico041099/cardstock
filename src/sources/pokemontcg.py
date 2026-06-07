"""Pokemon TCG API source (https://pokemontcg.io). The free backbone.

Provides daily TCGplayer (USD) price snapshots per card. An API key is optional
but raises rate limits — set POKEMONTCG_API_KEY in .env.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, List, Optional

import requests

from ..models import CardRef, PriceSnapshot
from .base import PriceSource

if TYPE_CHECKING:
    from ..config import Config

log = logging.getLogger("cardstock.pokemontcg")

API_BASE = "https://api.pokemontcg.io/v2"

# Which TCGplayer variant to treat as "the" price, most-collectible first.
VARIANT_PREFERENCE = [
    "holofoil",
    "1stEditionHolofoil",
    "1stEditionNormal",
    "reverseHolofoil",
    "unlimitedHolofoil",
    "normal",
]


class PokemonTcgSource(PriceSource):
    name = "pokemontcg"

    def __init__(self, config: "Config"):
        super().__init__(config)
        self.session = requests.Session()
        key = config.pokemontcg_api_key
        if key:
            self.session.headers["X-Api-Key"] = key
        self.timeout = float(config.get("http.timeout_seconds", 30))
        self.max_retries = int(config.get("http.max_retries", 4))
        self.backoff_base = float(config.get("http.backoff_base_seconds", 2.0))
        self.pause = float(config.get("http.per_request_pause", 0.2))

    # ---- HTTP with retry / backoff ----
    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{API_BASE}/{path.lstrip('/')}"
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"status {resp.status_code}")
                resp.raise_for_status()
                time.sleep(self.pause)
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                wait = self.backoff_base * (2 ** attempt)
                log.warning(
                    "pokemontcg GET %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    path, attempt + 1, self.max_retries + 1, exc, wait,
                )
                time.sleep(wait)
        raise RuntimeError(f"pokemontcg GET {path} failed after retries: {last_exc}")

    # ---- price extraction ----
    @staticmethod
    def _pick_variant(prices: dict) -> Optional[dict]:
        if not prices:
            return None
        for variant in VARIANT_PREFERENCE:
            if variant in prices and isinstance(prices[variant], dict):
                return prices[variant]
        # fall back to any variant that has numbers
        for v in prices.values():
            if isinstance(v, dict):
                return v
        return None

    def _to_snapshot(self, card: dict) -> PriceSnapshot:
        tcg = (card.get("tcgplayer") or {}).get("prices") or {}
        variant = self._pick_variant(tcg) or {}
        set_obj = card.get("set") or {}
        return PriceSnapshot(
            card_id=card.get("id", ""),
            source=self.name,
            name=card.get("name", ""),
            set_id=set_obj.get("id", ""),
            number=str(card.get("number", "")),
            market=variant.get("market"),
            low=variant.get("low"),
            mid=variant.get("mid"),
            high=variant.get("high"),
        )

    # ---- public API ----
    def fetch_card(self, ref: CardRef) -> Optional[PriceSnapshot]:
        if ref.id:
            data = self._get(f"cards/{ref.id}")
            card = data.get("data")
            if not card:
                log.warning("card id not found: %s", ref.id)
                return None
            return self._to_snapshot(card)

        if ref.set and ref.number:
            q = f'set.id:{ref.set} number:"{ref.number}"'
            data = self._get("cards", params={"q": q, "pageSize": 1})
            results = data.get("data") or []
            if not results:
                log.warning("card not found: set=%s number=%s", ref.set, ref.number)
                return None
            return self._to_snapshot(results[0])

        log.warning("watchlist entry has neither id nor set+number: %s", ref)
        return None

    def fetch_set(self, set_id: str, max_cards: int = 0) -> List[PriceSnapshot]:
        snaps: List[PriceSnapshot] = []
        page = 1
        page_size = 250
        while True:
            data = self._get(
                "cards",
                params={
                    "q": f"set.id:{set_id}",
                    "page": page,
                    "pageSize": page_size,
                },
            )
            results = data.get("data") or []
            if not results:
                break
            for card in results:
                snaps.append(self._to_snapshot(card))
                if max_cards and len(snaps) >= max_cards:
                    return snaps
            if len(results) < page_size:
                break
            page += 1
        return snaps
