#!/usr/bin/env python3
"""
Dollar Trader 策略贝叶斯优化脚本
支持Walk-Forward验证
"""

import argparse
import sys
import json
import optuna
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple, List

sys.path.insert(0, '/home/ctyun/xauusd_backtest')

from strategies.dollar_trader import DollarTraderStrategy, calculate_dollar_trader_indicators
from engines.dollar_trader_engine import DollarTraderBacktestEngine
from core.config import TradingConfig

# 关闭Optuna日志
optuna.logging.set_verbosity(optuna.logging.WARNING)


def parse_args():
    parser = argparse.ArgumentParser(description='Dollar Trader Bayesian Optimization')
    parser.add_argument('--train-start', type=str, default='2024-01-01')
    parser.add_argument('--train-end', type=str, default='2025-06-30')
    parser.add_argument('--test-start', type=str, default='2025-07-01')
    parser.add_argument('--test-end', type=str, default='2026-02-28')
    parser.add_argument('--n-trials', type=int, default=500)
    parser.add_argument('--target', type=str, default='calmar',
                       choices=['sharpe', 'calmar', 'profit_factor', 'win_rate', 'total_return', 'composite'])
    parser.add_argument('--output', type=str, default='results/dt_optimize.json')
    parser.add_argument('--min-trades', type=int, default=50)
    return parser.parse_args()


def load_kline_data(start_date: str, end_date: str) -> pd.DataFrame:
    """加载15分钟K线数据"""
    kline_dir = Path('/home/ctyun/xauusd_data/kline/15m')

    # 生成月份列表
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    months = []
    current = start
    while current <= end:
        months.append(current.strftime('%Y-%m'))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    dfs = []
    for month_str in months:
        filepath = kline_dir / f'XAUUSD_{month_str}.csv'
        if filepath.exists():
            df = pd.read_csv(filepath, index_col=0, parse_dates=True)
            dfs.append(df)
        else:
            print(f"Warning: File not found: {filepath}")

    if not dfs:
        raise ValueError("No data loaded")

    ohlc_df = pd.concat(dfs).sort_index()
    ohlc_df = ohlc_df[~ohlc_df.index.duplicated(keep='first')]
    ohlc_df = ohlc_df.loc[start_date:end_date]

    return ohlc_df


def calculate_metrics(result) -> Dict[str, float]:
    """计算综合指标"""
    return {
        'sharpe': result.sharpe_ratio,
        'calmar': result.calmar_ratio,
        'profit_factor': result.profit_factor,
        'win_rate': result.win_rate,
        'total_return': result.total_return,
        'max_drawdown_pct': result.max_drawdown_pct,
        'total_trades': result.total_trades,
    }


def create_objective(df: pd.DataFrame, target: str, min_trades: int):
    """创建优化目标函数"""
    config = TradingConfig(
        initial_capital=100000.0,
        contract_size=100,
        spread_per_ounce=0.6,  # $60/手 = $0.6/盎司
    )
    engine = DollarTraderBacktestEngine(config)

    def objective(trial: optuna.Trial) -> float:
        # 定义参数范围
        sma_short = trial.suggest_int('sma_short', 10, 30)
        sma_medium = trial.suggest_int('sma_medium', 30, 70)
        sma_long = trial.suggest_int('sma_long', 100, 300)

        # 确保参数逻辑合理
        if not (sma_short < sma_medium < sma_long):
            return -1e9

        # 计算指标
        df_with_ind = calculate_dollar_trader_indicators(
            df.copy(),
            sma_short=sma_short,
            sma_medium=sma_medium,
            sma_long=sma_long
        )

        # 创建策略
        strategy = DollarTraderStrategy(params={
            'sma_short': sma_short,
            'sma_medium': sma_medium,
            'sma_long': sma_long,
            'position_size': 1.0,
        })

        # 生成信号
        signals = []
        warmup_bars = sma_long + 5
        for i in range(warmup_bars, len(df_with_ind)):
            signal = strategy.generate_signal(df_with_ind, i)
            if signal:
                signals.append(signal)

        if len(signals) < min_trades:
            return -1e6 + len(signals)

        # 运行回测
        result = engine.run(df_with_ind, signals)

        if result.total_trades < min_trades:
            return -1e6 + result.total_trades

        # 根据目标返回适应度
        if target == 'sharpe':
            return result.sharpe_ratio
        elif target == 'calmar':
            return result.calmar_ratio
        elif target == 'profit_factor':
            return result.profit_factor
        elif target == 'win_rate':
            return result.win_rate
        elif target == 'total_return':
            return result.total_return
        else:  # composite
            return (
                result.sharpe_ratio * 0.3 +
                result.calmar_ratio * 0.3 +
                min(result.profit_factor, 3.0) * 0.2 +
                result.win_rate * 0.2
            )

    return objective


def run_optimization(args):
    """运行优化"""
    print(f"\n{'='*70}")
    print(f"Dollar Trader Bayesian Optimization")
    print(f"Target: {args.target}")
    print(f"{'='*70}\n")

    # 加载训练数据
    print(f"Loading training data ({args.train_start} to {args.train_end})...")
    train_df = load_kline_data(args.train_start, args.train_end)
    print(f"Loaded {len(train_df)} bars")

    # 加载测试数据
    print(f"\nLoading test data ({args.test_start} to {args.test_end})...")
    test_df = load_kline_data(args.test_start, args.test_end)
    print(f"Loaded {len(test_df)} bars")

    # 创建优化器
    study = optuna.create_study(
        direction='maximize',
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=10, n_warmup_steps=20)
    )

    # 运行优化
    print(f"\nRunning {args.n_trials} trials...")
    objective = create_objective(train_df, args.target, args.min_trades)
    study.optimize(objective, n_trials=args.n_trials, show_progress_bar=True)

    # 获取最优参数
    best_params = study.best_params
    print(f"\n{'='*70}")
    print("Best Parameters (In-Sample):")
    print(f"{'='*70}")
    for param, value in best_params.items():
        print(f"  {param}: {value}")

    # 使用最优参数运行完整回测
    print(f"\n{'='*70}")
    print("Final Backtest - In-Sample")
    print(f"{'='*70}")

    config = TradingConfig(
        initial_capital=100000.0,
        contract_size=100,
        spread_per_ounce=0.6,
    )
    engine = DollarTraderBacktestEngine(config)

    train_df_ind = calculate_dollar_trader_indicators(
        train_df.copy(),
        sma_short=best_params['sma_short'],
        sma_medium=best_params['sma_medium'],
        sma_long=best_params['sma_long']
    )

    strategy = DollarTraderStrategy(params={
        'sma_short': best_params['sma_short'],
        'sma_medium': best_params['sma_medium'],
        'sma_long': best_params['sma_long'],
        'position_size': 1.0,
    })

    signals = []
    warmup_bars = best_params['sma_long'] + 5
    for i in range(warmup_bars, len(train_df_ind)):
        signal = strategy.generate_signal(train_df_ind, i)
        if signal:
            signals.append(signal)

    is_result = engine.run(train_df_ind, signals)
    is_metrics = calculate_metrics(is_result)

    print(f"Total Trades:     {is_result.total_trades}")
    print(f"Win Rate:         {is_result.win_rate:.2%}")
    print(f"Total Return:     {is_result.total_return:.2%}")
    print(f"Max Drawdown:     {is_result.max_drawdown_pct:.2%}")
    print(f"Sharpe Ratio:     {is_result.sharpe_ratio:.2f}")
    print(f"Calmar Ratio:     {is_result.calmar_ratio:.2f}")
    print(f"Profit Factor:    {is_result.profit_factor:.2f}")

    # 样本外测试
    print(f"\n{'='*70}")
    print("Out-of-Sample Test")
    print(f"{'='*70}")

    test_df_ind = calculate_dollar_trader_indicators(
        test_df.copy(),
        sma_short=best_params['sma_short'],
        sma_medium=best_params['sma_medium'],
        sma_long=best_params['sma_long']
    )

    strategy.reset()
    signals = []
    for i in range(warmup_bars, len(test_df_ind)):
        signal = strategy.generate_signal(test_df_ind, i)
        if signal:
            signals.append(signal)

    oos_result = engine.run(test_df_ind, signals)
    oos_metrics = calculate_metrics(oos_result)

    print(f"Total Trades:     {oos_result.total_trades}")
    print(f"Win Rate:         {oos_result.win_rate:.2%}")
    print(f"Total Return:     {oos_result.total_return:.2%}")
    print(f"Max Drawdown:     {oos_result.max_drawdown_pct:.2%}")
    print(f"Sharpe Ratio:     {oos_result.sharpe_ratio:.2f}")
    print(f"Calmar Ratio:     {oos_result.calmar_ratio:.2f}")
    print(f"Profit Factor:    {oos_result.profit_factor:.2f}")

    # 保存结果
    results = {
        'target': args.target,
        'best_params': best_params,
        'in_sample': is_metrics,
        'out_of_sample': oos_metrics,
        'n_trials': args.n_trials,
        'train_period': f"{args.train_start} to {args.train_end}",
        'test_period': f"{args.test_start} to {args.test_end}",
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_path}")

    return results


if __name__ == '__main__':
    args = parse_args()
    run_optimization(args)
