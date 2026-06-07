from conftest import DEFAULT_RULES, make_config
from src import evaluate
from src.evaluate import LinkInfo
from src.models import PriceSnapshot


# ---- URL parsing (no network: fetch=False) ----
def test_parse_tcgplayer_slug():
    url = "https://www.tcgplayer.com/product/107712/pokemon-base-set-charizard-holo-4-102"
    info = evaluate.parse_link(url, fetch=False)
    assert info.site == "tcgplayer"
    assert "charizard" in info.name_guess
    assert info.set_guess == "base1"        # "base-set" -> base1
    assert info.number_guess == "4"          # from 4-102


def test_parse_ebay_site():
    url = "https://www.ebay.com/itm/123456789"
    info = evaluate.parse_link(url, fetch=False)
    assert info.site == "ebay"


def test_parse_collectr_site():
    info = evaluate.parse_link("https://app.getcollectr.com/showcase/abc", fetch=False)
    assert info.site == "collectr"


def test_clean_slug_strips_noise():
    name = evaluate._clean_slug_to_name("charizard-base-set-psa-10-holo-4-102")
    assert "charizard" in name
    assert "psa" not in name
    assert "holo" not in name


def test_clean_slug_drops_generic_set_words():
    # "base" must not survive as a name token (it matched every "...Base" card before).
    name = evaluate._clean_slug_to_name("pokemon-base-set-charizard-holo-4-102")
    assert name == "charizard"


def test_candidates_tries_set_number_first():
    # When set+number are known, the first query must be the exact (set,number) id,
    # with no name — the most reliable lookup.
    calls = []

    class FakeSource:
        def search(self, name=None, set_id=None, number=None, limit=50):
            calls.append((name, set_id, number))
            from src.models import PriceSnapshot
            return [PriceSnapshot(card_id="base1-4", source="pokemontcg",
                                  name="Charizard", set_id="base1", number="4",
                                  market=572.0)]

    evaluate._candidates(FakeSource(), "base charizard", "base1", "4")
    assert calls[0] == (None, "base1", "4")


# ---- verdict logic (no network: feed a snapshot directly) ----
def _snap(market):
    return PriceSnapshot(card_id="base1-4", source="pokemontcg", name="Charizard",
                         set_id="base1", number="4", market=market)


def _info():
    return LinkInfo(raw="x", site="tcgplayer")


def test_verdict_buy_when_below_max():
    cfg = make_config({**DEFAULT_RULES, "pricing": {"price_field": "market"},
                       "database": {"path": "data/none.sqlite"}})
    # market 100 -> max_buy 56.67 ; asking 50 -> BUY
    v = evaluate.build_verdict(cfg, _info(), _snap(100.0), alternatives=1, asking=50.0)
    assert v.rating == "BUY"
    assert v.max_buy == 56.67


def test_verdict_fair_between_max_and_market():
    cfg = make_config({**DEFAULT_RULES, "pricing": {"price_field": "market"},
                       "database": {"path": "data/none.sqlite"}})
    # market 100, max_buy 56.67 ; asking 80 -> below market, above max -> FAIR
    v = evaluate.build_verdict(cfg, _info(), _snap(100.0), alternatives=1, asking=80.0)
    assert v.rating == "FAIR"


def test_verdict_pass_above_market():
    cfg = make_config({**DEFAULT_RULES, "pricing": {"price_field": "market"},
                       "database": {"path": "data/none.sqlite"}})
    v = evaluate.build_verdict(cfg, _info(), _snap(100.0), alternatives=1, asking=130.0)
    assert v.rating == "PASS"


def test_verdict_info_without_price():
    cfg = make_config({**DEFAULT_RULES, "pricing": {"price_field": "market"},
                       "database": {"path": "data/none.sqlite"}})
    v = evaluate.build_verdict(cfg, _info(), _snap(100.0), alternatives=1, asking=None)
    assert v.rating == "INFO"
    assert v.max_buy == 56.67


def test_verdict_roi_override_changes_max_buy():
    cfg = make_config({**DEFAULT_RULES, "pricing": {"price_field": "market"},
                       "database": {"path": "data/none.sqlite"}})
    # roi 0.0 -> max_buy = 100*0.864 - 0.4 - 1 = 85.0
    v = evaluate.build_verdict(cfg, _info(), _snap(100.0), alternatives=1, asking=None, roi=0.0)
    assert v.max_buy == 85.0
