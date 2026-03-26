"""Quick backtest with default parameters to establish baseline"""
import sys
sys.path.insert(0, '/home/ctyun/xauusd_backtest')

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

from engines.tick_engine import TickBacktestEngine
from engines.base import ExecutionModel
from core.config import TradingConfig
from strategies.trend_angle_breakout import TrendAngleBreakoutStrategy, calculate_strategy_indicators
from core.data_loader import DataLoader

DATA_DIR = "/home/ctyun/xauusd_data"

print("=" * 60)
print("Baseline Backtest - Default Parameters")
print("=" * 60)

# Default parameters
params = {
    'sma_period': 20,
    'angle_threshold': 3.0,
    'risk_reward_ratio': 2.0,
    'breakout_lookback': 2,
    'use_fixed_exit': True,
    'trailing_stop_atr': 2.0,
    'atr_period': 14,
    'position_size': 1.0,
}

loader = DataLoader(DATA_DIR)

# IS Period
print("\n[In-Sample: Jan-Oct 2025]")
months = ['2025-01', '2025-02', '2025-03', '2025-04', '2025-05',
          '2025-06', '2025-07', '2025-08', '2025-09', '2025-10']

df = loader.load_range(months, "15min")
df = df[(df.index >= '2025-01-01') & (df.index <= '2025-10-31')]
print(f"Loaded {len(df)} bars")

# Load tick data
print("Loading tick data...")
tick_files = []
for m in months:
    y, mo = m.split('-')
    f = loader.data_dir / f"XAUUSD_{y}-{mo}.csv"
    if f.exists():
        tick_files.append(f)

tick_dfs = [loader.load_tick_data(f) for f in tick_files]
tick_df = pd.concat(tick_dfs)
tick_df['Mid'] = (tick_df['Bid'] + tick_df['Ask']) / 2
tick_df = tick_df[(tick_df.index >= '2025-01-01') & (tick_df.index <= '2025-10-31')]
print(f"Loaded {len(tick_df):,} ticks")

# Calculate indicators
df = calculate_strategy_indicators(df, sma_period=20, atr_period=14, angle_lookback=5)

# Create strategy
strategy = TrendAngleBreakoutStrategy(params=params, strategy_id="TrendAngleBaseline")

# Generate signals
print("Generating signals...")
signals = []
for i in range(100, len(df)):
    signal = strategy.generate_signal(df, i)
    if signal:
        signals.append(signal)
print(f"Generated {len(signals)} signals")

# Create engine and run
config = TradingConfig(
    symbol="XAUUSD",
    contract_size=100,
    spread_per_ounce=0.2,
    commission_per_lot=3.5,
    initial_capital=100000.0,
    leverage=100,
    base_slippage=0.1,
)

execution = ExecutionModel()
engine = TickBacktestEngine(config=config, execution_model=execution, use_numba=False)

# Prepare tick mapping
print("Preparing tick mapping...")
bar_idx_to_ticks = engine.prepare_tick_data(tick_df, df.index)
engine.tick_df = tick_df
engine.bar_idx_to_ticks = bar_idx_to_ticks

# Run backtest
print("Running backtest...")
result = engine.run(df, signals, tick_df)

# Display results
print(f"\n{'='*60}")
print("BASELINE RESULTS")
print(f"{'='*60}")
print(f"Total Trades:     {result.total_trades}")
print(f"Winning Trades:   {result.winning_trades}")
print(f"Losing Trades:    {result.losing_trades}")
print(f"Win Rate:         {result.win_rate:.2%}")
print(f"Profit Factor:    {result.profit_factor:.2f}")
print(f"Total Return:     {result.total_return:.2%}")
print(f"Max Drawdown:     {result.max_drawdown_pct:.2%}")
print(f"Sharpe Ratio:     {result.sharpe_ratio:.2f}")

if result.max_drawdown_pct != 0:
    calmar = result.total_return / abs(result.max_drawdown_pct)
    print(f"Calmar Ratio:     {calmar:.2f}")

# Check trade distribution
if result.trades:
    long_trades = [t for t in result.trades if t.direction.name == 'LONG']
    short_trades = [t for t in result.trades if t.direction.name == 'SHORT']
    print(f"\nLong Trades:  {len(long_trades)}")
    print(f"Short Trades: {len(short_trades)}")

    # Exit reasons
    from collections import Counter
    exit_reasons = Counter(t.exit_reason.name for t in result.trades)
    print(f"\nExit Reasons:")
    for reason, count in exit_reasons.most_common():
        print(f"  {reason}: {count}")

print(f"\n{'='*60}")
