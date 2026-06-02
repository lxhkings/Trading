from trading.trader.recovery import recover_t_position, startup_check


def test_recover_t_position():
    assert recover_t_position(actual_total=375, base_qty=400) == -25
    assert recover_t_position(actual_total=425, base_qty=400) == 25
    assert recover_t_position(actual_total=400, base_qty=400) == 0


def test_startup_check_all_ok():
    assert startup_check(feed_ok=True, broker_ok=True, redis_ok=True) is True


def test_startup_check_fails():
    import pytest
    with pytest.raises(RuntimeError, match="broker"):
        startup_check(feed_ok=True, broker_ok=False, redis_ok=True)