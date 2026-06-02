from __future__ import annotations


def recover_t_position(actual_total: float, base_qty: float) -> float:
    """从 IB 实际持仓减底仓反推 t_position。"""
    return actual_total - base_qty


def startup_check(*, feed_ok: bool, broker_ok: bool, redis_ok: bool) -> bool:
    """任一前置不通过则抛错,阻止进入交易态。"""
    if not feed_ok:
        raise RuntimeError("startup check failed: data feed not ready")
    if not broker_ok:
        raise RuntimeError("startup check failed: broker not connected")
    if not redis_ok:
        raise RuntimeError("startup check failed: redis not reachable")
    return True