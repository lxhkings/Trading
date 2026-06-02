from datetime import datetime, timezone, timedelta
from trading.trader.order_tracker import OrderTracker

T0 = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)


def test_timed_out_after_timeout():
    tr = OrderTracker(timeout_s=30)
    tr.track("1", "X", T0)
    assert tr.timed_out(T0 + timedelta(seconds=20)) == []
    assert tr.timed_out(T0 + timedelta(seconds=31)) == ["1"]


def test_complete_removes_pending():
    tr = OrderTracker(timeout_s=30)
    tr.track("1", "X", T0)
    tr.complete("1")
    assert tr.timed_out(T0 + timedelta(seconds=60)) == []