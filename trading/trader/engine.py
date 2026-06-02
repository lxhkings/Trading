from __future__ import annotations
from datetime import datetime
from trading.common.models import Order, Side, OrderType, Fill, Bar
from trading.strategy.signals import MeanReversionStrategy, MeanReversionParams, Action
from trading.strategy.grid import GridParams, GridPositionMgr
from trading.backtest.pnl import PnLTracker
from trading.risk.manager import RiskManager
from trading.common.state_store import StateStore
from trading.trader.order_tracker import OrderTracker


class TraderEngine:
    def __init__(self, *, base_qtys: dict[str, float],
                 params_by_symbol: dict[str, MeanReversionParams],
                 risk: RiskManager, broker, state_store: StateStore,
                 clock, order_tracker: OrderTracker, event_bus=None):
        self.base_qtys = base_qtys
        self.risk = risk
        self.broker = broker
        self.state = state_store
        self.clock = clock
        self.tracker = order_tracker
        self.bus = event_bus
        self.strategies = {s: MeanReversionStrategy(s, p)
                           for s, p in params_by_symbol.items()}
        self.grids = {s: GridPositionMgr(GridParams(base_qty=base_qtys[s]))
                      for s in base_qtys}
        self.pnl = {s: PnLTracker() for s in base_qtys}
        self.connected = True

    def on_bar(self, bar: Bar) -> None:
        sym = bar.symbol
        if sym not in self.strategies:
            return
        self.check_timeouts(bar.ts)
        # 同步 IB 实际持仓 → 意图基于实际
        actual_total = self.broker.get_positions().get(sym, self.base_qtys[sym])
        self.grids[sym].t_position = actual_total - self.base_qtys[sym]

        sig = self.strategies[sym].on_bar(bar)
        base_value = self.base_qtys[sym] * bar.close
        t_pnl = self.pnl[sym].realized + self.pnl[sym].unrealized(bar.close)
        decision = self.risk.check(
            sym, sig.action, self.grids[sym].t_position, bar.ts,
            daily_t_pnl=t_pnl, base_value=base_value, connected=self.connected)
        if not decision.approved:
            self._emit("signal." + sym, {"ts": bar.ts, "action": sig.action.value,
                                         "rejected": decision.reason})
            return

        delta = self.grids[sym].apply(sig.action)
        if delta == 0:
            return
        side = Side.BUY if delta > 0 else Side.SELL
        order = Order(symbol=sym, side=side, qty=abs(delta),
                      order_type=OrderType.LMT, limit_price=bar.close)
        oid = self.broker.place_order(order)
        self.tracker.track(oid, sym, bar.ts)
        try:
            self.state.save_t_position(sym, self.grids[sym].t_position)
        except Exception as e:                       # Redis 断 → 降级,内存仓位继续
            self._emit("alert", {"type": "state_save_failed", "err": str(e)})
        self._emit("signal." + sym, {"ts": bar.ts, "action": sig.action.value,
                                     "qty": abs(delta), "px": bar.close})

    def on_fill(self, fill: Fill) -> None:
        signed = fill.qty if fill.side == Side.BUY else -fill.qty
        self.pnl[fill.symbol].fill(signed, fill.price)
        self.tracker.complete(fill.order_id)
        self._emit("fill." + fill.symbol, {"side": fill.side.value, "qty": fill.qty,
                                           "px": fill.price, "oid": fill.order_id})

    def check_timeouts(self, now: datetime) -> None:
        for oid in self.tracker.timed_out(now):
            self.broker.cancel(oid)
            self.tracker.complete(oid)
            self._emit("alert", {"type": "order_timeout", "oid": oid})

    def _emit(self, topic: str, payload: dict) -> None:
        if self.bus is not None:
            self.bus.publish_event(topic, payload)