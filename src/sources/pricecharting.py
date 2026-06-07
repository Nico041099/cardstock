"""PriceCharting source (paid) — graded prices + broader coverage.

Phase 7 enrichment. This is a real client skeleton: it talks to the PriceCharting
API shape (https://www.pricecharting.com/api) but is OFF by default and needs a
paid token (PRICECHARTING_TOKEN in .env). Enable by setting pricing.source:
pricecharting in config.yaml, or use it alongside pokemontcg in a future blended run.

Demonstrates the pluggable design: adding a source = one file here + a REGISTRY entry.
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

log = logging.getLogger("cardstock.pricecharting")

API_BASE = "https://www.pricecharting.com/api"


class PriceChartingSource(PriceSource):
    name = "pricecharting"

    def __init__(self, config: "Config"):
        super().__init__(config)
        self.token = config.pricecharting_token
        self.session = requests.Session()
        self.timeout = float(config.get("http.timeout_seconds", 30))
        self.pause = float(config.get("http.per_request_pause", 0.2))

    def _require_token(self) -> None:
        if not self.token:
            raise RuntimeError(
                "PriceCharting source selected but PRICECHARTING_TOKEN is not set in .env"
            )

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        self._require_token()
        params = dict(params or {})
        params["t"] = self.token
        resp = self.session.get(f"{API_BASE}/{path.lstrip('/')}", params=params, timeout=self.timeout)
        resp.raise_for_status()
        time.sleep(self.pause)
        return resp.json()

    @staticmethod
    def _cents_to_dollars(v) -> Optional[float]:
        # PriceCharting returns prices in integer cents.
        return round(v / 100.0, 2) if isinstance(v, (int, float)) else None

    def _to_snapshot(self, product: dict, card_id: str) -> PriceSnapshot:
        # loose-price = ungraded; graded-price / manual-only-price etc. available too.
        return PriceSnapshot(
            card_id=card_id,
            source=self.name,
            name=product.get("product-name", ""),
            market=self._cents_to_dollars(product.get("loose-price")),
            low=self._cents_to_dollars(product.get("loose-price")),
            mid=self._cents_to_dollars(product.get("graded-price")),
            high=self._cents_to_dollars(product.get("manual-only-price")),
        )

    def fetch_card(self, ref: CardRef) -> Optional[PriceSnapshot]:
        # PriceCharting keys products by its own ids; map via search by name as a baseline.
        query = ref.name or ref.describe()
        data = self._get("products", params={"q": query})
        products = data.get("products") or []
        if not products:
            log.warning("pricecharting: no match for %s", query)
            return None
        return self._to_snapshot(products[0], card_id=ref.id or ref.describe())

    def fetch_set(self, set_id: str, max_cards: int = 0) -> List[PriceSnapshot]:
        # Set-level scan isn't a first-class PriceCharting concept; left for future work.
        log.info("pricecharting set scan not implemented for %s (use pokemontcg for sets)", set_id)
        return []
