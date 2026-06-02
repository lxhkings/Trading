from __future__ import annotations
from trading.common.models import Bar
from trading.strategy.indicators import atr


def atr_pct(bars: list[Bar], n: int = 14) -> float | None:
    if len(bars) < n + 1:
        return None
    a = atr([b.high for b in bars], [b.low for b in bars],
            [b.close for b in bars], n)
    avg_price = sum(b.close for b in bars) / len(bars)
    return a / avg_price if avg_price else None


def autocorr_lag1(bars: list[Bar]) -> float:
    closes = [b.close for b in bars]
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    denom = sum((r - mean) ** 2 for r in rets)
    if denom == 0:
        return 0.0
    num = sum((rets[i] - mean) * (rets[i - 1] - mean) for i in range(1, len(rets)))
    return num / denom


def avg_turnover(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    return sum(b.turnover for b in bars) / len(bars)