from __future__ import annotations
import redis
from trading.common.models import Bar


class EventBus:
    """Redis pub/sub(实时广播)+ stream(回放日志)封装。"""

    def __init__(self, client: redis.Redis):
        self._r = client

    def publish_bar(self, bar: Bar) -> None:
        channel = f"bar.{bar.market.value}.{bar.symbol}"
        payload = bar.to_json()
        self._r.publish(channel, payload)
        self._r.xadd("stream.bars", {"data": payload})