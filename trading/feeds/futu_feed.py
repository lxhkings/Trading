from __future__ import annotations
from typing import Callable
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.common.models import Bar, Market
from trading.common.ports import DataFeed

_TZ = {Market.HK: ZoneInfo("Asia/Hong_Kong"),
       Market.US: ZoneInfo("America/New_York")}


def market_of(futu_code: str) -> Market:
    return Market[futu_code.split(".")[0]]


def parse_kline_row(row: dict) -> Bar:
    market = market_of(row["code"])
    naive = datetime.strptime(row["time_key"], "%Y-%m-%d %H:%M:%S")
    ts = naive.replace(tzinfo=_TZ[market])
    return Bar(
        symbol=row["code"], market=market, ts=ts,
        open=float(row["open"]), high=float(row["high"]),
        low=float(row["low"]), close=float(row["close"]),
        volume=int(row["volume"]), turnover=float(row["turnover"]),
    )


class GapDetector:
    """返回相对上一个 bar 缺失的分钟数(0=连续或首个)。"""

    def __init__(self):
        self._last: dict[str, datetime] = {}

    def check(self, bar: Bar) -> int:
        last = self._last.get(bar.symbol)
        self._last[bar.symbol] = bar.ts
        if last is None:
            return 0
        delta = (bar.ts - last).total_seconds()
        return max(0, int(delta // 60) - 1) if delta > 60 else 0


class FutuDataFeed(DataFeed):
    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self._host, self._port = host, port
        self._ctx = None
        self._handler: Callable[[Bar], None] | None = None
        self._gaps = GapDetector()

    def connect(self) -> None:
        from futu import OpenQuoteContext
        self._ctx = OpenQuoteContext(host=self._host, port=self._port)

    def set_bar_handler(self, handler: Callable[[Bar], None]) -> None:
        self._handler = handler

    def subscribe(self, futu_symbols: list[str]) -> None:
        from futu import SubType, RET_OK, CurKlineHandlerBase
        feed = self

        class _Handler(CurKlineHandlerBase):
            def on_recv_rsp(self, rsp_pb):
                ret, data = super().on_recv_rsp(rsp_pb)
                if ret != RET_OK:
                    return ret, data
                for _, r in data.iterrows():
                    bar = parse_kline_row(r.to_dict())
                    feed._gaps.check(bar)
                    if feed._handler:
                        feed._handler(bar)
                return ret, data

        self._ctx.set_handler(_Handler())
        ret, msg = self._ctx.subscribe(futu_symbols, [SubType.K_1M])
        if ret != RET_OK:
            raise RuntimeError(f"futu subscribe failed: {msg}")

    def get_history_kline(self, futu_symbol: str, start=None, end=None):
        from futu import KLType, RET_OK
        import pandas as pd
        rows, page_key = [], None
        while True:
            ret, data, page_key = self._ctx.request_history_kline(
                futu_symbol, start=start, end=end,
                ktype=KLType.K_1M, max_count=1000, page_req_key=page_key)
            if ret != RET_OK:
                raise RuntimeError(f"history_kline failed: {data}")
            rows.append(data)
            if not page_key:
                break
        return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()

    def quota(self):
        from futu import RET_OK
        ret, data = self._ctx.get_history_kl_quota(get_detail=False)
        if ret != RET_OK:
            raise RuntimeError(f"quota failed: {data}")
        return data

    def close(self) -> None:
        if self._ctx:
            self._ctx.close()