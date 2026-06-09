# 重构回归测试报告

**测试时间**: 2026-06-08
**测试范围**: 全策略导入、核心策略回测、API功能、引擎导入
**数据周期**: 2025-01-01 至 2025-01-31 (15min K线)

---

## 1. 全策略导入测试

| 状态 | 策略名 |
|------|--------|
| PASS | mean_reversion |
| PASS | momentum_breakout |
| PASS | trend_angle_breakout |
| PASS | dollar_trader |
| PASS | dollar_trader_martingale |
| PASS | dollar_trader_martingale_adx |
| PASS | dollar_trader_martingale_sl |
| PASS | adaptive_trend |
| PASS | mean_reversion_martingale |
| PASS | smart_martingale |
| PASS | breakout_grid |

**结果**: 11/11 策略导入成功

---

## 2. 核心策略回测回归测试

| 策略 | 状态 | 交易次数 | 总盈亏 | 最大回撤 | 备注 |
|------|------|----------|--------|----------|------|
| mean_reversion | PASS | 6 | -892.08 | -1.16% | 正常运行 |
| momentum_breakout | PASS | 12 | -53.39 | -1.47% | 正常运行 |
| dollar_trader | **FAIL** | - | - | - | Missing required column: SMA_20 |
| dollar_trader_martingale | **FAIL** | - | - | - | Missing required column: SMA_20 |
| breakout_grid | PASS | 11 | -87.86 | -0.09% | 正常运行 |

### Dollar Trader 系列策略问题说明

**错误信息**:
```
ValueError: Missing required column: SMA_20. Please ensure SMA indicators are calculated.
```

**根因分析**:
- `run_backtest.py` 中的 `add_indicators()` 函数只调用 `add_all_indicators()`，该函数计算的是 `EMA_20/50` 而非 `SMA_20/50/200`
- Dollar Trader 系列策略（dollar_trader、dollar_trader_martingale 等）需要 `SMA_20`、`SMA_50`、`SMA_200` 列
- 这些策略有各自的指标计算函数（如 `calculate_dollar_trader_indicators`），但 `run_backtest.py` 未调用

**影响范围**:
- dollar_trader
- dollar_trader_martingale
- dollar_trader_martingale_adx
- dollar_trader_martingale_sl

**手动验证结果**（补充SMA指标后）:
| 策略 | 交易次数 | 总盈亏 | 最大回撤 |
|------|----------|--------|----------|
| dollar_trader | 38 | -7848.08 | -15.70% |
| dollar_trader_martingale | 38 | -7848.08 | -15.70% |

---

## 3. API功能测试

| 状态 | 测试项 |
|------|--------|
| PASS | FastAPI路由可导入（需 `sys.path.insert(0, 'web/backend')`） |

**注意**: `web/backend/main.py` 使用相对导入 `from api.dollar_trader import router`，直接运行会报 `ModuleNotFoundError: No module named 'api'`。需要在 `web/backend` 目录下运行或通过 `sys.path` 添加路径。

---

## 4. 引擎导入测试

| 状态 | 引擎 |
|------|------|
| PASS | BaseBacktestEngine |
| PASS | CandleBacktestEngine |
| PASS | TickBacktestEngine |
| PASS | DollarTraderBacktestEngine |
| PASS | BreakoutGridEngine |

**结果**: 5/5 引擎导入成功

---

## 5. Bug汇总

| 优先级 | 问题 | 影响 |
|--------|------|------|
| **P1** | `run_backtest.py` 未为 Dollar Trader 系列策略计算 SMA 指标 | dollar_trader、dollar_trader_martingale 等策略无法通过 `run_backtest.py` 运行 |
| **P2** | `web/backend/main.py` 相对导入问题 | API 服务启动可能失败，需确保工作目录正确 |

---

## 6. 结论

- **通过**: mean_reversion、momentum_breakout、breakout_grid 策略回测正常
- **失败**: dollar_trader、dollar_trader_martingale 因指标计算缺失无法运行（手动补充指标后可运行）
- **建议**: 修复 `run_backtest.py` 的 `add_indicators()` 函数，根据策略类型调用对应的指标计算函数
