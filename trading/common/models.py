from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
import json


class Market(str, Enum):
    HK = "HK"
    US = "US"


@dataclass(frozen=True)
class Bar:
    symbol: str          # 内部代码,如 "HK.00700"
    market: Market
    ts: datetime         # tz-aware,bar 起始时间
    open: float
    high: float
    low: float
    close: float
    volume: int
    turnover: float

    def to_json(self) -> str:
        d = asdict(self)
        d["market"] = self.market.value
        d["ts"] = self.ts.isoformat()
        return json.dumps(d)

    @classmethod
    def from_json(cls, s: str) -> "Bar":
        d = json.loads(s)
        return cls(
            symbol=d["symbol"],
            market=Market(d["market"]),
            ts=datetime.fromisoformat(d["ts"]),
            open=d["open"], high=d["high"], low=d["low"],
            close=d["close"], volume=d["volume"], turnover=d["turnover"],
        )