import fakeredis
from datetime import datetime, timezone
from trading.common.eventbus import EventBus
from trading.common.models import Bar, Market


def _bar():
    return Bar("HK.00700", Market.HK,
               datetime(2026, 6, 2, 9, 31, tzinfo=timezone.utc),
               1.0, 2.0, 0.5, 1.5, 1000, 1500.0)


def test_publish_writes_stream():
    r = fakeredis.FakeRedis(decode_responses=True)
    EventBus(r).publish_bar(_bar())
    entries = r.xrange("stream.bars")
    assert len(entries) == 1
    _, fields = entries[0]
    assert Bar.from_json(fields["data"]) == _bar()


def test_publish_pubsub_broadcast():
    r = fakeredis.FakeRedis(decode_responses=True)
    ps = r.pubsub()
    ps.psubscribe("bar.*")
    ps.get_message(timeout=1)  # consume subscribe confirmation
    EventBus(r).publish_bar(_bar())
    received = None
    for _ in range(10):
        msg = ps.get_message(timeout=1)
        if msg and msg["type"] == "pmessage":
            received = msg
            break
    assert received is not None
    assert received["channel"] == "bar.HK.HK.00700"
    assert Bar.from_json(received["data"]) == _bar()