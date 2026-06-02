from __future__ import annotations
import json
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

    def publish_event(self, topic: str, payload: dict) -> None:
        s = json.dumps(payload, default=str)
        self._r.publish(topic, s)
        self._r.xadd(f"stream.{topic.split('.')[0]}", {"data": s})

    @staticmethod
    def _handle_message(msg: dict, handler) -> None:
        if msg.get("type") != "pmessage":
            return
        handler(Bar.from_json(msg["data"]))

    def subscribe_bars(self, handler) -> None:
        ps = self._r.pubsub()
        ps.psubscribe("bar.*")
        for msg in ps.listen():
            self._handle_message(msg, handler)