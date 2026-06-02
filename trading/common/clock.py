from __future__ import annotations
from datetime import datetime, time
from zoneinfo import ZoneInfo
from trading.common.models import Market

_HK_TZ = ZoneInfo("Asia/Hong_Kong")
_US_TZ = ZoneInfo("America/New_York")

_HK_SESSIONS = [(time(9, 30), time(12, 0)), (time(13, 0), time(16, 0))]
_US_SESSIONS = [(time(9, 30), time(16, 0))]


def _in_sessions(t: time, sessions) -> bool:
    return any(start <= t < end for start, end in sessions)


class MarketClock:
    def active_market(self, now: datetime) -> Market | None:
        """返回当前开盘市场,无则 None。now 必须 tz-aware。"""
        hk = now.astimezone(_HK_TZ)
        if hk.weekday() < 5 and _in_sessions(hk.time(), _HK_SESSIONS):
            return Market.HK
        us = now.astimezone(_US_TZ)
        if us.weekday() < 5 and _in_sessions(us.time(), _US_SESSIONS):
            return Market.US
        return None