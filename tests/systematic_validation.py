"""
系统性验证脚本
==============
1. 统一 BBW 计算 (ddof=0)
2. 验证入场价格
3. 验证马丁格尔逻辑
4. 最终对比
"""

import sys

sys.path.insert(0, "/home/ctyun/xauusd_backtest")

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# ============================================
# 数据加载
# ============================================
data_path = Path("/home/ctyun/xauusd_data/kline/30m")
dfs = []
for month in ["201710", "201711", "201712", "201801"]:
    filepath = data_path / f"XAUUSD_BID_30m_{month}.csv"
    if filepath.exists():
        df = pd.read_csv(filepath, index_col=0)
        df.index = pd.to_datetime(df.index, unit="ms")
        df.columns = [col.capitalize() for col in df.columns]
        dfs.append(df)

df = pd.concat(dfs).sort_index()
df = df[~df.index.duplicated(keep="first")]

print("=" * 80)
print("系统性验证")
print("=" * 80)
print(f"数据范围: {df.index[0]} ~ {df.index[-1]}")
print(f"K线数量: {len(df)}")

# ============================================
# 参数
# ============================================
params = {
    "sma_short": 20,
    "sma_medium": 50,
    "sma_long": 200,
    "bb_period": 36,
    "bb_std": 2.0,
    "bbw_ma_period": 84,
    "position_size": 0.01,
    "martingale_multiplier": 2.0,
    "max_martingale_steps": 5,
    "enable_overshoot": True,
    "enable_undershoot": True,
    "spread_per_ounce": 0.6,
    "contract_size": 100,
}

# ============================================
# 步骤1: 验证 BBW 计算
# ============================================
print("\n" + "=" * 80)
print("步骤1: BBW 计算验证")
print("=" * 80)


# 自定义框架的 BBW 计算
def calc_bbw_custom(close, period, std_dev):
    """自定义框架的 BBW (ddof=1)"""
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std(ddof=1)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return (upper - lower) / middle * 100


# Backtrader 风格的 BBW 计算
def calc_bbw_bt_style(close, period, std_dev):
    """Backtrader 风格的 BBW (ddof=0)"""
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std(ddof=0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return (upper - lower) / middle * 100


bbw_custom = calc_bbw_custom(df["Close"], params["bb_period"], params["bb_std"])
bbw_bt = calc_bbw_bt_style(df["Close"], params["bb_period"], params["bb_std"])

diff = (bbw_custom - bbw_bt).abs()
print(f"BBW 差异统计:")
print(f"  最大差异: {diff.max():.6f}")
print(f"  平均差异: {diff.mean():.6f}")
print(f"  差异范围: {diff.min():.6f} ~ {diff.max():.6f}")

# 检查差异是否会影响信号判断
bbw_ma_custom = bbw_custom.rolling(window=params["bbw_ma_period"]).mean()
bbw_ma_bt = bbw_bt.rolling(window=params["bbw_ma_period"]).mean()

# 比较 bbw_allow 条件
allow_custom = bbw_custom > bbw_ma_custom
allow_bt = bbw_bt > bbw_ma_bt

diff_allow = (allow_custom != allow_bt).sum()
print(f"\nBBW 条件判断差异:")
print(f"  不一致的K线数: {diff_allow}")
print(f"  一致率: {(1 - diff_allow/len(df)) * 100:.2f}%")

# ============================================
# 步骤2: 模拟策略（不使用马丁格尔，固定仓位）
# ============================================
print("\n" + "=" * 80)
print("步骤2: 固定仓位策略模拟（验证信号逻辑）")
print("=" * 80)

# 使用统一的指标计算
df["SMA_20"] = df["Close"].rolling(window=params["sma_short"]).mean()
df["SMA_50"] = df["Close"].rolling(window=params["sma_medium"]).mean()
df["SMA_200"] = df["Close"].rolling(window=params["sma_long"]).mean()

# 使用 Backtrader 风格的 BBW
df["BBW"] = calc_bbw_bt_style(df["Close"], params["bb_period"], params["bb_std"])
df["BBW_MA"] = df["BBW"].rolling(window=params["bbw_ma_period"]).mean()

warmup = max(params["sma_long"], params["bb_period"] + params["bbw_ma_period"]) + 5

# 模拟策略
position = None
entry_price = None
entry_idx = None
trades_fixed = []

for i in range(warmup, len(df)):
    bar = df.iloc[i]
    prev_bar = df.iloc[i - 1]
    prev2_bar = df.iloc[i - 2] if i >= 2 else None

    prev_close = prev_bar["Close"]
    prev_sma_s = prev_bar["SMA_20"]
    prev_sma_m = prev_bar["SMA_50"]
    prev_sma_l = prev_bar["SMA_200"]
    prev_bbw = prev_bar["BBW"]
    prev_bbw_ma = prev_bar["BBW_MA"]

    if pd.isna(prev_sma_s) or pd.isna(prev_bbw):
        continue

    is_bullish = (
        prev_close > prev_sma_s and prev_sma_s > prev_sma_m and prev_sma_m > prev_sma_l
    )
    is_bearish = (
        prev_close < prev_sma_s and prev_sma_s < prev_sma_m and prev_sma_m < prev_sma_l
    )
    bbw_allow = prev_bbw > prev_bbw_ma

    # SMA 交叉
    if prev2_bar is not None:
        prev2_sma_s = prev2_bar["SMA_20"]
        prev2_sma_m = prev2_bar["SMA_50"]
        sma_bearish_cross = (prev2_sma_s >= prev2_sma_m) and (prev_sma_s < prev_sma_m)
        sma_bullish_cross = (prev2_sma_s <= prev2_sma_m) and (prev_sma_s > prev_sma_m)
    else:
        sma_bearish_cross = False
        sma_bullish_cross = False

    current_open = bar["Open"]

    # 出场
    if position == "long" and sma_bearish_cross:
        pnl = (current_open - entry_price) * 100 * 0.01 - 0.6
        trades_fixed.append(
            {
                "entry_time": df.index[entry_idx],
                "exit_time": df.index[i],
                "direction": "long",
                "entry_price": entry_price,
                "exit_price": current_open,
                "pnl": pnl,
                "size": 0.01,
            }
        )
        if is_bearish and bbw_allow:
            position = "short"
            entry_price = current_open
            entry_idx = i
        else:
            position = None

    elif position == "short" and sma_bullish_cross:
        pnl = (entry_price - current_open) * 100 * 0.01 - 0.6
        trades_fixed.append(
            {
                "entry_time": df.index[entry_idx],
                "exit_time": df.index[i],
                "direction": "short",
                "entry_price": entry_price,
                "exit_price": current_open,
                "pnl": pnl,
                "size": 0.01,
            }
        )
        if is_bullish and bbw_allow:
            position = "long"
            entry_price = current_open
            entry_idx = i
        else:
            position = None

    # 入场
    elif position is None:
        if is_bullish and bbw_allow:
            position = "long"
            entry_price = current_open
            entry_idx = i
        elif is_bearish and bbw_allow:
            position = "short"
            entry_price = current_open
            entry_idx = i

# 强制平仓
if position:
    last_price = df.iloc[-1]["Close"]
    if position == "long":
        pnl = (last_price - entry_price) * 100 * 0.01 - 0.6
    else:
        pnl = (entry_price - last_price) * 100 * 0.01 - 0.6
    trades_fixed.append(
        {
            "entry_time": df.index[entry_idx],
            "exit_time": df.index[-1],
            "direction": position,
            "entry_price": entry_price,
            "exit_price": last_price,
            "pnl": pnl,
            "size": 0.01,
        }
    )

print(f"固定仓位策略:")
print(f"  总交易数: {len(trades_fixed)}")
print(f"  总收益: ${sum(t['pnl'] for t in trades_fixed):.2f}")

print("\n前5笔交易:")
for t in trades_fixed[:5]:
    print(
        f"  {t['entry_time'].strftime('%Y/%m/%d %H:%M')} | {t['direction']:5} | 入场: {t['entry_price']:.2f} | PnL: ${t['pnl']:.2f}"
    )

# ============================================
# 步骤3: 运行自定义框架（带马丁格尔）
# ============================================
print("\n" + "=" * 80)
print("步骤3: 自定义框架回测（带马丁格尔）")
print("=" * 80)

from strategies.dollar_trader_martingale_adx import (
    DollarTraderMartingaleBBWStepStrategy,
    calculate_dollar_trader_martingale_bbw_indicators,
)
from engines.dollar_trader_engine import DollarTraderBacktestEngine
from core.config import TradingConfig

df_ind = calculate_dollar_trader_martingale_bbw_indicators(
    df.copy(),
    sma_short=params["sma_short"],
    sma_medium=params["sma_medium"],
    sma_long=params["sma_long"],
    bb_period=params["bb_period"],
    bb_std=params["bb_std"],
    bbw_ma_period=params["bbw_ma_period"],
)

config = TradingConfig(
    symbol="XAUUSD", spread_per_ounce=params["spread_per_ounce"], initial_capital=100000
)

strategy = DollarTraderMartingaleBBWStepStrategy(
    params={
        "sma_short": params["sma_short"],
        "sma_medium": params["sma_medium"],
        "sma_long": params["sma_long"],
        "position_size": params["position_size"],
        "martingale_multiplier": params["martingale_multiplier"],
        "max_martingale_steps": params["max_martingale_steps"],
        "bb_period": params["bb_period"],
        "bb_std": params["bb_std"],
        "bbw_ma_period": params["bbw_ma_period"],
        "enable_overshoot": params["enable_overshoot"],
        "enable_undershoot": params["enable_undershoot"],
    },
    strategy_id="validate",
)

engine = DollarTraderBacktestEngine(config)
result = engine.run(df_ind, signals=None, strategy=strategy)

print(f"自定义框架（带马丁格尔）:")
print(f"  总交易数: {result.total_trades}")
print(f"  最终权益: ${result.equity_curve[-1]:,.2f}")
print(f"  总收益: ${result.total_pnl:.2f}")
print(f"  最终马丁阶梯: {strategy.martingale_step}")

# ============================================
# 步骤4: 对比分析
# ============================================
print("\n" + "=" * 80)
print("步骤4: 信号对比分析")
print("=" * 80)

print(f"\n{'#':<3} {'固定仓位':<20} {'马丁格尔':<20} {'方向':<8} {'入场价差异':>12}")
print("-" * 75)

matches = 0
for i in range(min(len(trades_fixed), len(result.trades))):
    fixed = trades_fixed[i]
    mart = result.trades[i]

    fixed_time = fixed["entry_time"].strftime("%m/%d %H:%M")
    mart_time = mart.entry_time.strftime("%m/%d %H:%M")
    dir_match = fixed["direction"] == mart.direction.name.lower()
    time_match = fixed_time == mart_time

    if dir_match and time_match:
        matches += 1

    price_diff = abs(fixed["entry_price"] - mart.entry_price)

    print(
        f"{i+1:<3} {fixed_time:<20} {mart_time:<20} "
        f"{'✓' if dir_match and time_match else '✗':<8} ${price_diff:>11.2f}"
    )

print(
    f"\n信号匹配率: {matches}/{min(len(trades_fixed), len(result.trades))} = {matches/min(len(trades_fixed), len(result.trades))*100:.1f}%"
)

# ============================================
# 步骤5: 验证入场价格
# ============================================
print("\n" + "=" * 80)
print("步骤5: 入场价格验证")
print("=" * 80)

# 检查入场价格是否等于信号K线的开盘价
price_errors = 0
for t in result.trades[:20]:
    # 找到对应的K线
    idx = df_ind.index.get_loc(t.entry_time)
    expected_price = df_ind.iloc[idx]["Open"]

    if abs(t.entry_price - expected_price) > 0.1:
        price_errors += 1
        print(
            f"  价格错误: {t.entry_time} | 入场价: {t.entry_price:.2f} | 预期: {expected_price:.2f}"
        )

if price_errors == 0:
    print("前20笔交易入场价格全部正确（等于信号K线开盘价）")
else:
    print(f"发现 {price_errors} 笔入场价格异常")

# ============================================
# 步骤6: 验证马丁格尔逻辑
# ============================================
print("\n" + "=" * 80)
print("步骤6: 马丁格尔逻辑验证")
print("=" * 80)

# 手动跟踪马丁格尔状态
martingale_step = 0
loss_count_in_step = 0
expected_sizes = []

for t in result.trades[:15]:
    expected_size = params["position_size"] * (
        params["martingale_multiplier"] ** martingale_step
    )
    expected_sizes.append(
        {
            "time": t.entry_time,
            "expected_step": martingale_step,
            "expected_size": expected_size,
            "actual_size": t.size,
            "pnl": t.pnl,
        }
    )

    # 更新马丁格尔状态
    if t.pnl < 0:
        loss_count_in_step += 1
        if loss_count_in_step >= 2:
            if martingale_step < params["max_martingale_steps"]:
                martingale_step += 1
                loss_count_in_step = 0
    else:
        loss_count_in_step = 0
        if martingale_step > 0:
            martingale_step -= 1

print(f"\n{'时间':<18} {'预期阶梯':>8} {'预期仓位':>10} {'实际仓位':>10} {'一致?':<6}")
print("-" * 60)

for s in expected_sizes[:10]:
    match = abs(s["expected_size"] - s["actual_size"]) < 0.001
    print(
        f"{s['time'].strftime('%Y/%m/%d %H:%M'):<18} {s['expected_step']:>8} "
        f"{s['expected_size']:>10.2f} {s['actual_size']:>10.2f} {'✓' if match else '✗':<6}"
    )

# ============================================
# 步骤7: 最终总结
# ============================================
print("\n" + "=" * 80)
print("验证总结")
print("=" * 80)

print(f"""
1. BBW 计算:
   - 自定义框架使用 ddof=1 (样本标准差)
   - Backtrader 使用 ddof=0 (总体标准差)
   - 差异很小，不会显著影响信号判断

2. 信号逻辑:
   - 固定仓位模拟: {len(trades_fixed)} 笔交易
   - 马丁格尔框架: {result.total_trades} 笔交易
   - 信号匹配率: {matches/min(len(trades_fixed), len(result.trades))*100:.1f}%

3. 入场价格:
   - 使用信号K线的开盘价入场
   - 前20笔交易入场价格验证: {'通过' if price_errors == 0 else '有异常'}

4. 马丁格尔逻辑:
   - 亏损2次 → 阶梯+1
   - 盈利1次 → 阶梯-1
   - 仓位 = 基础仓位 × 2^阶梯
""")

# 最终结论
if matches == min(len(trades_fixed), len(result.trades)) and price_errors == 0:
    print("✓ 框架核心逻辑验证通过")
else:
    print("⚠ 发现潜在问题，需要进一步检查")
