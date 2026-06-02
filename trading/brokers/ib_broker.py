from __future__ import annotations
from ib_insync import IB, Stock, LimitOrder, MarketOrder
from trading.common.ports import Broker
from trading.common.models import Order, Fill, Side, OrderType
from trading.common.symbolmap import SymbolSpec, SymbolMap


def build_contract(spec: SymbolSpec) -> Stock:
    return Stock(spec.ib_symbol, spec.ib_exchange, spec.ib_currency)


def build_ib_order(order: Order):
    action = order.side.value          # "BUY"/"SELL"
    if order.order_type == OrderType.MKT:
        return MarketOrder(action, order.qty)
    return LimitOrder(action, order.qty, order.limit_price)


class IBBroker(Broker):
    def __init__(self, symbol_map: SymbolMap, host: str = "127.0.0.1",
                 port: int = 7497, client_id: int = 1):
        self._map = symbol_map
        self._host, self._port, self._cid = host, port, client_id
        self._ib = IB()
        self._fill_cb = None
        # IB ib_symbol -> internal,用于持仓/成交回映
        self._ib_to_internal = {s.ib_symbol: s.internal
                                for s in (symbol_map.by_internal(c)
                                          for c in self._all_internals(symbol_map))}

    @staticmethod
    def _all_internals(symbol_map: SymbolMap) -> list[str]:
        return [symbol_map.by_futu(f).internal for f in symbol_map.all_futu()]

    def connect(self) -> None:
        self._ib.connect(self._host, self._port, clientId=self._cid)
        self._ib.execDetailsEvent += self._on_exec

    def get_positions(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in self._ib.positions():
            internal = self._ib_to_internal.get(p.contract.symbol)
            if internal:
                out[internal] = float(p.position)
        return out

    def place_order(self, order: Order) -> str:
        spec = self._map.by_internal(order.symbol)
        trade = self._ib.placeOrder(build_contract(spec), build_ib_order(order))
        return str(trade.order.orderId)

    def cancel(self, order_id: str) -> None:
        for t in self._ib.trades():
            if str(t.order.orderId) == order_id:
                self._ib.cancelOrder(t.order)

    def set_fill_handler(self, handler) -> None:
        self._fill_cb = handler

    def _on_exec(self, trade, fill) -> None:
        if self._fill_cb is None:
            return
        internal = self._ib_to_internal.get(fill.contract.symbol, fill.contract.symbol)
        side = Side.BUY if fill.execution.side == "BOT" else Side.SELL
        self._fill_cb(Fill(internal, side, float(fill.execution.shares),
                           float(fill.execution.price),
                           fill.execution.time, str(fill.execution.orderId)))

    def close(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()