#!/usr/bin/env python3
"""
优化运行脚本
============
统一的优化入口，支持贝叶斯优化和Walk-Forward验证

用法：
    python run_optimization.py --strategy mean_reversion --train-start 2025-01-01 --train-end 2025-10-31 --test-start 2025-11-01 --test-end 2025-12-31
    python run_optimization.py --strategy momentum_breakout --n-trials 500 --target sharpe
"""

import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from core.config import Config, get_config
from core.indicators import add_all_indicators
from core.data_loader import DataLoader
from strategies import StrategyRegistry
from engines import CandleBacktestEngine
from optimizers import OptunaOptimizer


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='XAUUSD Strategy Optimization')

    # 策略选择
    parser.add_argument('--strategy', type=str, required=True,
                        choices=StrategyRegistry.list_strategies(),
                        help='Strategy to optimize')

    # 训练集时间范围
    parser.add_argument('--train-start', type=str, required=True,
                        help='Training start date (YYYY-MM-DD)')
    parser.add_argument('--train-end', type=str, required=True,
                        help='Training end date (YYYY-MM-DD)')

    # 测试集时间范围（Walk-Forward）
    parser.add_argument('--test-start', type=str,
                        help='Test start date (YYYY-MM-DD)')
    parser.add_argument('--test-end', type=str,
                        help='Test end date (YYYY-MM-DD)')

    # 优化配置
    parser.add_argument('--n-trials', type=int, default=300,
                        help='Number of optimization trials')
    parser.add_argument('--target', type=str, default='calmar',
                        choices=['sharpe', 'calmar', 'profit_factor', 'win_rate', 'total_return'],
                        help='Optimization target')
    parser.add_argument('--min-trades', type=int, default=30,
                        help='Minimum trades required')
    parser.add_argument('--timeout', type=int,
                        help='Optimization timeout in seconds')

    # 配置文件
    parser.add_argument('--config', type=str,
                        help='Config file path')

    # 输出
    parser.add_argument('--output', type=str, default='optimization_results.json',
                        help='Output file path for results')

    # 早停
    parser.add_argument('--no-early-stopping', action='store_true',
                        help='Disable early stopping')

    return parser.parse_args()


def load_config(args) -> Config:
    """加载配置"""
    if args.config:
        return Config.from_file(args.config)
    return get_config()


def get_months_in_range(start_date: str, end_date: str) -> list:
    """获取日期范围内的所有月份"""
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

    return months


def load_and_prepare_data(config: Config, start_date: str, end_date: str):
    """加载并准备数据"""
    loader = DataLoader(config.data.data_dir)

    months = get_months_in_range(start_date, end_date)
    print(f"Loading data for {len(months)} months...")

    df = loader.load_range(months, config.data.interval)
    df = df[(df.index >= start_date) & (df.index <= end_date)]

    print(f"Loaded {len(df)} bars")

    # 添加指标
    print("Calculating indicators...")
    params = config.strategy.to_dict()
    df = add_all_indicators(
        df,
        bb_period=params.get('bb_period', 20),
        bb_std=params.get('bb_std', 2.0),
        kc_period=params.get('kc_period', 20),
        kc_atr_mult=params.get('kc_atr_mult', 1.5),
        atr_period=params.get('atr_period', 14),
        rsi_period=params.get('rsi_period', 14),
        ema_fast=params.get('ema_fast', 20),
        ema_slow=params.get('ema_slow', 50),
        vwap_reset_hour=config.data.vwap_reset_hour_et
    )

    return df


def create_objective_function(df: pd.DataFrame, strategy_name: str, config: Config):
    """创建目标函数"""
    engine = CandleBacktestEngine(config.trading)

    def objective(params: dict) -> float:
        try:
            # 创建策略
            strategy = StrategyRegistry.create(strategy_name, params)

            # 运行回测
            result = engine.run_with_strategy(df, strategy, warmup_bars=100)

            # 检查最小交易次数
            if result.total_trades < config.optimization.min_trades:
                return -1e6 + result.total_trades  # 惩罚但没有完全失败

            # 计算适应度
            target = config.optimization.optimization_target

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
            else:
                # 综合评分
                return (
                    result.sharpe_ratio * 0.3 +
                    result.calmar_ratio * 0.3 +
                    min(result.profit_factor, 3.0) * 0.2 +
                    result.win_rate * 0.2
                )

        except Exception as e:
            print(f"Error in objective function: {e}")
            return -1e9

    return objective


def run_optimization(args):
    """运行优化"""
    print(f"\n{'='*60}")
    print(f"XAUUSD Strategy Optimization - {args.strategy}")
    print(f"{'='*60}\n")

    # 加载配置
    config = load_config(args)

    # 更新优化配置
    config.optimization.n_trials = args.n_trials
    config.optimization.optimization_target = args.target
    config.optimization.min_trades = args.min_trades
    config.optimization.early_stopping = not args.no_early_stopping
    if args.timeout:
        config.optimization.timeout = args.timeout

    # 加载训练数据
    print("Loading training data...")
    train_df = load_and_prepare_data(config, args.train_start, args.train_end)

    # 加载测试数据（如果提供）
    test_df = None
    if args.test_start and args.test_end:
        print("\nLoading test data...")
        test_df = load_and_prepare_data(config, args.test_start, args.test_end)

    # 创建策略获取参数范围
    strategy_info = StrategyRegistry.get_info(args.strategy)
    param_bounds = strategy_info['param_bounds']

    print(f"\nOptimization settings:")
    print(f"  Trials: {args.n_trials}")
    print(f"  Target: {args.target}")
    print(f"  Min trades: {args.min_trades}")
    print(f"  Walk-forward: {'Yes' if test_df is not None else 'No'}\n")

    # 创建优化器
    optimizer = OptunaOptimizer(
        param_bounds=param_bounds,
        n_trials=args.n_trials,
        timeout=args.timeout,
        min_trades=args.min_trades,
        optimization_target=args.target,
        early_stopping=not args.no_early_stopping
    )

    # 创建目标函数
    train_objective = create_objective_function(train_df, args.strategy, config)

    # 运行优化
    if test_df is not None:
        # Walk-forward 优化
        print("Running Walk-Forward optimization...")
        test_objective = create_objective_function(test_df, args.strategy, config)
        result = optimizer.optimize_with_walk_forward(train_objective, test_objective)
    else:
        # 单数据集优化
        print("Running optimization...")
        result = optimizer.optimize(train_objective)

    # 输出结果
    print(f"\n{'='*60}")
    print("Optimization Results")
    print(f"{'='*60}\n")

    print(f"Best Fitness: {result.best_fitness:.4f}")
    print(f"Total Trials: {result.total_trials}")
    print(f"Duration: {result.duration_seconds:.1f}s\n")

    print("Best Parameters:")
    for param, value in result.best_params.items():
        print(f"  {param}: {value}")

    # 使用最优参数运行完整回测
    print(f"\n{'='*60}")
    print("Final Backtest with Best Parameters")
    print(f"{'='*60}\n")

    best_strategy = StrategyRegistry.create(args.strategy, result.best_params)
    engine = CandleBacktestEngine(config.trading)
    backtest_result = engine.run_with_strategy(train_df, best_strategy)

    print(f"Total Trades:     {backtest_result.total_trades}")
    print(f"Win Rate:         {backtest_result.win_rate:.2%}")
    print(f"Total Return:     {backtest_result.total_return:.2%}")
    print(f"Max Drawdown:     {backtest_result.max_drawdown_pct:.2%}")
    print(f"Sharpe Ratio:     {backtest_result.sharpe_ratio:.2f}")
    print(f"Profit Factor:    {backtest_result.profit_factor:.2f}")

    # 如果有测试集，也运行测试
    if test_df is not None:
        print(f"\n{'='*60}")
        print("Out-of-Sample Test Results")
        print(f"{'='*60}\n")

        test_result = engine.run_with_strategy(test_df, best_strategy)

        print(f"Total Trades:     {test_result.total_trades}")
        print(f"Win Rate:         {test_result.win_rate:.2%}")
        print(f"Total Return:     {test_result.total_return:.2%}")
        print(f"Max Drawdown:     {test_result.max_drawdown_pct:.2%}")
        print(f"Sharpe Ratio:     {test_result.sharpe_ratio:.2f}")
        print(f"Profit Factor:    {test_result.profit_factor:.2f}")

        result.test_results = test_result

    # 保存结果
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    import json
    result_data = {
        'strategy': args.strategy,
        'best_params': result.best_params,
        'best_fitness': result.best_fitness,
        'total_trials': result.total_trials,
        'duration_seconds': result.duration_seconds,
        'train_results': backtest_result.to_dict(),
        'test_results': test_result.to_dict() if test_df is not None else None
    }

    with open(output_path, 'w') as f:
        json.dump(result_data, f, indent=2)

    print(f"\nResults saved to: {output_path}")

    return result


def main():
    """主函数"""
    args = parse_args()

    try:
        result = run_optimization(args)
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
