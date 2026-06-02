from datetime import datetime, timezone, timedelta
from trading.risk.manager import RiskManager, RiskParams
from trading.strategy.signals import Action

T0 = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)


def _rm():
    return RiskManager(RiskParams(daily_loss_limit_pct=0.02, min_order_interval_s=60))


def test_hold_rejected():
    d = _rm().check("X", Action.HOLD, 0, T0, daily_t_pnl=0, base_value=40000, connected=True)
    assert not d.approved and d.reason == "hold"


def test_disconnected_rejected():
    d = _rm().check("X", Action.BUY, 0, T0, daily_t_pnl=0, base_value=40000, connected=False)
    assert not d.approved and d.reason == "disconnected"


def test_frequency_limit():
    rm = _rm()
    assert rm.check("X", Action.BUY, 0, T0, daily_t_pnl=0, base_value=40000, connected=True).approved
    d2 = rm.check("X", Action.BUY, 25, T0 + timedelta(seconds=30),
                  daily_t_pnl=0, base_value=40000, connected=True)
    assert not d2.approved and d2.reason == "too-frequent"
    d3 = rm.check("X", Action.BUY, 25, T0 + timedelta(seconds=61),
                  daily_t_pnl=0, base_value=40000, connected=True)
    assert d3.approved


def test_circuit_breaker_blocks_opening_allows_reducing():
    rm = _rm()
    # 当日亏损 -3% 超过 2% 限
    loss = -0.03 * 40000
    # 持多仓 t=25,BUY=加仓(开)→ 拒
    d_open = rm.check("X", Action.BUY, 25, T0, daily_t_pnl=loss, base_value=40000, connected=True)
    assert not d_open.approved and d_open.reason == "circuit-breaker"
    # 持多仓 t=25,SELL=减仓 → 允许
    d_reduce = rm.check("X", Action.SELL, 25, T0, daily_t_pnl=loss, base_value=40000, connected=True)
    assert d_reduce.approved