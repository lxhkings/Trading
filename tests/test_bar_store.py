from datetime import datetime
from zoneinfo import ZoneInfo
from trading.storage.bar_store import BarStore
from trading.common.models import Bar, Market

HK = ZoneInfo("Asia/Hong_Kong")


def _bar(minute, close):
    return Bar("HK.00700", Market.HK,
               datetime(2026, 6, 2, 9, minute, tzinfo=HK),
               close, close, close, close, 100, 100.0 * close)


def test_append_and_load(tmp_path):
    store = BarStore(str(tmp_path))
    store.append(_bar(31, 100.0))
    store.append(_bar(32, 101.0))
    df = store.load("HK", "HK.00700", "2026-06-02")
    assert len(df) == 2
    assert list(df["close"]) == [100.0, 101.0]


def test_append_dedup_same_ts(tmp_path):
    store = BarStore(str(tmp_path))
    store.append(_bar(31, 100.0))
    store.append(_bar(31, 999.0))  # same ts, newer value
    df = store.load("HK", "HK.00700", "2026-06-02")
    assert len(df) == 1
    assert df.iloc[0]["close"] == 999.0


def test_load_missing_returns_empty(tmp_path):
    df = BarStore(str(tmp_path)).load("HK", "HK.00700", "2026-06-02")
    assert df.empty