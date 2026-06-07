"""Rules engine: BUY / AVOID / SELL signals from movement data. All thresholds in config."""
from __future__ import annotations

from typing import List, Optional

from .config import Config
from .models import Movement, Signal


def target_max_buy(cfg: Config, market: float) -> Optional[float]:
    """Most we should pay and still hit target ROI after eBay fees + shipping.

    max_buy = (market * ebay_fee_multiplier - per_order_fee - ship) / (1 + target_roi)
    """
    if market is None or market <= 0:
        return None
    fee_mult = float(cfg.get("economics.ebay_fee_multiplier", 0.864))
    per_order = float(cfg.get("economics.ebay_per_order_fee", 0.40))
    ship = float(cfg.get("economics.ship_cost", 1.0))
    roi = float(cfg.get("economics.target_roi", 0.5))
    net = market * fee_mult - per_order - ship
    mb = net / (1.0 + roi)
    return round(mb, 2) if mb > 0 else None


def evaluate(cfg: Config, movements: List[Movement]) -> List[Signal]:
    buy_drop = float(cfg.get("rules.buy_drop_pct", 0.85))
    min_price = float(cfg.get("rules.min_price", 5.0))
    spike = float(cfg.get("rules.spike_pct", 0.30))
    sell_gain = float(cfg.get("rules.sell_gain_pct", 0.20))
    sell_vs_avg = float(cfg.get("rules.sell_vs_avg_pct", 1.15))
    min_points = int(cfg.get("rules.min_data_points", 3))

    signals: List[Signal] = []

    for m in movements:
        cur = m.current
        if cur is None:
            continue

        # --- BUY candidate ---
        if (
            m.avg30 is not None
            and m.avg30 >= min_price
            and m.points >= min_points
            and cur <= m.avg30 * buy_drop
        ):
            drop_pct = (1 - cur / m.avg30) * 100
            mb = target_max_buy(cfg, cur)
            room = "flip room OK" if (mb is not None and cur <= mb) else "TIGHT margin"
            signals.append(
                Signal(
                    card_id=m.card_id,
                    name=m.name,
                    kind="BUY",
                    reason=f"{drop_pct:.0f}% below 30d avg (${m.avg30:.2f}); {room}"
                           + (" [thin data]" if m.thin else ""),
                    current=cur,
                    max_buy=mb,
                    extra={"avg30": m.avg30, "thin": m.thin},
                )
            )

        # --- AVOID / overheated ---
        if m.pct_7d is not None and m.pct_7d >= spike:
            signals.append(
                Signal(
                    card_id=m.card_id,
                    name=m.name,
                    kind="AVOID",
                    reason=f"up {m.pct_7d*100:.0f}% vs 7d avg — overheated, may revert"
                           + (" [thin data]" if m.thin else ""),
                    current=cur,
                    extra={"pct_7d": m.pct_7d, "thin": m.thin},
                )
            )

        # --- SELL / take-profit (owned only) ---
        if m.owned:
            reasons = []
            if m.cost_basis and cur >= m.cost_basis * (1 + sell_gain):
                gain = (cur / m.cost_basis - 1) * 100
                reasons.append(f"+{gain:.0f}% over cost (${m.cost_basis:.2f})")
            if m.avg30 is not None and cur >= m.avg30 * sell_vs_avg:
                over = (cur / m.avg30 - 1) * 100
                reasons.append(f"+{over:.0f}% over 30d avg")
            if reasons:
                signals.append(
                    Signal(
                        card_id=m.card_id,
                        name=m.name,
                        kind="SELL",
                        reason="; ".join(reasons)
                               + (" [thin data]" if m.thin else ""),
                        current=cur,
                        extra={"cost_basis": m.cost_basis, "thin": m.thin},
                    )
                )

    return signals
