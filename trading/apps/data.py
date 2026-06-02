from __future__ import annotations
import os
import time
import redis
from trading.common.eventbus import EventBus
from trading.common.symbolmap import SymbolMap
from trading.common.models import Bar
from trading.feeds.futu_feed import FutuDataFeed
from trading.storage.bar_store import BarStore


def main():
    symbols = SymbolMap.from_yaml(os.environ.get("SYMBOLS_YAML", "config/symbols.yaml"))
    r = redis.Redis(host=os.environ.get("REDIS_HOST", "127.0.0.1"),
                    port=int(os.environ.get("REDIS_PORT", "6379")),
                    decode_responses=True)
    bus = EventBus(r)
    store = BarStore(os.environ.get("BAR_ROOT", "data/bars"))
    feed = FutuDataFeed(host=os.environ.get("FUTU_HOST", "127.0.0.1"),
                        port=int(os.environ.get("FUTU_PORT", "11111")))

    def on_bar(bar: Bar):
        bus.publish_bar(bar)
        store.append(bar)
        print(f"[bar] {bar.symbol} {bar.ts.isoformat()} c={bar.close} v={bar.volume}")

    feed.connect()
    feed.set_bar_handler(on_bar)
    feed.subscribe(symbols.all_futu())
    print(f"data process running, subscribed {symbols.all_futu()}. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        feed.close()
        print("stopped.")


if __name__ == "__main__":
    main()