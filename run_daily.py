#!/usr/bin/env python3
"""The Card Squad — daily entry point.

  python run_daily.py                 # full run: fetch, store, analyze, email
  python run_daily.py --no-email      # run but don't send (good for testing)
  python run_daily.py --preview out.html   # write the digest HTML to a file
  python run_daily.py --date 2026-06-07    # store under a specific date (backfill/testing)

Logs go to stdout and logs/cardstock.log.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config import Config
from src.pipeline import run

ROOT = Path(__file__).resolve().parent


def setup_logging() -> None:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(logs / "cardstock.log"),
        ],
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="The Card Squad daily price digest")
    ap.add_argument("--no-email", action="store_true", help="don't send the email")
    ap.add_argument("--preview", metavar="PATH", help="write digest HTML to this file")
    ap.add_argument("--date", metavar="YYYY-MM-DD", help="run date stamp (default: today)")
    args = ap.parse_args()

    setup_logging()
    log = logging.getLogger("cardstock")
    cfg = Config()

    try:
        result = run(
            cfg,
            run_date=args.date,
            send=not args.no_email,
            preview_path=args.preview,
        )
    except Exception:  # noqa: BLE001
        log.exception("daily run failed")
        return 1

    log.info("done: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
