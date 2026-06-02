from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from trading.strategy.signals import Action


@dataclass
class RiskParams:
    daily_loss_limit_pct: float = 0.02
    min_order_interval_s: float = 60.0


@dataclass(frozen=True)
class Decision:
    approved: bool
    reason: str


class RiskManager:
    def __init__(self, params: RiskParams | None = None):
        self.p = params or RiskParams()
        self._last: dict[str, datetime] = {}

    def check(self, symbol: str, action: Action, t_position: float,
              now: datetime, *, daily_t_pnl: float, base_value: float,
              connected: bool) -> Decision:
        if action == Action.HOLD:
            return Decision(False, "hold")
        if not connected:
            return Decision(False, "disconnected")
        last = self._last.get(symbol)
        if last is not None and (now - last).total_seconds() < self.p.min_order_interval_s:
            return Decision(False, "too-frequent")
        if base_value > 0 and daily_t_pnl / base_value < -self.p.daily_loss_limit_pct:
            reducing = ((t_position > 0 and action == Action.SELL) or
                        (t_position < 0 and action == Action.BUY))
            if not reducing:
                return Decision(False, "circuit-breaker")
        self._last[symbol] = now
        return Decision(True, "ok")