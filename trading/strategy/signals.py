from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from datetime import datetime, date
from enum import Enum
from trading.common.models import Bar
from trading.strategy.indicators import bollinger, rsi, ema


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Signal:
    symbol: str
    ts: datetime
    action: Action
    reason: str


@dataclass
class MeanReversionParams:
    bb_period: int = 20
    bb_k: float = 2.0
    rsi_period: int = 14
    rsi_low: float = 30.0
    rsi_high: float = 70.0
    ema_fast: int = 9
    ema_slow: int = 21


class MeanReversionStrategy:
    """单标的均值回归。on_bar 流式喂入;VWAP 按自然日重置。"""

    def __init__(self, symbol: str, params: MeanReversionParams | None = None):
        self.symbol = symbol
        self.p = params or MeanReversionParams()
        maxlen = max(self.p.bb_period, self.p.rsi_period + 1, self.p.ema_slow) + 1
        self._closes: deque[float] = deque(maxlen=maxlen)
        self._cur_day: date | None = None
        self._pv = 0.0
        self._vol = 0.0
        self._vwap = 0.0

    def _update_vwap(self, bar: Bar) -> None:
        d = bar.ts.date()
        if d != self._cur_day:
            self._cur_day, self._pv, self._vol = d, 0.0, 0.0
        typical = (bar.high + bar.low + bar.close) / 3
        self._pv += typical * bar.volume
        self._vol += bar.volume
        self._vwap = self._pv / self._vol if self._vol else bar.close

    def on_bar(self, bar: Bar) -> Signal:
        self._update_vwap(bar)
        self._closes.append(bar.close)
        xs = list(self._closes)
        bb = bollinger(xs, self.p.bb_period, self.p.bb_k)
        r = rsi(xs, self.p.rsi_period)
        ef = ema(xs, self.p.ema_fast)
        es = ema(xs, self.p.ema_slow)
        if bb is None or r is None or ef is None or es is None:
            return Signal(self.symbol, bar.ts, Action.HOLD, "warmup")
        _, upper, lower = bb
        downtrend = bar.close < self._vwap and ef < es
        if bar.close < lower and r < self.p.rsi_low and not downtrend:
            return Signal(self.symbol, bar.ts, Action.BUY, f"<{lower:.2f} rsi{r:.0f}")
        if bar.close > upper and r > self.p.rsi_high:
            return Signal(self.symbol, bar.ts, Action.SELL, f">{upper:.2f} rsi{r:.0f}")
        return Signal(self.symbol, bar.ts, Action.HOLD, "no-signal")