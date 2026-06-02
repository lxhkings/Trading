import fakeredis
from trading.common.state_store import StateStore


def test_save_and_load():
    r = fakeredis.FakeRedis(decode_responses=True)
    s = StateStore(r)
    s.save_t_position("HK.00700", -25.0)
    assert s.load_t_position("HK.00700") == -25.0


def test_load_missing_returns_zero():
    s = StateStore(fakeredis.FakeRedis(decode_responses=True))
    assert s.load_t_position("UNKNOWN") == 0.0


def test_all_positions():
    s = StateStore(fakeredis.FakeRedis(decode_responses=True))
    s.save_t_position("A", 25.0)
    s.save_t_position("B", -50.0)
    assert s.all_t_positions() == {"A": 25.0, "B": -50.0}