from __future__ import annotations
from datetime import datetime, timezone
from trading.common.ports import Broker
from trading.common.models import Order, Fill, Side


class FakeBroker(Broker):
    def __init__(self, positions: dict[str, float] | None = None,
                 fill_immediately: bool = True):
        self._positions = dict(positions or {})
        self._fill_cb = None
        self.orders: list[tuple[str, Order]] = []
        self.canceled: list[str] = []
        self.fill_immediately = fill_immediately
        self._next = 0

    def connect(self) -> None:
        pass

    def get_positions(self) -> dict[str, float]:
        return dict(self._positions)

    def place_order(self, order: Order) -> str:
        self._next += 1
        oid = str(self._next)
        self.orders.append((oid, order))
        if self.fill_immediately:
            signed = order.qty if order.side == Side.BUY else -order.qty
            self._positions[order.symbol] = self._positions.get(order.symbol, 0) + signed
            if self._fill_cb:
                self._fill_cb(Fill(order.symbol, order.side, order.qty,
                                   order.limit_price or 0.0,
                                   datetime.now(timezone.utc), oid))
        return oid

    def cancel(self, order_id: str) -> None:
        self.canceled.append(order_id)

    def set_fill_handler(self, handler) -> None:
        self._fill_cb = handler

    def close(self) -> None:
        pass