from trading.common.symbolmap import SymbolMap, SymbolSpec
from trading.common.models import Market


def _specs():
    return [
        SymbolSpec("HK.00700", "HK.00700", "700", "SEHK", "HKD", Market.HK),
        SymbolSpec("US.AAPL", "US.AAPL", "AAPL", "SMART", "USD", Market.US),
    ]


def test_lookup_by_internal_and_futu():
    m = SymbolMap(_specs())
    assert m.by_internal("HK.00700").ib_symbol == "700"
    assert m.by_futu("US.AAPL").market == Market.US


def test_all_futu():
    m = SymbolMap(_specs())
    assert set(m.all_futu()) == {"HK.00700", "US.AAPL"}


def test_from_yaml(tmp_path):
    p = tmp_path / "symbols.yaml"
    p.write_text(
        "symbols:\n"
        "  - internal: HK.00700\n"
        "    futu: HK.00700\n"
        "    ib_symbol: '700'\n"
        "    ib_exchange: SEHK\n"
        "    ib_currency: HKD\n"
        "    market: HK\n"
    )
    m = SymbolMap.from_yaml(str(p))
    assert m.by_internal("HK.00700").ib_exchange == "SEHK"
    assert m.by_internal("HK.00700").market == Market.HK