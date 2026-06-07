from conftest import DEFAULT_RULES, make_config
from src import rules
from src.models import Movement


def _cfg():
    return make_config(DEFAULT_RULES)


def test_target_max_buy_math():
    cfg = _cfg()
    # market=100: 100*0.864 - 0.40 - 1.00 = 85.0 ; /1.5 = 56.67
    assert rules.target_max_buy(cfg, 100.0) == 56.67
    assert rules.target_max_buy(cfg, 0) is None
    assert rules.target_max_buy(cfg, None) is None


def test_buy_fires_when_below_threshold():
    cfg = _cfg()
    # avg30=20, current=15 -> 15 <= 20*0.85 (17) -> BUY
    m = Movement(card_id="x", name="Card X", current=15.0, avg30=20.0, points=10)
    sigs = rules.evaluate(cfg, [m])
    kinds = [s.kind for s in sigs]
    assert "BUY" in kinds
    buy = next(s for s in sigs if s.kind == "BUY")
    assert buy.max_buy is not None


def test_buy_skips_pennies():
    cfg = _cfg()
    # avg30=4 (< min_price 5) -> no BUY even though current is far below
    m = Movement(card_id="x", name="Penny", current=1.0, avg30=4.0, points=10)
    assert not any(s.kind == "BUY" for s in rules.evaluate(cfg, [m]))


def test_buy_needs_enough_points():
    cfg = _cfg()
    m = Movement(card_id="x", name="Thin", current=15.0, avg30=20.0, points=2)
    assert not any(s.kind == "BUY" for s in rules.evaluate(cfg, [m]))


def test_avoid_fires_on_spike():
    cfg = _cfg()
    m = Movement(card_id="x", name="Hot", current=50.0, avg30=40.0, pct_7d=0.40, points=10)
    assert any(s.kind == "AVOID" for s in rules.evaluate(cfg, [m]))


def test_avoid_not_fire_below_spike():
    cfg = _cfg()
    m = Movement(card_id="x", name="Mild", current=50.0, pct_7d=0.10, points=10)
    assert not any(s.kind == "AVOID" for s in rules.evaluate(cfg, [m]))


def test_sell_on_cost_basis_gain():
    cfg = _cfg()
    # owned, cost 40, current 50 -> +25% >= 20% -> SELL
    m = Movement(card_id="x", name="Held", current=50.0, avg30=48.0,
                 owned=True, cost_basis=40.0, points=10)
    assert any(s.kind == "SELL" for s in rules.evaluate(cfg, [m]))


def test_sell_only_for_owned():
    cfg = _cfg()
    m = Movement(card_id="x", name="NotHeld", current=50.0, avg30=30.0,
                 owned=False, cost_basis=40.0, points=10)
    assert not any(s.kind == "SELL" for s in rules.evaluate(cfg, [m]))


def test_sell_on_avg_premium():
    cfg = _cfg()
    # owned, current 60 >= avg30 50 * 1.15 (57.5) -> SELL even with no cost basis
    m = Movement(card_id="x", name="Held2", current=60.0, avg30=50.0,
                 owned=True, cost_basis=None, points=10)
    assert any(s.kind == "SELL" for s in rules.evaluate(cfg, [m]))
