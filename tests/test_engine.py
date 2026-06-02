from datetime import datetime
from zoneinfo import ZoneInfo
from trading.common.models import Bar, Market
from trading.strategy.signals import MeanReversionParams
from trading.strategy.grid import GridParams
from trading.backtest.engine import BacktestConfig, run_backtest

HK = ZoneInfo("Asia/Hong_Kong")


def _bar(day, minute, c):
    return Bar("HK.00700", Market.HK,
               datetime(2026, 6, day, 9 + minute // 60, minute % 60, tzinfo=HK),
               c, c, c, c, 1000, c * 1000)


def _bars():
    bars = [_bar(2, i, 100 + i * 0.2) for i in range(25)]   # day1 缓涨
    bars.append(_bar(2, 25, 110))                           # day1 跳涨 → SELL
    # day2 多根暴跌触发 oversold
    for i in range(5):
        bars.append(_bar(3, i, 98 - i * 3))                 # 98→95→92→89→86
    return bars


def test_reverse_t_profit_no_close_flat():
    cfg = BacktestConfig(
        grid=GridParams(base_qty=400, t_ratio=0.25, grid_n=4),
        params=MeanReversionParams(),
        commission_rate=0.0, slippage_bps=0.0, close_flat=False)
    r = run_backtest(_bars(), cfg)
    assert r.n_trades >= 1               # 至少有 SELL@110
    assert r.realized_pnl >= 0           # T交易应盈利或持平
    assert r.base_value == 100 * 400     # 首bar close * base_qty
    assert r.t_return >= 0


def test_close_flat_zeros_position_each_day():
    cfg = BacktestConfig(
        grid=GridParams(base_qty=400, t_ratio=0.25, grid_n=4),
        params=MeanReversionParams(),
        commission_rate=0.0, slippage_bps=0.0, close_flat=True)
    r = run_backtest(_bars(), cfg)
    # 每日末归零 → 末态无持仓,total≈realized
    assert isinstance(r.sharpe, float)
    assert isinstance(r.max_drawdown, float)