"""Read the Google Sheet (published CSV, read-only) and compute spend/saved/budget.

All money is treated as CAD (the sheet's currency). USD market prices are converted
with economics.usd_to_cad when we value current holdings.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from .config import Config

log = logging.getLogger("cardstock.inventory")


def csv_export_url(sheet_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def parse_money(raw) -> Optional[float]:
    """'$1,234.50' / '12' / '-' / '' -> float or None."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("$", "").replace("CA", "").strip()
    if s in ("", "-", "–", "—", "n/a", "N/A"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("%", "")
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


@dataclass
class InventoryItem:
    name: str = ""
    set_id: str = ""
    number: str = ""
    cost_basis: Optional[float] = None
    sale_price: Optional[float] = None
    net_proceeds: Optional[float] = None
    profit: Optional[float] = None
    status: str = ""
    sold: bool = False
    # filled in when we value holdings against the live market:
    market_cad: Optional[float] = None


@dataclass
class InventorySummary:
    currency: str = "CAD"
    starting_capital: float = 0.0
    spent: float = 0.0                 # sum of all cost basis
    realized_profit: float = 0.0       # profit on sold
    proceeds: float = 0.0              # net proceeds on sold
    budget_left: float = 0.0           # starting_capital + proceeds - spent
    n_held: int = 0
    n_sold: int = 0
    holdings_cost: float = 0.0
    holdings_market_cad: Optional[float] = None
    below_market_savings: Optional[float] = None
    items: List[InventoryItem] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


# --- CSV fetch -------------------------------------------------------------
def _fetch_rows(url: str, timeout: float) -> List[List[str]]:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    text = resp.text
    if text.lstrip().startswith("<"):
        raise RuntimeError(
            "got HTML, not CSV — the sheet isn't publicly readable. "
            "Share it: File -> Share -> Anyone with the link (Viewer)."
        )
    return list(csv.reader(io.StringIO(text)))


# --- column matching -------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_COLS = {
    "name": ["cardname", "card", "name"],
    "set": ["set"],
    "number": ["number", "no", "cardnumber"],
    "cost_basis": ["costbasis", "cost", "costbasis$"],
    "sale_price": ["saleprice", "saleprice$", "soldprice"],
    "net_proceeds": ["netproceeds", "netproceeds$", "net"],
    "profit": ["profit", "profit$"],
    "status": ["status"],
    "date_sold": ["datesold"],
}


def _find_header(rows: List[List[str]]) -> Optional[int]:
    for i, row in enumerate(rows):
        normed = {_norm(c) for c in row}
        if "cardname" in normed or ("card" in normed and "costbasis" in normed):
            return i
        if "costbasis" in normed and "saleprice" in normed:
            return i
    return None


def _col_index(header: List[str], keys: List[str]) -> Optional[int]:
    norm_header = [_norm(c) for c in header]
    for key in keys:
        if key in norm_header:
            return norm_header.index(key)
    return None


def parse_inventory_rows(rows: List[List[str]]) -> List[InventoryItem]:
    h = _find_header(rows)
    if h is None:
        log.warning("inventory: couldn't find a header row with Card Name / Cost Basis")
        return []
    header = rows[h]
    idx = {k: _col_index(header, keys) for k, keys in _COLS.items()}

    def cell(row, key):
        i = idx.get(key)
        return row[i] if (i is not None and i < len(row)) else ""

    items: List[InventoryItem] = []
    for row in rows[h + 1:]:
        name = (cell(row, "name") or "").strip()
        cost = parse_money(cell(row, "cost_basis"))
        if not name and cost is None:
            continue  # blank row
        sale = parse_money(cell(row, "sale_price"))
        status = (cell(row, "status") or "").strip()
        date_sold = (cell(row, "date_sold") or "").strip()
        sold = (status.lower() == "sold") or bool(date_sold) or (sale is not None)
        items.append(
            InventoryItem(
                name=name,
                set_id=(cell(row, "set") or "").strip(),
                number=(cell(row, "number") or "").strip(),
                cost_basis=cost,
                sale_price=sale,
                net_proceeds=parse_money(cell(row, "net_proceeds")),
                profit=parse_money(cell(row, "profit")),
                status=status,
                sold=sold,
            )
        )
    return items


def parse_starting_capital(rows: List[List[str]]) -> Optional[float]:
    """Find a 'starting capital' label and take a numeric value near it."""
    for row in rows:
        for j, cell in enumerate(row):
            if "starting capital" in (cell or "").lower():
                # look right along the row, then the rest of the row
                for k in range(j + 1, len(row)):
                    v = parse_money(row[k])
                    if v is not None:
                        return v
    return None


# --- top-level -------------------------------------------------------------
def load_summary(cfg: Config, value_holdings: bool = True) -> Optional[InventorySummary]:
    if not cfg.get("inventory.enabled", False):
        return None
    sheet_id = cfg.get("inventory.sheet_id", "")
    inv_gid = str(cfg.get("inventory.inventory_gid", ""))
    if not sheet_id or not inv_gid:
        log.warning("inventory enabled but sheet_id/inventory_gid not set")
        return None

    timeout = float(cfg.get("http.timeout_seconds", 30))
    try:
        inv_rows = _fetch_rows(csv_export_url(sheet_id, inv_gid), timeout)
    except Exception as exc:  # noqa: BLE001
        log.error("could not read inventory tab: %s", exc)
        return None

    items = parse_inventory_rows(inv_rows)

    # starting capital: settings tab if configured, else config fallback
    cap = None
    settings_gid = str(cfg.get("inventory.settings_gid", "") or "")
    if settings_gid:
        try:
            set_rows = _fetch_rows(csv_export_url(sheet_id, settings_gid), timeout)
            cap = parse_starting_capital(set_rows)
        except Exception as exc:  # noqa: BLE001
            log.info("could not read settings tab: %s", exc)
    if cap is None:
        cap = float(cfg.get("inventory.starting_capital_cad", 0) or 0)

    summ = summarize(items, cap)

    if value_holdings:
        _value_holdings(cfg, summ)

    if summ.starting_capital == 0:
        summ.notes.append("starting capital is 0 — set inventory.starting_capital_cad or the Settings tab")
    return summ


def summarize(items: List[InventoryItem], starting_capital: float) -> InventorySummary:
    """Pure budget math from parsed items (no network). All CAD."""
    summ = InventorySummary(items=items, starting_capital=starting_capital)
    for it in items:
        if it.cost_basis is not None:
            summ.spent += it.cost_basis
        if it.sold:
            summ.n_sold += 1
            summ.realized_profit += it.profit or 0.0
            summ.proceeds += it.net_proceeds if it.net_proceeds is not None else (it.sale_price or 0.0)
        else:
            summ.n_held += 1
            summ.holdings_cost += it.cost_basis or 0.0
    summ.budget_left = summ.starting_capital + summ.proceeds - summ.spent
    return summ


def _value_holdings(cfg: Config, summ: InventorySummary) -> None:
    """Look up current market for held cards and compute below-market savings (CAD)."""
    held = [it for it in summ.items if not it.sold and it.name]
    if not held:
        return
    from .sources.pokemontcg import PokemonTcgSource  # local import to avoid cycle

    fx = float(cfg.get("economics.usd_to_cad", 1.37))
    field_name = cfg.get("pricing.price_field", "market")
    src = PokemonTcgSource(cfg)

    total_market = 0.0
    savings = 0.0
    valued = 0
    for it in held:
        try:
            results = src.search(it.name, it.set_id or None, it.number or None, limit=20)
        except Exception as exc:  # noqa: BLE001
            log.info("holdings lookup failed for %s: %s", it.name, exc)
            continue
        priced = [r for r in results if r.price(field_name) is not None]
        if not priced:
            continue
        # if we know cost, pick the variant closest to cost (CAD->USD) to avoid mismatches
        if it.cost_basis:
            target_usd = it.cost_basis / fx
            best = min(priced, key=lambda r: abs((r.price(field_name) or 0) - target_usd))
        else:
            best = max(priced, key=lambda r: (r.price(field_name) or 0))
        market_cad = (best.price(field_name) or 0) * fx
        it.market_cad = round(market_cad, 2)
        total_market += market_cad
        if it.cost_basis is not None:
            savings += market_cad - it.cost_basis
        valued += 1

    if valued:
        summ.holdings_market_cad = round(total_market, 2)
        summ.below_market_savings = round(savings, 2)
    else:
        summ.notes.append("couldn't value any holdings against the market")
