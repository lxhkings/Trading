from __future__ import annotations
from pathlib import Path
import pandas as pd
from trading.common.models import Bar


class BarStore:
    """按 市场/标的/日 分区落 parquet。"""

    def __init__(self, root: str):
        self.root = Path(root)

    def _day_str(self, bar: Bar) -> str:
        return bar.ts.strftime("%Y-%m-%d")

    def _path(self, market: str, symbol: str, day: str) -> Path:
        return self.root / market / symbol / f"{day}.parquet"

    def append(self, bar: Bar) -> None:
        p = self._path(bar.market.value, bar.symbol, self._day_str(bar))
        p.parent.mkdir(parents=True, exist_ok=True)
        row = pd.DataFrame([{
            "ts": bar.ts.isoformat(),
            "open": bar.open, "high": bar.high, "low": bar.low,
            "close": bar.close, "volume": bar.volume, "turnover": bar.turnover,
        }])
        if p.exists():
            df = pd.concat([pd.read_parquet(p), row], ignore_index=True)
            df = df.drop_duplicates(subset="ts", keep="last").reset_index(drop=True)
        else:
            df = row
        df.to_parquet(p, index=False)

    def load(self, market: str, symbol: str, day: str) -> pd.DataFrame:
        p = self._path(market, symbol, day)
        return pd.read_parquet(p) if p.exists() else pd.DataFrame()