from __future__ import annotations


class PnLTracker:
    def __init__(self):
        self.position = 0.0
        self.avg_cost = 0.0
        self.realized = 0.0

    def fill(self, qty: float, price: float) -> None:
        """qty>0 买入, qty<0 卖出。"""
        before = self.position
        if before == 0 or (before > 0) == (qty > 0):
            total = before + qty
            self.avg_cost = (self.avg_cost * before + price * qty) / total
            self.position = total
            return
        # 反向:先平仓实现盈亏
        closing = min(abs(qty), abs(before))
        if before > 0:
            self.realized += closing * (price - self.avg_cost)
        else:
            self.realized += closing * (self.avg_cost - price)
        self.position = before + qty
        if self.position == 0:
            self.avg_cost = 0.0
        elif (self.position > 0) != (before > 0):    # 翻转到反向
            self.avg_cost = price
        # 部分平仓:均价不变

    def unrealized(self, price: float) -> float:
        return self.position * (price - self.avg_cost)