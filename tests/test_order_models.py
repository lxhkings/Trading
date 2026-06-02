from datetime import datetime, timezone
from trading.common.models import Side, OrderType, Order, Fill


def test_order_fields():
    o = Order(symbol="HK.00700", side=Side.BUY, qty=25,
              order_type=OrderType.LMT, limit_price=100.5)
    assert o.side == Side.BUY
    assert o.order_type == OrderType.LMT
    assert o.limit_price == 100.5


def test_fill_fields():
    f = Fill(symbol="HK.00700", side=Side.SELL, qty=25, price=110.0,
             ts=datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc), order_id="7")
    assert f.side == Side.SELL
    assert f.qty == 25
    assert f.order_id == "7"