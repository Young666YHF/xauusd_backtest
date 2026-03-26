"""
分析未成交信号
==============
详细分析信号生成与实际成交之间的差异
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from strategies.trend_angle_breakout import (
    TrendAngleBreakoutStrategy,
    calculate_strategy_indicators
)
from core.data_loader import DataLoader

# 配置
DATA_DIR = "/home/ctyun/xauusd_data"
START_DATE = "2025-01-01"
END_DATE = "2025-10-31"


def load_data():
    """加载数据"""
    print(f"Loading data from {START_DATE} to {END_DATE}...")

    loader = DataLoader(DATA_DIR)

    start_dt = pd.to_datetime(START_DATE)
    end_dt = pd.to_datetime(END_DATE)

    months = []
    current = start_dt.replace(day=1)
    while current <= end_dt:
        months.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    df = loader.load_range(months, "15min")
    df = df[(df.index >= START_DATE) & (df.index <= END_DATE)]

    print(f"Loaded {len(df)} 15min bars")

    # 计算指标
    df = calculate_strategy_indicators(df, sma_period=20, atr_period=14, angle_lookback=5)

    return df


def analyze_signals():
    """分析所有信号，找出未成交的原因"""

    df = load_data()

    # 创建策略
    strategy = TrendAngleBreakoutStrategy(
        params={
            'sma_period': 20,
            'angle_threshold': 3.0,
            'risk_reward_ratio': 2.0,
            'use_fixed_exit': True,
        },
        strategy_id="TrendAngleBreakout"
    )

    # 生成所有信号
    print("\nGenerating signals...")
    signals = []
    warmup_bars = 100

    for i in range(warmup_bars, len(df)):
        signal = strategy.generate_signal(df, i)
        if signal:
            signals.append({
                'timestamp': signal.timestamp,
                'direction': signal.direction.name,
                'entry_price': signal.entry_price,
                'stop_loss': signal.stop_loss,
                'take_profit': signal.take_profit,
                'reason': signal.reason,
                'signal_bar_idx': signal.signal_bar_index,
                'execution_bar_idx': signal.execution_bar_index,
            })

    print(f"Total signals generated: {len(signals)}")

    # 将信号转换为DataFrame便于分析
    signals_df = pd.DataFrame(signals)

    # 模拟入场过滤逻辑（与回测引擎一致）
    print("\nAnalyzing signal execution...")

    executed = []
    skipped = []

    for sig in signals:
        idx = sig['execution_bar_idx']

        if idx >= len(df):
            skipped.append({**sig, 'skip_reason': 'Execution index out of range (end of data)'})
            continue

        bar = df.iloc[idx]
        direction = sig['direction']
        entry_price = sig['entry_price']
        stop_loss = sig['stop_loss']

        # 检查1: 价格是否在K线范围内
        price_valid = bar['Low'] <= entry_price <= bar['High']

        # 检查2: 止损是否立即触发（开盘跳空）- 仅在存在止损时检查
        stop_immediate = False
        if stop_loss is not None:
            if direction == 'LONG' and bar['Open'] <= stop_loss:
                stop_immediate = True
            if direction == 'SHORT' and bar['Open'] >= stop_loss:
                stop_immediate = True

        # 检查3: 是否有持仓冲突（简化假设）
        # 实际回测中还会检查是否有未平仓持仓

        if not price_valid:
            skipped.append({
                **sig,
                'skip_reason': f'Entry price {entry_price:.2f} outside bar range [{bar["Low"]:.2f}, {bar["High"]:.2f}]',
                'bar_open': bar['Open'],
                'bar_high': bar['High'],
                'bar_low': bar['Low'],
                'bar_close': bar['Close'],
            })
        elif stop_immediate:
            skipped.append({
                **sig,
                'skip_reason': f'Stop loss would trigger immediately on open ({bar["Open"]:.2f} vs SL {stop_loss:.2f})',
                'bar_open': bar['Open'],
                'bar_high': bar['High'],
                'bar_low': bar['Low'],
                'bar_close': bar['Close'],
            })
        else:
            executed.append(sig)

    print(f"\n{'='*70}")
    print("SIGNAL EXECUTION ANALYSIS")
    print(f"{'='*70}")
    print(f"Total signals:      {len(signals)}")
    print(f"Would execute:      {len(executed)}")
    print(f"Would skip:         {len(skipped)}")
    print(f"Difference:         {len(signals) - len(executed)} (vs 420 trades in backtest)")

    # 打印跳过的信号详情
    if skipped:
        print(f"\n{'='*70}")
        print("SKIPPED SIGNALS DETAILS")
        print(f"{'='*70}")

        for i, skip in enumerate(skipped, 1):
            print(f"\n[{i}] {skip['timestamp']} | {skip['direction']}")
            print(f"    Signal reason: {skip['reason'][:60]}...")
            print(f"    Entry price:   {skip['entry_price']:.2f}")
            sl_str = f"{skip['stop_loss']:.2f}" if skip['stop_loss'] is not None else 'None'
            print(f"    Stop loss:     {sl_str}")
            print(f"    Skip reason:   {skip['skip_reason']}")
            if 'bar_open' in skip:
                print(f"    Bar OHLC:      O={skip['bar_open']:.2f} H={skip['bar_high']:.2f} L={skip['bar_low']:.2f} C={skip['bar_close']:.2f}")

    # 统计跳过原因
    print(f"\n{'='*70}")
    print("SKIP REASON SUMMARY")
    print(f"{'='*70}")

    skip_reasons = {}
    for skip in skipped:
        reason = skip['skip_reason'].split(':')[0]  # 取主要部分
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    return signals_df, skipped


if __name__ == "__main__":
    analyze_signals()
