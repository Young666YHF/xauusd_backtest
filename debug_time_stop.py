"""Quick debug test for time stop logic"""
import sys
sys.path.insert(0, '/home/ctyun/xauusd_backtest')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from engines.tick_engine import TickBacktestEngine
from engines.base import ExecutionModel
from core.config import TradingConfig
from core.types import TradeSignal, TradeDirection, SignalType

# Create minimal test data - 20 bars
np.random.seed(42)
dates = pd.date_range(start='2025-01-01', periods=20, freq='15min')
df = pd.DataFrame({
    'Open': 2650 + np.random.randn(20) * 0.5,
    'High': 2651 + np.random.randn(20) * 0.5,
    'Low': 2649 + np.random.randn(20) * 0.5,
    'Close': 2650 + np.random.randn(20) * 0.5,
    'Volume': np.random.randint(1000, 5000, 20),
    'ATR': np.ones(20) * 2.0,  # Fixed ATR for simplicity
}, index=dates)

# Create tick data - simple one tick per bar
tick_dates = []
tick_bids = []
tick_asks = []
for i, d in enumerate(dates):
    tick_dates.append(d)
    tick_bids.append(df['Close'].iloc[i] - 0.1)
    tick_asks.append(df['Close'].iloc[i] + 0.1)

tick_df = pd.DataFrame({
    'Bid': tick_bids,
    'Ask': tick_asks,
    'Mid': [(b+a)/2 for b,a in zip(tick_bids, tick_asks)]
}, index=tick_dates)

# Create config
config = TradingConfig(
    symbol="XAUUSD",
    contract_size=100,
    spread_per_ounce=0.2,
    commission_per_lot=3.5,
    initial_capital=100000.0,
    leverage=100,
    base_slippage=0.1,
)

# Create signal at bar 5
signal = TradeSignal(
    timestamp=dates[5],
    direction=TradeDirection.LONG,
    entry_price=df['Close'].iloc[5],
    size=1.0,
    stop_loss=df['Close'].iloc[5] - 5.0,  # Far stop
    take_profit=df['Close'].iloc[5] + 5.0,  # Far take profit - won't hit
    strategy_id="TestStrategy",
    signal_type=SignalType.LONG,
    signal_bar_index=5,
    execution_bar_index=5
)

# Create engine
execution = ExecutionModel()
engine = TickBacktestEngine(config=config, execution_model=execution, use_numba=False)

# Prepare tick mapping
bar_idx_to_ticks = engine.prepare_tick_data(tick_df, df.index)
engine.tick_df = tick_df
engine.bar_idx_to_ticks = bar_idx_to_ticks

print(f"Bar mapping (first 10): {bar_idx_to_ticks[:10]}")
print(f"Signal at bar index: {signal.execution_bar_index}")
print(f"Total bars: {len(df)}")
print()

# Run backtest
result = engine.run(df, [signal], tick_df)

print(f"Trades executed: {result.total_trades}")
if result.trades:
    trade = result.trades[0]
    print(f"Entry: {trade.entry_time} @ {trade.entry_price:.2f}")
    print(f"Exit: {trade.exit_time} @ {trade.exit_price:.2f}")
    print(f"Bars held: {trade.bars_held}")
    print(f"Exit reason: {trade.exit_reason}")
    print(f"Expected: TIME_STOP after 10 bars")
    print()
    if trade.bars_held == 10:
        print("✓ PASS: Time stop working correctly (closed at exactly 10 bars)")
    elif trade.bars_held < 10:
        print("✗ FAIL: Time stop triggered too early!")
    else:
        print(f"✗ FAIL: Time stop triggered late ({trade.bars_held} bars)")
else:
    print("No trades recorded!")
