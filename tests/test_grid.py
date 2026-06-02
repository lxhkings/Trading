from trading.strategy.grid import GridParams, GridPositionMgr
from trading.strategy.signals import Action


def _mgr():
    return GridPositionMgr(GridParams(base_qty=400, t_ratio=0.25, grid_n=4))
    # t_pool=100, grid_step=25


def test_buy_increments_capped():
    m = _mgr()
    assert m.apply(Action.BUY) == 25      # 0 -> 25
    assert m.apply(Action.BUY) == 25      # 25 -> 50
    m.apply(Action.BUY); m.apply(Action.BUY)  # -> 100 (上限)
    assert m.t_position == 100
    assert m.apply(Action.BUY) == 0       # 已封顶,无增量


def test_sell_decrements_capped():
    m = _mgr()
    assert m.apply(Action.SELL) == -25
    for _ in range(5):
        m.apply(Action.SELL)
    assert m.t_position == -100           # 下限
    assert m.apply(Action.SELL) == 0


def test_hold_no_change():
    m = _mgr()
    m.apply(Action.BUY)
    assert m.apply(Action.HOLD) == 0
    assert m.t_position == 25


def test_flatten():
    m = _mgr()
    m.apply(Action.BUY); m.apply(Action.BUY)   # t=50
    assert m.flatten() == -50
    assert m.t_position == 0