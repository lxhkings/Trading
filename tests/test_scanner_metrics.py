import math
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.common.models import Bar, Market
from trading.scanner.metrics import atr_pct, autocorr_lag1, avg_turnover

HK = ZoneInfo("Asia/Hong_Kong")


def _bar(i, o, h, l, c, v=1000, turnover=None):
    return Bar("X", Market.HK, datetime(2026, 6, 2, 10, i, tzinfo=HK),
               o, h, l, c, v, turnover if turnover is not None else c * v)


def test_atr_pct_positive():
    bars = [_bar(i, 100, 101, 99, 100) for i in range(20)]
    v = atr_pct(bars, 14)
    assert v is not None and v > 0


def test_autocorr_mean_reverting_negative():
    # 收益交替 +1/-1 → 一阶自相关接近 -1
    closes = [100, 101, 100, 101, 100, 101, 100, 101]
    bars = [_bar(i, c, c, c, c) for i, c in enumerate(closes)]
    assert autocorr_lag1(bars) < 0


def test_avg_turnover():
    bars = [_bar(i, 100, 100, 100, 100, turnover=t) for i, t in enumerate([100, 200, 300])]
    assert math.isclose(avg_turnover(bars), 200.0)