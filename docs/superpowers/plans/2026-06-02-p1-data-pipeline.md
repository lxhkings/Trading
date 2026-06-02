# P1 数据管道 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通「富途 OpenD 1分钟 bar → 内部 Bar 模型 → Redis 广播 + parquet 落库」的数据管道,并提供富途连通/额度验证脚本。

**Architecture:** 端口-适配器。`DataFeed` 端口由 `FutuDataFeed` 适配富途 SDK 实现。bar 经统一 `Bar` 模型流转,`EventBus`(Redis pub/sub + stream)广播,`BarStore` 落 parquet。data 进程装配以上组件。富途行情解析与缺口检测抽为纯函数,可单测;SDK IO 靠验证脚本与端到端冒烟覆盖。

**Tech Stack:** Python 3.11+、futu-api、redis-py、pandas + pyarrow、pyyaml、zoneinfo(标准库)、pytest + fakeredis。

**前置依赖(本机)：**
- FutuOpenD 已登录运行(默认 `127.0.0.1:11111`)
- Redis 运行(`brew install redis && redis-server`,或 `docker run -p 6379:6379 redis`)—— 仅 Task 9 端到端冒烟需要;单测用 fakeredis,不需真 Redis

**关于 spec：** 对应 `docs/superpowers/specs/2026-06-02-hk-us-intraday-t-design.md` §4(模型/端口)、§5(数据流)、§8(自录/额度)。P1 不含策略/执行/风控(在 P2/P3)。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `pyproject.toml` | 包定义、依赖、pytest 可发现 `trading` 包 |
| `trading/__init__.py` 及各子包 `__init__.py` | 包标记 |
| `trading/common/models.py` | `Market` 枚举、`Bar` dataclass + JSON 序列化 |
| `trading/common/symbolmap.py` | `SymbolSpec`、`SymbolMap`(富途↔IB 映射,yaml 加载) |
| `trading/common/clock.py` | `MarketClock`(港/美时段判定,含港股午休) |
| `trading/common/eventbus.py` | `EventBus`(Redis pub/sub + stream 封装,P1 仅 publish) |
| `trading/common/ports.py` | `DataFeed` 抽象端口 |
| `trading/feeds/futu_feed.py` | `market_of`/`parse_kline_row`/`GapDetector` 纯函数 + `FutuDataFeed` 适配器 |
| `trading/storage/bar_store.py` | `BarStore`(按 市场/标的/日 分区落 parquet) |
| `trading/apps/data.py` | data 进程入口(装配) |
| `scripts/check_futu.py` | 手动:富途连通/额度/历史/订阅验证 |
| `config/symbols.yaml` | 标的映射配置 |
| `tests/...` | 各模块单测 |

---

## Task 0: 项目骨架与依赖

**Files:**
- Create: `pyproject.toml`
- Create: `trading/__init__.py`, `trading/common/__init__.py`, `trading/feeds/__init__.py`, `trading/storage/__init__.py`, `trading/apps/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "trading"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "futu-api>=9.0",
  "redis>=5.0",
  "pandas>=2.0",
  "pyarrow>=14.0",
  "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "fakeredis>=2.20"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["trading*"]
```

- [ ] **Step 2: 建包目录与空 __init__.py**

```bash
mkdir -p trading/common trading/feeds trading/storage trading/apps tests config scripts
touch trading/__init__.py trading/common/__init__.py trading/feeds/__init__.py \
      trading/storage/__init__.py trading/apps/__init__.py tests/__init__.py
```

- [ ] **Step 3: 建 venv 并安装(可编辑)**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
Expected: 安装成功,末尾 `Successfully installed ... trading-0.1.0 ...`

- [ ] **Step 4: 验证导入与 pytest 可运行**

Run:
```bash
python -c "import trading; print('ok')"
pytest -q
```
Expected: 打印 `ok`;pytest 输出 `no tests ran`(0 collected),退出码 5,正常。

- [ ] **Step 5: 写 .gitignore 并提交**

Create `.gitignore`:
```
.venv/
__pycache__/
*.pyc
data/
*.parquet
```

```bash
git add pyproject.toml .gitignore trading/ tests/
git commit -m "chore: scaffold trading package (P1 task 0)"
```

---

## Task 1: Bar 数据模型

**Files:**
- Create: `trading/common/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 写失败测试**

`tests/test_models.py`:
```python
from datetime import datetime, timezone
from trading.common.models import Bar, Market


def test_market_enum_values():
    assert Market.HK.value == "HK"
    assert Market.US.value == "US"


def test_bar_roundtrip_json():
    bar = Bar(
        symbol="HK.00700", market=Market.HK,
        ts=datetime(2026, 6, 2, 9, 31, tzinfo=timezone.utc),
        open=1.0, high=2.0, low=0.5, close=1.5,
        volume=1000, turnover=1500.0,
    )
    restored = Bar.from_json(bar.to_json())
    assert restored == bar
    assert isinstance(restored.market, Market)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_models.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'trading.common.models'`

- [ ] **Step 3: 实现 models.py**

`trading/common/models.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
import json


class Market(str, Enum):
    HK = "HK"
    US = "US"


@dataclass(frozen=True)
class Bar:
    symbol: str          # 内部代码,如 "HK.00700"
    market: Market
    ts: datetime         # tz-aware,bar 起始时间
    open: float
    high: float
    low: float
    close: float
    volume: int
    turnover: float

    def to_json(self) -> str:
        d = asdict(self)
        d["market"] = self.market.value
        d["ts"] = self.ts.isoformat()
        return json.dumps(d)

    @classmethod
    def from_json(cls, s: str) -> "Bar":
        d = json.loads(s)
        return cls(
            symbol=d["symbol"],
            market=Market(d["market"]),
            ts=datetime.fromisoformat(d["ts"]),
            open=d["open"], high=d["high"], low=d["low"],
            close=d["close"], volume=d["volume"], turnover=d["turnover"],
        )
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_models.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add trading/common/models.py tests/test_models.py
git commit -m "feat: Bar model with JSON serialization (P1 task 1)"
```

---

## Task 2: SymbolMap

**Files:**
- Create: `trading/common/symbolmap.py`
- Create: `config/symbols.yaml`
- Test: `tests/test_symbolmap.py`

- [ ] **Step 1: 写失败测试**

`tests/test_symbolmap.py`:
```python
from trading.common.symbolmap import SymbolMap, SymbolSpec
from trading.common.models import Market


def _specs():
    return [
        SymbolSpec("HK.00700", "HK.00700", "700", "SEHK", "HKD", Market.HK),
        SymbolSpec("US.AAPL", "US.AAPL", "AAPL", "SMART", "USD", Market.US),
    ]


def test_lookup_by_internal_and_futu():
    m = SymbolMap(_specs())
    assert m.by_internal("HK.00700").ib_symbol == "700"
    assert m.by_futu("US.AAPL").market == Market.US


def test_all_futu():
    m = SymbolMap(_specs())
    assert set(m.all_futu()) == {"HK.00700", "US.AAPL"}


def test_from_yaml(tmp_path):
    p = tmp_path / "symbols.yaml"
    p.write_text(
        "symbols:\n"
        "  - internal: HK.00700\n"
        "    futu: HK.00700\n"
        "    ib_symbol: '700'\n"
        "    ib_exchange: SEHK\n"
        "    ib_currency: HKD\n"
        "    market: HK\n"
    )
    m = SymbolMap.from_yaml(str(p))
    assert m.by_internal("HK.00700").ib_exchange == "SEHK"
    assert m.by_internal("HK.00700").market == Market.HK
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_symbolmap.py -v`
Expected: FAIL,`ModuleNotFoundError: ... symbolmap`

- [ ] **Step 3: 实现 symbolmap.py**

`trading/common/symbolmap.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from trading.common.models import Market


@dataclass(frozen=True)
class SymbolSpec:
    internal: str
    futu: str
    ib_symbol: str
    ib_exchange: str
    ib_currency: str
    market: Market


class SymbolMap:
    def __init__(self, specs: list[SymbolSpec]):
        self._by_internal = {s.internal: s for s in specs}
        self._by_futu = {s.futu: s for s in specs}

    def by_internal(self, code: str) -> SymbolSpec:
        return self._by_internal[code]

    def by_futu(self, code: str) -> SymbolSpec:
        return self._by_futu[code]

    def all_futu(self) -> list[str]:
        return list(self._by_futu.keys())

    @classmethod
    def from_yaml(cls, path: str) -> "SymbolMap":
        import yaml
        with open(path) as f:
            raw = yaml.safe_load(f)
        specs = [
            SymbolSpec(
                internal=e["internal"], futu=e["futu"],
                ib_symbol=str(e["ib_symbol"]), ib_exchange=e["ib_exchange"],
                ib_currency=e["ib_currency"], market=Market(e["market"]),
            )
            for e in raw["symbols"]
        ]
        return cls(specs)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_symbolmap.py -v`
Expected: 3 passed

- [ ] **Step 5: 写默认配置文件**

`config/symbols.yaml`(占位示例,实盘标的 P2 Scanner 筛选后替换):
```yaml
symbols:
  - internal: HK.00700
    futu: HK.00700
    ib_symbol: '700'
    ib_exchange: SEHK
    ib_currency: HKD
    market: HK
```

- [ ] **Step 6: 提交**

```bash
git add trading/common/symbolmap.py tests/test_symbolmap.py config/symbols.yaml
git commit -m "feat: SymbolMap futu/IB mapping with yaml loader (P1 task 2)"
```

---

## Task 3: MarketClock

**说明:** 仅判定常规交易时段,**不含节假日、半日市**(后续接交易日历)。港股含午休 12:00-13:00。

**Files:**
- Create: `trading/common/clock.py`
- Test: `tests/test_clock.py`

- [ ] **Step 1: 写失败测试**

`tests/test_clock.py`(注:2026-06-02 为周二工作日,2026-06-06 为周六):
```python
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.common.clock import MarketClock
from trading.common.models import Market

HK = ZoneInfo("Asia/Hong_Kong")
US = ZoneInfo("America/New_York")


def test_hk_morning_session():
    assert MarketClock().active_market(datetime(2026, 6, 2, 10, 0, tzinfo=HK)) == Market.HK


def test_hk_lunch_break_closed():
    assert MarketClock().active_market(datetime(2026, 6, 2, 12, 30, tzinfo=HK)) is None


def test_hk_afternoon_session():
    assert MarketClock().active_market(datetime(2026, 6, 2, 14, 0, tzinfo=HK)) == Market.HK


def test_us_session():
    assert MarketClock().active_market(datetime(2026, 6, 2, 10, 0, tzinfo=US)) == Market.US


def test_weekend_closed():
    assert MarketClock().active_market(datetime(2026, 6, 6, 10, 0, tzinfo=HK)) is None
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_clock.py -v`
Expected: FAIL,`ModuleNotFoundError: ... clock`

- [ ] **Step 3: 实现 clock.py**

`trading/common/clock.py`:
```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_clock.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add trading/common/clock.py tests/test_clock.py
git commit -m "feat: MarketClock HK/US session detection (P1 task 3)"
```

---

## Task 4: EventBus

**说明:** P1 data 进程是 publisher,只实现 `publish_bar`(pub/sub 实时 + stream 落日志)。订阅侧 `subscribe_bars` 留到 P3 trader(YAGNI)。

**Files:**
- Create: `trading/common/eventbus.py`
- Test: `tests/test_eventbus.py`

- [ ] **Step 1: 写失败测试**

`tests/test_eventbus.py`:
```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_eventbus.py -v`
Expected: FAIL,`ModuleNotFoundError: ... eventbus`

- [ ] **Step 3: 实现 eventbus.py**

`trading/common/eventbus.py`:
```python
from __future__ import annotations
import redis
from trading.common.models import Bar


class EventBus:
    """Redis pub/sub(实时广播)+ stream(回放日志)封装。"""

    def __init__(self, client: redis.Redis):
        self._r = client

    def publish_bar(self, bar: Bar) -> None:
        channel = f"bar.{bar.market.value}.{bar.symbol}"
        payload = bar.to_json()
        self._r.publish(channel, payload)
        self._r.xadd("stream.bars", {"data": payload})
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_eventbus.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add trading/common/eventbus.py tests/test_eventbus.py
git commit -m "feat: EventBus publish_bar via redis pub/sub + stream (P1 task 4)"
```

---

## Task 5: BarStore

**说明:** 按 `市场/标的/日期.parquet` 分区落库,去重(同 ts 保留最新)。每 bar 读写适合分钟级低频,不优化。

**Files:**
- Create: `trading/storage/bar_store.py`
- Test: `tests/test_bar_store.py`

- [ ] **Step 1: 写失败测试**

`tests/test_bar_store.py`:
```python
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.storage.bar_store import BarStore
from trading.common.models import Bar, Market

HK = ZoneInfo("Asia/Hong_Kong")


def _bar(minute, close):
    return Bar("HK.00700", Market.HK,
               datetime(2026, 6, 2, 9, minute, tzinfo=HK),
               close, close, close, close, 100, 100.0 * close)


def test_append_and_load(tmp_path):
    store = BarStore(str(tmp_path))
    store.append(_bar(31, 100.0))
    store.append(_bar(32, 101.0))
    df = store.load("HK", "HK.00700", "2026-06-02")
    assert len(df) == 2
    assert list(df["close"]) == [100.0, 101.0]


def test_append_dedup_same_ts(tmp_path):
    store = BarStore(str(tmp_path))
    store.append(_bar(31, 100.0))
    store.append(_bar(31, 999.0))  # same ts, newer value
    df = store.load("HK", "HK.00700", "2026-06-02")
    assert len(df) == 1
    assert df.iloc[0]["close"] == 999.0


def test_load_missing_returns_empty(tmp_path):
    df = BarStore(str(tmp_path)).load("HK", "HK.00700", "2026-06-02")
    assert df.empty
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_bar_store.py -v`
Expected: FAIL,`ModuleNotFoundError: ... bar_store`

- [ ] **Step 3: 实现 bar_store.py**

`trading/storage/bar_store.py`:
```python
from __future__ import annotations
from pathlib import Path
import pandas as pd
from trading.common.models import Bar


class BarStore:
    """按 市场/标的/日 分区落 parquet。"""

    def __init__(self, root: str):
        self.root = Path(root)

    def _day_str(self, bar: Bar) -> str:
        return bar.ts.strftime("%Y-%m-%d")

    def _path(self, market: str, symbol: str, day: str) -> Path:
        return self.root / market / symbol / f"{day}.parquet"

    def append(self, bar: Bar) -> None:
        p = self._path(bar.market.value, bar.symbol, self._day_str(bar))
        p.parent.mkdir(parents=True, exist_ok=True)
        row = pd.DataFrame([{
            "ts": bar.ts.isoformat(),
            "open": bar.open, "high": bar.high, "low": bar.low,
            "close": bar.close, "volume": bar.volume, "turnover": bar.turnover,
        }])
        if p.exists():
            df = pd.concat([pd.read_parquet(p), row], ignore_index=True)
            df = df.drop_duplicates(subset="ts", keep="last").reset_index(drop=True)
        else:
            df = row
        df.to_parquet(p, index=False)

    def load(self, market: str, symbol: str, day: str) -> pd.DataFrame:
        p = self._path(market, symbol, day)
        return pd.read_parquet(p) if p.exists() else pd.DataFrame()
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_bar_store.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add trading/storage/bar_store.py tests/test_bar_store.py
git commit -m "feat: BarStore parquet partitioned by market/symbol/day (P1 task 5)"
```

---

## Task 6: DataFeed 端口 + FutuDataFeed

**说明:** 行情解析(`market_of`、`parse_kline_row`)与缺口检测(`GapDetector`)为纯函数,单测覆盖。`FutuDataFeed` 的 connect/subscribe/history/quota 包装富途 SDK,IO 不单测,靠 Task 8 脚本与 Task 9 冒烟验证。

**缺口检测局限:** 跨午休、隔夜的正常间隔会被算作"缺口"。P1 仅记录分钟差用于观测,不作错误处理;按 session 过滤留到后续(需 MarketClock 联动)。

**Files:**
- Create: `trading/common/ports.py`
- Create: `trading/feeds/futu_feed.py`
- Test: `tests/test_futu_feed.py`

- [ ] **Step 1: 写失败测试(纯函数)**

`tests/test_futu_feed.py`:
```python
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.feeds.futu_feed import market_of, parse_kline_row, GapDetector
from trading.common.models import Market, Bar

HK = ZoneInfo("Asia/Hong_Kong")


def test_market_of():
    assert market_of("HK.00700") == Market.HK
    assert market_of("US.AAPL") == Market.US


def test_parse_kline_row():
    row = {"code": "HK.00700", "time_key": "2026-06-02 09:31:00",
           "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5,
           "volume": 1000, "turnover": 100500.0}
    bar = parse_kline_row(row)
    assert bar.symbol == "HK.00700"
    assert bar.market == Market.HK
    assert bar.ts == datetime(2026, 6, 2, 9, 31, tzinfo=HK)
    assert bar.close == 100.5
    assert bar.volume == 1000


def _b(minute):
    return Bar("HK.00700", Market.HK, datetime(2026, 6, 2, 9, minute, tzinfo=HK),
               1, 1, 1, 1, 1, 1.0)


def test_gap_detector():
    g = GapDetector()
    assert g.check(_b(31)) == 0   # first
    assert g.check(_b(32)) == 0   # consecutive
    assert g.check(_b(35)) == 2   # missing 33, 34
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_futu_feed.py -v`
Expected: FAIL,`ModuleNotFoundError: ... futu_feed`

- [ ] **Step 3: 实现 ports.py**

`trading/common/ports.py`:
```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable
from trading.common.models import Bar


class DataFeed(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def set_bar_handler(self, handler: Callable[[Bar], None]) -> None: ...

    @abstractmethod
    def subscribe(self, futu_symbols: list[str]) -> None: ...

    @abstractmethod
    def close(self) -> None: ...
```

- [ ] **Step 4: 实现 futu_feed.py**

`trading/feeds/futu_feed.py`:
```python
from __future__ import annotations
from typing import Callable
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.common.models import Bar, Market
from trading.common.ports import DataFeed

_TZ = {Market.HK: ZoneInfo("Asia/Hong_Kong"),
       Market.US: ZoneInfo("America/New_York")}


def market_of(futu_code: str) -> Market:
    return Market[futu_code.split(".")[0]]


def parse_kline_row(row: dict) -> Bar:
    market = market_of(row["code"])
    naive = datetime.strptime(row["time_key"], "%Y-%m-%d %H:%M:%S")
    ts = naive.replace(tzinfo=_TZ[market])
    return Bar(
        symbol=row["code"], market=market, ts=ts,
        open=float(row["open"]), high=float(row["high"]),
        low=float(row["low"]), close=float(row["close"]),
        volume=int(row["volume"]), turnover=float(row["turnover"]),
    )


class GapDetector:
    """返回相对上一个 bar 缺失的分钟数(0=连续或首个)。"""

    def __init__(self):
        self._last: dict[str, datetime] = {}

    def check(self, bar: Bar) -> int:
        last = self._last.get(bar.symbol)
        self._last[bar.symbol] = bar.ts
        if last is None:
            return 0
        delta = (bar.ts - last).total_seconds()
        return max(0, int(delta // 60) - 1) if delta > 60 else 0


class FutuDataFeed(DataFeed):
    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self._host, self._port = host, port
        self._ctx = None
        self._handler: Callable[[Bar], None] | None = None
        self._gaps = GapDetector()

    def connect(self) -> None:
        from futu import OpenQuoteContext
        self._ctx = OpenQuoteContext(host=self._host, port=self._port)

    def set_bar_handler(self, handler: Callable[[Bar], None]) -> None:
        self._handler = handler

    def subscribe(self, futu_symbols: list[str]) -> None:
        from futu import SubType, RET_OK, CurKlineHandlerBase
        feed = self

        class _Handler(CurKlineHandlerBase):
            def on_recv_rsp(self, rsp_pb):
                ret, data = super().on_recv_rsp(rsp_pb)
                if ret != RET_OK:
                    return ret, data
                for _, r in data.iterrows():
                    bar = parse_kline_row(r.to_dict())
                    feed._gaps.check(bar)
                    if feed._handler:
                        feed._handler(bar)
                return ret, data

        self._ctx.set_handler(_Handler())
        ret, msg = self._ctx.subscribe(futu_symbols, [SubType.K_1M])
        if ret != RET_OK:
            raise RuntimeError(f"futu subscribe failed: {msg}")

    def get_history_kline(self, futu_symbol: str, start=None, end=None):
        from futu import KLType, RET_OK
        import pandas as pd
        rows, page_key = [], None
        while True:
            ret, data, page_key = self._ctx.request_history_kline(
                futu_symbol, start=start, end=end,
                ktype=KLType.K_1M, max_count=1000, page_req_key=page_key)
            if ret != RET_OK:
                raise RuntimeError(f"history_kline failed: {data}")
            rows.append(data)
            if not page_key:
                break
        return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()

    def quota(self):
        from futu import RET_OK
        ret, data = self._ctx.get_history_kl_quota(get_detail=False)
        if ret != RET_OK:
            raise RuntimeError(f"quota failed: {data}")
        return data

    def close(self) -> None:
        if self._ctx:
            self._ctx.close()
```

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/test_futu_feed.py -v`
Expected: 3 passed

- [ ] **Step 6: 全量回归**

Run: `pytest -q`
Expected: 全部通过(此前各 Task 测试 + 本 Task)。

- [ ] **Step 7: 提交**

```bash
git add trading/common/ports.py trading/feeds/futu_feed.py tests/test_futu_feed.py
git commit -m "feat: DataFeed port + FutuDataFeed adapter (P1 task 6)"
```

---

## Task 7: data 进程装配

**说明:** 装配 FutuDataFeed → EventBus + BarStore。无单测(纯 IO 装配),由 Task 9 端到端冒烟验证。

**Files:**
- Create: `trading/apps/data.py`

- [ ] **Step 1: 实现 data.py**

`trading/apps/data.py`:
```python
from __future__ import annotations
import os
import time
import redis
from trading.common.eventbus import EventBus
from trading.common.symbolmap import SymbolMap
from trading.common.models import Bar
from trading.feeds.futu_feed import FutuDataFeed
from trading.storage.bar_store import BarStore


def main():
    symbols = SymbolMap.from_yaml(os.environ.get("SYMBOLS_YAML", "config/symbols.yaml"))
    r = redis.Redis(host=os.environ.get("REDIS_HOST", "127.0.0.1"),
                    port=int(os.environ.get("REDIS_PORT", "6379")),
                    decode_responses=True)
    bus = EventBus(r)
    store = BarStore(os.environ.get("BAR_ROOT", "data/bars"))
    feed = FutuDataFeed(host=os.environ.get("FUTU_HOST", "127.0.0.1"),
                        port=int(os.environ.get("FUTU_PORT", "11111")))

    def on_bar(bar: Bar):
        bus.publish_bar(bar)
        store.append(bar)
        print(f"[bar] {bar.symbol} {bar.ts.isoformat()} c={bar.close} v={bar.volume}")

    feed.connect()
    feed.set_bar_handler(on_bar)
    feed.subscribe(symbols.all_futu())
    print(f"data process running, subscribed {symbols.all_futu()}. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        feed.close()
        print("stopped.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 语法/导入自检**

Run: `python -c "import trading.apps.data; print('import ok')"`
Expected: 打印 `import ok`(不运行 main,仅验证可导入)

- [ ] **Step 3: 提交**

```bash
git add trading/apps/data.py
git commit -m "feat: data process wiring futu->eventbus+barstore (P1 task 7)"
```

---

## Task 8: 富途验证脚本(手动)

**说明:** 一次性脚本,验证富途连通、行情权限、历史额度、拉历史 1 分钟、实时订阅。需 FutuOpenD 运行。

**Files:**
- Create: `scripts/check_futu.py`

- [ ] **Step 1: 实现 check_futu.py**

`scripts/check_futu.py`:
```python
"""手动验证富途连通/额度/历史/订阅。
前置: FutuOpenD 已登录运行。
用法: python scripts/check_futu.py HK.00700
"""
import sys
from futu import OpenQuoteContext, KLType, SubType, RET_OK


def main(code: str):
    ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    try:
        ret, quota = ctx.get_history_kl_quota(get_detail=True)
        print("== 历史K线额度 ==")
        print(quota if ret == RET_OK else f"FAIL: {quota}")

        ret, data, _ = ctx.request_history_kline(code, ktype=KLType.K_1M, max_count=5)
        print(f"== {code} 历史1分钟(前5) ==")
        print(data if ret == RET_OK else f"FAIL: {data}")

        ret, msg = ctx.subscribe([code], [SubType.K_1M])
        print("== 订阅1分钟 ==")
        print("OK" if ret == RET_OK else f"FAIL: {msg}")
        if ret == RET_OK:
            ret, cur = ctx.get_cur_kline(code, 3, KLType.K_1M)
            print(f"== {code} 当前1分钟(后3) ==")
            print(cur if ret == RET_OK else f"FAIL: {cur}")
    finally:
        ctx.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "HK.00700")
```

- [ ] **Step 2: 运行验证(港股时段,FutuOpenD 在线)**

Run: `python scripts/check_futu.py HK.00700`
Expected:
- 「历史K线额度」打印剩余额度数字(确认 >0)
- 「历史1分钟」打印 5 行 K 线 DataFrame(含 time_key/open/high/low/close/volume/turnover)
- 「订阅1分钟」打印 `OK`
- 「当前1分钟」打印最近 3 根(港股时段内有当日数据)

若任一 `FAIL`:记录错误信息。常见:行情权限不足(订阅失败)→ 查富途账户港股行情权限;额度为 0 → 等 30 天释放或减少历史拉取标的数。

- [ ] **Step 3: 提交**

```bash
git add scripts/check_futu.py
git commit -m "chore: futu connectivity/quota verification script (P1 task 8)"
```

---

## Task 9: 端到端冒烟(手动,港股时段)

**说明:** 启动 Redis + data 进程,确认实时 bar 流入 Redis 与 parquet。需港股开盘时段(09:30-12:00 / 13:00-16:00 HKT)+ FutuOpenD 在线。

- [ ] **Step 1: 启动 Redis**

Run(任选): `redis-server` 或 `docker run -d -p 6379:6379 redis`
验证: `redis-cli ping` → Expected: `PONG`

- [ ] **Step 2: 启动 data 进程**

Run:
```bash
source .venv/bin/activate
python -m trading.apps.data
```
Expected: 打印 `data process running, subscribed ['HK.00700']...`,随后每分钟 bar 闭合打印一行 `[bar] HK.00700 2026-... c=... v=...`

- [ ] **Step 3: 验证 Redis 收到(另开终端)**

Run: `redis-cli XLEN stream.bars`
Expected: 随时间增长的整数(>0)

Run 实时广播验证: `redis-cli PSUBSCRIBE 'bar.*'`
Expected: 每分钟收到一条 `pmessage`,channel 形如 `bar.HK.HK.00700`,payload 是 Bar JSON

- [ ] **Step 4: 验证 parquet 落库**

Run:
```bash
python -c "from trading.storage.bar_store import BarStore; import datetime; \
print(BarStore('data/bars').load('HK','HK.00700',datetime.date.today().isoformat()))"
```
Expected: 打印当日已收 bar 的 DataFrame(行数 = 已闭合分钟数)

- [ ] **Step 5: 停止并记录**

Ctrl-C 停止 data 进程(应打印 `stopped.`)。记录冒烟结果(收到 bar 数、有无缺口告警、parquet 行数)。

**P1 完成判定:** Task 1-6 单测全绿 + Task 8 脚本验证富途数据可得(含额度>0)+ Task 9 实时 bar 端到端落 Redis 与 parquet。

---

## Self-Review

**1. Spec 覆盖(P1 范围):**
- §4 模型/端口 → Task 1(Bar)、Task 6(DataFeed 端口)✓
- §4 FutuDataFeed/EventBus/SymbolMap/MarketClock → Task 6/4/2/3 ✓
- §4 BarStore 自录 → Task 5 ✓
- §5 数据流(futu→bar→Redis→落库)→ Task 7 装配 + Task 9 冒烟 ✓
- §8 额度自检 + 8年历史验证 → Task 8 脚本(quota + history_kline)✓
- §13.1 数据管道验证里程碑 → Task 8/9 ✓
- 不在 P1:策略/网格/风控/IBBroker/Scanner/回测 → P2/P3,正确不覆盖

**2. 占位符扫描:** 无 TBD/TODO;每 code step 含完整代码;每验证 step 含命令+预期输出。✓

**3. 类型一致性:**
- `Bar` 字段(symbol/market/ts/open/high/low/close/volume/turnover)在 models/eventbus/bar_store/futu_feed 一致 ✓
- `Market` 枚举值 "HK"/"US" 全程一致;`market_of` 用 `Market[prefix]` 按名取,前缀 "HK"/"US" 与枚举名一致 ✓
- `EventBus.publish_bar`、`BarStore.append/load`、`FutuDataFeed.connect/set_bar_handler/subscribe/close` 在 Task 7 装配中调用名一致 ✓
- `parse_kline_row` 输入字段(code/time_key/open/high/low/close/volume/turnover)与 Task 8 脚本拉取的富途 DataFrame 列名一致 ✓

无遗留问题。
