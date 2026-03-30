# 突破网格策略 (Breakout Grid Strategy)

## 策略概述

以5美元为间隔，从0-10000美元建立虚拟网格的区间突破策略。价格在突破网格线时触发交易，固定止盈，无止损。

## 核心参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| grid_spacing | 5.0 | 网格间隔（美元） |
| coverage_count | 5 | 上下覆盖网格数量 |
| initial_position | 0.01 | 初始仓位（手） |
| take_profit | 5.0 | 止盈距离（美元） |

## 交易逻辑

### 1. 初始化

- 策略启动时，根据当前价格建立初始仓位0.01手
- 如果价格高于当前网格中心，建立多单
- 如果价格低于当前网格中心，建立空单

### 2. 挂单布局

策略始终在**当前价格周围各5个网格**的范围内布置挂单：

- **上方网格**：挂多单（突破做多）
- **下方网格**：挂空单（突破做空）

### 3. 仓位平衡机制

根据多空仓位差异动态调整挂单手数：

| 条件 | 多单挂单数量 | 空单挂单数量 |
|------|--------------|--------------|
| 空单 > 多单 | 差额 + 0.01 | 0.01 |
| 多单 > 空单 | 0.01 | 差额 + 0.01 |
| 平衡 | 0.01 | 0.01 |

### 4. 挂单更新规则

每次tick检查并更新挂单：

1. **新增挂单**：当前价格周围coverage_count个网格内没有挂单的，新增挂单
2. **删除挂单**：超出coverage_count范围的挂单删除
3. **更新手数**：根据仓位平衡机制调整手数
4. **持仓网格跳过**：已有同向持仓的网格，不再挂同向单（可挂反向单）

## 出场机制

- **止盈**：每个仓位固定止盈5美元
- **止损**：无止损

## 网格范围

- 最小价格：0美元
- 最大价格：10,000美元
- 网格数量：2,001个
- 网格索引：0 ~ 2000

## 代码文件

- 策略实现：`strategies/breakout_grid.py`
- 回测引擎：`engines/breakout_grid_engine.py`

## 使用示例

```python
from strategies import BreakoutGridStrategy
from engines.breakout_grid_engine import BreakoutGridEngine
from core.config import TradingConfig

# 创建策略
strategy = BreakoutGridStrategy(params={
    'grid_spacing': 5.0,
    'coverage_count': 5,
    'initial_position': 0.01,
    'take_profit': 5.0,
})

# 创建回测引擎
config = TradingConfig()
engine = BreakoutGridEngine(config)

# 运行回测
result = engine.run(df, strategy=strategy, tick_df=tick_df)
```

## 注意事项

1. 本策略无止损设计，依赖仓位平衡和止盈实现风险控制
2. 建议使用Tick数据回测以获得精确执行结果
3. 网格范围覆盖黄金正常交易区间（0-10000美元）
4. 策略适用于波动行情，震荡区间频繁触发交易

## 更新记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0.0 | 2026-03-30 | 初始版本 |
