import fakeredis
from datetime import datetime, timezone
from trading.common.eventbus import EventBus
from trading.common.models import Bar, Market


def _bar():
    return Bar("HK.00700", Market.HK,
               datetime(2026, 6, 2, 9, 31, tzinfo=timezone.utc),
               1.0, 2.0, 0.5, 1.5, 1000, 1500.0)


def test_handle_message_decodes_bar():
    got = []
    msg = {"type": "pmessage", "channel": "bar.HK.HK.00700", "data": _bar().to_json()}
    EventBus._handle_message(msg, got.append)
    assert got == [_bar()]


def test_handle_message_ignores_non_pmessage():
    got = []
    EventBus._handle_message({"type": "subscribe", "data": 1}, got.append)
    assert got == []


def test_publish_event_writes_stream():
    r = fakeredis.FakeRedis(decode_responses=True)
    EventBus(r).publish_event("fill.HK.00700", {"qty": 25, "price": 110})
    entries = r.xrange("stream.fill")
    assert len(entries) == 1