# XAUUSD 量化交易系统

Tick 级回测 + Optuna 优化 + 多策略。

## 全局配置 (`core/config.py`)

所有策略共享的交易配置：

| 参数 | 值 | 说明 |
|------|-----|------|
| **杠杆** | 1000倍 | 高杠杆支持马丁格尔策略 |
| **合约大小** | 100盎司/手 | XAUUSD标准合约 |
| **点差成本** | 0.6美元/盎司 | 每0.01手往返成本=0.6美元 |
| **初始资金** | 100,000美元 | 回测默认初始资金 |
| **爆仓比例** | 50% | 保证金比例低于此值触发爆仓 |

### 成本计算

```
每手总成本 = spread_per_ounce × contract_size = 0.6 × 100 = 60美元/手
每0.01手成本 = 60 × 0.01 = 0.6美元
```

### 马丁格尔策略默认仓位

| 阶梯 | 仓位 | 说明 |
|------|------|------|
| Step 0 | 0.01手 | 基础仓位 |
| Step 1 | 0.02手 | 亏损2次后 |
| Step 2 | 0.04手 | |
| Step 3 | 0.08手 | |
| Step 4 | 0.16手 | |
| Step 5 | 0.32手 | 最大阶梯 |

## 结构

```
xauusd_backtest/
├── core/           # 类型、配置、指标、数据加载
├── strategies/     # 策略模块
├── engines/        # K线引擎、Tick引擎
├── optimizers/     # Optuna 优化器
├── mt4/            # EA 代码
├── pine/           # Pine Script
└── web/            # Web 界面
```

## 策略

| 策略 | 类型 | 时段 | 说明文档 |
|------|------|------|----------|
| MeanReversion | 均值回归 | 亚盘 | - |
| MomentumBreakout | 动量突破 | 欧美盘 | - |
| TrendAngleBreakout | 趋势突破 | 全时段 | - |
| DollarTrader | 价格行为 | 全时段 | - |
| DollarTraderMartingale | 马丁格尔 | 全时段 | - |
| DollarTraderMartingaleADX | 马丁格尔+ADX | 全时段 | - |
| DollarTraderMartingaleBBW | 马丁格尔+BBW阶梯 | 全时段 | - |
| **BreakoutGrid** | **突破网格** | **全时段** | **[查看](strategies/docs/breakout_grid.md)** |

## 新增策略流程

每次新增策略时，按以下流程操作：

1. **创建策略代码**：`strategies/{strategy_name}.py`
2. **创建说明文档**：`strategies/docs/{strategy_name}.md`
3. **更新策略列表**：`strategies/__init__.py` 中导入并注册策略
4. **更新README**：将策略添加到上表，并链接到说明文档
5. **创建专用引擎**（如需）：`engines/{strategy_name}_engine.py`

**后续工作规范**：
- 涉及策略相关工作时，**先读取策略说明文档**
- 策略更新时，**同步更新策略说明文档**
- 说明文档应包含：参数、逻辑、使用示例、注意事项

## 引擎

| 引擎 | 用途 |
|------|------|
| CandleBacktestEngine | 快速验证 |
| TickBacktestEngine | 精确优化 (Numba JIT) |

## 运行

```bash
python run_backtest.py --strategy mean_reversion --start-date 2025-01-01 --end-date 2025-03-31
python run_optimization.py --strategy mean_reversion --n-trials 300
```

## 核心规则

- 数据: Dukascopy, UTC
- 时段: 亚盘 00:00-08:00, 欧美盘 08:00-22:00
- 双引擎同步修改
- 前视偏差防护

## 多平台同步

Python 策略修改后，同步更新 `mt4/` 和 `pine/`。
系统修改后，检查 `web/` 是否需同步。

### 当前平台文件对应关系

| 策略 | Python | MT4 EA | Pine Script |
|------|--------|--------|-------------|
| BreakoutGrid | `strategies/breakout_grid.py` | `mt4/Breakout_Grid.mq4` | `pine/breakout_grid.pine` |
| DollarTraderMartingale | `strategies/dollar_trader_martingale.py` | `mt4/DollarTrader_Martingale.mq4` | `pine/dollar_trader_martingale.pine` |
| DollarTraderMartingaleADX | `strategies/dollar_trader_martingale_adx.py` | `mt4/DollarTrader_Martingale_ADX.mq4` | `pine/dollar_trader_martingale_adx.pine` |
| MeanReversion | `strategies/mean_reversion.py` | - | `pine/mean_reversion.pine` |
| MomentumBreakout | `strategies/momentum_breakout.py` | - | `pine/momentum_breakout.pine` |
| DollarTrader | `strategies/dollar_trader.py` | `mt4/XAUUSD_DollarTrader.mq4` | `pine/dollar_trader.pine` |
