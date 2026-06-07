#!/usr/bin/env python3
"""Business snapshot — how much we've spent, saved, and have left.

  python inventory_report.py            # full snapshot (values holdings vs market)
  python inventory_report.py --fast     # skip the live holdings valuation

Reads your Google Sheet (Inventory + Settings tabs) via published CSV, read-only.
All figures in CAD; USD market prices converted via economics.usd_to_cad.
"""
from __future__ import annotations

import argparse
import logging
import sys

from src.config import Config
from src.inventory import load_summary


def money(v):
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    return f"{sign}CA${abs(v):,.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Card Squad business snapshot")
    ap.add_argument("--fast", action="store_true", help="skip live holdings valuation")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr,
    )
    cfg = Config()
    summ = load_summary(cfg, value_holdings=not args.fast)
    if summ is None:
        print("Inventory not available. Check inventory.enabled / sheet sharing in config.")
        return 1

    print()
    print("📊 The Card Squad — Business Snapshot   (CAD)")
    print("─" * 48)
    print(f"  Starting capital   {money(summ.starting_capital)}")
    print(f"  Spent (cost basis) {money(summ.spent)}   ({summ.n_held} held, {summ.n_sold} sold)")
    print(f"  Sale proceeds      {money(summ.proceeds)}")
    print(f"  Budget left        {money(summ.budget_left)}")
    print("  " + "·" * 44)
    print("  Saved / earned:")
    print(f"    Realized profit (sold)        {money(summ.realized_profit)}")
    if summ.below_market_savings is not None:
        print(f"    Below-market on holdings      {money(summ.below_market_savings)}")
        print(f"    Holdings market value         {money(summ.holdings_market_cad)}"
              f"  (cost {money(summ.holdings_cost)})")
    else:
        print("    Below-market on holdings      (run without --fast to value holdings)")
    for note in summ.notes:
        print(f"  ⚠ {note}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
