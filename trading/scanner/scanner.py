from __future__ import annotations
from dataclasses import dataclass, asdict
import yaml
from trading.common.models import Market
from trading.strategy.signals import MeanReversionParams
from trading.strategy.grid import GridParams
from trading.backtest.engine import BacktestConfig, run_backtest
from trading.scanner.metrics import atr_pct, autocorr_lag1, avg_turnover


@dataclass
class ScanResult:
    symbol: str
    market: Market
    sharpe: float
    t_return: float
    atr_pct: float
    autocorr: float
    avg_turnover: float
    params: MeanReversionParams
    passed_filters: bool


class Scanner:
    def __init__(self, loader, min_turnover: float, min_atr_pct: float):
        self._loader = loader
        self._min_turnover = min_turnover
        self._min_atr_pct = min_atr_pct

    def scan_symbol(self, futu_symbol: str, market: Market,
                    start: str, end: str, base_qty: float) -> ScanResult:
        bars = self._loader.load(futu_symbol, start, end)
        params = MeanReversionParams()
        cfg = BacktestConfig(grid=GridParams(base_qty=base_qty), params=params)
        bt = run_backtest(bars, cfg)
        ap = atr_pct(bars) or 0.0
        ac = autocorr_lag1(bars)
        turn = avg_turnover(bars)
        passed = turn >= self._min_turnover and ap >= self._min_atr_pct and ac < 0
        return ScanResult(futu_symbol, market, bt.sharpe, bt.t_return,
                          ap, ac, turn, params, passed)

    def rank(self, results: list[ScanResult], top: int = 3) -> list[ScanResult]:
        selected: list[ScanResult] = []
        for mkt in (Market.HK, Market.US):
            pool = [r for r in results if r.market == mkt and r.passed_filters]
            pool.sort(key=lambda r: r.sharpe, reverse=True)
            selected.extend(pool[:top])
        return selected

    def export_yaml(self, selected: list[ScanResult], path: str) -> None:
        doc = {"symbols": [
            {"symbol": r.symbol, "market": r.market.value,
             "sharpe": round(r.sharpe, 4), "t_return": round(r.t_return, 4),
             "params": asdict(r.params)}
            for r in selected
        ]}
        with open(path, "w") as f:
            yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)