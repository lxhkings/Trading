from __future__ import annotations
from pathlib import Path
import pandas as pd
from trading.common.models import Bar
from trading.feeds.futu_feed import parse_kline_row


def df_to_bars(df: pd.DataFrame) -> list[Bar]:
    return [parse_kline_row(row) for row in df.to_dict("records")]


class HistoryLoader:
    """富途历史1分钟 → list[Bar],带 parquet 缓存(同 symbol+区间不重复拉)。"""

    def __init__(self, feed, cache_root: str = "data/hist"):
        self._feed = feed
        self._root = Path(cache_root)

    def _cache_path(self, futu_symbol: str, start: str, end: str) -> Path:
        safe = futu_symbol.replace(".", "_")
        return self._root / f"{safe}__{start}__{end}.parquet"

    def load(self, futu_symbol: str, start: str, end: str) -> list[Bar]:
        p = self._cache_path(futu_symbol, start, end)
        if p.exists():
            return df_to_bars(pd.read_parquet(p))
        df = self._feed.get_history_kline(futu_symbol, start=start, end=end)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False)
        return df_to_bars(df)