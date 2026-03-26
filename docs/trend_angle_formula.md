# 趋势角度突破策略 (Trend Angle Breakout)

## 数学公式

### 1. SMA角度计算（量纲标准化）

由于价格（~2700美元）和时间（K线根数）量纲不同，直接使用 `atan(Δprice/bars)` 会严重失真。

**标准化公式**:

$$
\theta_t = \arctan\left(\frac{SMA_t - SMA_{t-n}}{ATR_t \times n}\right) \times \frac{180}{\pi}
$$

其中:
- $\theta_t$: 当前时刻的SMA角度（度）
- $SMA_t$: 当前SMA值
- $SMA_{t-n}$: n根K线前的SMA值
- $ATR_t$: 当前ATR值
- $n$: 回看K线数（默认5）

**标准化意义**:
- 分子 $SMA_t - SMA_{t-n}$: 价格变化（美元）
- 分母 $ATR_t \times n$: 将时间转换为"等效美元波动"
- 结果: 无量纲比率，角度范围 -90° 到 +90°

### 2. 进场条件

**做多条件**:
```
IF (θ_t > θ_threshold) AND (High_t > MAX(High[t-1], High[t-2]))
    THEN LONG
```

**做空条件**:
```
IF (θ_t < -θ_threshold) AND (Low_t < MIN(Low[t-1], Low[t-2]))
    THEN SHORT
```

默认参数:
- $\theta_{threshold}$ = 3°
- 突破回看 = 2根K线

### 3. 出场条件

**固定盈亏比模式**:
- 止损: $SL = Entry \pm ATR \times trailing\_mult$
- 止盈: $TP = Entry \mp ATR \times trailing\_mult \times RR$

**反向信号出场**:
- 当出现反向信号时，平掉当前持仓并反向开仓

### 4. 成本模型

**点差成本** (Spread):
- 20 points = 0.20美元/盎司
- 每手成本 = $0.20 \times 100 = $20

**滑点成本** (Slippage):
- 10 points = 0.10美元
- 入场: +slippage (买高卖低)
- 止损出场: slippage × 2 (流动性枯竭)
- 止盈出场: 0 (限价单无滑点)

**佣金** (Commission):
- $3.5/手/单边
- 往返 = $7/手

### 5. 回测统计指标

**Calmar Ratio** (优化目标):
$$
Calmar = \frac{Annual\ Return}{Max\ Drawdown}
$$

**Sharpe Ratio**:
$$
Sharpe = \frac{R_p - R_f}{\sigma_p} \times \sqrt{252 \times 24 \times 4}
$$

**Profit Factor**:
$$
PF = \frac{\sum_{wins} PnL}{|\sum_{losses} PnL|}
$$

---

## 数据与回测周期

| 项目 | 配置 |
|------|------|
| 品种 | XAUUSD (现货黄金) |
| 周期 | 15分钟K线 |
| 数据源 | Dukascopy Tick数据 |
| IS样本内 | 2025-01-01 ~ 2025-10-31 |
| OOS样本外 | 2025-11-01 ~ 2026-02-28 |
| 优化方法 | Optuna TPE + Walk-Forward |

---

## 参数优化范围

| 参数 | 类型 | 范围 | 默认值 |
|------|------|------|--------|
| sma_period | int | [10, 50] | 20 |
| angle_lookback | int | [3, 10] | 5 |
| angle_threshold | float | [1.0, 10.0] | 3.0 |
| **breakout_lookback** | **int** | **[1, 10]** | **2** |
| risk_reward_ratio | float | [1.0, 4.0] | 2.0 |
| trailing_stop_atr | float | [1.0, 4.0] | 2.0 |
| atr_period | int | [10, 20] | 14 |

---

## 文件结构

```
xauusd_backtest/
├── core/indicators.py                    # 新增: SMA角度计算函数
├── strategies/
│   ├── trend_angle_breakout.py           # 新增: 策略实现
│   └── __init__.py                       # 更新: 注册新策略
├── run_trend_angle_backtest.py           # 新增: 回测入口
├── run_trend_angle_optimization.py       # 新增: 优化入口
└── docs/
    └── trend_angle_formula.md            # 本文档
```

---

## 使用方法

### 1. 运行回测

```bash
# IS样本内回测
python run_trend_angle_backtest.py --mode is --sma-period 20 --angle-threshold 3.0

# OOS样本外回测
python run_trend_angle_backtest.py --mode oos

# 全周期回测
python run_trend_angle_backtest.py --mode full
```

### 2. 运行贝叶斯优化

```bash
# 完整优化 (300 trials + Walk-Forward)
python run_trend_angle_optimization.py --trials 300

# 快速优化 (100 trials, 无Walk-Forward)
python run_trend_angle_optimization.py --trials 100 --no-walk-forward
```

---

## 策略特点

1. **量纲标准化**: 通过ATR将价格变化标准化，角度计算具有实际意义
2. **趋势确认**: 突破前2根K线高低点，避免假突破
3. **双出场模式**: 支持固定盈亏比和反向信号出场
4. **真实成本**: 包含点差、滑点、佣金
5. **防过拟合**: Walk-Forward验证确保泛化能力

---

## MT4/TradingView 同步要求

当Python策略验证有效后，必须同步改写为:
- **MT4**: MQL4 EA代码
- **TradingView**: Pine Script v6

**一致性要求**: 三种代码的数学公式和参数必须完全一致
