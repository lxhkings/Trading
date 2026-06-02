import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.backtest.history import df_to_bars
from trading.common.models import Market

HK = ZoneInfo("Asia/Hong_Kong")


def test_df_to_bars():
    df = pd.DataFrame([
        {"code": "HK.00700", "time_key": "2026-06-02 09:31:00",
         "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
         "volume": 1000, "turnover": 100500.0},
        {"code": "HK.00700", "time_key": "2026-06-02 09:32:00",
         "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5,
         "volume": 1200, "turnover": 121800.0},
    ])
    bars = df_to_bars(df)
    assert len(bars) == 2
    assert bars[0].symbol == "HK.00700"
    assert bars[0].market == Market.HK
    assert bars[0].ts == datetime(2026, 6, 2, 9, 31, tzinfo=HK)
    assert bars[1].close == 101.5