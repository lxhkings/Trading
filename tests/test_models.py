from datetime import datetime, timezone
from trading.common.models import Bar, Market


def test_market_enum_values():
    assert Market.HK.value == "HK"
    assert Market.US.value == "US"


def test_bar_roundtrip_json():
    bar = Bar(
        symbol="HK.00700", market=Market.HK,
        ts=datetime(2026, 6, 2, 9, 31, tzinfo=timezone.utc),
        open=1.0, high=2.0, low=0.5, close=1.5,
        volume=1000, turnover=1500.0,
    )
    restored = Bar.from_json(bar.to_json())
    assert restored == bar
    assert isinstance(restored.market, Market)