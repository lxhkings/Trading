import math
from trading.strategy.indicators import sma, ema, rsi, bollinger, atr


def test_sma_insufficient_returns_none():
    assert sma([1, 2], 3) is None


def test_sma():
    assert sma([1, 2, 3, 4], 2) == 3.5


def test_ema_seed_is_sma():
    # 仅 n 个数据时,EMA 等于首 n 个的 SMA
    assert ema([2, 4, 6], 3) == 4.0


def test_bollinger():
    mid, up, low = bollinger([10, 12, 14, 16, 18], 5, 2.0)
    assert mid == 14.0
    sd = math.sqrt(sum((x - 14) ** 2 for x in [10, 12, 14, 16, 18]) / 5)
    assert math.isclose(up, 14 + 2 * sd)
    assert math.isclose(low, 14 - 2 * sd)


def test_rsi_all_gains_is_100():
    assert rsi([1, 2, 3, 4, 5], 4) == 100.0


def test_rsi_known():
    # 交替 +1/-1,平均涨跌相等 → RSI=50
    assert math.isclose(rsi([10, 11, 10, 11, 10, 11], 4), 50.0)


def test_atr():
    highs = [10, 11, 12, 13, 14]
    lows = [9, 10, 11, 12, 13]
    closes = [9.5, 10.5, 11.5, 12.5, 13.5]
    # n=2: 取最后2根的TR均值
    val = atr(highs, lows, closes, 2)
    assert val is not None and val > 0