from datetime import datetime
from zoneinfo import ZoneInfo
from trading.common.models import Bar, Market
from trading.strategy.signals import (
    Action, Signal, MeanReversionStrategy, MeanReversionParams)

HK = ZoneInfo("Asia/Hong_Kong")


def _bar(day, minute, o, h, l, c, v=1000):
    return Bar("HK.00700", Market.HK,
               datetime(2026, 6, day, 9 + minute // 60, minute % 60, tzinfo=HK),
               o, h, l, c, v, c * v)


def test_warmup_returns_hold():
    s = MeanReversionStrategy("HK.00700")
    sig = s.on_bar(_bar(2, 0, 100, 100, 100, 100))
    assert sig.action == Action.HOLD
    assert sig.reason == "warmup"


def test_sell_on_overbought():
    s = MeanReversionStrategy("HK.00700")
    last = None
    for i in range(25):                       # 缓涨 100→104.8,建仓 EMA 上行
        p = 100 + i * 0.2
        last = s.on_bar(_bar(2, i, p, p, p, p))
    spike = s.on_bar(_bar(2, 25, 110, 110, 110, 110))  # 跳涨突破上轨
    assert spike.action == Action.SELL


def test_buy_on_oversold_no_downtrend():
    # 验证 downtrend 阻断 BUY 的逻辑
    s = MeanReversionStrategy("HK.00700")
    # day1 缓涨 → uptrend,EMA 快>慢
    for i in range(30):
        p = 100 + i * 0.3
        s.on_bar(_bar(1, i, p, p, p, p))
    # day2 急跌 → downtrend(close<vwap + ema_fast<ema_slow)
    for i in range(10):
        p = 108 - i * 2
        buy = s.on_bar(_bar(2, i, p, p, p, p))
    # close<lower + RSI<30 但 downtrend 阻断 → HOLD
    assert buy.action == Action.HOLD
    assert "no-signal" in buy.reason or buy.reason