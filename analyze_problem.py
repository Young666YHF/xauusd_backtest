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

# 分析资金曲线的关键阶段
print("资金曲线关键节点分析:")
print("="*80)

# 找到最低点和最高点
min_equity1 = min(result1.equity_curve)
max_equity1 = max(result1.equity_curve)
min_idx1 = result1.equity_curve.index(min_equity1)
max_idx1 = result1.equity_curve.index(max_equity1)

min_equity2 = min(result2.equity_curve)
max_equity2 = max(result2.equity_curve)
min_idx2 = result2.equity_curve.index(min_equity2)
max_idx2 = result2.equity_curve.index(max_equity2)

print(f"\n固定手数:")
print(f"  初始: ${result1.equity_curve[0]:,.2f}")
print(f"  最低: ${min_equity1:,.2f} (bar {min_idx1})")
print(f"  最高: ${max_equity1:,.2f} (bar {max_idx1})")
print(f"  最终: ${result1.equity_curve[-1]:,.2f}")

print(f"\n百分比手数:")
print(f"  初始: ${result2.equity_curve[0]:,.2f}")
print(f"  最低: ${min_equity2:,.2f} (bar {min_idx2})")
print(f"  最高: ${max_equity2:,.2f} (bar {max_idx2})")
print(f"  最终: ${result2.equity_curve[-1]:,.2f}")

# 分析后期的大盈利交易
print(f"\n\n后期大盈利交易分析 (后100笔):")
print("="*80)
start_idx = len(result1.trades) - 100

fixed_wins = [t for t in result1.trades[start_idx:] if t.pnl > 1000]
pct_wins = [t for t in result2.trades[start_idx:] if t.pnl > 500]

print(f"固定手数大盈利交易数量: {len(fixed_wins)}")
print(f"百分比手数大盈利交易数量: {len(pct_wins)}")

if fixed_wins:
    print(f"\n固定手数最大几笔盈利:")
    for t in sorted(fixed_wins, key=lambda x: -x.pnl)[:5]:
        print(f"  {t.exit_time}: ${t.pnl:,.2f}")

if pct_wins:
    print(f"\n百分比手数最大几笔盈利:")
    for t in sorted(pct_wins, key=lambda x: -x.pnl)[:5]:
        print(f"  {t.exit_time}: ${t.pnl:,.2f} (手数: {t.size:.4f})")

# 核心问题：检查资金低点的手数
print(f"\n\n关键问题分析:")
print("="*80)
print("当资金跌到低点时，百分比手数会大幅降低")
print(f"固定手数最低点权益: ${min_equity1:,.2f}, 但始终用1手")
print(f"百分比手数最低点权益: ${min_equity2:,.2f}, 手数会降低到约 {min_equity2/100000*0.02*100:.4f} 手")
print("\n这意味着在后续的反弹中，百分比手数无法充分利用盈利机会!")
