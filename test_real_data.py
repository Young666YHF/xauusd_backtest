"""Test time stop with real data"""
import sys
sys.path.insert(0, '/home/ctyun/xauusd_backtest')

import pandas as pd
import numpy as np
from pathlib import Path

from engines.tick_engine import TickBacktestEngine
from engines.base import ExecutionModel
from core.config import TradingConfig
from strategies.trend_angle_breakout import TrendAngleBreakoutStrategy, calculate_strategy_indicators
from core.data_loader import DataLoader

DATA_DIR = "/home/ctyun/xauusd_data"

print("Loading test data (Jan 2025 only)...")
loader = DataLoader(DATA_DIR)

# Load just January 2025 for quick test
df = loader.load_range(['2025-01'], "15min")
df = df[df.index >= '2025-01-01']
print(f"Loaded {len(df)} bars")

# Load tick data
tick_df = loader.load_tick_data(loader.data_dir / "XAUUSD_2025-01.csv")
tick_df['Mid'] = (tick_df['Bid'] + tick_df['Ask']) / 2
print(f"Loaded {len(tick_df):,} ticks")

# Calculate indicators
df = calculate_strategy_indicators(df, sma_period=20, atr_period=14, angle_lookback=5)

# Create strategy with use_fixed_exit=False (to test time stop without SL/TP)
params = {
    'sma_period': 20,
    'angle_threshold': 3.0,
    'risk_reward_ratio': 2.0,
    'breakout_lookback': 2,
    'use_fixed_exit': False,  # This disables SL/TP, time stop should still work
    'trailing_stop_atr': 2.0,
    'atr_period': 14,
    'position_size': 1.0,
}

strategy = TrendAngleBreakoutStrategy(params=params, strategy_id="Test")

# Generate signals
print("Generating signals...")
signals = []
for i in range(100, len(df)):
    signal = strategy.generate_signal(df, i)
    if signal:
        signals.append(signal)

print(f"Generated {len(signals)} signals")

# Create engine
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

print(f"\n{'='*50}")
print(f"Results: {result.total_trades} trades")
print(f"{'='*50}")

# Check for long-held positions
if result.trades:
    max_bars = max(t.bars_held for t in result.trades)
    avg_bars = sum(t.bars_held for t in result.trades) / len(result.trades)
    print(f"Max bars held: {max_bars}")
    print(f"Avg bars held: {avg_bars:.1f}")

    # Show first few trades
    print(f"\nFirst 5 trades:")
    for t in result.trades[:5]:
        print(f"  {t.direction.name:5} entry={t.entry_time}, bars={t.bars_held}, exit={t.exit_reason.name}")

    # Check if any trade held more than 15 bars (should be time stopped at 10)
    long_trades = [t for t in result.trades if t.bars_held > 15]
    if long_trades:
        print(f"\n⚠ WARNING: {len(long_trades)} trades held >15 bars (time stop not working?)")
        for t in long_trades[:3]:
            print(f"  {t.direction.name:5} bars={t.bars_held}, exit={t.exit_reason.name}")
    else:
        print(f"\n✓ All trades properly time-stopped (max ~10 bars)")
else:
    print("No trades!")
