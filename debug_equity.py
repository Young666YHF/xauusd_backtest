#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/ctyun/xauusd_backtest')

import pandas as pd
from strategies.dollar_trader import DollarTraderStrategy, calculate_dollar_trader_indicators
from core.config import TradingConfig
from engines.dollar_trader_engine import DollarTraderBacktestEngine
from pathlib import Path

# 加载数据
kline_dir = Path('/home/ctyun/xauusd_data/kline/15m')
months = [f'2024-{m:02d}' for m in range(1, 13)] + ['2025-01', '2025-02', '2025-03', '2025-04', '2025-05', '2025-06', '2025-07', '2025-08', '2025-09', '2025-10', '2025-11', '2025-12', '2026-01', '2026-02']

dfs = []
for m in months:
    fp = kline_dir / f'XAUUSD_{m}.csv'
    if fp.exists():
        dfs.append(pd.read_csv(fp, index_col=0, parse_dates=True))

ohlc_df = pd.concat(dfs).sort_index()
ohlc_df = ohlc_df[~ohlc_df.index.duplicated(keep='first')]
ohlc_df = ohlc_df.loc['2024-01-01':'2026-02-28']
ohlc_df = calculate_dollar_trader_indicators(ohlc_df)

config = TradingConfig(initial_capital=100000, contract_size=100, spread_per_ounce=0.6, leverage=100)

# 固定手数
strategy1 = DollarTraderStrategy(params={'position_size': 1.0}, strategy_id='DollarTrader')
signals1 = []
for i in range(205, len(ohlc_df)):
    sig = strategy1.generate_signal(ohlc_df, i)
    if sig: signals1.append(sig)

engine1 = DollarTraderBacktestEngine(config)
result1 = engine1.run(ohlc_df, signals1)

# 百分比手数
strategy2 = DollarTraderStrategy(params={'position_size': None, 'risk_per_trade': 0.02}, strategy_id='DollarTrader')
signals2 = []
for i in range(205, len(ohlc_df)):
    sig = strategy2.generate_signal(ohlc_df, i)
    if sig: signals2.append(sig)

engine2 = DollarTraderBacktestEngine(config)
result2 = engine2.run(ohlc_df, signals2)

# 找到第一个出现差异的bar
first_diff_idx = None
for i in range(len(result1.equity_curve)):
    if abs(result1.equity_curve[i] - result2.equity_curve[i]) > 1:
        first_diff_idx = i
        break

print(f"第一个差异出现在 bar index: {first_diff_idx}")
print(f"该位置固定权益: {result1.equity_curve[first_diff_idx]:.2f}")
print(f"该位置百分比权益: {result2.equity_curve[first_diff_idx]:.2f}")

# 检查每笔交易后的累计盈亏
print("\n每笔交易后的累计盈亏对比:")
header = "#    | 固定累计    | 百分比累计  | 固定单笔   | 百分比单笔 | 手数"
print(header)
print("-" * 70)
cum1, cum2 = 0, 0
for i in range(min(20, len(result1.trades))):
    t1 = result1.trades[i]
    t2 = result2.trades[i]
    cum1 += t1.pnl
    cum2 += t2.pnl
    print(f"{i+1:>4} | {cum1:>10.2f} | {cum2:>10.2f} | {t1.pnl:>9.2f} | {t2.pnl:>9.2f} | {t2.size:.4f}")

# 关键检查：查看资金曲线的最大差异点
max_diff = 0
max_diff_idx = 0
for i in range(len(result1.equity_curve)):
    diff = result1.equity_curve[i] - result2.equity_curve[i]
    if diff > max_diff:
        max_diff = diff
        max_diff_idx = i

print(f"\n最大差异出现在 bar {max_diff_idx}: ${max_diff:,.2f}")
print(f"固定权益: ${result1.equity_curve[max_diff_idx]:,.2f}")
print(f"百分比权益: ${result2.equity_curve[max_diff_idx]:,.2f}")
