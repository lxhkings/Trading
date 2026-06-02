# Trading

港美股底仓做T系统：富途取行情 → 策略信号 → IB 执行 → 风控熔断。三进程 + Redis 事件总线。

## 核心概念

**做T**：在持有底仓的基础上，日内高抛低吸赚取差价，收盘归零 T 仓位。

- **底仓**：长期持有的股票数量（base_qty）
- **T仓**：日内增减的股数（t_position），范围 [-t_pool, +t_pool]
- **T池**：t_pool = base_qty × t_ratio（如 400 × 0.25 = 100）

## 系统架构

三进程 + Redis 事件总线：

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   data      │     │   trader    │     │   monitor   │
│  (富途取数) │────►│  (策略执行) │────►│  (日志告警) │
└─────────────┘     └─────────────┘     └─────────────┘
      │                   │                   │
      └───────────────────┴───────────────────┘
                    Redis pub/sub
```

**数据流**：
```
FutuOpenD → FutuDataFeed → Bar → EventBus (bar.*)
                                        ↓
                            TraderEngine.on_bar()
                                        ↓
                    MeanReversionStrategy → Signal
                                        ↓
                    RiskManager.check() → Decision
                                        ↓
                    GridPositionMgr → delta (目标增量)
                                        ↓
                    IBBroker.place_order() → Fill
                                        ↓
                    PnLTracker → 日内盈亏 → 熔断回灌
```

## 进程职责

| 进程 | 入口 | 职责 |
|------|------|------|
| data | `trading/apps/data.py` | 富途订阅 1 分钟 bar → Redis 广播 + Parquet 落库 |
| trader | `trading/apps/trader.py` | 订阅 bar → 策略 → 风控 → 网格 → IB 下单 → 状态持久化 |
| monitor | `trading/apps/monitor.py` | 订阅 fill/alert/signal → jsonl 日志 + 告警打印 |

## 模块结构

### P1 数据层

| 模块 | 职责 |
|------|------|
| `trading/common/models.py` | `Market`/`Bar`/`Side`/`Order`/`Fill` 数据模型 |
| `trading/common/symbolmap.py` | 富途 ↔ IB 标的映射（SymbolSpec + SymbolMap） |
| `trading/common/clock.py` | 港/美股交易时段判定（含港股午休） |
| `trading/common/eventbus.py` | Redis pub/sub + stream（publish_bar/subscribe_bars） |
| `trading/common/state_store.py` | t_position 持久化（Redis hash） |
| `trading/feeds/futu_feed.py` | FutuDataFeed 适配器 + parse_kline_row 纯函数 |
| `trading/storage/bar_store.py` | Parquet 分区落库（market/symbol/day） |

### P2 策略层

| 模块 | 职责 |
|------|------|
| `trading/strategy/indicators.py` | SMA/EMA/RSI/Bollinger/ATR 纯函数 |
| `trading/strategy/signals.py` | MeanReversionStrategy（布林+RSI+VWAP+趋势过滤） |
| `trading/strategy/grid.py` | GridPositionMgr（信号转增量，±t_pool 硬上限） |
| `trading/backtest/pnl.py` | PnLTracker（加权成本法，realized/unrealized） |
| `trading/backtest/engine.py` | 事件回测引擎（逐 bar 模拟，含成本/滑点/收盘归零） |
| `trading/backtest/history.py` | HistoryLoader（富途历史 + Parquet 缓存） |
| `trading/scanner/metrics.py` | 适配性指标（atr_pct/autocorr/avg_turnover） |
| `trading/scanner/scanner.py` | Scanner（回测+过滤+排名+导出 yaml） |
| `trading/apps/scan.py` | Scanner CLI（候选池 → selected.yaml） |

### P3 执行层

| 模块 | 职责 |
|------|------|
| `trading/common/ports.py` | Broker 抽象端口 |
| `trading/brokers/fake_broker.py` | FakeBroker（内存替身，集成测试） |
| `trading/brokers/ib_broker.py` | IBBroker（ib_insync 适配器） |
| `trading/risk/manager.py` | RiskManager（熔断/频率/断线闸门） |
| `trading/trader/order_tracker.py` | OrderTracker（撤单超时 30s） |
| `trading/trader/recovery.py` | recover_t_position + startup_check |
| `trading/trader/engine.py` | TraderEngine（核心闭环） |

## 策略逻辑

**MeanReversionStrategy**（均值回归）：

- **买入信号**：close < lower_bollinger + RSI < 30 + 非 downtrend
- **卖出信号**：close > upper_bollinger + RSI > 70
- **趋势过滤**：downtrend = close < VWAP 且 EMA9 < EMA21 → 禁买只允卖
- **VWAP**：按自然日重置

**GridPositionMgr**：

- 每次 BUY → t_position += grid_step（不超过 +t_pool）
- 每次 SELL → t_position -= grid_step（不低于 -t_pool）
- grid_step = t_pool / grid_n（如 100 / 4 = 25）

## 风控规则

| 规则 | 实现 |
|------|------|
| 日内熔断 | 日亏损 > daily_loss_limit_pct → 只允许减仓 |
| 下单频率 | 同标下单间隔 ≥ min_order_interval_s（默认 60s） |
| 断线拒绝 | IB/Redis 断开 → 拒绝新开仓 |
| 撤单超时 | 限价单 > 30s 未成交 → 自动撤单 |
| T仓上限 | ±t_pool 硬约束（grid 层） |

## 配置文件

| 文件 | 用途 |
|------|------|
| `config/symbols.yaml` | 标的映射（富途代码 → IB symbol/exchange/currency） |
| `config/candidates.yaml` | Scanner 候选池（min_turnover/min_atr_pct/top） |
| `config/selected.yaml` | Scanner 输出（每市场 top 标 + 参数） |

## 使用流程

**1. 离线筛选标的（P2 Scanner）**：
```bash
uv run python -m trading.apps.scan config/candidates.yaml config/selected.yaml
```

**2. 启动三进程（P3）**：
```bash
# 前置：FutuOpenD + Redis + IB Gateway(paper, port 4002)
redis-cli ping
uv run python -m trading.apps.data &
uv run python -m trading.apps.monitor &
IB_PORT=4002 uv run python -m trading.apps.trader
```

**3. 观察一个交易时段**：
- monitor 打印 `[fill.X]` 成交、`[signal.X]` 信号、`[ALERT]` 告警
- IB paper 持仓变化 = base_qty ± t_position
- 撤单超时 → `[ALERT] order_timeout`

## 测试

```bash
uv sync --all-extras        # 安装依赖
uv run pytest -q            # 全量测试（72 tests）
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FUTU_HOST` | 127.0.0.1 | FutuOpenD host |
| `FUTU_PORT` | 11111 | FutuOpenD port |
| `REDIS_HOST` | 127.0.0.1 | Redis host |
| `REDIS_PORT` | 6379 | Redis port |
| `IB_HOST` | 127.0.0.1 | IB Gateway host |
| `IB_PORT` | 7497 | IB Gateway port（paper: 4002, 实盘: 7496） |
| `SYMBOLS_YAML` | config/symbols.yaml | 标的映射配置 |
| `SELECTED_YAML` | config/selected.yaml | Scanner 输出配置 |
| `MONITOR_LOG` | data/monitor.jsonl | monitor 日志路径 |

## 技术栈

- Python 3.11+
- 富途 futu-api（行情）
- ib_insync（IB 执行）
- Redis（事件总线 + 状态存储）
- pandas + pyarrow（Parquet 数据）
- pytest + fakeredis（测试）

## 阶段路线

| 阶段 | 状态 | 内容 |
|------|------|------|
| P1 | ✅ | 数据管道：富途取数 → Bar 模型 → Redis + Parquet |
| P2 | ✅ | 策略层：均值回归信号 + 网格仓位 + 回测 + Scanner |
| P3 | ✅ | 执行层：IB 下单 + 风控熔断 + trader/monitor 进程 |
| P4 | 🔜 | 参数优化：网格寻优 + 多策略组合 |