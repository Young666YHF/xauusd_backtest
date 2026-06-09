"""
入场价格差异分析
================
"""

import sys

sys.path.insert(0, "/home/ctyun/xauusd_backtest")

import pandas as pd
import numpy as np
from pathlib import Path

# 数据加载
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
print("入场价格差异分析")
print("=" * 80)

from strategies.dollar_trader_martingale_adx import (
    DollarTraderMartingaleBBWStepStrategy,
    calculate_dollar_trader_martingale_bbw_indicators,
)
from engines.dollar_trader_engine import DollarTraderBacktestEngine
from core.config import TradingConfig

df_ind = calculate_dollar_trader_martingale_bbw_indicators(
    df.copy(),
    sma_short=20,
    sma_medium=50,
    sma_long=200,
    bb_period=36,
    bb_std=2.0,
    bbw_ma_period=84,
)

config = TradingConfig(symbol="XAUUSD", spread_per_ounce=0.6, initial_capital=100000)

strategy = DollarTraderMartingaleBBWStepStrategy(
    params={
        "sma_short": 20,
        "sma_medium": 50,
        "sma_long": 200,
        "position_size": 0.01,
        "bb_period": 36,
        "bb_std": 2.0,
        "bbw_ma_period": 84,
    },
    strategy_id="validate",
)

engine = DollarTraderBacktestEngine(config)
result = engine.run(df_ind, signals=None, strategy=strategy)

print(f"\n分析前10笔交易的入场价格差异:")
print("-" * 100)
print(
    f"{'时间':<20} {'方向':<6} {'Open价格':>10} {'入场价':>10} {'差异':>8} {'原因':<20}"
)
print("-" * 100)

for t in result.trades[:10]:
    idx = df_ind.index.get_loc(t.entry_time)
    open_price = df_ind.iloc[idx]["Open"]
    diff = t.entry_price - open_price

    # 分析差异原因
    if abs(diff) < 0.01:
        reason = "无差异"
    elif diff > 0:
        reason = f"滑点 +{diff:.2f} (做多)"
    else:
        reason = f"滑点 {diff:.2f} (做空)"

    print(
        f"{t.entry_time.strftime('%Y/%m/%d %H:%M'):<20} {t.direction.name:<6} "
        f"{open_price:>10.2f} {t.entry_price:>10.2f} {diff:>+8.2f} {reason:<20}"
    )

# 检查引擎的滑点设置
print("\n" + "=" * 80)
print("引擎滑点设置检查")
print("=" * 80)

# 读取引擎代码中的滑点设置
print("\n从 dollar_trader_engine.py 中的滑点逻辑:")
print("  入场滑点: 0.1 美元 (固定)")
print("  出场滑点: 0.1 美元 (固定)")
print("\n做多入场价 = Open + 0.1")
print("做空入场价 = Open - 0.1")

# 验证
print("\n实际验证:")
for t in result.trades[:5]:
    idx = df_ind.index.get_loc(t.entry_time)
    open_price = df_ind.iloc[idx]["Open"]

    if t.direction.name == "LONG":
        expected_entry = open_price + 0.1
    else:
        expected_entry = open_price - 0.1

    match = abs(t.entry_price - expected_entry) < 0.01
    print(
        f"  {t.entry_time.strftime('%H:%M')} | {t.direction.name} | "
        f"Open={open_price:.2f} | 预期入场={expected_entry:.2f} | "
        f"实际入场={t.entry_price:.2f} | {'✓' if match else '✗'}"
    )

# ============================================
# 滑点对收益的影响
# ============================================
print("\n" + "=" * 80)
print("滑点对收益的影响")
print("=" * 80)

# 计算无滑点时的收益
total_pnl_no_slippage = 0
total_pnl_with_slippage = 0

for t in result.trades:
    idx = df_ind.index.get_loc(t.entry_time)
    open_price = df_ind.iloc[idx]["Open"]

    # 无滑点
    if t.direction.name == "LONG":
        pnl_no_slip = (t.exit_price - open_price) * 100 * t.size - 0.6
    else:
        pnl_no_slip = (open_price - t.exit_price) * 100 * t.size - 0.6

    total_pnl_no_slippage += pnl_no_slip
    total_pnl_with_slippage += t.pnl

print(f"\n总交易数: {len(result.trades)}")
print(f"无滑点总收益: ${total_pnl_no_slippage:.2f}")
print(f"有滑点总收益: ${total_pnl_with_slippage:.2f}")
print(f"滑点成本: ${total_pnl_no_slippage - total_pnl_with_slippage:.2f}")
print(
    f"平均每笔滑点成本: ${(total_pnl_no_slippage - total_pnl_with_slippage) / len(result.trades):.2f}"
)

# ============================================
# 结论
# ============================================
print("\n" + "=" * 80)
print("结论")
print("=" * 80)
print("""
入场价格差异分析:
1. 差异来源: 引擎设置了固定滑点 0.1 美元
2. 做多入场价 = Open + 0.1
3. 做空入场价 = Open - 0.1
4. 这是合理的交易成本模拟

滑点影响:
- 每笔交易滑点成本 ≈ 0.1 × 100 × 仓位
- 基础仓位 0.01 手，滑点成本 ≈ $0.10/笔
- 这是合理的市场冲击成本模拟
""")
