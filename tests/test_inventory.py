from src import inventory
from src.inventory import parse_money, parse_inventory_rows, summarize


def test_parse_money():
    assert parse_money("$1,234.50") == 1234.50
    assert parse_money("12") == 12.0
    assert parse_money("-") is None
    assert parse_money("") is None
    assert parse_money("(5.00)") == -5.0
    assert parse_money("13.6%") == 13.6


SAMPLE = [
    ["The Card Squad inventory", "", "", "", ""],
    ["Date Acquired", "Card Name", "Set", "Cost Basis $", "Status",
     "Sale Price $", "Net Proceeds $", "Profit $", "Date Sold"],
    ["2026-01-01", "Charizard", "base1", "$300.00", "Sold",
     "$572.00", "$493.00", "$193.00", "2026-02-01"],
    ["2026-03-01", "Blastoise", "base1", "$120.00", "Held", "", "", "", ""],
    ["", "", "", "", "", "", "", "", ""],  # blank row ignored
]


def test_parse_inventory_rows():
    items = parse_inventory_rows(SAMPLE)
    assert len(items) == 2
    chari, blasto = items
    assert chari.name == "Charizard"
    assert chari.cost_basis == 300.0
    assert chari.sold is True
    assert chari.profit == 193.0
    assert blasto.sold is False
    assert blasto.cost_basis == 120.0


def test_summarize_budget_math():
    items = parse_inventory_rows(SAMPLE)
    summ = summarize(items, starting_capital=1000.0)
    assert summ.spent == 420.0            # 300 + 120
    assert summ.realized_profit == 193.0
    assert summ.proceeds == 493.0
    assert summ.n_held == 1
    assert summ.n_sold == 1
    assert summ.holdings_cost == 120.0
    # budget left = 1000 + 493 - 420
    assert summ.budget_left == 1073.0


def test_starting_capital_parse():
    rows = [["Settings"], ["Starting capital", "$2,500.00"], ["eBay fee %", "13.6%"]]
    assert inventory.parse_starting_capital(rows) == 2500.0


def test_sold_detected_by_sale_price_only():
    rows = [
        ["Card Name", "Cost Basis $", "Status", "Sale Price $"],
        ["Pikachu", "10", "", "25"],   # no explicit "Sold" status, but has a sale price
    ]
    items = parse_inventory_rows(rows)
    assert items[0].sold is True
