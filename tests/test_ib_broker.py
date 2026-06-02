from trading.common.symbolmap import SymbolSpec
from trading.common.models import Order, Side, OrderType, Market
from trading.brokers.ib_broker import build_contract, build_ib_order


def test_build_contract():
    spec = SymbolSpec("HK.00700", "HK.00700", "700", "SEHK", "HKD", Market.HK)
    c = build_contract(spec)
    assert c.symbol == "700"
    assert c.exchange == "SEHK"
    assert c.currency == "HKD"


def test_build_ib_order_limit_buy():
    o = Order("HK.00700", Side.BUY, 25, OrderType.LMT, 100.5)
    ib_o = build_ib_order(o)
    assert ib_o.action == "BUY"
    assert ib_o.totalQuantity == 25
    assert ib_o.orderType == "LMT"
    assert ib_o.lmtPrice == 100.5


def test_build_ib_order_market_sell():
    o = Order("HK.00700", Side.SELL, 25, OrderType.MKT)
    ib_o = build_ib_order(o)
    assert ib_o.action == "SELL"
    assert ib_o.orderType == "MKT"