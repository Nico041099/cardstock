import sys
from pathlib import Path

# Make `import src...` work when running pytest from anywhere.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402


def make_config(overrides: dict) -> Config:
    """A Config whose .data is a controlled dict (no dependence on the real yaml)."""
    cfg = Config()
    cfg.data = overrides
    return cfg


DEFAULT_RULES = {
    "rules": {
        "buy_drop_pct": 0.85,
        "min_price": 5.0,
        "spike_pct": 0.30,
        "sell_gain_pct": 0.20,
        "sell_vs_avg_pct": 1.15,
        "min_data_points": 3,
    },
    "economics": {
        "ebay_fee_multiplier": 0.864,
        "ebay_per_order_fee": 0.40,
        "ship_cost": 1.0,
        "target_roi": 0.5,
    },
    "movement": {"thin_min_points": 5, "top_movers_limit": 15},
}
