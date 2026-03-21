"""
运行优化脚本
============
加载2025-01至2026-02数据（14个月），运行Optuna TPE优化
支持Walk-Forward验证
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
import json
from typing import Dict, List, Optional

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_loader import load_data_range
from optuna_optimizer import (
    run_tick_optuna_optimization,
    run_walk_forward_optimization,
    OptimizationResult,
)
from strategy import TradingStrategy
from tick_engine import TickBacktestEngine
from config import DEFAULT_PARAMS


# 默认数据配置
DEFAULT_DATA_DIR = '/home/ctyun/xauusd_data'
DEFAULT_START_DATE = '2025-01-01'
DEFAULT_END_DATE = '2026-02-28'


def run_single_optimization(
    data_dir: str = DEFAULT_DATA_DIR,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    n_trials: int = 100,
    n_jobs: int = 1,
    output_dir: Optional[str] = None,
    verbose: bool = True
) -> OptimizationResult:
    """
    运行单次优化

    Args:
        data_dir: 数据目录
        start_date: 开始日期
        end_date: 结束日期
        n_trials: 优化轮数
        n_jobs: 并行数
        output_dir: 输出目录
        verbose: 是否打印进度

    Returns:
        OptimizationResult
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"XAUUSD 双策略 Tick级别优化")
        print(f"{'='*60}")
        print(f"数据目录: {data_dir}")
        print(f"日期范围: {start_date} ~ {end_date}")
        print(f"优化轮数: {n_trials}")
        print(f"{'='*60}\n")

    # 加载数据
    print("正在加载数据...")
    ticks_df, ohlcv_df = load_data_range(data_dir, start_date, end_date)

    print(f"加载完成:")
    print(f"  Tick数据: {len(ticks_df):,} 条")
    print(f"  时间范围: {ticks_df.index[0]} ~ {ticks_df.index[-1]}")
    print(f"  K线数据: {len(ohlcv_df):,} 根")

    # 运行优化
    result = run_tick_optuna_optimization(
        ticks_df=ticks_df,
        ohlcv_df=ohlcv_df,
        n_trials=n_trials,
        n_jobs=n_jobs,
        verbose=verbose,
    )

    # 保存结果
    if output_dir:
        save_results(result, output_dir, start_date, end_date)

    return result


def run_wfo_optimization(
    data_dir: str = DEFAULT_DATA_DIR,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    n_splits: int = 5,
    n_trials: int = 50,
    output_dir: Optional[str] = None,
    verbose: bool = True
) -> List[Dict]:
    """
    运行Walk-Forward优化验证

    Args:
        data_dir: 数据目录
        start_date: 开始日期
        end_date: 结束日期
        n_splits: 分割数
        n_trials: 每个分割的优化轮数
        output_dir: 输出目录
        verbose: 是否打印进度

    Returns:
        每个fold的结果列表
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"XAUUSD 双策略 Walk-Forward优化验证")
        print(f"{'='*60}")
        print(f"数据目录: {data_dir}")
        print(f"日期范围: {start_date} ~ {end_date}")
        print(f"分割数: {n_splits}")
        print(f"每分割优化轮数: {n_trials}")
        print(f"{'='*60}\n")

    # 加载数据
    print("正在加载数据...")
    ticks_df, ohlcv_df = load_data_range(data_dir, start_date, end_date)

    print(f"加载完成:")
    print(f"  Tick数据: {len(ticks_df):,} 条")
    print(f"  时间范围: {ticks_df.index[0]} ~ {ticks_df.index[-1]}")
    print(f"  K线数据: {len(ohlcv_df):,} 根")

    # 运行WFO
    results = run_walk_forward_optimization(
        ticks_df=ticks_df,
        ohlcv_df=ohlcv_df,
        n_splits=n_splits,
        n_trials=n_trials,
        verbose=verbose,
    )

    # 保存结果
    if output_dir:
        save_wfo_results(results, output_dir)

    return results


def save_results(
    result: OptimizationResult,
    output_dir: str,
    start_date: str,
    end_date: str
):
    """保存优化结果"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # 保存最佳参数
    params_file = output_path / f'best_params_{timestamp}.json'
    with open(params_file, 'w') as f:
        json.dump(result.best_params, f, indent=2)
    print(f"参数已保存: {params_file}")

    # 保存统计结果
    stats_file = output_path / f'stats_{timestamp}.json'
    with open(stats_file, 'w') as f:
        json.dump(result.best_stats, f, indent=2)
    print(f"统计已保存: {stats_file}")

    # 保存所有试验
    if result.all_trials is not None and len(result.all_trials) > 0:
        trials_file = output_path / f'all_trials_{timestamp}.csv'
        result.all_trials.to_csv(trials_file, index=False)
        print(f"试验记录已保存: {trials_file}")


def save_wfo_results(results: List[Dict], output_dir: str):
    """保存WFO结果"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # 汇总每个fold的参数和统计
    summary = []
    for r in results:
        summary.append({
            'fold': r['fold'],
            'train_start': str(r['train_start']),
            'train_end': str(r['train_end']),
            'val_start': str(r['val_start']),
            'val_end': str(r['val_end']),
            'train_return': r['train_stats']['total_return'],
            'train_sharpe': r['train_stats']['sharpe_ratio'],
            'train_dd': r['train_stats']['max_drawdown'],
            'val_return': r['val_stats']['total_return'],
            'val_sharpe': r['val_stats']['sharpe_ratio'],
            'val_dd': r['val_stats']['max_drawdown'],
        })

    summary_df = pd.DataFrame(summary)
    summary_file = output_path / f'wfo_summary_{timestamp}.csv'
    summary_df.to_csv(summary_file, index=False)
    print(f"WFO汇总已保存: {summary_file}")

    # 保存每个fold的详细参数
    for r in results:
        params_file = output_path / f'wfo_fold{r["fold"]}_params_{timestamp}.json'
        with open(params_file, 'w') as f:
            # 转换参数值为Python原生类型
            params = {k: float(v) if isinstance(v, (np.floating, np.integer)) else v
                      for k, v in r['best_params'].items()}
            json.dump(params, f, indent=2)


def run_backtest_with_params(
    params: Dict,
    data_dir: str = DEFAULT_DATA_DIR,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    verbose: bool = True
) -> Dict:
    """
    使用指定参数运行回测

    Args:
        params: 策略参数
        data_dir: 数据目录
        start_date: 开始日期
        end_date: 结束日期
        verbose: 是否打印进度

    Returns:
        回测统计结果
    """
    if verbose:
        print(f"\n使用指定参数运行回测...")
        print(f"日期范围: {start_date} ~ {end_date}")

    # 加载数据
    ticks_df, ohlcv_df = load_data_range(data_dir, start_date, end_date)

    # 创建策略
    strategy = TradingStrategy(params)

    # 准备指标
    ohlcv_with_indicators = strategy.prepare_indicators(ohlcv_df)

    # 生成信号
    from strategy import SignalType
    signals = []
    for i in range(max(params.get('bb_period', 20), params.get('ema_slow', 50)) + 1,
                   len(ohlcv_with_indicators)):
        sig_a = strategy.generate_strategy_a_signal(ohlcv_with_indicators, i)
        if sig_a:
            signals.append({
                'timestamp': sig_a.timestamp,
                'direction': 1 if sig_a.signal_type == SignalType.LONG else -1,
                'stop_loss': sig_a.stop_loss,
                'strategy': 'A',
            })

        sig_b = strategy.generate_strategy_b_signal(ohlcv_with_indicators, i)
        if sig_b:
            signals.append({
                'timestamp': sig_b.timestamp,
                'direction': 1 if sig_b.signal_type == SignalType.LONG else -1,
                'stop_loss': sig_b.stop_loss,
                'strategy': 'B',
            })

    # 创建回测引擎 (不传spread参数)
    engine = TickBacktestEngine(
        initial_capital=100000,
        position_size=1.0,
        contract_size=100,
        stop_loss_mult_b=params.get('stop_loss_mult_b', 2.0),
        trailing_stop_mult=params.get('trailing_stop_mult', 3.0),
        max_hold_bars_a=params.get('max_hold_bars_a', 6),
        atr_time_stop_base=params.get('atr_time_stop_base', 5.0),
        atr_time_stop_mult=params.get('atr_time_stop_mult', 0.5),
    )

    # 运行回测
    stats = engine.run(ticks_df, signals, ohlcv_df)

    if verbose:
        print(f"\n回测结果:")
        print(f"  总交易次数: {stats['total_trades']}")
        print(f"  胜率: {stats['win_rate']:.2f}%")
        print(f"  总收益: {stats['total_return']:.2f}%")
        print(f"  夏普比率: {stats['sharpe_ratio']:.2f}")
        print(f"  最大回撤: {stats['max_drawdown']:.2f}%")
        print(f"  盈亏比: {stats['profit_factor']:.2f}")

    return stats


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='XAUUSD双策略优化')

    parser.add_argument('--mode', type=str, default='single',
                        choices=['single', 'wfo', 'backtest'],
                        help='运行模式: single=单次优化, wfo=Walk-Forward优化, backtest=回测')

    parser.add_argument('--data-dir', type=str, default=DEFAULT_DATA_DIR,
                        help='数据目录')

    parser.add_argument('--start-date', type=str, default=DEFAULT_START_DATE,
                        help='开始日期 (YYYY-MM-DD)')

    parser.add_argument('--end-date', type=str, default=DEFAULT_END_DATE,
                        help='结束日期 (YYYY-MM-DD)')

    parser.add_argument('--n-trials', type=int, default=100,
                        help='优化轮数')

    parser.add_argument('--n-splits', type=int, default=5,
                        help='WFO分割数')

    parser.add_argument('--n-jobs', type=int, default=1,
                        help='并行数')

    parser.add_argument('--output-dir', type=str, default='./optimization_results',
                        help='输出目录')

    parser.add_argument('--params-file', type=str, default=None,
                        help='参数文件路径 (用于backtest模式)')

    parser.add_argument('--quiet', action='store_true',
                        help='静默模式')

    args = parser.parse_args()

    verbose = not args.quiet

    if args.mode == 'single':
        result = run_single_optimization(
            data_dir=args.data_dir,
            start_date=args.start_date,
            end_date=args.end_date,
            n_trials=args.n_trials,
            n_jobs=args.n_jobs,
            output_dir=args.output_dir,
            verbose=verbose,
        )

    elif args.mode == 'wfo':
        results = run_wfo_optimization(
            data_dir=args.data_dir,
            start_date=args.start_date,
            end_date=args.end_date,
            n_splits=args.n_splits,
            n_trials=args.n_trials,
            output_dir=args.output_dir,
            verbose=verbose,
        )

    elif args.mode == 'backtest':
        # 加载参数
        if args.params_file:
            with open(args.params_file, 'r') as f:
                params = json.load(f)
        else:
            params = DEFAULT_PARAMS

        stats = run_backtest_with_params(
            params=params,
            data_dir=args.data_dir,
            start_date=args.start_date,
            end_date=args.end_date,
            verbose=verbose,
        )


if __name__ == '__main__':
    main()
