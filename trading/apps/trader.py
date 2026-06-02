from __future__ import annotations
import os
import yaml
import redis
from trading.common.eventbus import EventBus
from trading.common.symbolmap import SymbolMap
from trading.common.state_store import StateStore
from trading.common.clock import MarketClock
from trading.strategy.signals import MeanReversionParams
from trading.brokers.ib_broker import IBBroker
from trading.risk.manager import RiskManager, RiskParams
from trading.trader.order_tracker import OrderTracker
from trading.trader.engine import TraderEngine
from trading.trader.recovery import startup_check, recover_t_position


def _load_targets(path: str) -> dict[str, dict]:
    """selected.yaml → {internal_symbol: {base_qty, params}}。"""
    doc = yaml.safe_load(open(path))
    out = {}
    for s in doc["symbols"]:
        out[s["symbol"]] = {
            "base_qty": s.get("base_qty", 400),
            "params": MeanReversionParams(**s.get("params", {})),
        }
    return out


def main():
    symbol_map = SymbolMap.from_yaml(os.environ.get("SYMBOLS_YAML", "config/symbols.yaml"))
    targets = _load_targets(os.environ.get("SELECTED_YAML", "config/selected.yaml"))
    base_qtys = {s: t["base_qty"] for s, t in targets.items()}
    params = {s: t["params"] for s, t in targets.items()}

    r = redis.Redis(host=os.environ.get("REDIS_HOST", "127.0.0.1"),
                    port=int(os.environ.get("REDIS_PORT", "6379")),
                    decode_responses=True)
    bus = EventBus(r)
    store = StateStore(r)
    broker = IBBroker(symbol_map,
                      host=os.environ.get("IB_HOST", "127.0.0.1"),
                      port=int(os.environ.get("IB_PORT", "7497")),  # paper 默认
                      client_id=int(os.environ.get("IB_CID", "1")))

    redis_ok = r.ping()
    broker.connect()
    startup_check(feed_ok=True, broker_ok=broker._ib.isConnected(), redis_ok=bool(redis_ok))

    # 状态恢复:从 IB 实际持仓反推 t_position 并落库
    positions = broker.get_positions()
    for sym, bq in base_qtys.items():
        t = recover_t_position(positions.get(sym, bq), bq)
        store.save_t_position(sym, t)
        print(f"[recover] {sym} actual={positions.get(sym, bq)} base={bq} t={t}")

    eng = TraderEngine(base_qtys=base_qtys, params_by_symbol=params,
                       risk=RiskManager(RiskParams()), broker=broker,
                       state_store=store, clock=MarketClock(),
                       order_tracker=OrderTracker(), event_bus=bus)
    broker.set_fill_handler(eng.on_fill)
    print(f"trader running, symbols={list(base_qtys)}. subscribing bars...")
    bus.subscribe_bars(eng.on_bar)


if __name__ == "__main__":
    main()