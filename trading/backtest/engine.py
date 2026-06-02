from __future__ import annotations
from dataclasses import dataclass
from trading.common.models import Bar
from trading.strategy.signals import MeanReversionStrategy, MeanReversionParams
from trading.strategy.grid import GridParams, GridPositionMgr
from trading.backtest.pnl import PnLTracker


@dataclass
class BacktestConfig:
    grid: GridParams
    params: MeanReversionParams
    commission_rate: float = 0.0003
    slippage_bps: float = 1.0
    close_flat: bool = True


@dataclass
class BacktestResult:
    n_trades: int
    realized_pnl: float
    total_pnl: float
    total_cost: float
    win_rate: float
    sharpe: float
    max_drawdown: float
    base_value: float
    t_return: float


def _sharpe(curve: list[float]) -> float:
    if len(curve) < 2:
        return 0.0
    diffs = [curve[i] - curve[i - 1] for i in range(1, len(curve))]
    mean = sum(diffs) / len(diffs)
    var = sum((d - mean) ** 2 for d in diffs) / len(diffs)
    sd = var ** 0.5
    return mean / sd if sd > 0 else 0.0


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0] if curve else 0.0
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v - peak)
    return mdd


def run_backtest(bars: list[Bar], cfg: BacktestConfig) -> BacktestResult:
    if not bars:
        return BacktestResult(0, 0, 0, 0, 0, 0, 0, 0, 0)
    strat = MeanReversionStrategy(bars[0].symbol, cfg.params)
    grid = GridPositionMgr(cfg.grid)
    pnl = PnLTracker()
    cost_total = 0.0
    n_trades = 0
    wins = closes = 0
    curve: list[float] = []
    for i, bar in enumerate(bars):
        sig = strat.on_bar(bar)
        is_last_of_day = (i == len(bars) - 1) or (bars[i + 1].ts.date() != bar.ts.date())
        delta = grid.apply(sig.action)
        if cfg.close_flat and is_last_of_day:
            delta += grid.flatten()
        if delta != 0:
            n_trades += 1
            fill_price = bar.close * (1 + (cfg.slippage_bps / 10000) * (1 if delta > 0 else -1))
            before_realized = pnl.realized
            pnl.fill(delta, fill_price)
            cost_total += abs(delta) * fill_price * cfg.commission_rate
            if pnl.realized != before_realized:
                closes += 1
                if pnl.realized - before_realized > 0:
                    wins += 1
        curve.append(pnl.realized + pnl.unrealized(bar.close) - cost_total)
    base_value = bars[0].close * cfg.grid.base_qty
    total_pnl = curve[-1]
    return BacktestResult(
        n_trades=n_trades,
        realized_pnl=pnl.realized,
        total_pnl=total_pnl,
        total_cost=cost_total,
        win_rate=wins / closes if closes else 0.0,
        sharpe=_sharpe(curve),
        max_drawdown=_max_drawdown(curve),
        base_value=base_value,
        t_return=total_pnl / base_value if base_value else 0.0,
    )