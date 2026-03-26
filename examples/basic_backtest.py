#!/usr/bin/env python3
"""
基础回测示例
============
演示如何使用重构后的系统进行简单回测
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime

from core.config import Config
from core.data_loader import DataLoader
from core.indicators import add_all_indicators
from strategies import StrategyRegistry
from engines import CandleBacktestEngine


def main():
    """运行示例回测"""
    print("="*60)
    print("Basic Backtest Example")
    print("="*60)

    # 加载配置
    config = Config()

    # 加载数据
    loader = DataLoader(config.data.data_dir)

    # 尝试加载一个月的数据
    try:
        df = loader.load_monthly_data(2025, 1, config.data.interval)
        print(f"\nLoaded {len(df)} bars")
    except FileNotFoundError as e:
        print(f"\nData file not found: {e}")
        print("Please make sure you have data in /home/ctyun/xauusd_data")
        return

    # 添加指标
    df = add_all_indicators(df)
    print("Indicators calculated")

    # 创建策略
    strategy = StrategyRegistry.create(
        'mean_reversion',
        config.strategy.to_dict(),
        strategy_id='MeanReversion_A'
    )
    print(f"\nStrategy: {strategy.strategy_id}")

    # 创建回测引擎
    engine = CandleBacktestEngine(config.trading)
    print("Engine created")

    # 运行回测
    print("\nRunning backtest...")
    result = engine.run_with_strategy(df, strategy, warmup_bars=100)

    # 输出结果
    print("\n" + "="*60)
    print("Results")
    print("="*60)
    print(f"Total Trades:   {result.total_trades}")
    print(f"Winning:        {result.winning_trades}")
    print(f"Losing:         {result.losing_trades}")
    print(f"Win Rate:       {result.win_rate:.2%}")
    print(f"Total P&L:      ${result.total_pnl:,.2f}")
    print(f"Return:         {result.total_return:.2%}")
    print(f"Max Drawdown:   {result.max_drawdown_pct:.2%}")
    print(f"Sharpe Ratio:   {result.sharpe_ratio:.2f}")
    print(f"Profit Factor:  {result.profit_factor:.2f}")

    if result.trades:
        print(f"\nFirst trade:")
        t = result.trades[0]
        print(f"  Entry: {t.entry_time} @ {t.entry_price:.2f}")
        print(f"  Exit:  {t.exit_time} @ {t.exit_price:.2f}")
        print(f"  P&L:   ${t.pnl:,.2f}")


if __name__ == '__main__':
    main()
