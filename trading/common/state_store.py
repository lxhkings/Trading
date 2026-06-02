from __future__ import annotations
import redis

_KEY = "t_positions"


class StateStore:
    def __init__(self, client: redis.Redis):
        self._r = client

    def save_t_position(self, symbol: str, t_position: float) -> None:
        self._r.hset(_KEY, symbol, t_position)

    def load_t_position(self, symbol: str) -> float:
        v = self._r.hget(_KEY, symbol)
        return float(v) if v is not None else 0.0

    def all_t_positions(self) -> dict[str, float]:
        return {k: float(v) for k, v in self._r.hgetall(_KEY).items()}