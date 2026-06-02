import math
from trading.backtest.pnl import PnLTracker


def test_long_add_then_close_profit():
    t = PnLTracker()
    t.fill(10, 100)          # 买10@100
    t.fill(10, 110)          # 加10@110 → 均价105
    assert math.isclose(t.avg_cost, 105)
    t.fill(-20, 120)         # 全平@120 → realized=20*(120-105)=300
    assert math.isclose(t.realized, 300)
    assert t.position == 0


def test_partial_close():
    t = PnLTracker()
    t.fill(10, 100)
    t.fill(-4, 110)          # 平4 → realized=4*(110-100)=40
    assert math.isclose(t.realized, 40)
    assert t.position == 6
    assert math.isclose(t.avg_cost, 100)   # 均价不变


def test_short_close_profit():
    t = PnLTracker()
    t.fill(-10, 110)         # 卖空10@110
    t.fill(10, 98)           # 买回@98 → realized=10*(110-98)=120
    assert math.isclose(t.realized, 120)
    assert t.position == 0


def test_flip_long_to_short():
    t = PnLTracker()
    t.fill(10, 100)          # 多10@100
    t.fill(-15, 120)         # 平10(realized=200)并反手空5@120
    assert math.isclose(t.realized, 200)
    assert t.position == -5
    assert math.isclose(t.avg_cost, 120)


def test_unrealized():
    t = PnLTracker()
    t.fill(10, 100)
    assert math.isclose(t.unrealized(105), 50)     # 多仓涨
    t2 = PnLTracker()
    t2.fill(-10, 100)
    assert math.isclose(t2.unrealized(95), 50)     # 空仓跌