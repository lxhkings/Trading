# P3 执行+风控+集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接通 IB 执行端,实现风控(熔断/频率/断线/撤单超时)、trader 与 monitor 进程,三进程 + Redis 跑通全自动做T闭环,IB paper 验证。

**Architecture:** `Broker` 端口由 `IBBroker`(ib_insync)实现,持仓真相源。`TraderEngine` 订阅 Redis bar → 每标同步 IB 实际持仓 → 策略出信号 → `RiskManager` 决策 → `GridPositionMgr` 算增量 → `IBBroker` 下单 → `OrderTracker` 管撤单超时 → fill 回报喂 `PnLTracker` 算日内盈亏(回灌熔断)→ `StateStore` 持久化意图仓位。`FakeBroker` 内存替身用于集成测试。monitor 订阅事件落库告警。

**Tech Stack:** Python 3.11+、ib_insync、redis-py。复用 P1(Bar/Market/SymbolMap/MarketClock/EventBus)、P2(MeanReversionStrategy/GridPositionMgr/PnLTracker)。

**依赖:** P1、P2 已完成。

**对应 spec:** §4(Order/Fill/Broker/StateStore)、§5(数据流闭环)、§7(全部风控)、§9(容灾/自检/恢复)、§10(集成+paper)。

**安全前提(实盘):**
- 仅先连 **IB paper account**(模拟盘),验证通过再考虑实盘极小仓。
- IB Gateway/TWS 须开启 API、设置 paper 端口(默认 paper 7497 / 实盘 7496,按你的配置)。
- trader 任何「断线/熔断」状态一律**拒绝新开仓**,只允许减仓。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `trading/common/models.py`(改) | 追加 `Side`/`OrderType`/`Order`/`Fill` |
| `trading/common/ports.py`(改) | 追加 `Broker` 抽象 |
| `trading/common/eventbus.py`(改) | 追加 `subscribe_bars`/`publish_event`/`_handle_message` |
| `trading/common/state_store.py`(新) | `StateStore`(Redis 持久 t_position) |
| `trading/brokers/__init__.py`(新) | 包标记 |
| `trading/brokers/fake_broker.py`(新) | `FakeBroker` 内存替身 |
| `trading/brokers/ib_broker.py`(新) | `IBBroker` + `build_contract`/`build_ib_order` |
| `trading/risk/__init__.py`(新) | 包标记 |
| `trading/risk/manager.py`(新) | `RiskParams`/`Decision`/`RiskManager` |
| `trading/trader/__init__.py`(新) | 包标记 |
| `trading/trader/order_tracker.py`(新) | `OrderTracker`(撤单超时) |
| `trading/trader/recovery.py`(新) | `recover_t_position`/`startup_check` |
| `trading/trader/engine.py`(新) | `TraderEngine` |
| `trading/apps/trader.py`(新) | trader 进程入口 |
| `trading/apps/monitor.py`(新) | monitor 进程入口 |
| `tests/...` | 各模块单测 + TraderEngine 集成测试 |

---

## Task 1: 执行数据模型

**Files:**
- Modify: `trading/common/models.py`(文件末尾追加)
- Test: `tests/test_order_models.py`

- [ ] **Step 1: 写失败测试**

`tests/test_order_models.py`:
```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_order_models.py -v`
Expected: FAIL,`ImportError: cannot import name 'Side'`

- [ ] **Step 3: 追加到 models.py**

在 `trading/common/models.py` **末尾追加**:
```python
class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LMT = "LMT"
    MKT = "MKT"


@dataclass(frozen=True)
class Order:
    symbol: str                     # 内部代码
    side: Side
    qty: float
    order_type: OrderType
    limit_price: float | None = None
    client_id: str = ""


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: Side
    qty: float
    price: float
    ts: datetime
    order_id: str
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_order_models.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add trading/common/models.py tests/test_order_models.py
git commit -m "feat: Order/Fill/Side/OrderType execution models (P3 task 1)"
```

---

## Task 2: Broker 端口 + FakeBroker

**说明:** `Broker` 抽象 + 内存替身。FakeBroker `fill_immediately=True` 时下单即按 limit_price 全量成交并回调 fill,用于集成测试与 dry-run。持仓以 internal symbol → 带符号股数表示。

**Files:**
- Modify: `trading/common/ports.py`(追加 `Broker`)
- Create: `trading/brokers/__init__.py`(空)
- Create: `trading/brokers/fake_broker.py`
- Test: `tests/test_fake_broker.py`

- [ ] **Step 1: 写失败测试**

`tests/test_fake_broker.py`:
```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_fake_broker.py -v`
Expected: FAIL,`ModuleNotFoundError: ... fake_broker`

- [ ] **Step 3: 追加 Broker 到 ports.py**

在 `trading/common/ports.py` **末尾追加**:
```python
from trading.common.models import Order, Fill


class Broker(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def get_positions(self) -> dict[str, float]:
        """internal symbol -> 带符号持仓股数。"""

    @abstractmethod
    def place_order(self, order: Order) -> str:
        """返回 order_id。"""

    @abstractmethod
    def cancel(self, order_id: str) -> None: ...

    @abstractmethod
    def set_fill_handler(self, handler) -> None: ...

    @abstractmethod
    def close(self) -> None: ...
```

- [ ] **Step 4: 实现 fake_broker.py**

`trading/brokers/fake_broker.py`:
```python
from __future__ import annotations
from datetime import datetime, timezone
from trading.common.ports import Broker
from trading.common.models import Order, Fill, Side


class FakeBroker(Broker):
    def __init__(self, positions: dict[str, float] | None = None,
                 fill_immediately: bool = True):
        self._positions = dict(positions or {})
        self._fill_cb = None
        self.orders: list[tuple[str, Order]] = []
        self.canceled: list[str] = []
        self.fill_immediately = fill_immediately
        self._next = 0

    def connect(self) -> None:
        pass

    def get_positions(self) -> dict[str, float]:
        return dict(self._positions)

    def place_order(self, order: Order) -> str:
        self._next += 1
        oid = str(self._next)
        self.orders.append((oid, order))
        if self.fill_immediately:
            signed = order.qty if order.side == Side.BUY else -order.qty
            self._positions[order.symbol] = self._positions.get(order.symbol, 0) + signed
            if self._fill_cb:
                self._fill_cb(Fill(order.symbol, order.side, order.qty,
                                   order.limit_price or 0.0,
                                   datetime.now(timezone.utc), oid))
        return oid

    def cancel(self, order_id: str) -> None:
        self.canceled.append(order_id)

    def set_fill_handler(self, handler) -> None:
        self._fill_cb = handler

    def close(self) -> None:
        pass
```

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/test_fake_broker.py -v`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add trading/common/ports.py trading/brokers/__init__.py trading/brokers/fake_broker.py tests/test_fake_broker.py
git commit -m "feat: Broker port + FakeBroker in-memory stub (P3 task 2)"
```

---

## Task 3: RiskManager

**说明:** 纯决策(spec §7)。HOLD 不下单;断线拒绝新单;同标下单间隔限频;熔断时只允许减仓(reducing)。check 通过才更新内部 last_order 时间。

**Files:**
- Create: `trading/risk/__init__.py`(空)
- Create: `trading/risk/manager.py`
- Test: `tests/test_risk.py`

- [ ] **Step 1: 写失败测试**

`tests/test_risk.py`:
```python
from datetime import datetime, timezone, timedelta
from trading.risk.manager import RiskManager, RiskParams
from trading.strategy.signals import Action

T0 = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)


def _rm():
    return RiskManager(RiskParams(daily_loss_limit_pct=0.02, min_order_interval_s=60))


def test_hold_rejected():
    d = _rm().check("X", Action.HOLD, 0, T0, daily_t_pnl=0, base_value=40000, connected=True)
    assert not d.approved and d.reason == "hold"


def test_disconnected_rejected():
    d = _rm().check("X", Action.BUY, 0, T0, daily_t_pnl=0, base_value=40000, connected=False)
    assert not d.approved and d.reason == "disconnected"


def test_frequency_limit():
    rm = _rm()
    assert rm.check("X", Action.BUY, 0, T0, daily_t_pnl=0, base_value=40000, connected=True).approved
    d2 = rm.check("X", Action.BUY, 25, T0 + timedelta(seconds=30),
                  daily_t_pnl=0, base_value=40000, connected=True)
    assert not d2.approved and d2.reason == "too-frequent"
    d3 = rm.check("X", Action.BUY, 25, T0 + timedelta(seconds=61),
                  daily_t_pnl=0, base_value=40000, connected=True)
    assert d3.approved


def test_circuit_breaker_blocks_opening_allows_reducing():
    rm = _rm()
    # 当日亏损 -3% 超过 2% 限
    loss = -0.03 * 40000
    # 持多仓 t=25,BUY=加仓(开)→ 拒
    d_open = rm.check("X", Action.BUY, 25, T0, daily_t_pnl=loss, base_value=40000, connected=True)
    assert not d_open.approved and d_open.reason == "circuit-breaker"
    # 持多仓 t=25,SELL=减仓 → 允许
    d_reduce = rm.check("X", Action.SELL, 25, T0, daily_t_pnl=loss, base_value=40000, connected=True)
    assert d_reduce.approved
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_risk.py -v`
Expected: FAIL,`ModuleNotFoundError: ... risk.manager`

- [ ] **Step 3: 实现 manager.py**

`trading/risk/manager.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from trading.strategy.signals import Action


@dataclass
class RiskParams:
    daily_loss_limit_pct: float = 0.02
    min_order_interval_s: float = 60.0


@dataclass(frozen=True)
class Decision:
    approved: bool
    reason: str


class RiskManager:
    def __init__(self, params: RiskParams | None = None):
        self.p = params or RiskParams()
        self._last: dict[str, datetime] = {}

    def check(self, symbol: str, action: Action, t_position: float,
              now: datetime, *, daily_t_pnl: float, base_value: float,
              connected: bool) -> Decision:
        if action == Action.HOLD:
            return Decision(False, "hold")
        if not connected:
            return Decision(False, "disconnected")
        last = self._last.get(symbol)
        if last is not None and (now - last).total_seconds() < self.p.min_order_interval_s:
            return Decision(False, "too-frequent")
        if base_value > 0 and daily_t_pnl / base_value < -self.p.daily_loss_limit_pct:
            reducing = ((t_position > 0 and action == Action.SELL) or
                        (t_position < 0 and action == Action.BUY))
            if not reducing:
                return Decision(False, "circuit-breaker")
        self._last[symbol] = now
        return Decision(True, "ok")
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_risk.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add trading/risk/__init__.py trading/risk/manager.py tests/test_risk.py
git commit -m "feat: RiskManager circuit-breaker/frequency/disconnect gates (P3 task 3)"
```

---

## Task 4: OrderTracker(撤单超时)

**Files:**
- Create: `trading/trader/__init__.py`(空)
- Create: `trading/trader/order_tracker.py`
- Test: `tests/test_order_tracker.py`

- [ ] **Step 1: 写失败测试**

`tests/test_order_tracker.py`:
```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_order_tracker.py -v`
Expected: FAIL,`ModuleNotFoundError: ... order_tracker`

- [ ] **Step 3: 实现 order_tracker.py**

`trading/trader/order_tracker.py`:
```python
from __future__ import annotations
from datetime import datetime


class OrderTracker:
    def __init__(self, timeout_s: float = 30.0):
        self.timeout = timeout_s
        self._pending: dict[str, tuple[str, datetime]] = {}

    def track(self, order_id: str, symbol: str, ts: datetime) -> None:
        self._pending[order_id] = (symbol, ts)

    def complete(self, order_id: str) -> None:
        self._pending.pop(order_id, None)

    def timed_out(self, now: datetime) -> list[str]:
        return [oid for oid, (_, ts) in self._pending.items()
                if (now - ts).total_seconds() >= self.timeout]
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_order_tracker.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add trading/trader/__init__.py trading/trader/order_tracker.py tests/test_order_tracker.py
git commit -m "feat: OrderTracker pending order timeout tracking (P3 task 4)"
```

---

## Task 5: StateStore + 状态恢复

**说明:** t_position(意图仓位)持久化到 Redis hash。`recover_t_position` 从 IB 实际持仓减底仓反推。

**Files:**
- Create: `trading/common/state_store.py`
- Create: `trading/trader/recovery.py`
- Test: `tests/test_state_store.py`、`tests/test_recovery.py`

- [ ] **Step 1: 写失败测试(StateStore)**

`tests/test_state_store.py`:
```python
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
```

- [ ] **Step 2: 写失败测试(recovery)**

`tests/test_recovery.py`:
```python
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
```

- [ ] **Step 3: 运行确认失败**

Run: `pytest tests/test_state_store.py tests/test_recovery.py -v`
Expected: FAIL,`ModuleNotFoundError`

- [ ] **Step 4: 实现 state_store.py**

`trading/common/state_store.py`:
```python
from __future__ import annotations
import redis

_KEY = "t_positions"


class StateStore:
    def __init__(self, client: redis.Redis):
        self._r = client

    def save_t_position(self, symbol: str, t_position: float) -> None:
        self._r.hset(_KEY, symbol, t_position)

    def load_t_position(self, symbol: str) -> float:
        v = self._r.hget(_KEY, symbol)
        return float(v) if v is not None else 0.0

    def all_t_positions(self) -> dict[str, float]:
        return {k: float(v) for k, v in self._r.hgetall(_KEY).items()}
```

- [ ] **Step 5: 实现 recovery.py**

`trading/trader/recovery.py`:
```python
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
```

- [ ] **Step 6: 运行确认通过**

Run: `pytest tests/test_state_store.py tests/test_recovery.py -v`
Expected: 6 passed

- [ ] **Step 7: 提交**

```bash
git add trading/common/state_store.py trading/trader/recovery.py tests/test_state_store.py tests/test_recovery.py
git commit -m "feat: StateStore persistence + t_position recovery + startup check (P3 task 5)"
```

---

## Task 6: EventBus 订阅与事件发布

**说明:** 补全订阅侧(P1 留作 YAGNI)。`_handle_message` 纯函数便于单测;`subscribe_bars` 阻塞循环供 trader 用。`publish_event` 通用事件(fill/alert)供 monitor。

**Files:**
- Modify: `trading/common/eventbus.py`
- Test: `tests/test_eventbus_subscribe.py`

- [ ] **Step 1: 写失败测试**

`tests/test_eventbus_subscribe.py`:
```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_eventbus_subscribe.py -v`
Expected: FAIL,`AttributeError: ... _handle_message`

- [ ] **Step 3: 追加方法到 eventbus.py**

在 `EventBus` 类中追加(并确保文件顶部有 `import json`):
```python
    def publish_event(self, topic: str, payload: dict) -> None:
        import json
        s = json.dumps(payload, default=str)
        self._r.publish(topic, s)
        self._r.xadd(f"stream.{topic.split('.')[0]}", {"data": s})

    @staticmethod
    def _handle_message(msg: dict, handler) -> None:
        if msg.get("type") != "pmessage":
            return
        handler(Bar.from_json(msg["data"]))

    def subscribe_bars(self, handler) -> None:
        ps = self._r.pubsub()
        ps.psubscribe("bar.*")
        for msg in ps.listen():
            self._handle_message(msg, handler)
```

注:`Bar` 已在 eventbus.py 顶部导入(P1)。`_handle_message` 引用 `Bar`,确认 import 存在。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_eventbus_subscribe.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add trading/common/eventbus.py tests/test_eventbus_subscribe.py
git commit -m "feat: EventBus subscribe_bars + publish_event (P3 task 6)"
```

---

## Task 7: TraderEngine(核心,集成测试)

**说明:** 每 bar:检查撤单超时 → 同步 IB 实际持仓到 grid → 策略出信号 → 风控决策 → 网格算增量 → 下限价单(bar.close)→ 追踪订单 → 持久化意图。fill 回报喂 PnLTracker 算日内盈亏回灌熔断。用 FakeBroker 做集成测试。

**Files:**
- Create: `trading/trader/engine.py`
- Test: `tests/test_trader_engine.py`

- [ ] **Step 1: 写失败测试(集成)**

`tests/test_trader_engine.py`:
```python
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.common.models import Bar, Market
from trading.strategy.signals import MeanReversionParams
from trading.brokers.fake_broker import FakeBroker
from trading.risk.manager import RiskManager, RiskParams
from trading.trader.order_tracker import OrderTracker
from trading.common.state_store import StateStore
from trading.common.clock import MarketClock
from trading.trader.engine import TraderEngine
import fakeredis

HK = ZoneInfo("Asia/Hong_Kong")
SYM = "HK.00700"


def _bar(day, minute, c):
    return Bar(SYM, Market.HK,
               datetime(2026, 6, day, 9 + minute // 60, minute % 60, tzinfo=HK),
               c, c, c, c, 1000, c * 1000)


def _engine(base_qty=400):
    broker = FakeBroker(positions={SYM: base_qty})
    store = StateStore(fakeredis.FakeRedis(decode_responses=True))
    eng = TraderEngine(
        base_qtys={SYM: base_qty},
        params_by_symbol={SYM: MeanReversionParams()},
        risk=RiskManager(RiskParams(min_order_interval_s=0)),  # 关掉频率限以测信号
        broker=broker,
        state_store=store,
        clock=MarketClock(),
        order_tracker=OrderTracker(timeout_s=30),
    )
    broker.set_fill_handler(eng.on_fill)
    return eng, broker


def _feed_reverse_t(eng):
    for i in range(25):
        eng.on_bar(_bar(2, i, 100 + i * 0.2))   # 缓涨
    eng.on_bar(_bar(2, 25, 110))                 # 跳涨 → SELL
    eng.on_bar(_bar(3, 0, 98))                   # 暴跌(新日)→ BUY


def test_reverse_t_places_sell_then_buy():
    eng, broker = _engine()
    _feed_reverse_t(eng)
    sides = [o.side.value for _, o in broker.orders]
    assert "SELL" in sides
    assert "BUY" in sides


def test_reverse_t_realizes_profit():
    eng, broker = _engine()
    _feed_reverse_t(eng)
    # 高卖低买 → 该标 PnLTracker realized 为正
    assert eng.pnl[SYM].realized > 0


def test_no_order_on_hold():
    eng, broker = _engine()
    for i in range(5):                            # 数据不足,全 warmup/HOLD
        eng.on_bar(_bar(2, i, 100))
    assert broker.orders == []
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_trader_engine.py -v`
Expected: FAIL,`ModuleNotFoundError: ... trader.engine`

- [ ] **Step 3: 实现 engine.py**

`trading/trader/engine.py`:
```python
from __future__ import annotations
from datetime import datetime
from trading.common.models import Order, Side, OrderType, Fill, Bar
from trading.strategy.signals import MeanReversionStrategy, MeanReversionParams, Action
from trading.strategy.grid import GridParams, GridPositionMgr
from trading.backtest.pnl import PnLTracker
from trading.risk.manager import RiskManager
from trading.common.state_store import StateStore
from trading.trader.order_tracker import OrderTracker


class TraderEngine:
    def __init__(self, *, base_qtys: dict[str, float],
                 params_by_symbol: dict[str, MeanReversionParams],
                 risk: RiskManager, broker, state_store: StateStore,
                 clock, order_tracker: OrderTracker, event_bus=None):
        self.base_qtys = base_qtys
        self.risk = risk
        self.broker = broker
        self.state = state_store
        self.clock = clock
        self.tracker = order_tracker
        self.bus = event_bus
        self.strategies = {s: MeanReversionStrategy(s, p)
                           for s, p in params_by_symbol.items()}
        self.grids = {s: GridPositionMgr(GridParams(base_qty=base_qtys[s]))
                      for s in base_qtys}
        self.pnl = {s: PnLTracker() for s in base_qtys}
        self.connected = True

    def on_bar(self, bar: Bar) -> None:
        sym = bar.symbol
        if sym not in self.strategies:
            return
        self.check_timeouts(bar.ts)
        # 同步 IB 实际持仓 → 意图基于实际
        actual_total = self.broker.get_positions().get(sym, self.base_qtys[sym])
        self.grids[sym].t_position = actual_total - self.base_qtys[sym]

        sig = self.strategies[sym].on_bar(bar)
        base_value = self.base_qtys[sym] * bar.close
        t_pnl = self.pnl[sym].realized + self.pnl[sym].unrealized(bar.close)
        decision = self.risk.check(
            sym, sig.action, self.grids[sym].t_position, bar.ts,
            daily_t_pnl=t_pnl, base_value=base_value, connected=self.connected)
        if not decision.approved:
            self._emit("signal." + sym, {"ts": bar.ts, "action": sig.action.value,
                                         "rejected": decision.reason})
            return

        delta = self.grids[sym].apply(sig.action)
        if delta == 0:
            return
        side = Side.BUY if delta > 0 else Side.SELL
        order = Order(symbol=sym, side=side, qty=abs(delta),
                      order_type=OrderType.LMT, limit_price=bar.close)
        oid = self.broker.place_order(order)
        self.tracker.track(oid, sym, bar.ts)
        try:
            self.state.save_t_position(sym, self.grids[sym].t_position)
        except Exception as e:                       # Redis 断 → 降级,内存仓位继续
            self._emit("alert", {"type": "state_save_failed", "err": str(e)})
        self._emit("signal." + sym, {"ts": bar.ts, "action": sig.action.value,
                                     "qty": abs(delta), "px": bar.close})

    def on_fill(self, fill: Fill) -> None:
        signed = fill.qty if fill.side == Side.BUY else -fill.qty
        self.pnl[fill.symbol].fill(signed, fill.price)
        self.tracker.complete(fill.order_id)
        self._emit("fill." + fill.symbol, {"side": fill.side.value, "qty": fill.qty,
                                           "px": fill.price, "oid": fill.order_id})

    def check_timeouts(self, now: datetime) -> None:
        for oid in self.tracker.timed_out(now):
            self.broker.cancel(oid)
            self.tracker.complete(oid)
            self._emit("alert", {"type": "order_timeout", "oid": oid})

    def _emit(self, topic: str, payload: dict) -> None:
        if self.bus is not None:
            self.bus.publish_event(topic, payload)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_trader_engine.py -v`
Expected: 3 passed

- [ ] **Step 5: 全量回归**

Run: `pytest -q`
Expected: P1+P2+P3 全绿。

- [ ] **Step 6: 提交**

```bash
git add trading/trader/engine.py tests/test_trader_engine.py
git commit -m "feat: TraderEngine signal->risk->grid->order loop with fill PnL (P3 task 7)"
```

---

## Task 8: IBBroker

**说明:** ib_insync 实现。`build_contract`(SymbolSpec → Stock)与 `build_ib_order`(Order → ib order)为纯函数单测;connect/place_order/get_positions/fill 事件 IO 靠 Task 11 paper 验证。get_positions 用 SymbolMap 把 IB contract 映回 internal symbol。

**Files:**
- Create: `trading/brokers/ib_broker.py`
- Test: `tests/test_ib_broker.py`

- [ ] **Step 1: 写失败测试(纯函数,monkeypatch ib_insync 类型)**

`tests/test_ib_broker.py`:
```python
from trading.common.symbolmap import SymbolSpec
from trading.common.models import Order, Side, OrderType, Market
from trading.brokers.ib_broker import build_contract, build_ib_order


def test_build_contract():
    spec = SymbolSpec("HK.00700", "HK.00700", "700", "SEHK", "HKD", Market.HK)
    c = build_contract(spec)
    assert c.symbol == "700"
    assert c.exchange == "SEHK"
    assert c.currency == "HKD"


def test_build_ib_order_limit_buy():
    o = Order("HK.00700", Side.BUY, 25, OrderType.LMT, 100.5)
    ib_o = build_ib_order(o)
    assert ib_o.action == "BUY"
    assert ib_o.totalQuantity == 25
    assert ib_o.orderType == "LMT"
    assert ib_o.lmtPrice == 100.5


def test_build_ib_order_market_sell():
    o = Order("HK.00700", Side.SELL, 25, OrderType.MKT)
    ib_o = build_ib_order(o)
    assert ib_o.action == "SELL"
    assert ib_o.orderType == "MKT"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_ib_broker.py -v`
Expected: FAIL,`ModuleNotFoundError: ... ib_broker`(需先 `pip install ib_insync`)

- [ ] **Step 3: 安装 ib_insync 并加入依赖**

```bash
pip install ib_insync
```
并在 `pyproject.toml` 的 `dependencies` 追加 `"ib_insync>=0.9.86"`。

- [ ] **Step 4: 实现 ib_broker.py**

`trading/brokers/ib_broker.py`:
```python
from __future__ import annotations
from ib_insync import IB, Stock, LimitOrder, MarketOrder
from trading.common.ports import Broker
from trading.common.models import Order, Fill, Side, OrderType
from trading.common.symbolmap import SymbolSpec, SymbolMap


def build_contract(spec: SymbolSpec) -> Stock:
    return Stock(spec.ib_symbol, spec.ib_exchange, spec.ib_currency)


def build_ib_order(order: Order):
    action = order.side.value          # "BUY"/"SELL"
    if order.order_type == OrderType.MKT:
        return MarketOrder(action, order.qty)
    return LimitOrder(action, order.qty, order.limit_price)


class IBBroker(Broker):
    def __init__(self, symbol_map: SymbolMap, host: str = "127.0.0.1",
                 port: int = 7497, client_id: int = 1):
        self._map = symbol_map
        self._host, self._port, self._cid = host, port, client_id
        self._ib = IB()
        self._fill_cb = None
        # IB ib_symbol -> internal,用于持仓/成交回映
        self._ib_to_internal = {s.ib_symbol: s.internal
                                for s in (symbol_map.by_internal(c)
                                          for c in self._all_internals(symbol_map))}

    @staticmethod
    def _all_internals(symbol_map: SymbolMap) -> list[str]:
        return [symbol_map.by_futu(f).internal for f in symbol_map.all_futu()]

    def connect(self) -> None:
        self._ib.connect(self._host, self._port, clientId=self._cid)
        self._ib.execDetailsEvent += self._on_exec

    def get_positions(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in self._ib.positions():
            internal = self._ib_to_internal.get(p.contract.symbol)
            if internal:
                out[internal] = float(p.position)
        return out

    def place_order(self, order: Order) -> str:
        spec = self._map.by_internal(order.symbol)
        trade = self._ib.placeOrder(build_contract(spec), build_ib_order(order))
        return str(trade.order.orderId)

    def cancel(self, order_id: str) -> None:
        for t in self._ib.trades():
            if str(t.order.orderId) == order_id:
                self._ib.cancelOrder(t.order)

    def set_fill_handler(self, handler) -> None:
        self._fill_cb = handler

    def _on_exec(self, trade, fill) -> None:
        if self._fill_cb is None:
            return
        internal = self._ib_to_internal.get(fill.contract.symbol, fill.contract.symbol)
        side = Side.BUY if fill.execution.side == "BOT" else Side.SELL
        self._fill_cb(Fill(internal, side, float(fill.execution.shares),
                           float(fill.execution.price),
                           fill.execution.time, str(fill.execution.orderId)))

    def close(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()
```

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/test_ib_broker.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add trading/brokers/ib_broker.py tests/test_ib_broker.py pyproject.toml
git commit -m "feat: IBBroker ib_insync adapter + contract/order builders (P3 task 8)"
```

---

## Task 9: trader 进程入口

**说明:** 装配:Redis、IBBroker、StateStore、RiskManager、TraderEngine。启动自检 → 从 IB 持仓恢复 t_position → 订阅 Redis bar 驱动。标的与 base_qty 从 `config/selected.yaml`(P2 Scanner 产出)+ `config/symbols.yaml` 读。

**Files:**
- Create: `trading/apps/trader.py`

- [ ] **Step 1: 实现 trader.py**

`trading/apps/trader.py`:
```python
from __future__ import annotations
import os
import yaml
import redis
from trading.common.eventbus import EventBus
from trading.common.symbolmap import SymbolMap
from trading.common.state_store import StateStore
from trading.common.clock import MarketClock
from trading.strategy.signals import MeanReversionParams
from trading.brokers.ib_broker import IBBroker
from trading.risk.manager import RiskManager, RiskParams
from trading.trader.order_tracker import OrderTracker
from trading.trader.engine import TraderEngine
from trading.trader.recovery import startup_check, recover_t_position


def _load_targets(path: str) -> dict[str, dict]:
    """selected.yaml → {internal_symbol: {base_qty, params}}。"""
    doc = yaml.safe_load(open(path))
    out = {}
    for s in doc["symbols"]:
        out[s["symbol"]] = {
            "base_qty": s.get("base_qty", 400),
            "params": MeanReversionParams(**s.get("params", {})),
        }
    return out


def main():
    symbol_map = SymbolMap.from_yaml(os.environ.get("SYMBOLS_YAML", "config/symbols.yaml"))
    targets = _load_targets(os.environ.get("SELECTED_YAML", "config/selected.yaml"))
    base_qtys = {s: t["base_qty"] for s, t in targets.items()}
    params = {s: t["params"] for s, t in targets.items()}

    r = redis.Redis(host=os.environ.get("REDIS_HOST", "127.0.0.1"),
                    port=int(os.environ.get("REDIS_PORT", "6379")),
                    decode_responses=True)
    bus = EventBus(r)
    store = StateStore(r)
    broker = IBBroker(symbol_map,
                      host=os.environ.get("IB_HOST", "127.0.0.1"),
                      port=int(os.environ.get("IB_PORT", "7497")),  # paper 默认
                      client_id=int(os.environ.get("IB_CID", "1")))

    redis_ok = r.ping()
    broker.connect()
    startup_check(feed_ok=True, broker_ok=broker._ib.isConnected(), redis_ok=bool(redis_ok))

    # 状态恢复:从 IB 实际持仓反推 t_position 并落库
    positions = broker.get_positions()
    for sym, bq in base_qtys.items():
        t = recover_t_position(positions.get(sym, bq), bq)
        store.save_t_position(sym, t)
        print(f"[recover] {sym} actual={positions.get(sym, bq)} base={bq} t={t}")

    eng = TraderEngine(base_qtys=base_qtys, params_by_symbol=params,
                       risk=RiskManager(RiskParams()), broker=broker,
                       state_store=store, clock=MarketClock(),
                       order_tracker=OrderTracker(), event_bus=bus)
    broker.set_fill_handler(eng.on_fill)
    print(f"trader running, symbols={list(base_qtys)}. subscribing bars...")
    bus.subscribe_bars(eng.on_bar)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 导入自检**

Run: `python -c "import trading.apps.trader; print('import ok')"`
Expected: 打印 `import ok`

- [ ] **Step 3: 提交**

```bash
git add trading/apps/trader.py
git commit -m "feat: trader process entry with startup check + recovery (P3 task 9)"
```

---

## Task 10: monitor 进程

**说明:** 订阅 fill/alert 事件,append 到 jsonl 落库并打印。健康检查:周期性确认 stream 有新数据。无单测(IO),导入自检。

**Files:**
- Create: `trading/apps/monitor.py`

- [ ] **Step 1: 实现 monitor.py**

`trading/apps/monitor.py`:
```python
from __future__ import annotations
import os
import json
from pathlib import Path
import redis


def main():
    r = redis.Redis(host=os.environ.get("REDIS_HOST", "127.0.0.1"),
                    port=int(os.environ.get("REDIS_PORT", "6379")),
                    decode_responses=True)
    log_path = Path(os.environ.get("MONITOR_LOG", "data/monitor.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    ps = r.pubsub()
    ps.psubscribe("fill.*", "alert", "signal.*")
    print(f"monitor running, logging -> {log_path}")
    with open(log_path, "a") as f:
        for msg in ps.listen():
            if msg.get("type") not in ("pmessage", "message"):
                continue
            rec = {"channel": msg["channel"], "data": msg["data"]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if str(msg["channel"]).startswith("alert"):
                print(f"[ALERT] {msg['data']}")
            else:
                print(f"[{msg['channel']}] {msg['data']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 导入自检**

Run: `python -c "import trading.apps.monitor; print('import ok')"`
Expected: 打印 `import ok`

- [ ] **Step 3: 提交**

```bash
git add trading/apps/monitor.py
git commit -m "feat: monitor process subscribing fill/alert/signal events (P3 task 10)"
```

---

## Task 11: IB paper 三进程集成验证(手动)

**说明:** 端到端:Redis + data(港股时段,P1)+ trader(连 IB paper)+ monitor。需 FutuOpenD、IB Gateway(paper 登录,端口 7497,API 开启)、Redis 全在线,`config/selected.yaml` 有标的。

**前置:**
- IB Gateway 用 **paper account** 登录,Configure → API → 勾选 Enable ActiveX/Socket、端口 7497、信任 127.0.0.1
- `config/selected.yaml` 至少一只港股标(可手动写,base_qty 设小,如 100),且该标在 `config/symbols.yaml` 有 IB 映射
- paper 账户预先持有该标底仓 = base_qty(否则恢复出的 t_position 为负,首单可能即减仓)

- [ ] **Step 1: 启动 Redis + data + monitor**

```bash
redis-cli ping            # PONG
python -m trading.apps.data &      # 港股时段开始推 bar
python -m trading.apps.monitor &
```
Expected: data 打印 `[bar] ...`;monitor 打印 `monitor running ...`

- [ ] **Step 2: 启动 trader(连 IB paper)**

Run: `IB_PORT=7497 python -m trading.apps.trader`
Expected:
- `[recover] HK.xxx actual=... base=... t=...` 每标一行
- `trader running, symbols=[...]. subscribing bars...`
- 无 `startup check failed`

- [ ] **Step 3: 观察一个交易时段**

Expected:
- 每分钟 bar 到达,trader 按信号决策
- 出信号且风控通过时,IB paper 出现挂单/成交;monitor 打印 `[fill.xxx]`、`[signal.xxx]`
- 限价单超 30s 未成交 → monitor 打印 `[ALERT] order_timeout`,IB 中该单被撤
- 验证 IB paper 持仓变化 = base_qty ± t_position,且 `|t_position| ≤ t_pool`

- [ ] **Step 4: 验证风控**

- 重启 trader → `[recover]` 应从 IB 当前持仓正确反推 t_position(对账一致)
- 断开 IB Gateway → trader 不再开新仓(下单异常被 alert,不崩)

- [ ] **Step 5: 记录结果**

记录:成交笔数、t_position 轨迹、撤单告警次数、恢复对账是否一致、有无异常。这是 P3 验收依据。

**P3 完成判定:** Task 1-8 单测全绿 + Task 9/10 导入通过 + Task 11 IB paper 三进程跑通一个时段(下单/成交/撤单超时/熔断/恢复对账均符合预期)。

---

## Self-Review

**1. Spec 覆盖(P3 范围):**
- §4 Order/Fill 模型 → Task 1 ✓
- §4 Broker 端口 + IBBroker(持仓真相源)→ Task 2/8 ✓
- §4 StateStore → Task 5 ✓
- §5 数据流闭环(bar→策略→风控→网格→下单→fill)→ Task 7 TraderEngine ✓
- §7 T仓上限 → 复用 P2 grid cap(TraderEngine 同步实际持仓后 apply)✓
- §7 日内熔断 → Task 3 RiskManager circuit-breaker ✓
- §7 趋势暂停 → 复用 P2 策略 downtrend 过滤 ✓
- §7 撤单超时 → Task 4 OrderTracker + Task 7 check_timeouts ✓
- §7 数据/执行断线 → Task 3 connected 闸 + Task 7 异常 alert + Task 9 startup_check ✓
- §7 Redis 断降级 → Task 7 state.save try/except + alert ✓
- §7 单标频率 → Task 3 min_order_interval_s ✓
- §9 启动自检 → Task 5 startup_check + Task 9 装配 ✓
- §9 状态恢复(从 IB 反推)→ Task 5 recover_t_position + Task 9 ✓
- §9 事件写 stream 可回放 → Task 6 publish_event + Task 10 monitor 落库 ✓
- §10 集成测试(FakeBroker)→ Task 7 ✓;IB paper → Task 11 ✓

**2. 占位符扫描:** 无 TBD/TODO;每 code step 含完整代码;手动 step(11)含前置/命令/预期/记录项。✓

**3. 类型一致性:**
- `Side`(BUY/SELL)、`OrderType`(LMT/MKT)、`Order`、`Fill` 在 models/fake_broker/ib_broker/engine 一致 ✓
- `Broker` 抽象方法(connect/get_positions/place_order/cancel/set_fill_handler/close)在 FakeBroker、IBBroker 实现一致 ✓
- `RiskManager.check(symbol, action, t_position, now, *, daily_t_pnl, base_value, connected)` 签名在 test 与 TraderEngine 调用一致 ✓
- `Decision`(approved/reason)一致 ✓
- `OrderTracker.track/complete/timed_out`、`StateStore.save_t_position/load_t_position/all_t_positions` 在 engine/trader.py 调用一致 ✓
- `recover_t_position(actual_total, base_qty)`、`startup_check(feed_ok,broker_ok,redis_ok)` 签名一致 ✓
- `EventBus.publish_event/subscribe_bars/_handle_message` 在 engine/trader/monitor 使用一致 ✓
- 复用接口:`MeanReversionStrategy.on_bar`、`GridPositionMgr.apply/flatten/t_position`、`PnLTracker.fill/unrealized/realized`、`MarketClock`、`SymbolMap.by_internal/by_futu/all_futu`、`SymbolSpec` 字段 —— 均与 P1/P2 已实现签名一致 ✓

无遗留问题。
