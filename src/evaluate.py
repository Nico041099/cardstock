"""Evaluate a single card link (Collectr / eBay / TCGplayer) or a card name.

Approach A: read the card identity from the URL slug, best-effort grab the asking
price from the page's meta tags (silently skip if blocked/JS-only), pull the real
MARKET price from the official Pokemon TCG API, then give a clear BUY/FAIR/PASS
verdict against your target ROI. Market data always comes from the allowed API —
we never depend on scraping.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse

import requests

from . import analyze, db, rules
from .config import Config
from .models import Movement, PriceSnapshot
from .sources.pokemontcg import PokemonTcgSource

log = logging.getLogger("cardstock.evaluate")

# Slug tokens that are noise, not part of the card name.
NOISE = {
    "pokemon", "card", "cards", "tcg", "single", "singles", "holo", "holofoil",
    "reverse", "foil", "rare", "promo", "near", "mint", "nm", "lp", "mp", "hp",
    "psa", "bgs", "cgc", "sgc", "ace", "gem", "graded", "ungraded", "raw",
    "lot", "x1", "english", "eng", "japanese", "jpn", "first", "edition",
    "1st", "unlimited", "set", "the", "and", "of", "for", "with", "new",
    "item", "listing", "product", "p", "itm",
    # generic set-name words that aren't Pokemon names
    "base", "jungle", "fossil", "gym", "neo", "ex", "gx", "vmax", "vstar", "v",
}

SET_HINTS = {
    "base-set": "base1", "base set": "base1", "baseset": "base1",
}


@dataclass
class LinkInfo:
    raw: str
    site: str = "unknown"            # collectr | ebay | tcgplayer | other
    name_guess: Optional[str] = None
    set_guess: Optional[str] = None
    number_guess: Optional[str] = None
    asking_price: Optional[float] = None
    page_title: Optional[str] = None


@dataclass
class Verdict:
    rating: str                       # BUY | FAIR | PASS | INFO | NO_MATCH
    card_name: str = ""
    card_id: str = ""
    set_id: str = ""
    number: str = ""
    asking: Optional[float] = None
    market: Optional[float] = None
    max_buy: Optional[float] = None
    target_roi: float = 0.5
    market_note: str = ""
    reasons: List[str] = field(default_factory=list)
    alternatives: int = 0
    source_site: str = "unknown"
    # eBay active-listing comps (USD)
    ebay_count: int = 0
    ebay_low: Optional[float] = None
    ebay_median: Optional[float] = None
    # budget (CAD)
    fx: float = 1.0
    budget_left_cad: Optional[float] = None
    cost_cad: Optional[float] = None
    affordable: Optional[bool] = None


# ---------------------------------------------------------------------------
# 1. Parse the link
# ---------------------------------------------------------------------------
def _detect_site(host: str) -> str:
    host = host.lower()
    if "collectr" in host:
        return "collectr"
    if "ebay" in host:
        return "ebay"
    if "tcgplayer" in host:
        return "tcgplayer"
    return "other"


def _clean_slug_to_name(slug: str) -> Optional[str]:
    """Turn a URL slug into a best-guess card name query."""
    text = slug.replace("_", "-").replace("/", "-")
    text = re.sub(r"[^a-zA-Z0-9\- ]", " ", text)
    tokens = re.split(r"[-\s]+", text.lower())
    kept = [t for t in tokens if t and t not in NOISE and not t.isdigit()]
    # drop pure grade-ish tokens like "9", "10", "psa10"
    kept = [t for t in kept if not re.fullmatch(r"(psa|bgs|cgc)?\d{1,2}", t)]
    name = " ".join(kept).strip()
    return name or None


def _number_from_slug(slug: str) -> Optional[str]:
    """Look for a collector number like '4-102' or '#4' in the slug."""
    m = re.search(r"(\d{1,3})\s*[-/]\s*\d{1,3}", slug)  # 4-102 / 4/102
    if m:
        return m.group(1)
    m = re.search(r"#\s*(\d{1,3})", slug)
    if m:
        return m.group(1)
    return None


def _set_from_text(text: str) -> Optional[str]:
    low = text.lower()
    for hint, set_id in SET_HINTS.items():
        if hint in low:
            return set_id
    return None


def parse_link(url: str, fetch: bool = True, timeout: float = 8.0) -> LinkInfo:
    info = LinkInfo(raw=url)
    parsed = urlparse(url)
    info.site = _detect_site(parsed.netloc)
    path = parsed.path or ""

    info.name_guess = _clean_slug_to_name(path)
    info.number_guess = _number_from_slug(path)
    info.set_guess = _set_from_text(path)

    if fetch:
        try:
            _enrich_from_page(url, info, timeout)
        except Exception as exc:  # noqa: BLE001 — best-effort only
            log.info("page fetch skipped (%s): %s", info.site, exc)

    # If the page title gave us a better name and the slug was thin, use it.
    if info.page_title and (not info.name_guess or len(info.name_guess) < 3):
        info.name_guess = _clean_slug_to_name(info.page_title) or info.name_guess
    if info.page_title and not info.set_guess:
        info.set_guess = _set_from_text(info.page_title)
    return info


_PRICE_PATTERNS = [
    r'"price"\s*:\s*"?(\d+(?:\.\d{1,2})?)',
    r'property=["\']product:price:amount["\'][^>]*content=["\'](\d+(?:\.\d{1,2})?)',
    r'property=["\']og:price:amount["\'][^>]*content=["\'](\d+(?:\.\d{1,2})?)',
    r'itemprop=["\']price["\'][^>]*content=["\'](\d+(?:\.\d{1,2})?)',
]


def _enrich_from_page(url: str, info: LinkInfo, timeout: float) -> None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
        return
    html = resp.text

    m = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)', html)
    if not m:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if m:
        info.page_title = m.group(1).strip()

    for pat in _PRICE_PATTERNS:
        pm = re.search(pat, html)
        if pm:
            try:
                info.asking_price = float(pm.group(1))
                break
            except ValueError:
                continue


# ---------------------------------------------------------------------------
# 2. Resolve to a real card via the official API
# ---------------------------------------------------------------------------
def _candidates(
    source: PokemonTcgSource,
    name: Optional[str],
    set_id: Optional[str],
    number: Optional[str],
) -> List[PriceSnapshot]:
    # Try most specific / most reliable query first, then loosen.
    tries = []
    # set + number alone is an exact card identifier — most reliable when we have it.
    if set_id and number:
        tries.append((None, set_id, number))
    if name:
        tries.append((name, set_id, number))
        tries.append((name, set_id, None))
        tries.append((name, None, None))
        first_token = name.split()[0] if name.split() else None
        # only fall back to a single token if it's specific enough to not match everything
        if first_token and first_token != name and len(first_token) >= 4:
            tries.append((first_token, set_id, None))
            tries.append((first_token, None, None))

    seen = set()
    for nm, sid, num in tries:
        try:
            results = source.search(nm, sid, num, limit=50)
        except Exception as exc:  # noqa: BLE001
            log.warning("search failed: %s", exc)
            continue
        results = [r for r in results if r.card_id not in seen]
        for r in results:
            seen.add(r.card_id)
        if results:
            return results
    return []


def resolve_card(
    cfg: Config,
    info: LinkInfo,
    *,
    name: Optional[str] = None,
    set_id: Optional[str] = None,
    number: Optional[str] = None,
    asking: Optional[float] = None,
) -> tuple:
    """Return (best_snapshot, total_candidates). Overrides win over slug guesses."""
    source = PokemonTcgSource(cfg)
    use_name = name or info.name_guess
    use_set = set_id or info.set_guess
    use_num = number or info.number_guess

    cands = _candidates(source, use_name, use_set, use_num)
    priced = [c for c in cands if c.price() is not None]
    pool = priced or cands
    if not pool:
        return None, 0

    if asking is not None and priced:
        best = min(priced, key=lambda c: abs((c.price() or 0) - asking))
    else:
        best = max(pool, key=lambda c: (c.price() or 0))
    return best, len(cands)


# ---------------------------------------------------------------------------
# 3. Market context (uses local history if we have any) + verdict
# ---------------------------------------------------------------------------
def market_context(cfg: Config, snap: PriceSnapshot) -> Optional[Movement]:
    path = cfg.db_path
    if not path.exists():
        return None
    conn = db.connect(path)
    try:
        field_name = cfg.get("pricing.price_field", "market")
        return analyze.movement_for_card(conn, cfg, snap.card_id, snap.source, field_name)
    finally:
        conn.close()


def ebay_source(cfg: Config):
    """Return a configured EbaySource, or None if creds are absent."""
    from .sources.ebay import EbaySource
    s = EbaySource(cfg)
    return s if s.configured else None


def resolve_ebay_link(cfg: Config, url: str) -> Optional[dict]:
    """If url is an eBay listing and eBay is configured, fetch its price+title via API."""
    from .sources.ebay import ebay_item_id
    s = ebay_source(cfg)
    if not s:
        return None
    iid = ebay_item_id(url)
    if not iid:
        return None
    try:
        return s.item_by_legacy_id(iid)
    except Exception as exc:  # noqa: BLE001
        log.info("eBay item lookup failed: %s", exc)
        return None


def ebay_active_comps(cfg: Config, name: Optional[str], number: Optional[str] = None) -> Optional[dict]:
    s = ebay_source(cfg)
    if not s or not name:
        return None
    q = f"{name} {number}".strip() if number else name
    try:
        return s.active_comps(q)
    except Exception as exc:  # noqa: BLE001
        log.info("eBay comps failed: %s", exc)
        return None


def build_verdict(
    cfg: Config,
    info: LinkInfo,
    snap: PriceSnapshot,
    alternatives: int,
    asking: Optional[float],
    roi: Optional[float] = None,
    ebay_stats: Optional[dict] = None,
    summary=None,
) -> Verdict:
    target_roi = roi if roi is not None else float(cfg.get("economics.target_roi", 0.5))
    field_name = cfg.get("pricing.price_field", "market")
    market = snap.price(field_name)
    max_buy = rules.target_max_buy(cfg, market, roi=target_roi) if market else None

    v = Verdict(
        rating="INFO",
        card_name=snap.name or snap.card_id,
        card_id=snap.card_id,
        set_id=snap.set_id,
        number=snap.number,
        asking=asking,
        market=market,
        max_buy=max_buy,
        target_roi=target_roi,
        alternatives=alternatives,
        source_site=info.site,
        fx=float(cfg.get("economics.usd_to_cad", 1.37)),
    )

    # eBay active-listing comps (USD), if provided.
    if ebay_stats and ebay_stats.get("count"):
        v.ebay_count = ebay_stats["count"]
        v.ebay_low = ebay_stats.get("low")
        v.ebay_median = ebay_stats.get("median")

    # Budget affordability (CAD) from inventory summary, if provided.
    if summary is not None:
        v.budget_left_cad = summary.budget_left
        cost_usd = asking if asking is not None else max_buy
        if cost_usd is not None:
            v.cost_cad = round(cost_usd * v.fx, 2)
            v.affordable = v.cost_cad <= summary.budget_left

    # Market timing note from local history, if available.
    ctx = market_context(cfg, snap)
    if ctx and ctx.avg30:
        buy_drop = float(cfg.get("rules.buy_drop_pct", 0.85))
        spike = float(cfg.get("rules.spike_pct", 0.30))
        if ctx.current is not None and ctx.current <= ctx.avg30 * buy_drop:
            pct = (1 - ctx.current / ctx.avg30) * 100
            v.market_note = f"market dipping — {pct:.0f}% below 30d avg (good timing)"
        elif ctx.pct_7d is not None and ctx.pct_7d >= spike:
            v.market_note = f"overheated — up {ctx.pct_7d*100:.0f}% vs 7d avg (careful)"
        else:
            v.market_note = f"near 30d avg (${ctx.avg30:.2f})"
        if ctx.thin:
            v.market_note += " [thin history]"

    # Rating.
    if market is None:
        v.rating = "NO_MATCH"
        v.reasons.append("no market price available for the matched card")
        return v

    if asking is None:
        v.rating = "INFO"
        v.reasons.append(
            f"pay up to ${max_buy:.2f} to hit {target_roi*100:.0f}% ROI after fees"
            if max_buy else "couldn't compute a max buy"
        )
        v.reasons.append("re-run with --price to judge a specific asking price")
        return v

    if max_buy is not None and asking <= max_buy:
        v.rating = "BUY"
        v.reasons.append(f"${asking:.2f} is at/below your max buy (${max_buy:.2f}) — flip room for {target_roi*100:.0f}% ROI")
    elif asking <= market:
        v.rating = "FAIR"
        gap = market - asking
        v.reasons.append(
            f"${asking:.2f} is below market (${market:.2f}, save ${gap:.2f}) but above your "
            f"max buy (${max_buy:.2f}) — thin flip margin"
            if max_buy else f"${asking:.2f} is below market (${market:.2f})"
        )
    else:
        v.rating = "PASS"
        over = asking - market
        v.reasons.append(f"${asking:.2f} is ABOVE market (${market:.2f}, +${over:.2f}) — overpaying")

    # Budget overlay (CAD) — never blocks, just warns.
    if v.affordable is False and v.rating in ("BUY", "FAIR"):
        v.reasons.append(
            f"⚠ but ~CA${v.cost_cad:,.2f} exceeds remaining budget (CA${v.budget_left_cad:,.2f} left)"
        )
    elif v.affordable is True and v.rating == "BUY":
        v.reasons.append(
            f"fits budget — ~CA${v.cost_cad:,.2f} of CA${v.budget_left_cad:,.2f} left"
        )

    return v
