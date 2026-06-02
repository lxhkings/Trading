from trading.brokers.fake_broker import FakeBroker
from trading.common.models import Order, Side, OrderType, Fill


def _order(side, qty, px):
    return Order("HK.00700", side, qty, OrderType.LMT, px)


def test_place_order_fills_and_updates_position():
    b = FakeBroker(positions={"HK.00700": 400})
    fills = []
    b.set_fill_handler(fills.append)
    oid = b.place_order(_order(Side.SELL, 25, 110))
    assert oid == "1"
    assert b.get_positions()["HK.00700"] == 375     # 400 - 25
    assert len(fills) == 1
    assert isinstance(fills[0], Fill)
    assert fills[0].price == 110


def test_buy_increases_position():
    b = FakeBroker(positions={"HK.00700": 400})
    b.place_order(_order(Side.BUY, 25, 98))
    assert b.get_positions()["HK.00700"] == 425


def test_cancel_recorded():
    b = FakeBroker()
    b.cancel("3")
    assert "3" in b.canceled


def test_no_immediate_fill_when_disabled():
    b = FakeBroker(fill_immediately=False)
    fills = []
    b.set_fill_handler(fills.append)
    b.place_order(_order(Side.BUY, 25, 98))
    assert fills == []
    assert len(b.orders) == 1