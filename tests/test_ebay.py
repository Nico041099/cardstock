from conftest import make_config
from src.sources.ebay import EbaySource, ebay_item_id


def test_ebay_item_id_from_urls():
    assert ebay_item_id("https://www.ebay.com/itm/123456789012") == "123456789012"
    assert ebay_item_id("https://www.ebay.com/itm/Charizard-Base-Set/123456789012") == "123456789012"
    assert ebay_item_id("https://www.ebay.com/itm/x?item=234567890123") == "234567890123"
    assert ebay_item_id("https://www.ebay.com/sch/i.html?_nkw=charizard") is None


def test_ebay_not_configured():
    cfg = make_config({})  # no env creds in test
    src = EbaySource(cfg)
    assert src.configured is False


def test_active_comps_aggregation(monkeypatch):
    cfg = make_config({"ebay": {"marketplace": "EBAY_US"}})
    src = EbaySource(cfg)

    # Avoid real network/auth.
    monkeypatch.setattr(src, "_get_token", lambda: "fake-token")

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"itemSummaries": [
                {"price": {"value": "10.00", "currency": "USD"}},
                {"price": {"value": "20.00", "currency": "USD"}},
                {"price": {"value": "30.00", "currency": "USD"}},
                {"title": "no price item"},
            ]}

    monkeypatch.setattr(src.session, "get", lambda *a, **k: FakeResp())
    stats = src.active_comps("charizard base set 4")
    assert stats["count"] == 3
    assert stats["low"] == 10.0
    assert stats["high"] == 30.0
    assert stats["median"] == 20.0
    assert stats["currency"] == "USD"
