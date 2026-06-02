from __future__ import annotations
from datetime import datetime


class OrderTracker:
    def __init__(self, timeout_s: float = 30.0):
        self.timeout = timeout_s
        self._pending: dict[str, tuple[str, datetime]] = {}

    def track(self, order_id: str, symbol: str, ts: datetime) -> None:
        self._pending[order_id] = (symbol, ts)

    def complete(self, order_id: str) -> None:
        self._pending.pop(order_id, None)

    def timed_out(self, now: datetime) -> list[str]:
        return [oid for oid, (_, ts) in self._pending.items()
                if (now - ts).total_seconds() >= self.timeout]