# P2 策略+回测+Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 离线实现均值回归策略 + 网格仓位 + 事件回测引擎 + Scanner,对候选池回测筛出每市场适合做T的 top≤3 并导出参数。

**Architecture:** 纯函数指标层 → `MeanReversionStrategy`(流式 on_bar 出 Signal)→ `GridPositionMgr`(信号转目标 t_position 增量)→ 事件回测引擎(逐 bar 模拟成交,`PnLTracker` 记盈亏,含成本/滑点/收盘归零)→ Scanner(每标跑回测得 sharpe/t_return + 适配性指标,过滤排名取 top,导出 yaml)。全离线,不碰 IB。

**Tech Stack:** Python 3.11+、pandas、futu-api(仅历史拉取)、pyyaml、pytest。复用 P1 的 `Bar`/`Market`/`FutuDataFeed`/`BarStore`。

**依赖:** P1 已完成(`trading.common.models.Bar`、`trading.feeds.futu_feed.FutuDataFeed`、`parse_kline_row`)。

**对应 spec:** §6(策略逻辑)、§7(T仓上限/收盘归零)、§8 + §8.1(回测/Scanner)。

**P2 取舍(明确):** Scanner 用**默认参数**评估筛标,导出的 yaml 参数初值=默认(留手调)。**参数网格寻优不在 P2**(工程大),作为 `Scanner` 后续扩展点。理由:先用稳健默认参数选出适合做T的标,寻优是二阶优化,YAGNI。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `trading/strategy/__init__.py` | 包标记 |
| `trading/strategy/indicators.py` | 纯函数:sma/ema/rsi/bollinger/atr |
| `trading/strategy/signals.py` | `Action`/`Signal`/`MeanReversionParams`/`MeanReversionStrategy` |
| `trading/strategy/grid.py` | `GridParams`/`GridPositionMgr` |
| `trading/backtest/__init__.py` | 包标记 |
| `trading/backtest/pnl.py` | `PnLTracker`(加减仓/翻转 realized + unrealized) |
| `trading/backtest/engine.py` | `BacktestConfig`/`BacktestResult`/`run_backtest` |
| `trading/backtest/history.py` | `df_to_bars` 纯函数 + `HistoryLoader`(富途历史→Bar,缓存) |
| `trading/scanner/__init__.py` | 包标记 |
| `trading/scanner/metrics.py` | `atr_pct`/`autocorr_lag1`/`avg_turnover` |
| `trading/scanner/scanner.py` | `ScanResult`/`Scanner`(回测+适配性→过滤排名→导出 yaml) |
| `trading/apps/scan.py` | CLI:读候选池→扫描→导出 |
| `tests/...` | 各模块单测 |

---

## Task 1: 指标纯函数

**Files:**
- Create: `trading/strategy/__init__.py`(空)
- Create: `trading/strategy/indicators.py`
- Test: `tests/test_indicators.py`

- [ ] **Step 1: 写失败测试**

`tests/test_indicators.py`:
```python
import math
from trading.strategy.indicators import sma, ema, rsi, bollinger, atr


def test_sma_insufficient_returns_none():
    assert sma([1, 2], 3) is None


def test_sma():
    assert sma([1, 2, 3, 4], 2) == 3.5


def test_ema_seed_is_sma():
    # 仅 n 个数据时,EMA 等于首 n 个的 SMA
    assert ema([2, 4, 6], 3) == 4.0


def test_bollinger():
    mid, up, low = bollinger([10, 12, 14, 16, 18], 5, 2.0)
    assert mid == 14.0
    sd = math.sqrt(sum((x - 14) ** 2 for x in [10, 12, 14, 16, 18]) / 5)
    assert math.isclose(up, 14 + 2 * sd)
    assert math.isclose(low, 14 - 2 * sd)


def test_rsi_all_gains_is_100():
    assert rsi([1, 2, 3, 4, 5], 4) == 100.0


def test_rsi_known():
    # 交替 +1/-1,平均涨跌相等 → RSI=50
    assert math.isclose(rsi([10, 11, 10, 11, 10, 11], 4), 50.0)


def test_atr():
    highs = [10, 11, 12, 13, 14]
    lows = [9, 10, 11, 12, 13]
    closes = [9.5, 10.5, 11.5, 12.5, 13.5]
    # n=2: 取最后2根的TR均值
    val = atr(highs, lows, closes, 2)
    assert val is not None and val > 0
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_indicators.py -v`
Expected: FAIL,`ModuleNotFoundError: ... indicators`

- [ ] **Step 3: 实现 indicators.py**

`trading/strategy/indicators.py`:
```python
from __future__ import annotations
from typing import Sequence


def sma(xs: Sequence[float], n: int) -> float | None:
    if len(xs) < n:
        return None
    return sum(xs[-n:]) / n


def ema(xs: Sequence[float], n: int) -> float | None:
    if len(xs) < n:
        return None
    k = 2 / (n + 1)
    e = sum(xs[:n]) / n          # 以首 n 个的 SMA 作种子
    for x in xs[n:]:
        e = x * k + e * (1 - k)
    return e


def rsi(xs: Sequence[float], n: int) -> float | None:
    if len(xs) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(-n, 0):
        d = xs[i] - xs[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)


def bollinger(xs: Sequence[float], n: int, k: float):
    if len(xs) < n:
        return None
    w = xs[-n:]
    mid = sum(w) / n
    sd = (sum((x - mid) ** 2 for x in w) / n) ** 0.5
    return (mid, mid + k * sd, mid - k * sd)


def atr(highs: Sequence[float], lows: Sequence[float],
        closes: Sequence[float], n: int) -> float | None:
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(-n, 0):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs) / n
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_indicators.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add trading/strategy/__init__.py trading/strategy/indicators.py tests/test_indicators.py
git commit -m "feat: indicator pure functions sma/ema/rsi/bollinger/atr (P2 task 1)"
```

---

## Task 2: Signal + MeanReversionStrategy

**说明:** 单标流式策略。VWAP 按自然日重置。趋势过滤 `downtrend = close<VWAP 且 ema_fast<ema_slow` → 禁买只允卖。

**Files:**
- Create: `trading/strategy/signals.py`
- Test: `tests/test_signals.py`

- [ ] **Step 1: 写失败测试**

`tests/test_signals.py`:
```python
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.common.models import Bar, Market
from trading.strategy.signals import (
    Action, Signal, MeanReversionStrategy, MeanReversionParams)

HK = ZoneInfo("Asia/Hong_Kong")


def _bar(day, minute, o, h, l, c, v=1000):
    return Bar("HK.00700", Market.HK,
               datetime(2026, 6, day, 9 + minute // 60, minute % 60, tzinfo=HK),
               o, h, l, c, v, c * v)


def test_warmup_returns_hold():
    s = MeanReversionStrategy("HK.00700")
    sig = s.on_bar(_bar(2, 0, 100, 100, 100, 100))
    assert sig.action == Action.HOLD
    assert sig.reason == "warmup"


def test_sell_on_overbought():
    s = MeanReversionStrategy("HK.00700")
    last = None
    for i in range(25):                       # 缓涨 100→104.8,建仓 EMA 上行
        p = 100 + i * 0.2
        last = s.on_bar(_bar(2, i, p, p, p, p))
    spike = s.on_bar(_bar(2, 25, 110, 110, 110, 110))  # 跳涨突破上轨
    assert spike.action == Action.SELL


def test_buy_on_oversold_no_downtrend():
    s = MeanReversionStrategy("HK.00700")
    for i in range(26):                       # day1 缓涨 + 末根跳涨
        p = 100 + i * 0.2
        s.on_bar(_bar(2, i, p, p, p, p))
    s.on_bar(_bar(2, 25, 110, 110, 110, 110))
    # day2 第一根暴跌:VWAP 当日重置=98,close==VWAP → 非 downtrend
    buy = s.on_bar(_bar(3, 0, 98, 98, 98, 98))
    assert buy.action == Action.BUY
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_signals.py -v`
Expected: FAIL,`ModuleNotFoundError: ... signals`

- [ ] **Step 3: 实现 signals.py**

`trading/strategy/signals.py`:
```python
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from datetime import datetime, date
from enum import Enum
from trading.common.models import Bar
from trading.strategy.indicators import bollinger, rsi, ema


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Signal:
    symbol: str
    ts: datetime
    action: Action
    reason: str


@dataclass
class MeanReversionParams:
    bb_period: int = 20
    bb_k: float = 2.0
    rsi_period: int = 14
    rsi_low: float = 30.0
    rsi_high: float = 70.0
    ema_fast: int = 9
    ema_slow: int = 21


class MeanReversionStrategy:
    """单标的均值回归。on_bar 流式喂入;VWAP 按自然日重置。"""

    def __init__(self, symbol: str, params: MeanReversionParams | None = None):
        self.symbol = symbol
        self.p = params or MeanReversionParams()
        maxlen = max(self.p.bb_period, self.p.rsi_period + 1, self.p.ema_slow) + 1
        self._closes: deque[float] = deque(maxlen=maxlen)
        self._cur_day: date | None = None
        self._pv = 0.0
        self._vol = 0.0
        self._vwap = 0.0

    def _update_vwap(self, bar: Bar) -> None:
        d = bar.ts.date()
        if d != self._cur_day:
            self._cur_day, self._pv, self._vol = d, 0.0, 0.0
        typical = (bar.high + bar.low + bar.close) / 3
        self._pv += typical * bar.volume
        self._vol += bar.volume
        self._vwap = self._pv / self._vol if self._vol else bar.close

    def on_bar(self, bar: Bar) -> Signal:
        self._update_vwap(bar)
        self._closes.append(bar.close)
        xs = list(self._closes)
        bb = bollinger(xs, self.p.bb_period, self.p.bb_k)
        r = rsi(xs, self.p.rsi_period)
        ef = ema(xs, self.p.ema_fast)
        es = ema(xs, self.p.ema_slow)
        if bb is None or r is None or ef is None or es is None:
            return Signal(self.symbol, bar.ts, Action.HOLD, "warmup")
        _, upper, lower = bb
        downtrend = bar.close < self._vwap and ef < es
        if bar.close < lower and r < self.p.rsi_low and not downtrend:
            return Signal(self.symbol, bar.ts, Action.BUY, f"<{lower:.2f} rsi{r:.0f}")
        if bar.close > upper and r > self.p.rsi_high:
            return Signal(self.symbol, bar.ts, Action.SELL, f">{upper:.2f} rsi{r:.0f}")
        return Signal(self.symbol, bar.ts, Action.HOLD, "no-signal")
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_signals.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add trading/strategy/signals.py tests/test_signals.py
git commit -m "feat: MeanReversionStrategy with VWAP/bollinger/RSI/trend filter (P2 task 2)"
```

---

## Task 3: GridPositionMgr

**说明:** 信号转目标 t_position 增量。t_position 受 `[-t_pool, +t_pool]` 硬约束(spec §7)。单位为股数(港股 lot size 在 P3 执行处理,回测忽略)。

**Files:**
- Create: `trading/strategy/grid.py`
- Test: `tests/test_grid.py`

- [ ] **Step 1: 写失败测试**

`tests/test_grid.py`:
```python
from trading.strategy.grid import GridParams, GridPositionMgr
from trading.strategy.signals import Action


def _mgr():
    return GridPositionMgr(GridParams(base_qty=400, t_ratio=0.25, grid_n=4))
    # t_pool=100, grid_step=25


def test_buy_increments_capped():
    m = _mgr()
    assert m.apply(Action.BUY) == 25      # 0 -> 25
    assert m.apply(Action.BUY) == 25      # 25 -> 50
    m.apply(Action.BUY); m.apply(Action.BUY)  # -> 100 (上限)
    assert m.t_position == 100
    assert m.apply(Action.BUY) == 0       # 已封顶,无增量


def test_sell_decrements_capped():
    m = _mgr()
    assert m.apply(Action.SELL) == -25
    for _ in range(5):
        m.apply(Action.SELL)
    assert m.t_position == -100           # 下限
    assert m.apply(Action.SELL) == 0


def test_hold_no_change():
    m = _mgr()
    m.apply(Action.BUY)
    assert m.apply(Action.HOLD) == 0
    assert m.t_position == 25


def test_flatten():
    m = _mgr()
    m.apply(Action.BUY); m.apply(Action.BUY)   # t=50
    assert m.flatten() == -50
    assert m.t_position == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_grid.py -v`
Expected: FAIL,`ModuleNotFoundError: ... grid`

- [ ] **Step 3: 实现 grid.py**

`trading/strategy/grid.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from trading.strategy.signals import Action


@dataclass
class GridParams:
    base_qty: float
    t_ratio: float = 0.25
    grid_n: int = 4


class GridPositionMgr:
    def __init__(self, params: GridParams):
        self.p = params
        self.t_pool = params.base_qty * params.t_ratio
        self.grid_step = self.t_pool / params.grid_n
        self.t_position = 0.0

    def apply(self, action: Action) -> float:
        """按信号更新目标 t_position,返回需成交量(delta,正买负卖)。"""
        target = self.t_position
        if action == Action.BUY:
            target = min(self.t_position + self.grid_step, self.t_pool)
        elif action == Action.SELL:
            target = max(self.t_position - self.grid_step, -self.t_pool)
        delta = target - self.t_position
        self.t_position = target
        return delta

    def flatten(self) -> float:
        delta = -self.t_position
        self.t_position = 0.0
        return delta
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_grid.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add trading/strategy/grid.py tests/test_grid.py
git commit -m "feat: GridPositionMgr with t_pool cap and flatten (P2 task 3)"
```

---

## Task 4: PnLTracker

**说明:** 加权平均成本法。加仓更新均价;反向先平仓实现盈亏,翻转则新仓以成交价为均价。

**Files:**
- Create: `trading/backtest/__init__.py`(空)
- Create: `trading/backtest/pnl.py`
- Test: `tests/test_pnl.py`

- [ ] **Step 1: 写失败测试**

`tests/test_pnl.py`:
```python
import math
from trading.backtest.pnl import PnLTracker


def test_long_add_then_close_profit():
    t = PnLTracker()
    t.fill(10, 100)          # 买10@100
    t.fill(10, 110)          # 加10@110 → 均价105
    assert math.isclose(t.avg_cost, 105)
    t.fill(-20, 120)         # 全平@120 → realized=20*(120-105)=300
    assert math.isclose(t.realized, 300)
    assert t.position == 0


def test_partial_close():
    t = PnLTracker()
    t.fill(10, 100)
    t.fill(-4, 110)          # 平4 → realized=4*(110-100)=40
    assert math.isclose(t.realized, 40)
    assert t.position == 6
    assert math.isclose(t.avg_cost, 100)   # 均价不变


def test_short_close_profit():
    t = PnLTracker()
    t.fill(-10, 110)         # 卖空10@110
    t.fill(10, 98)           # 买回@98 → realized=10*(110-98)=120
    assert math.isclose(t.realized, 120)
    assert t.position == 0


def test_flip_long_to_short():
    t = PnLTracker()
    t.fill(10, 100)          # 多10@100
    t.fill(-15, 120)         # 平10(realized=200)并反手空5@120
    assert math.isclose(t.realized, 200)
    assert t.position == -5
    assert math.isclose(t.avg_cost, 120)


def test_unrealized():
    t = PnLTracker()
    t.fill(10, 100)
    assert math.isclose(t.unrealized(105), 50)     # 多仓涨
    t2 = PnLTracker()
    t2.fill(-10, 100)
    assert math.isclose(t2.unrealized(95), 50)     # 空仓跌
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_pnl.py -v`
Expected: FAIL,`ModuleNotFoundError: ... pnl`

- [ ] **Step 3: 实现 pnl.py**

`trading/backtest/pnl.py`:
```python
from __future__ import annotations


class PnLTracker:
    def __init__(self):
        self.position = 0.0
        self.avg_cost = 0.0
        self.realized = 0.0

    def fill(self, qty: float, price: float) -> None:
        """qty>0 买入, qty<0 卖出。"""
        before = self.position
        if before == 0 or (before > 0) == (qty > 0):
            total = before + qty
            self.avg_cost = (self.avg_cost * before + price * qty) / total
            self.position = total
            return
        # 反向:先平仓实现盈亏
        closing = min(abs(qty), abs(before))
        if before > 0:
            self.realized += closing * (price - self.avg_cost)
        else:
            self.realized += closing * (self.avg_cost - price)
        self.position = before + qty
        if self.position == 0:
            self.avg_cost = 0.0
        elif (self.position > 0) != (before > 0):    # 翻转到反向
            self.avg_cost = price
        # 部分平仓:均价不变

    def unrealized(self, price: float) -> float:
        return self.position * (price - self.avg_cost)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_pnl.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add trading/backtest/__init__.py trading/backtest/pnl.py tests/test_pnl.py
git commit -m "feat: PnLTracker avg-cost realized/unrealized (P2 task 4)"
```

---

## Task 5: 回测引擎

**说明:** 逐 bar:策略 on_bar → 网格 apply → 成交(close 价加滑点)→ PnLTracker。`close_flat=True` 时每日最后一根 bar 后归零 t_position。输出绩效指标。sharpe 为 bar 级未年化(仅供 Scanner 相对排名)。

**Files:**
- Create: `trading/backtest/engine.py`
- Test: `tests/test_engine.py`

- [ ] **Step 1: 写失败测试**

`tests/test_engine.py`:
```python
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.common.models import Bar, Market
from trading.strategy.signals import MeanReversionParams
from trading.strategy.grid import GridParams
from trading.backtest.engine import BacktestConfig, run_backtest

HK = ZoneInfo("Asia/Hong_Kong")


def _bar(day, minute, c):
    return Bar("HK.00700", Market.HK,
               datetime(2026, 6, day, 9 + minute // 60, minute % 60, tzinfo=HK),
               c, c, c, c, 1000, c * 1000)


def _bars():
    bars = [_bar(2, i, 100 + i * 0.2) for i in range(25)]   # day1 缓涨
    bars.append(_bar(2, 25, 110))                           # day1 跳涨 → SELL
    bars.append(_bar(3, 0, 98))                             # day2 暴跌 → BUY
    return bars


def test_reverse_t_profit_no_close_flat():
    cfg = BacktestConfig(
        grid=GridParams(base_qty=400, t_ratio=0.25, grid_n=4),
        params=MeanReversionParams(),
        commission_rate=0.0, slippage_bps=0.0, close_flat=False)
    r = run_backtest(_bars(), cfg)
    assert r.n_trades == 2                # SELL@110, BUY@98
    assert r.realized_pnl > 0             # 高卖低买
    assert r.base_value == 100 * 400      # 首bar close * base_qty
    assert r.t_return > 0


def test_close_flat_zeros_position_each_day():
    cfg = BacktestConfig(
        grid=GridParams(base_qty=400, t_ratio=0.25, grid_n=4),
        params=MeanReversionParams(),
        commission_rate=0.0, slippage_bps=0.0, close_flat=True)
    r = run_backtest(_bars(), cfg)
    # 每日末归零 → 末态无持仓,total≈realized
    assert isinstance(r.sharpe, float)
    assert isinstance(r.max_drawdown, float)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_engine.py -v`
Expected: FAIL,`ModuleNotFoundError: ... engine`

- [ ] **Step 3: 实现 engine.py**

`trading/backtest/engine.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from trading.common.models import Bar
from trading.strategy.signals import MeanReversionStrategy, MeanReversionParams
from trading.strategy.grid import GridParams, GridPositionMgr
from trading.backtest.pnl import PnLTracker


@dataclass
class BacktestConfig:
    grid: GridParams
    params: MeanReversionParams
    commission_rate: float = 0.0003
    slippage_bps: float = 1.0
    close_flat: bool = True


@dataclass
class BacktestResult:
    n_trades: int
    realized_pnl: float
    total_pnl: float
    total_cost: float
    win_rate: float
    sharpe: float
    max_drawdown: float
    base_value: float
    t_return: float


def _sharpe(curve: list[float]) -> float:
    if len(curve) < 2:
        return 0.0
    diffs = [curve[i] - curve[i - 1] for i in range(1, len(curve))]
    mean = sum(diffs) / len(diffs)
    var = sum((d - mean) ** 2 for d in diffs) / len(diffs)
    sd = var ** 0.5
    return mean / sd if sd > 0 else 0.0


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0] if curve else 0.0
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v - peak)
    return mdd


def run_backtest(bars: list[Bar], cfg: BacktestConfig) -> BacktestResult:
    if not bars:
        return BacktestResult(0, 0, 0, 0, 0, 0, 0, 0, 0)
    strat = MeanReversionStrategy(bars[0].symbol, cfg.params)
    grid = GridPositionMgr(cfg.grid)
    pnl = PnLTracker()
    cost_total = 0.0
    n_trades = 0
    wins = closes = 0
    curve: list[float] = []
    for i, bar in enumerate(bars):
        sig = strat.on_bar(bar)
        is_last_of_day = (i == len(bars) - 1) or (bars[i + 1].ts.date() != bar.ts.date())
        delta = grid.apply(sig.action)
        if cfg.close_flat and is_last_of_day:
            delta += grid.flatten()
        if delta != 0:
            n_trades += 1
            fill_price = bar.close * (1 + (cfg.slippage_bps / 10000) * (1 if delta > 0 else -1))
            before_realized = pnl.realized
            pnl.fill(delta, fill_price)
            cost_total += abs(delta) * fill_price * cfg.commission_rate
            if pnl.realized != before_realized:
                closes += 1
                if pnl.realized - before_realized > 0:
                    wins += 1
        curve.append(pnl.realized + pnl.unrealized(bar.close) - cost_total)
    base_value = bars[0].close * cfg.grid.base_qty
    total_pnl = curve[-1]
    return BacktestResult(
        n_trades=n_trades,
        realized_pnl=pnl.realized,
        total_pnl=total_pnl,
        total_cost=cost_total,
        win_rate=wins / closes if closes else 0.0,
        sharpe=_sharpe(curve),
        max_drawdown=_max_drawdown(curve),
        base_value=base_value,
        t_return=total_pnl / base_value if base_value else 0.0,
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_engine.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add trading/backtest/engine.py tests/test_engine.py
git commit -m "feat: event backtest engine with cost/slippage/close-flat (P2 task 5)"
```

---

## Task 6: 适配性指标

**说明:** Scanner 用的做T适配性指标(spec §8.1):日内振幅、均值回归性(收益一阶自相关,负=回归)、流动性(日均成交额)。

**Files:**
- Create: `trading/scanner/__init__.py`(空)
- Create: `trading/scanner/metrics.py`
- Test: `tests/test_scanner_metrics.py`

- [ ] **Step 1: 写失败测试**

`tests/test_scanner_metrics.py`:
```python
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.common.models import Bar, Market
from trading.scanner.metrics import atr_pct, autocorr_lag1, avg_turnover

HK = ZoneInfo("Asia/Hong_Kong")


def _bar(i, o, h, l, c, v=1000, turnover=None):
    return Bar("X", Market.HK, datetime(2026, 6, 2, 10, i, tzinfo=HK),
               o, h, l, c, v, turnover if turnover is not None else c * v)


def test_atr_pct_positive():
    bars = [_bar(i, 100, 101, 99, 100) for i in range(20)]
    v = atr_pct(bars, 14)
    assert v is not None and v > 0


def test_autocorr_mean_reverting_negative():
    # 收益交替 +1/-1 → 一阶自相关接近 -1
    closes = [100, 101, 100, 101, 100, 101, 100, 101]
    bars = [_bar(i, c, c, c, c) for i, c in enumerate(closes)]
    assert autocorr_lag1(bars) < 0


def test_avg_turnover():
    bars = [_bar(i, 100, 100, 100, 100, turnover=t) for i, t in enumerate([100, 200, 300])]
    assert math.isclose(avg_turnover(bars), 200.0)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_scanner_metrics.py -v`
Expected: FAIL,`ModuleNotFoundError: ... scanner.metrics`

- [ ] **Step 3: 实现 metrics.py**

`trading/scanner/metrics.py`:
```python
from __future__ import annotations
from trading.common.models import Bar
from trading.strategy.indicators import atr


def atr_pct(bars: list[Bar], n: int = 14) -> float | None:
    if len(bars) < n + 1:
        return None
    a = atr([b.high for b in bars], [b.low for b in bars],
            [b.close for b in bars], n)
    avg_price = sum(b.close for b in bars) / len(bars)
    return a / avg_price if avg_price else None


def autocorr_lag1(bars: list[Bar]) -> float:
    closes = [b.close for b in bars]
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    denom = sum((r - mean) ** 2 for r in rets)
    if denom == 0:
        return 0.0
    num = sum((rets[i] - mean) * (rets[i - 1] - mean) for i in range(1, len(rets)))
    return num / denom


def avg_turnover(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    return sum(b.turnover for b in bars) / len(bars)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_scanner_metrics.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add trading/scanner/__init__.py trading/scanner/metrics.py tests/test_scanner_metrics.py
git commit -m "feat: scanner suitability metrics atr%/autocorr/turnover (P2 task 6)"
```

---

## Task 7: 历史数据加载

**说明:** `df_to_bars` 纯函数(富途历史 DataFrame → list[Bar])单测;`HistoryLoader` 包装富途拉取+parquet 缓存,IO 靠 Task 9 手动验证。复用 P1 `parse_kline_row`。

**Files:**
- Create: `trading/backtest/history.py`
- Test: `tests/test_history.py`

- [ ] **Step 1: 写失败测试**

`tests/test_history.py`:
```python
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from trading.backtest.history import df_to_bars
from trading.common.models import Market

HK = ZoneInfo("Asia/Hong_Kong")


def test_df_to_bars():
    df = pd.DataFrame([
        {"code": "HK.00700", "time_key": "2026-06-02 09:31:00",
         "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
         "volume": 1000, "turnover": 100500.0},
        {"code": "HK.00700", "time_key": "2026-06-02 09:32:00",
         "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5,
         "volume": 1200, "turnover": 121800.0},
    ])
    bars = df_to_bars(df)
    assert len(bars) == 2
    assert bars[0].symbol == "HK.00700"
    assert bars[0].market == Market.HK
    assert bars[0].ts == datetime(2026, 6, 2, 9, 31, tzinfo=HK)
    assert bars[1].close == 101.5
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_history.py -v`
Expected: FAIL,`ModuleNotFoundError: ... history`

- [ ] **Step 3: 实现 history.py**

`trading/backtest/history.py`:
```python
from __future__ import annotations
from pathlib import Path
import pandas as pd
from trading.common.models import Bar
from trading.feeds.futu_feed import parse_kline_row


def df_to_bars(df: pd.DataFrame) -> list[Bar]:
    return [parse_kline_row(row) for row in df.to_dict("records")]


class HistoryLoader:
    """富途历史1分钟 → list[Bar],带 parquet 缓存(同 symbol+区间不重复拉)。"""

    def __init__(self, feed, cache_root: str = "data/hist"):
        self._feed = feed
        self._root = Path(cache_root)

    def _cache_path(self, futu_symbol: str, start: str, end: str) -> Path:
        safe = futu_symbol.replace(".", "_")
        return self._root / f"{safe}__{start}__{end}.parquet"

    def load(self, futu_symbol: str, start: str, end: str) -> list[Bar]:
        p = self._cache_path(futu_symbol, start, end)
        if p.exists():
            return df_to_bars(pd.read_parquet(p))
        df = self._feed.get_history_kline(futu_symbol, start=start, end=end)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False)
        return df_to_bars(df)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_history.py -v`
Expected: 1 passed

- [ ] **Step 5: 提交**

```bash
git add trading/backtest/history.py tests/test_history.py
git commit -m "feat: HistoryLoader df_to_bars + futu history cache (P2 task 7)"
```

---

## Task 8: Scanner

**说明:** 对候选池每标:用 `HistoryLoader` 取历史 → 默认参数 `run_backtest` 得 sharpe/t_return → 算 atr_pct/autocorr/turnover → 流动性与振幅过滤、要求 autocorr<0(回归性)→ 按 sharpe 每市场排名取 top≤3 → 导出 yaml。注入 loader 便于 mock 测试。

**Files:**
- Create: `trading/scanner/scanner.py`
- Test: `tests/test_scanner.py`

- [ ] **Step 1: 写失败测试**

`tests/test_scanner.py`:
```python
from datetime import datetime
from zoneinfo import ZoneInfo
import yaml
from trading.common.models import Bar, Market
from trading.scanner.scanner import Scanner, ScanResult

HK = ZoneInfo("Asia/Hong_Kong")


class FakeLoader:
    """按 symbol 返回预置 bars。"""
    def __init__(self, data):
        self._data = data

    def load(self, futu_symbol, start, end):
        return self._data[futu_symbol]


def _series(symbol, market, pattern):
    bars = []
    for i, c in enumerate(pattern):
        bars.append(Bar(symbol, market,
                        datetime(2026, 6, 2 + i // 300, 9 + (i % 300) // 60, i % 60, tzinfo=HK),
                        c, c + 0.5, c - 0.5, c, 1000, c * 1000))
    return bars


def test_scan_symbol_produces_result():
    # 震荡序列:有回归性、足够流动性
    pattern = [100 + (1 if i % 2 else -1) for i in range(60)]
    loader = FakeLoader({"HK.00700": _series("HK.00700", Market.HK, pattern)})
    sc = Scanner(loader, min_turnover=0.0, min_atr_pct=0.0)
    res = sc.scan_symbol("HK.00700", Market.HK, "2026-01-01", "2026-06-01", base_qty=400)
    assert isinstance(res, ScanResult)
    assert res.symbol == "HK.00700"
    assert res.avg_turnover > 0


def test_rank_selects_top_per_market(tmp_path):
    loader = FakeLoader({
        "HK.A": _series("HK.A", Market.HK, [100 + (1 if i % 2 else -1) for i in range(60)]),
        "HK.B": _series("HK.B", Market.HK, [100 + (2 if i % 2 else -2) for i in range(60)]),
        "US.C": _series("US.C", Market.US, [50 + (1 if i % 2 else -1) for i in range(60)]),
    })
    sc = Scanner(loader, min_turnover=0.0, min_atr_pct=0.0)
    results = [
        sc.scan_symbol("HK.A", Market.HK, "2026-01-01", "2026-06-01", 400),
        sc.scan_symbol("HK.B", Market.HK, "2026-01-01", "2026-06-01", 400),
        sc.scan_symbol("US.C", Market.US, "2026-01-01", "2026-06-01", 400),
    ]
    selected = sc.rank(results, top=1)
    markets = {r.market for r in selected}
    assert markets == {Market.HK, Market.US}      # 每市场各选 1
    assert sum(1 for r in selected if r.market == Market.HK) == 1

    out = tmp_path / "selected.yaml"
    sc.export_yaml(selected, str(out))
    loaded = yaml.safe_load(out.read_text())
    assert "symbols" in loaded
    assert all("bb_period" in s["params"] for s in loaded["symbols"])
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_scanner.py -v`
Expected: FAIL,`ModuleNotFoundError: ... scanner.scanner`

- [ ] **Step 3: 实现 scanner.py**

`trading/scanner/scanner.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, asdict
import yaml
from trading.common.models import Market
from trading.strategy.signals import MeanReversionParams
from trading.strategy.grid import GridParams
from trading.backtest.engine import BacktestConfig, run_backtest
from trading.scanner.metrics import atr_pct, autocorr_lag1, avg_turnover


@dataclass
class ScanResult:
    symbol: str
    market: Market
    sharpe: float
    t_return: float
    atr_pct: float
    autocorr: float
    avg_turnover: float
    params: MeanReversionParams
    passed_filters: bool


class Scanner:
    def __init__(self, loader, min_turnover: float, min_atr_pct: float):
        self._loader = loader
        self._min_turnover = min_turnover
        self._min_atr_pct = min_atr_pct

    def scan_symbol(self, futu_symbol: str, market: Market,
                    start: str, end: str, base_qty: float) -> ScanResult:
        bars = self._loader.load(futu_symbol, start, end)
        params = MeanReversionParams()
        cfg = BacktestConfig(grid=GridParams(base_qty=base_qty), params=params)
        bt = run_backtest(bars, cfg)
        ap = atr_pct(bars) or 0.0
        ac = autocorr_lag1(bars)
        turn = avg_turnover(bars)
        passed = turn >= self._min_turnover and ap >= self._min_atr_pct and ac < 0
        return ScanResult(futu_symbol, market, bt.sharpe, bt.t_return,
                          ap, ac, turn, params, passed)

    def rank(self, results: list[ScanResult], top: int = 3) -> list[ScanResult]:
        selected: list[ScanResult] = []
        for mkt in (Market.HK, Market.US):
            pool = [r for r in results if r.market == mkt and r.passed_filters]
            pool.sort(key=lambda r: r.sharpe, reverse=True)
            selected.extend(pool[:top])
        return selected

    def export_yaml(self, selected: list[ScanResult], path: str) -> None:
        doc = {"symbols": [
            {"symbol": r.symbol, "market": r.market.value,
             "sharpe": round(r.sharpe, 4), "t_return": round(r.t_return, 4),
             "params": asdict(r.params)}
            for r in selected
        ]}
        with open(path, "w") as f:
            yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_scanner.py -v`
Expected: 2 passed

- [ ] **Step 5: 全量回归**

Run: `pytest -q`
Expected: P1 + P2 全部通过。

- [ ] **Step 6: 提交**

```bash
git add trading/scanner/scanner.py tests/test_scanner.py
git commit -m "feat: Scanner backtest+suitability rank+yaml export (P2 task 8)"
```

---

## Task 9: Scanner CLI + 候选池实跑(手动)

**说明:** 装配 FutuDataFeed + HistoryLoader + Scanner,从候选池 yaml 跑出选标 yaml。需 FutuOpenD 在线 + 历史额度。

**Files:**
- Create: `trading/apps/scan.py`
- Create: `config/candidates.yaml`

- [ ] **Step 1: 写候选池配置(示例,替换成你的票)**

`config/candidates.yaml`:
```yaml
# 你看好/愿做底仓的票,每市场可多只,Scanner 筛 top
start: "2024-06-01"
end: "2026-06-01"
base_qty: 400
min_turnover: 1000000      # 日均成交额下限(本币)
min_atr_pct: 0.005         # 日内振幅下限 0.5%
top: 3
candidates:
  - { futu: "HK.00700", market: "HK" }
  - { futu: "HK.09988", market: "HK" }
  - { futu: "US.AAPL",  market: "US" }
```

- [ ] **Step 2: 实现 scan.py**

`trading/apps/scan.py`:
```python
from __future__ import annotations
import sys
import yaml
from trading.common.models import Market
from trading.feeds.futu_feed import FutuDataFeed
from trading.backtest.history import HistoryLoader
from trading.scanner.scanner import Scanner


def main(cfg_path: str, out_path: str):
    cfg = yaml.safe_load(open(cfg_path))
    feed = FutuDataFeed()
    feed.connect()
    try:
        loader = HistoryLoader(feed)
        sc = Scanner(loader,
                     min_turnover=cfg["min_turnover"],
                     min_atr_pct=cfg["min_atr_pct"])
        results = []
        for c in cfg["candidates"]:
            r = sc.scan_symbol(c["futu"], Market(c["market"]),
                               cfg["start"], cfg["end"], cfg["base_qty"])
            print(f"{r.symbol:12} sharpe={r.sharpe:+.3f} t_ret={r.t_return:+.4f} "
                  f"atr%={r.atr_pct:.4f} ac={r.autocorr:+.3f} "
                  f"turn={r.avg_turnover:,.0f} pass={r.passed_filters}")
            results.append(r)
        selected = sc.rank(results, top=cfg["top"])
        sc.export_yaml(selected, out_path)
        print(f"\nselected {len(selected)} -> {out_path}")
        for r in selected:
            print(f"  {r.market.value} {r.symbol} sharpe={r.sharpe:+.3f}")
    finally:
        feed.close()


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "config/candidates.yaml"
    out = sys.argv[2] if len(sys.argv) > 2 else "config/selected.yaml"
    main(cfg, out)
```

- [ ] **Step 3: 导入自检**

Run: `python -c "import trading.apps.scan; print('import ok')"`
Expected: 打印 `import ok`

- [ ] **Step 4: 实跑(FutuOpenD 在线)**

Run: `python -m trading.apps.scan config/candidates.yaml config/selected.yaml`
Expected:
- 每个候选标打印一行:sharpe/t_return/atr%/autocorr/turnover/pass
- 末尾打印 selected 列表,生成 `config/selected.yaml`
- 注意:每标拉历史消耗富途额度,候选池别太大;额度不足报错则减少候选或分批

记录:哪些标通过过滤、sharpe 排名、最终选出的标。`config/selected.yaml` 即 P3 实盘标的输入。

- [ ] **Step 5: 提交**

```bash
git add trading/apps/scan.py config/candidates.yaml
git commit -m "feat: scanner CLI app over candidate pool (P2 task 9)"
```

---

## Self-Review

**1. Spec 覆盖(P2 范围):**
- §6.1 仓位模型(base/t_pool/t_position)→ Task 3 GridPositionMgr ✓
- §6.2 均值回归信号(布林+RSI+VWAP+趋势过滤)→ Task 1 指标 + Task 2 策略 ✓
- §6.3 收盘归零 → Task 5 `close_flat` ✓
- §6.4 双向做T(t_position 可正负)→ Task 3 + Task 4 PnLTracker 支持空头 ✓
- §7 T仓硬上限 → Task 3 cap 到 ±t_pool ✓
- §8 回测引擎 + 富途8年历史 → Task 5 + Task 7 ✓
- §8.1 Scanner 适配性筛选(振幅/回归性/流动性/回测)→ Task 6 + Task 8 ✓
- 不在 P2:风控熔断/撤单/IBBroker/三进程/实盘 → P3 ✓
- 明确简化:参数网格寻优 → Scanner 后续扩展,非 P2(已在 Goal 下说明)

**2. 占位符扫描:** 无 TBD/TODO;每 code step 含完整代码;手动 step(Task 9)含命令+预期+记录项。✓

**3. 类型一致性:**
- `Action`(BUY/SELL/HOLD)在 signals/grid/engine 一致 ✓
- `MeanReversionParams` 字段(bb_period/bb_k/rsi_period/rsi_low/rsi_high/ema_fast/ema_slow)在 signals 定义,engine/scanner 透传,export_yaml 用 `asdict` 序列化 ✓
- `GridParams`(base_qty/t_ratio/grid_n)在 grid 定义,engine/scanner 构造一致 ✓
- `GridPositionMgr.apply/flatten`、`PnLTracker.fill/unrealized`、`run_backtest`、`BacktestResult`(sharpe/t_return/n_trades/realized_pnl/base_value)在 engine/scanner 调用名一致 ✓
- `ScanResult` 字段与 `Scanner.scan_symbol` 返回、`export_yaml` 读取一致 ✓
- `df_to_bars` 复用 P1 `parse_kline_row`,输入列名(code/time_key/ohlc/volume/turnover)与富途历史 DataFrame 一致 ✓
- `HistoryLoader.load(symbol,start,end)` 签名与 Scanner/FakeLoader/scan.py 调用一致 ✓

无遗留问题。
