from datetime import datetime
from zoneinfo import ZoneInfo
from trading.common.clock import MarketClock
from trading.common.models import Market

HK = ZoneInfo("Asia/Hong_Kong")
US = ZoneInfo("America/New_York")


def test_hk_morning_session():
    assert MarketClock().active_market(datetime(2026, 6, 2, 10, 0, tzinfo=HK)) == Market.HK


def test_hk_lunch_break_closed():
    assert MarketClock().active_market(datetime(2026, 6, 2, 12, 30, tzinfo=HK)) is None


def test_hk_afternoon_session():
    assert MarketClock().active_market(datetime(2026, 6, 2, 14, 0, tzinfo=HK)) == Market.HK


def test_us_session():
    assert MarketClock().active_market(datetime(2026, 6, 2, 10, 0, tzinfo=US)) == Market.US


def test_weekend_closed():
    assert MarketClock().active_market(datetime(2026, 6, 6, 10, 0, tzinfo=HK)) is None