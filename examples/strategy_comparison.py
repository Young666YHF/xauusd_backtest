#!/usr/bin/env python3
"""
策略对比示例
============
比较不同策略在同一数据集上的表现
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from tabulate import tabulate

from core.config import Config
from core.data_loader import DataLoader
from core.indicators import add_all_indicators
from strategies import StrategyRegistry
from engines import CandleBacktestEngine


def run_strategy_comparison(months: list):
    """运行策略对比"""
    print("="*60)
    print("Strategy Comparison")
    print("="*60)

    config = Config()
    loader = DataLoader(config.data.data_dir)

    # 加载数据
    try:
        df = loader.load_range(months, config.data.interval)
        print(f"\nLoaded {len(df)} bars from {len(months)} months\n")
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    # 添加指标
    df = add_all_indicators(df)

    # 创建引擎
    engine = CandleBacktestEngine(config.trading)

    # 测试的策略
    strategies = [
        ('mean_reversion', config.strategy.to_dict()),
        ('momentum_breakout', config.strategy.to_dict()),
    ]

    results = []

    for strategy_name, params in strategies:
        print(f"Running {strategy_name}...")

        strategy = StrategyRegistry.create(strategy_name, params)
        result = engine.run_with_strategy(df, strategy, warmup_bars=100)

        results.append({
            'Strategy': strategy_name,
            'Trades': result.total_trades,
            'Win Rate': f"{result.win_rate:.1%}",
            'Total P&L': f"${result.total_pnl:,.0f}",
            'Return': f"{result.total_return:.1%}",
            'Max DD': f"{result.max_drawdown_pct:.1%}",
            'Sharpe': f"{result.sharpe_ratio:.2f}",
            'PF': f"{result.profit_factor:.2f}",
        })

    # 输出对比表格
    print("\n" + "="*60)
    print("Comparison Results")
    print("="*60 + "\n")

    if results:
        print(tabulate(results, headers='keys', tablefmt='grid'))

    # 找出最佳策略
    print("\n" + "="*60)
    print("Summary")
    print("="*60)

    # 按夏普比率排序
    # (这里简化处理，实际应该解析数值)

    return results


def main():
    """主函数"""
    # 测试2025年前3个月
    months = ['2025-01', '2025-02', '2025-03']
    run_strategy_comparison(months)


if __name__ == '__main__':
    try:
        from tabulate import tabulate
    except ImportError:
        print("Installing tabulate...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "tabulate", "-q"])
        from tabulate import tabulate

    main()
