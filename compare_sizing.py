#!/usr/bin/env python3
"""对比固定手数和百分比手数的回测结果"""
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
print("="*60)
print("固定手数 (1.0手)")
print("="*60)
strategy1 = DollarTraderStrategy(params={'position_size': 1.0}, strategy_id='DollarTrader')
signals1 = []
for i in range(205, len(ohlc_df)):
    sig = strategy1.generate_signal(ohlc_df, i)
    if sig: signals1.append(sig)

engine1 = DollarTraderBacktestEngine(config)
result1 = engine1.run(ohlc_df, signals1)
print(f"总盈亏: ${result1.total_pnl:,.2f}")
print(f"交易次数: {result1.total_trades}")

# 百分比手数
print("\n" + "="*60)
print("百分比手数 (risk_per_trade=0.02)")
print("="*60)
strategy2 = DollarTraderStrategy(params={'position_size': None, 'risk_per_trade': 0.02}, strategy_id='DollarTrader')
signals2 = []
for i in range(205, len(ohlc_df)):
    sig = strategy2.generate_signal(ohlc_df, i)
    if sig: signals2.append(sig)

engine2 = DollarTraderBacktestEngine(config)
result2 = engine2.run(ohlc_df, signals2)
print(f"总盈亏: ${result2.total_pnl:,.2f}")
print(f"交易次数: {result2.total_trades}")

# 对比前10笔交易
print("\n" + "="*60)
print("前10笔交易对比")
print("="*60)
print(f"{'#':>3} | {'固定盈亏':>10} | {'百分比盈亏':>12} | {'手数':>8} | {'入场价':>10} | {'出场价':>10}")
print("-" * 70)
for i in range(min(10, len(result1.trades))):
    t1 = result1.trades[i]
    t2 = result2.trades[i]
    print(f"{i+1:>3} | ${t1.pnl:>8.2f} | ${t2.pnl:>10.2f} | {t2.size:>8.4f} | {t1.entry_price:>10.2f} | {t1.exit_price:>10.2f}")

print("\n" + "="*60)
print("分析")
print("="*60)
print(f"固定手数终点权益: ${result1.equity_curve[-1]:,.2f}")
print(f"百分比手数终点权益: ${result2.equity_curve[-1]:,.2f}")
print(f"差异: ${result1.equity_curve[-1] - result2.equity_curve[-1]:,.2f}")

# 查看权益曲线变化
print("\n权益曲线前10个点:")
print(f"{'Bar':>5} | {'固定权益':>12} | {'百分比权益':>12} | {'差异':>10}")
print("-" * 50)
for i in range(min(10, len(result1.equity_curve))):
    diff = result1.equity_curve[i] - result2.equity_curve[i]
    print(f"{i:>5} | ${result1.equity_curve[i]:>10.2f} | ${result2.equity_curve[i]:>10.2f} | ${diff:>8.2f}")
