from __future__ import annotations
from dataclasses import dataclass
from trading.strategy.signals import Action


@dataclass
class GridParams:
    base_qty: float
    t_ratio: float = 0.25
    grid_n: int = 4


class GridPositionMgr:
    def __init__(self, params: GridParams):
        self.p = params
        self.t_pool = params.base_qty * params.t_ratio
        self.grid_step = self.t_pool / params.grid_n
        self.t_position = 0.0

    def apply(self, action: Action) -> float:
        """按信号更新目标 t_position,返回需成交量(delta,正买负卖)。"""
        target = self.t_position
        if action == Action.BUY:
            target = min(self.t_position + self.grid_step, self.t_pool)
        elif action == Action.SELL:
            target = max(self.t_position - self.grid_step, -self.t_pool)
        delta = target - self.t_position
        self.t_position = target
        return delta

    def flatten(self) -> float:
        delta = -self.t_position
        self.t_position = 0.0
        return delta