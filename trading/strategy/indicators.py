from __future__ import annotations
from typing import Sequence


def sma(xs: Sequence[float], n: int) -> float | None:
    if len(xs) < n:
        return None
    return sum(xs[-n:]) / n


def ema(xs: Sequence[float], n: int) -> float | None:
    if len(xs) < n:
        return None
    k = 2 / (n + 1)
    e = sum(xs[:n]) / n          # 以首 n 个的 SMA 作种子
    for x in xs[n:]:
        e = x * k + e * (1 - k)
    return e


def rsi(xs: Sequence[float], n: int) -> float | None:
    if len(xs) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(-n, 0):
        d = xs[i] - xs[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)


def bollinger(xs: Sequence[float], n: int, k: float):
    if len(xs) < n:
        return None
    w = xs[-n:]
    mid = sum(w) / n
    sd = (sum((x - mid) ** 2 for x in w) / n) ** 0.5
    return (mid, mid + k * sd, mid - k * sd)


def atr(highs: Sequence[float], lows: Sequence[float],
        closes: Sequence[float], n: int) -> float | None:
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(-n, 0):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs) / n