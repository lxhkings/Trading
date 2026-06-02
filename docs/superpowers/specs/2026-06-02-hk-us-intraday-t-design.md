# 港美股底仓做T 全自动量化系统 — 设计文档

- 日期:2026-06-02
- 状态:已批准,待写实现计划
- 作者:lxhkings + Claude

## 1. 背景与目标

对长期看好的核心持仓(底仓)做日内 T(高抛低吸),摊低成本、增厚收益。底仓不动,用一部分浮动额度在日内逆势滚动:跌了买、涨了卖。本质是**均值回归 / 逆势**,故动量突破不作主信号,仅作趋势过滤。

**成功标准:**

1. 港股、美股各 1-3 只标,全自动按 1 分钟信号做 T。
2. 富途取行情、IB 执行的混合架构稳定运行(断线自愈)。
3. 风控硬约束:任何情况下底仓不被做没、单日亏损可熔断。
4. 有可复现的回测,港美股分别标定参数。
5. 模块化、端口-适配器设计,数据源 / 券商可替换复用。

## 2. 需求快照

| 项 | 决定 |
|----|------|
| 市场 | 港股 + 美股,时段不重叠,按市场时段切换 |
| 目标 | 底仓做T(持仓增强) |
| 策略 | 均值回归(主)+ 网格(仓位管理)+ 趋势过滤(防接飞刀) |
| 自动化 | 全自动下单 |
| 数据源 | 富途 OpenD / futu-api,1 分钟 bar |
| 执行/持仓真相源 | IB / ib_insync |
| 标的 | 每市场 ≤3 只 |
| 账户 | IB 保证金 ≥$25k(美股无 PDT 限制;港股本无 PDT) |
| 语言 | Python |
| 进程架构 | 多进程(data / trader / monitor)+ Redis |
| 消息中间件 | Redis pub/sub(实时广播)+ stream(事件回放) |

## 3. 系统架构

三进程 + Redis。任意时刻仅一个市场开盘(港 09:30-16:00 HKT / 美 09:30-16:00 ET),并发标的 ≤3。

```
富途OpenD ──┐
            │  (1min bar 推送)
        ┌───▼────┐   Redis pub/sub: bar.* / signal.* / order.* / fill.*
        │  data  │──────────────┐  Redis stream: 事件回放日志 + 自录bar
        └────────┘              │
                          ┌─────▼─────┐      ib_insync       ┌──────────┐
                          │  trader   │◄──────────────────►│IB Gateway│
                          │ 策略+风控  │  下单/成交/持仓真相源  └──────────┘
                          │ +持仓状态  │
                          └─────┬─────┘
                                │ 全量事件
                          ┌─────▼─────┐
                          │  monitor  │  落库 / 告警 / 健康检查 / bar落parquet
                          └───────────┘
```

| 进程 | 职责 | 故障影响 |
|------|------|----------|
| **data** | 富途 OpenD 连接、订阅1min bar、缺口检测、发布到 Redis | 信号停更;trader 保持现状、不开新仓 |
| **trader** | 订阅 bar → 策略+网格+风控+IB下单;**持仓真相源** | 核心;挂了告警停机,重启从 IB 持仓重建状态 |
| **monitor** | 订阅全量事件、落库、告警、健康检查、bar 落 parquet | 仅观测,不影响交易 |

**持仓真相只在 trader,data/monitor 只读**,杜绝双重记账。

## 4. 模块清单与接口契约(端口-适配器,强调复用)

核心抽象用「端口」,具体实现用「适配器」,数据源 / 券商可整体替换。

### 4.1 统一数据模型(dataclass,跨进程序列化)

```python
Bar      : symbol, market, ts, open, high, low, close, volume, vwap
Signal   : symbol, ts, action(BUY/SELL/HOLD), grid_levels, reason
Order    : symbol, side, qty, type(LMT/MKT), limit_price, client_id
Fill     : order_id, symbol, side, qty, price, ts
Position : symbol, base_qty, t_position, avg_cost   # 实际持仓 = base_qty + t_position
```

### 4.2 端口(抽象接口)

| 端口 | 方法 | 说明 |
|------|------|------|
| `DataFeed` | `subscribe(symbols)`, `on_bar(cb)`, `get_history_kline(sym, n)`, `quota()` | 行情源抽象 |
| `Broker` | `place_order(Order)`, `cancel(id)`, `get_positions()`, `on_fill(cb)` | 券商执行抽象;持仓真相 |
| `Strategy` | `on_bar(Bar, ctx) -> Signal` | 纯函数式,易单测 |
| `RiskGate` | `check(Signal, state) -> Approved/Rejected` | 下单前校验 |

### 4.3 适配器与组件

| 组件 | 实现端口/职责 | 依赖 |
|------|----------|------|
| `FutuDataFeed` | DataFeed → futu-api/OpenD,1min K线、缺口检测 | futu-api |
| `IBBroker` | Broker → ib_insync,下单/成交/持仓 | ib_insync |
| `MeanReversionStrategy` | Strategy → 布林+RSI+VWAP+趋势过滤 | 无外部 IO,纯算 |
| `GridPositionMgr` | 底仓/T仓分离、网格分档、目标仓位计算 | 无 IO |
| `RiskManager` | RiskGate → T仓上限/熔断/趋势暂停/撤单超时/断线封锁 | 无 IO |
| `MarketClock` | 港/美时段判定、开收盘事件、非交易休眠 | pytz |
| `SymbolMap` | 富途 `HK.00700`/`US.AAPL` ↔ IB `700 SEHK`/`AAPL SMART` | 配置表 |
| `StateStore` | T仓状态持久化(Redis),重启从 IB 持仓重建 | redis |
| `EventBus` | Redis pub/sub + stream 封装 | redis |

复用点:换券商只写新 `Broker` 适配器;换数据源只写新 `DataFeed`;策略全部纯函数,可单独回测和复用。

## 5. 数据流(端到端)

```
OpenD 1min bar → FutuDataFeed → EventBus.pub "bar.{mkt}.{sym}"
  → trader 订阅 → MeanReversionStrategy.on_bar → Signal
  → RiskManager.check → GridPositionMgr 算目标 t_position
  → 与 IBBroker.get_positions() 对比 → 差额 place_order
  → IB 成交回报 on_fill → 更新 t_position → pub "fill.*" → monitor 落库
```

信号触发 = **1 分钟 bar 闭合驱动**(非 tick)。

## 6. 策略逻辑

### 6.1 仓位模型(每只标)

```
base_qty   : 底仓,永不动
t_pool     : 做T浮动额度 = base_qty × t_ratio (默认 25%)
t_position : 当前T偏移,范围 [-t_pool, +t_pool],初始 0
            >0 = 正T(低点加仓,待高点卖)
            <0 = 反T(高点卖底仓一部分,待低点买回)
实际持仓(IB) = base_qty + t_position
```

### 6.2 信号(均值回归,1min)

| 指标 | 默认参数 |
|------|----------|
| 布林带 | 20 周期, 2σ |
| RSI | 14 周期, 下 30 / 上 70 |
| 日内 VWAP | 当日累计 |
| 趋势过滤 | 价 vs VWAP + EMA(快/慢)斜率 |

```
买一格: 价<布林下轨 且 RSI<30 且 非单边下跌
        → t_position += grid_step (上限 +t_pool)
卖一格: 价>布林上轨 且 RSI>70
        → t_position -= grid_step (下限 -t_pool)
趋势过滤: 强单边下跌(价<VWAP 且 EMA死叉/斜率陡)→ 禁买、只允卖,防接飞刀
网格分档: grid_step = t_pool / N (默认 N=4),分批进出
```

### 6.3 收盘处理

默认**收盘前 M 分钟把 t_position 平回 0**(回到纯底仓,不留做T隔夜偏移)。可配置关闭。

### 6.4 做T方向

默认**双向**(正T + 反T)。可配置为只反T(不占额外现金,纯用底仓滚动)。

## 7. 风控(全自动硬约束)

| 风控 | 规则 |
|------|------|
| T仓硬上限 | `abs(t_position) ≤ t_pool`,保护底仓不被做没 |
| 日内熔断 | 当日T盈亏(已实现+浮动)< -2%(默认)→ 停做T,平回底仓 |
| 趋势暂停 | 见 6.2 趋势过滤 |
| 撤单超时 | 限价单 30s(默认)未成交 → 撤单重报或转市价 |
| 数据断线 | data 断 → 信号停更,trader 保持现状、不开新仓 |
| 执行断线 | trader/IB 断 → monitor 告警;重启从 IB 实际持仓重建 t_position |
| Redis 断 | trader 用本地缓存最后状态降级,告警 |
| 单标频率 | 每标每分钟最多 1 次下单,防抖 |

## 8. 回测与数据

- **数据源:富途 `request_history_kline`,1 分钟支持最近 8 年**,对 1-3 只标完全够,无需第三方源。
- 额度:历史K线额度按账户资产/交易发放,30 天后自动释放;近 7 天每只占 1 额度,重复同股不累计。回测前调 `get_history_kl_quota` 确认额度,不够则告警。
- 限频:每 30 秒 ≤60 次,分页拉取(仅首页计频)。
- 引擎:vectorbt 或自写事件回测;策略为纯函数,直接喂历史 Bar 序列。
- 标定:布林周期/σ、RSI 阈值、t_ratio、网格 N、熔断阈值 —— **港股 / 美股分别标定**(波动不同),输出每只标一套 yaml 参数。
- 增量自录:data 进程把实时 bar 落 parquet/库,边跑边攒自有数据集,回测/实盘对账双用,不占富途额度。

## 9. 错误处理 / 容灾

- 双网关健康检查 + 自动重连(OpenD、IB Gateway)。
- 启动自检:OpenD 登录? IB 连接? 行情权限? Redis? 全绿才进交易态。
- 状态恢复:trader 重启 → 拉 IB 实际持仓 → 减 base_qty 反推 t_position → 继续。
- 所有 order/fill 写 Redis stream,可回放对账。

## 10. 测试策略

| 层 | 内容 |
|----|------|
| 单元 | 策略信号函数(bar序列→预期信号)、网格仓位计算、代码映射、VWAP/布林/RSI、风控规则 |
| 集成 | 模拟 bar 流 → trader → **IB paper account** 下单验证全链路 |
| 数据验证 | 富途 bar vs IB 行情对账,缺口/时区检查(港股时段先验证) |
| 实盘灰度 | IB 模拟盘 → 实盘极小仓(1只, t_ratio=5%)→ 逐步放大 |

## 11. 默认参数

| 参数 | 默认 | 备注 |
|------|------|------|
| t_ratio(做T额度/底仓) | 25% | 可调 |
| 网格层数 N | 4 | |
| 日内熔断 | -2% | |
| 撤单超时 | 30s | |
| 收盘归零 | 开启 | |
| 做T方向 | 双向 | 可改只反T |
| 标的数量 | 每市场 ≤3 | 具体标的待定 |

## 12. 建议项目结构

```
trading/
  common/        # 数据模型、端口接口、配置、SymbolMap、EventBus
  feeds/         # FutuDataFeed
  brokers/       # IBBroker
  strategy/      # MeanReversionStrategy、GridPositionMgr、指标
  risk/          # RiskManager
  clock/         # MarketClock
  backtest/      # 回测引擎、参数标定脚本
  apps/
    data.py      # data 进程入口
    trader.py    # trader 进程入口
    monitor.py   # monitor 进程入口
  config/        # *.yaml 标的与参数
  tests/
```

## 13. 实施阶段(里程碑)

1. **数据管道验证(现可做)**:富途 OpenD 连通、`get_history_kl_quota` 查额度、拉一只港股 8 年 1 分钟、实时订阅验证缺口/时区。
2. **核心模块 + 单测**:数据模型、端口、FutuDataFeed、IBBroker、策略、网格、风控,全部单元测试。
3. **回测 + 参数标定**:港美股分别标定,产出 yaml。
4. **集成 + IB paper**:三进程 + Redis 跑通,paper account 验证全链路。
5. **实盘灰度**:1 只极小仓 → 逐步放大。

## 14. 假设与未决

- 假设每市场 ≤3 只,任意时刻并发 ≤3(单市场开盘)。
- 假设富途账户行情权限覆盖目标港美股 1 分钟实时(实施前 §13.1 验证)。
- 具体标的清单待定(进入实现前提供)。
- 做T方向默认双向;若资金紧可切只反T。
