from datetime import datetime
from zoneinfo import ZoneInfo
from trading.feeds.futu_feed import market_of, parse_kline_row, GapDetector
from trading.common.models import Market, Bar

HK = ZoneInfo("Asia/Hong_Kong")


def test_market_of():
    assert market_of("HK.00700") == Market.HK
    assert market_of("US.AAPL") == Market.US


def test_parse_kline_row():
    row = {"code": "HK.00700", "time_key": "2026-06-02 09:31:00",
           "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5,
           "volume": 1000, "turnover": 100500.0}
    bar = parse_kline_row(row)
    assert bar.symbol == "HK.00700"
    assert bar.market == Market.HK
    assert bar.ts == datetime(2026, 6, 2, 9, 31, tzinfo=HK)
    assert bar.close == 100.5
    assert bar.volume == 1000


def _b(minute):
    return Bar("HK.00700", Market.HK, datetime(2026, 6, 2, 9, minute, tzinfo=HK),
               1, 1, 1, 1, 1, 1.0)


def test_gap_detector():
    g = GapDetector()
    assert g.check(_b(31)) == 0   # first
    assert g.check(_b(32)) == 0   # consecutive
    assert g.check(_b(35)) == 2   # missing 33, 34