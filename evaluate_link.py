#!/usr/bin/env python3
"""Should I buy THIS card? — evaluate a link or card name.

  python evaluate_link.py "https://www.tcgplayer.com/product/.../charizard-base-set-4"
  python evaluate_link.py "<ebay or collectr link>" --price 450
  python evaluate_link.py "Charizard" --set base1 --number 4 --price 450
  python evaluate_link.py "<link>" --roi 0.3          # judge for 30% ROI instead of 50%
  python evaluate_link.py "<link>" --no-fetch         # skip the page fetch, slug-only

Market price always comes from the official Pokemon TCG API. The asking price is
read from the page when possible; otherwise pass it with --price.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config import Config
from src.evaluate import build_verdict, parse_link, resolve_card

ROOT = Path(__file__).resolve().parent

ICON = {"BUY": "🟢", "FAIR": "🟡", "PASS": "🔴", "INFO": "ℹ️ ", "NO_MATCH": "❓"}


def _money(v):
    return f"${v:,.2f}" if v is not None else "—"


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate a card link or name: buy or not?")
    ap.add_argument("input", help="a link (Collectr/eBay/TCGplayer/any) OR a card name")
    ap.add_argument("--price", type=float, help="asking price in USD (overrides page)")
    ap.add_argument("--set", dest="set_id", help="set id to disambiguate (e.g. base1)")
    ap.add_argument("--number", help="collector number to disambiguate (e.g. 4)")
    ap.add_argument("--name", help="card name to search (overrides slug guess)")
    ap.add_argument("--roi", type=float, help="target ROI for this check (e.g. 0.3 = 30%%)")
    ap.add_argument("--no-fetch", action="store_true", help="don't fetch the page; slug only")
    ap.add_argument("--verbose", action="store_true", help="show debug logs")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    cfg = Config()

    is_url = args.input.strip().lower().startswith(("http://", "https://"))
    if is_url:
        info = parse_link(args.input, fetch=not args.no_fetch)
    else:
        info = parse_link("", fetch=False)
        info.site = "name"
        info.name_guess = args.input

    asking = args.price if args.price is not None else info.asking_price

    snap, alts = resolve_card(
        cfg, info,
        name=args.name, set_id=args.set_id, number=args.number, asking=asking,
    )
    if snap is None:
        print("❓ No matching card found.")
        guess = args.name or info.name_guess
        print(f"   I searched for: {guess or '(nothing usable)'}"
              + (f"  set={info.set_guess}" if info.set_guess else "")
              + (f"  number={info.number_guess}" if info.number_guess else ""))
        print("   Try: evaluate_link.py \"<card name>\" --set <id> --number <n> --price <$>")
        return 2

    v = build_verdict(cfg, info, snap, alts, asking, roi=args.roi)

    icon = ICON.get(v.rating, "")
    setnum = f"{v.set_id} #{v.number}".strip()
    print()
    print(f"{icon} {v.rating} — {v.card_name}  ({setnum})")
    print(f"   Asking:   {_money(v.asking)}" + ("" if v.asking is not None else "  (none given — pass --price)"))
    print(f"   Market:   {_money(v.market)}   (TCGplayer market, USD)")
    print(f"   Max buy:  {_money(v.max_buy)}   for {v.target_roi*100:.0f}% ROI after eBay fees + shipping")
    if v.market_note:
        print(f"   Timing:   {v.market_note}")
    for r in v.reasons:
        print(f"   • {r}")
    if v.source_site not in ("name", "unknown"):
        print(f"   (matched from {v.source_site} link"
              + (f"; {v.alternatives} candidate cards — re-run with --set/--number if wrong" if v.alternatives > 1 else "")
              + ")")
    elif v.alternatives > 1:
        print(f"   ({v.alternatives} candidate cards matched — add --set/--number if this is the wrong one)")
    print()
    print("   Screening suggestion only — confirm condition & authenticity before buying.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
