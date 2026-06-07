"""eBay source via the official Browse API (active listings).

Legit, accessible auto-fill of "what is this selling for now":
- OAuth2 client-credentials token (free dev keys: EBAY_CLIENT_ID / EBAY_CLIENT_SECRET).
- Browse `item_summary/search` -> low / median across active listings for a card.
- `get_item_by_legacy_id` -> resolve a pasted eBay /itm/<id> link to its real price + title.

True SOLD comps live in the Marketplace Insights API, which is GATED (partner-only).
`sold_comps()` is wired but only works if your keyset is approved for that scope —
otherwise it logs and returns []. Active-listing data needs no special approval.
"""
from __future__ import annotations

import base64
import logging
import re
import statistics
import time
from typing import TYPE_CHECKING, List, Optional

import requests

from ..models import CardRef, PriceSnapshot
from .base import PriceSource

if TYPE_CHECKING:
    from ..config import Config

log = logging.getLogger("cardstock.ebay")

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_BASE = "https://api.ebay.com/buy/browse/v1"
INSIGHTS_BASE = "https://api.ebay.com/buy/marketplace_insights/v1_beta"
SCOPE = "https://api.ebay.com/oauth/api_scope"
# Trading Card Singles category (eBay US). Keeps queries from matching sealed/lots.
CATEGORY_SINGLES = "183454"

_LEGACY_ID_PATTERNS = [
    r"/itm/(?:[^/]+/)?(\d{9,})",        # /itm/Title/123456789012 or /itm/123456789012
    r"[?&](?:item|itm)=(\d{9,})",        # ?item=123456789012
]


def ebay_item_id(url: str) -> Optional[str]:
    """Extract the legacy numeric item id from an eBay listing URL, if present."""
    for pat in _LEGACY_ID_PATTERNS:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


class EbaySource(PriceSource):
    name = "ebay"

    def __init__(self, config: "Config"):
        super().__init__(config)
        self.client_id = config.ebay_client_id
        self.client_secret = config.ebay_client_secret
        self.marketplace = config.get("ebay.marketplace", "EBAY_US") or "EBAY_US"
        self.session = requests.Session()
        self.timeout = float(config.get("http.timeout_seconds", 30))
        self._token: Optional[str] = None
        self._token_exp: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # ---- OAuth ----
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        if not self.configured:
            raise RuntimeError("eBay not configured: set EBAY_CLIENT_ID / EBAY_CLIENT_SECRET in .env")
        creds = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = self.session.post(
            OAUTH_URL,
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": SCOPE},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + float(data.get("expires_in", 7200))
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
            "Content-Type": "application/json",
        }

    # ---- public helpers ----
    def active_comps(self, query: str, limit: int = 50, singles_only: bool = True) -> dict:
        """Aggregate active-listing prices for a query. Returns stats dict."""
        params = {
            "q": query,
            "limit": str(min(limit, 200)),
            "filter": "buyingOptions:{FIXED_PRICE}",
        }
        if singles_only:
            params["category_ids"] = CATEGORY_SINGLES
        resp = self.session.get(
            f"{BROWSE_BASE}/item_summary/search",
            headers=self._headers(), params=params, timeout=self.timeout,
        )
        resp.raise_for_status()
        items = resp.json().get("itemSummaries") or []
        prices = []
        currency = None
        for it in items:
            p = (it.get("price") or {})
            val = p.get("value")
            if val is not None:
                try:
                    prices.append(float(val))
                    currency = currency or p.get("currency")
                except (TypeError, ValueError):
                    pass
        if not prices:
            return {"count": 0, "low": None, "median": None, "high": None, "currency": currency}
        return {
            "count": len(prices),
            "low": min(prices),
            "median": round(statistics.median(prices), 2),
            "high": max(prices),
            "currency": currency or "USD",
        }

    def item_by_legacy_id(self, legacy_id: str) -> Optional[dict]:
        """Resolve a pasted /itm/<id> link to {price, currency, title, condition}."""
        resp = self.session.get(
            f"{BROWSE_BASE}/item/get_item_by_legacy_id",
            headers=self._headers(),
            params={"legacy_item_id": legacy_id},
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        price = (data.get("price") or {})
        return {
            "price": float(price["value"]) if price.get("value") is not None else None,
            "currency": price.get("currency"),
            "title": data.get("title"),
            "condition": data.get("condition"),
        }

    def sold_comps(self, query: str, limit: int = 50) -> List[float]:
        """Sold/completed prices — requires Marketplace Insights approval (gated)."""
        try:
            resp = self.session.get(
                f"{INSIGHTS_BASE}/item_sales/search",
                headers=self._headers(),
                params={"q": query, "limit": str(min(limit, 200)),
                        "category_ids": CATEGORY_SINGLES},
                timeout=self.timeout,
            )
            if resp.status_code in (401, 403):
                log.info("eBay Marketplace Insights not authorized (gated) — skipping sold comps")
                return []
            resp.raise_for_status()
            sales = resp.json().get("itemSales") or []
            out = []
            for s in sales:
                v = (s.get("lastSoldPrice") or {}).get("value")
                if v is not None:
                    out.append(float(v))
            return out
        except requests.RequestException as exc:
            log.info("eBay sold comps unavailable: %s", exc)
            return []

    # ---- PriceSource interface ----
    def _query_for(self, ref: CardRef) -> Optional[str]:
        name = ref.name
        if not name:
            return None
        parts = [name]
        if ref.number:
            parts.append(str(ref.number))
        return " ".join(parts)

    def fetch_card(self, ref: CardRef) -> Optional[PriceSnapshot]:
        query = self._query_for(ref)
        if not query:
            log.warning("eBay needs a card name to search (ref=%s)", ref.describe())
            return None
        stats = self.active_comps(query)
        if not stats["count"]:
            return None
        return PriceSnapshot(
            card_id=ref.id or ref.describe(),
            source=self.name,
            name=ref.name or "",
            set_id=ref.set or "",
            number=str(ref.number or ""),
            market=stats["median"],
            low=stats["low"],
            mid=stats["median"],
            high=stats["high"],
        )

    def fetch_set(self, set_id: str, max_cards: int = 0) -> List[PriceSnapshot]:
        log.info("eBay has no set concept — use pokemontcg for set scans (set=%s)", set_id)
        return []
