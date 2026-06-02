from datetime import datetime
from zoneinfo import ZoneInfo
import yaml
from trading.common.models import Bar, Market
from trading.scanner.scanner import Scanner, ScanResult

HK = ZoneInfo("Asia/Hong_Kong")


class FakeLoader:
    """按 symbol 返回预置 bars。"""
    def __init__(self, data):
        self._data = data

    def load(self, futu_symbol, start, end):
        return self._data[futu_symbol]


def _series(symbol, market, pattern):
    bars = []
    for i, c in enumerate(pattern):
        bars.append(Bar(symbol, market,
                        datetime(2026, 6, 2 + i // 300, 9 + (i % 300) // 60, i % 60, tzinfo=HK),
                        c, c + 0.5, c - 0.5, c, 1000, c * 1000))
    return bars


def test_scan_symbol_produces_result():
    # 震荡序列:有回归性、足够流动性
    pattern = [100 + (1 if i % 2 else -1) for i in range(60)]
    loader = FakeLoader({"HK.00700": _series("HK.00700", Market.HK, pattern)})
    sc = Scanner(loader, min_turnover=0.0, min_atr_pct=0.0)
    res = sc.scan_symbol("HK.00700", Market.HK, "2026-01-01", "2026-06-01", base_qty=400)
    assert isinstance(res, ScanResult)
    assert res.symbol == "HK.00700"
    assert res.avg_turnover > 0


def test_rank_selects_top_per_market(tmp_path):
    loader = FakeLoader({
        "HK.A": _series("HK.A", Market.HK, [100 + (1 if i % 2 else -1) for i in range(60)]),
        "HK.B": _series("HK.B", Market.HK, [100 + (2 if i % 2 else -2) for i in range(60)]),
        "US.C": _series("US.C", Market.US, [50 + (1 if i % 2 else -1) for i in range(60)]),
    })
    sc = Scanner(loader, min_turnover=0.0, min_atr_pct=0.0)
    results = [
        sc.scan_symbol("HK.A", Market.HK, "2026-01-01", "2026-06-01", 400),
        sc.scan_symbol("HK.B", Market.HK, "2026-01-01", "2026-06-01", 400),
        sc.scan_symbol("US.C", Market.US, "2026-01-01", "2026-06-01", 400),
    ]
    selected = sc.rank(results, top=1)
    markets = {r.market for r in selected}
    assert markets == {Market.HK, Market.US}      # 每市场各选 1
    assert sum(1 for r in selected if r.market == Market.HK) == 1

    out = tmp_path / "selected.yaml"
    sc.export_yaml(selected, str(out))
    loaded = yaml.safe_load(out.read_text())
    assert "symbols" in loaded
    assert all("bb_period" in s["params"] for s in loaded["symbols"])