from conftest import DEFAULT_RULES, make_config
from src import analyze, db
from src.models import PriceSnapshot


def _seed(conn, card_id, name, series):
    """series: list of (date, market)."""
    for d, m in series:
        snap = PriceSnapshot(card_id=card_id, source="pokemontcg", name=name, market=m)
        db.upsert_card(conn, snap)
        db.record_price(conn, snap, d)
    conn.commit()


def test_movement_basic():
    cfg = make_config(DEFAULT_RULES)
    conn = db.connect(":memory:")
    _seed(conn, "c1", "Card", [
        ("2026-06-01", 10.0),
        ("2026-06-02", 12.0),
        ("2026-06-03", 9.0),
    ])
    m = analyze.movement_for_card(conn, cfg, "c1", "pokemontcg", "market")
    assert m.current == 9.0
    assert m.prev == 12.0
    # day change: (9-12)/12 = -0.25
    assert round(m.pct_day, 4) == -0.25
    assert m.points == 3
    assert m.thin is True  # < 5 points
    conn.close()


def test_top_movers_split():
    cfg = make_config(DEFAULT_RULES)
    conn = db.connect(":memory:")
    _seed(conn, "up1", "Up", [("2026-06-01", 10.0), ("2026-06-02", 15.0)])
    _seed(conn, "dn1", "Down", [("2026-06-01", 10.0), ("2026-06-02", 8.0)])
    moves = analyze.all_movements(conn, cfg, "pokemontcg", "2026-06-02", "market")
    ups = analyze.top_movers(moves, "up", 10, "pct_day")
    downs = analyze.top_movers(moves, "down", 10, "pct_day")
    assert [m.card_id for m in ups] == ["up1"]
    assert [m.card_id for m in downs] == ["dn1"]
    conn.close()


def test_missing_prices_ignored():
    cfg = make_config(DEFAULT_RULES)
    conn = db.connect(":memory:")
    # a card with all-null markets should yield no movement
    snap = PriceSnapshot(card_id="empty", source="pokemontcg", name="E", market=None)
    db.upsert_card(conn, snap)
    db.record_price(conn, snap, "2026-06-02")
    conn.commit()
    m = analyze.movement_for_card(conn, cfg, "empty", "pokemontcg", "market")
    assert m is None
    conn.close()
