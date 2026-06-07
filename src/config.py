"""Load config.yaml + .env and expose typed accessors."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List

import yaml
from dotenv import load_dotenv

from .models import CardRef

ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class Config:
    """Parsed config.yaml plus environment secrets."""

    def __init__(self, root: Path = ROOT):
        self.root = root
        load_dotenv(root / ".env")
        self.data = _load_yaml(root / "config.yaml")

    # --- generic getter with dotted path + default ---
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # --- secrets ---
    @property
    def pokemontcg_api_key(self) -> str:
        return os.getenv("POKEMONTCG_API_KEY", "").strip()

    @property
    def pricecharting_token(self) -> str:
        return os.getenv("PRICECHARTING_TOKEN", "").strip()

    @property
    def ebay_client_id(self) -> str:
        return os.getenv("EBAY_CLIENT_ID", "").strip()

    @property
    def ebay_client_secret(self) -> str:
        return os.getenv("EBAY_CLIENT_SECRET", "").strip()

    @property
    def gmail_address(self) -> str:
        return os.getenv("GMAIL_ADDRESS", "").strip()

    @property
    def gmail_app_password(self) -> str:
        return os.getenv("GMAIL_APP_PASSWORD", "").strip()

    @property
    def digest_to(self) -> str:
        return os.getenv("DIGEST_TO", "").strip() or self.gmail_address

    # --- paths ---
    @property
    def db_path(self) -> Path:
        rel = self.get("database.path", "data/cardstock.sqlite")
        p = Path(rel)
        return p if p.is_absolute() else self.root / p

    # --- watchlist / sets ---
    def watchlist(self) -> List[CardRef]:
        raw = _load_yaml(self.root / "watchlist.yaml")
        out: List[CardRef] = []
        for c in raw.get("cards", []) or []:
            out.append(
                CardRef(
                    id=c.get("id"),
                    set=c.get("set"),
                    number=(str(c["number"]) if c.get("number") is not None else None),
                    name=c.get("name"),
                    owned=bool(c.get("owned", False)),
                    cost_basis=c.get("cost_basis"),
                    qty=c.get("qty"),
                )
            )
        return out

    def sets(self) -> List[str]:
        raw = _load_yaml(self.root / "sets.yaml")
        return [str(s) for s in (raw.get("sets") or [])]

    def max_cards_per_set(self) -> int:
        raw = _load_yaml(self.root / "sets.yaml")
        return int(raw.get("max_cards_per_set", 0) or 0)
