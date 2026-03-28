#!/usr/bin/env python3
"""
Dollar Trader Martingale BBW 策略 - Top 10 参数优化
=====================================================
运行500次贝叶斯优化，分别记录前10卡玛比率和前10夏普率的参数组合

优化参数:
- bb_period: 布林带周期 (10-30)
- bbw_ma_period: BBW均线周期 (30-100)

数据划分:
- 训练集: 2017-2022年
- 测试集: 2023-2026年2月

输出:
- Top 10 卡玛比率参数组合
- Top 10 夏普比率参数组合
- 每组包含: 训练期/测试期 收益、回撤、卡玛比率、夏普率

用法:
    python run_top10_optimization.py
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta
import warnings
warnings.filterwarnings('ignore')

# 添加项目根目录到路径
sys.path.insert(0, '/home/ctyun/xauusd_backtest')

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple

from strategies.dollar_trader_martingale_adx import (
    DollarTraderMartingaleBBWStepStrategy,
    calculate_dollar_trader_martingale_bbw_indicators
)
from engines.dollar_trader_engine import DollarTraderBacktestEngine
from core.config import TradingConfig

# Optuna导入
try:
    import optuna
    from optuna.samplers import TPESampler
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False
    print("Error: Optuna not installed. Please run: pip install optuna")
    sys.exit(1)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Dollar Trader Martingale BBW Top 10 参数优化'
    )

    parser.add_argument('--data-path', type=str, default='/home/ctyun/xauusd_data',
                        help='数据目录路径')

    parser.add_argument('--timeframe', type=str, default='30m',
                        help='K线周期 (默认: 30m)')

    parser.add_argument('--train-start', type=str, default='2017-01-01',
                        help='训练集开始日期')

    parser.add_argument('--train-end', type=str, default='2022-12-31',
                        help='训练集结束日期')

    parser.add_argument('--test-start', type=str, default='2023-01-01',
                        help='测试集开始日期')

    parser.add_argument('--test-end', type=str, default='2026-02-28',
                        help='测试集结束日期')

    parser.add_argument('--n-trials', type=int, default=500,
                        help='优化迭代次数 (默认: 500)')

    parser.add_argument('--min-trades', type=int, default=50,
                        help='最小交易次数要求 (默认: 50)')

    parser.add_argument('--output-dir', type=str, default='./optimization_results',
                        help='结果输出目录')

    parser.add_argument('--seed', type=int, default=42,
                        help='随机种子')

    parser.add_argument('--verbose', '-v', action='store_true',
                        help='显示详细信息')

    return parser.parse_args()


def load_data(data_path: str, timeframe: str, start_date: str, end_date: str,
              verbose: bool = False) -> pd.DataFrame:
    """加载K线数据"""

    if verbose:
        print(f"加载数据: {start_date} ~ {end_date}")

    # 生成月份列表
    months = []
    current = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    while current <= end:
        months.append(current.strftime('%Y-%m'))
        current += relativedelta(months=1)

    # 加载K线数据
    kline_dir = Path(data_path) / "kline" / timeframe
    dfs = []
    for month_str in months:
        year = month_str.split('-')[0]
        month = month_str.split('-')[1]

        filepath_v1 = kline_dir / f"XAUUSD_{month_str}.csv"
        filepath_v2 = kline_dir / f"XAUUSD_BID_{timeframe}_{year}{month}.csv"

        if filepath_v1.exists():
            df = pd.read_csv(filepath_v1, index_col=0, parse_dates=True)
            dfs.append(df)
        elif filepath_v2.exists():
            df = pd.read_csv(filepath_v2, index_col=0, parse_dates=True)
            if df.index.dtype == 'int64' or str(df.index.dtype).startswith('int'):
                df.index = pd.to_datetime(df.index, unit='ms')
            df.columns = [c.capitalize() for c in df.columns]
            dfs.append(df)

    if not dfs:
        raise ValueError(f"没有成功加载任何数据: {kline_dir}")

    ohlc_df = pd.concat(dfs)
    ohlc_df = ohlc_df.sort_index()
    ohlc_df = ohlc_df[~ohlc_df.index.duplicated(keep='first')]

    # 过滤日期范围
    ohlc_df = ohlc_df.loc[start_date:end_date]

    if verbose:
        print(f"OHLC数据 ({timeframe}): {len(ohlc_df):,} 条")

    return ohlc_df


def run_backtest_with_params(df: pd.DataFrame, params: Dict[str, Any],
                             config: TradingConfig) -> Dict[str, Any]:
    """使用给定参数运行回测"""

    # 准备数据
    df_with_indicators = calculate_dollar_trader_martingale_bbw_indicators(
        df,
        sma_short=params.get('sma_short', 20),
        sma_medium=params.get('sma_medium', 50),
        sma_long=params.get('sma_long', 200),
        bb_period=params.get('bb_period', 20),
        bb_std=params.get('bb_std', 2.0),
        bbw_ma_period=params.get('bbw_ma_period', 50)
    )

    # 创建策略
    strategy = DollarTraderMartingaleBBWStepStrategy(
        params=params,
        strategy_id=f"DT_Martingale_BBW_Opt"
    )

    # 生成信号
    signals = []
    warmup_bars = max(params.get('sma_long', 200),
                      params.get('bb_period', 20) + params.get('bbw_ma_period', 50)) + 5

    for i in range(warmup_bars, len(df_with_indicators)):
        signal = strategy.generate_signal(df_with_indicators, i)
        if signal:
            signals.append(signal)

    # 运行回测
    engine = DollarTraderBacktestEngine(config)
    result = engine.run(df_with_indicators, signals)

    return {
        'total_trades': result.total_trades,
        'winning_trades': result.winning_trades,
        'losing_trades': result.losing_trades,
        'win_rate': result.win_rate,
        'total_pnl': result.total_pnl,
        'total_return': result.total_return,
        'max_drawdown': result.max_drawdown,
        'max_drawdown_pct': result.max_drawdown_pct,
        'sharpe_ratio': result.sharpe_ratio if result.sharpe_ratio else 0,
        'sortino_ratio': result.sortino_ratio if result.sortino_ratio else 0,
        'calmar_ratio': result.calmar_ratio if hasattr(result, 'calmar_ratio') and result.calmar_ratio else 0,
        'profit_factor': result.profit_factor if result.profit_factor else 0,
        'avg_pnl': result.avg_pnl,
        'avg_win': result.avg_win,
        'avg_loss': result.avg_loss,
    }


def create_objective_function(df: pd.DataFrame, config: TradingConfig,
                              min_trades: int, all_results: List[Dict],
                              verbose: bool = False):
    """创建优化目标函数 - 记录所有结果"""

    def objective(trial) -> Tuple[float, float]:
        # 定义参数搜索空间
        params = {
            'sma_short': 20,
            'sma_medium': 50,
            'sma_long': 200,
            'position_size': 1.0,
            'martingale_multiplier': 2.0,
            'max_martingale_steps': 5,
            'bb_std': 2.0,
            'enable_overshoot': True,
            'enable_undershoot': True,

            # 待优化参数 - 扩大范围
            'bb_period': trial.suggest_int('bb_period', 20, 50),
            'bbw_ma_period': trial.suggest_int('bbw_ma_period', 50, 150),
        }

        try:
            # 运行回测
            result = run_backtest_with_params(df, params, config)

            # 检查最小交易次数
            if result['total_trades'] < min_trades:
                trial.set_user_attr('valid', False)
                return -1e6, -1e6

            # 记录结果
            result_record = {
                'trial_number': trial.number,
                'bb_period': params['bb_period'],
                'bbw_ma_period': params['bbw_ma_period'],
                'total_trades': result['total_trades'],
                'win_rate': result['win_rate'],
                'total_return': result['total_return'],
                'max_drawdown_pct': result['max_drawdown_pct'],
                'sharpe_ratio': result['sharpe_ratio'],
                'calmar_ratio': result['calmar_ratio'],
                'profit_factor': result['profit_factor'],
                'valid': True,
            }
            all_results.append(result_record)

            # 存储到trial属性
            trial.set_user_attr('sharpe_ratio', result['sharpe_ratio'])
            trial.set_user_attr('calmar_ratio', result['calmar_ratio'])
            trial.set_user_attr('total_return', result['total_return'])
            trial.set_user_attr('max_drawdown_pct', result['max_drawdown_pct'])
            trial.set_user_attr('total_trades', result['total_trades'])
            trial.set_user_attr('valid', True)

            if verbose and trial.number % 50 == 0:
                print(f"  Trial {trial.number}: bb_period={params['bb_period']}, "
                      f"bbw_ma_period={params['bbw_ma_period']}, "
                      f"calmar={result['calmar_ratio']:.2f}, sharpe={result['sharpe_ratio']:.2f}")

            # 返回多目标值 (卡玛比率, 夏普比率)
            return result['calmar_ratio'], result['sharpe_ratio']

        except Exception as e:
            if verbose:
                print(f"  Trial {trial.number} Error: {e}")
            trial.set_user_attr('valid', False)
            return -1e6, -1e6

    return objective


def get_top_n_by_metric(all_results: List[Dict], metric: str, n: int = 10) -> List[Dict]:
    """按指定指标获取前N个结果"""
    valid_results = [r for r in all_results if r.get('valid', False)]
    sorted_results = sorted(valid_results, key=lambda x: x[metric], reverse=True)
    return sorted_results[:n]


def evaluate_on_test_set(train_df: pd.DataFrame, test_df: pd.DataFrame,
                         params: Dict[str, Any], config: TradingConfig) -> Dict[str, Any]:
    """在训练集和测试集上评估参数"""

    # 训练集回测
    train_result = run_backtest_with_params(train_df, params, config)

    # 测试集回测
    test_result = run_backtest_with_params(test_df, params, config)

    return {
        'params': params,
        'train': {
            'total_return': train_result['total_return'],
            'max_drawdown_pct': train_result['max_drawdown_pct'],
            'calmar_ratio': train_result['calmar_ratio'],
            'sharpe_ratio': train_result['sharpe_ratio'],
            'total_trades': train_result['total_trades'],
            'win_rate': train_result['win_rate'],
            'profit_factor': train_result['profit_factor'],
        },
        'test': {
            'total_return': test_result['total_return'],
            'max_drawdown_pct': test_result['max_drawdown_pct'],
            'calmar_ratio': test_result['calmar_ratio'],
            'sharpe_ratio': test_result['sharpe_ratio'],
            'total_trades': test_result['total_trades'],
            'win_rate': test_result['win_rate'],
            'profit_factor': test_result['profit_factor'],
        }
    }


def main():
    """主函数"""
    args = parse_args()

    print("=" * 80)
    print("Dollar Trader Martingale BBW 策略 - Top 10 参数优化")
    print("=" * 80)
    print(f"\n配置:")
    print(f"  数据周期: {args.timeframe}")
    print(f"  训练集: {args.train_start} ~ {args.train_end}")
    print(f"  测试集: {args.test_start} ~ {args.test_end}")
    print(f"  优化迭代: {args.n_trials} 次")
    print(f"  最小交易次数: {args.min_trades}")
    print(f"  优化参数: bb_period(10-30), bbw_ma_period(30-100)")

    # 创建配置
    config = TradingConfig(
        symbol='XAUUSD',
        spread_points=20.0,
        slippage_points=10,
        initial_capital=100000,
    )

    # 加载数据
    print(f"\n[1/4] 加载数据...")
    train_df = load_data(args.data_path, args.timeframe,
                         args.train_start, args.train_end, args.verbose)
    print(f"  训练集: {len(train_df):,} 条K线")

    test_df = load_data(args.data_path, args.timeframe,
                        args.test_start, args.test_end, args.verbose)
    print(f"  测试集: {len(test_df):,} 条K线")

    # 创建优化器
    print(f"\n[2/4] 配置优化器...")
    print(f"  算法: TPE (贝叶斯优化)")
    print(f"  目标: 卡玛比率 + 夏普比率")

    # 存储所有结果
    all_results: List[Dict] = []

    # 创建Study - 多目标优化
    sampler = TPESampler(seed=args.seed)
    study = optuna.create_study(
        directions=['maximize', 'maximize'],  # 多目标优化
        sampler=sampler,
        study_name=f"martingale_bbw_top10_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    # 创建目标函数
    objective = create_objective_function(
        train_df, config, args.min_trades, all_results, args.verbose
    )

    # 运行优化
    print(f"\n[3/4] 开始贝叶斯优化 ({args.n_trials} 次迭代)...")
    print("-" * 80)

    study.optimize(
        objective,
        n_trials=args.n_trials,
        show_progress_bar=True
    )

    print("-" * 80)
    print(f"优化完成! 有效试验: {len([r for r in all_results if r.get('valid', False)])} 次")

    # 获取Top 10
    print(f"\n[4/4] 分析Top 10参数组合...")

    top10_calmar = get_top_n_by_metric(all_results, 'calmar_ratio', 10)
    top10_sharpe = get_top_n_by_metric(all_results, 'sharpe_ratio', 10)

    # 对Top 10分别计算训练期和测试期指标
    print(f"\n评估Top 10卡玛比率参数...")
    top10_calmar_full = []
    for i, result in enumerate(top10_calmar):
        params = {
            'sma_short': 20,
            'sma_medium': 50,
            'sma_long': 200,
            'position_size': 1.0,
            'martingale_multiplier': 2.0,
            'max_martingale_steps': 5,
            'bb_std': 2.0,
            'enable_overshoot': True,
            'enable_undershoot': True,
            'bb_period': result['bb_period'],
            'bbw_ma_period': result['bbw_ma_period'],
        }
        full_result = evaluate_on_test_set(train_df, test_df, params, config)
        top10_calmar_full.append(full_result)
        print(f"  #{i+1}: bb_period={result['bb_period']}, bbw_ma_period={result['bbw_ma_period']}")

    print(f"\n评估Top 10夏普比率参数...")
    top10_sharpe_full = []
    for i, result in enumerate(top10_sharpe):
        params = {
            'sma_short': 20,
            'sma_medium': 50,
            'sma_long': 200,
            'position_size': 1.0,
            'martingale_multiplier': 2.0,
            'max_martingale_steps': 5,
            'bb_std': 2.0,
            'enable_overshoot': True,
            'enable_undershoot': True,
            'bb_period': result['bb_period'],
            'bbw_ma_period': result['bbw_ma_period'],
        }
        full_result = evaluate_on_test_set(train_df, test_df, params, config)
        top10_sharpe_full.append(full_result)
        print(f"  #{i+1}: bb_period={result['bb_period']}, bbw_ma_period={result['bbw_ma_period']}")

    # 打印结果
    print("\n" + "=" * 80)
    print("Top 10 卡玛比率参数组合")
    print("=" * 80)
    print(f"{'排名':<4} {'BB周期':<8} {'BBW周期':<10} "
          f"{'训练收益':<12} {'训练回撤':<12} {'训练卡玛':<10} {'训练夏普':<10} "
          f"{'测试收益':<12} {'测试回撤':<12} {'测试卡玛':<10} {'测试夏普':<10}")
    print("-" * 120)

    for i, r in enumerate(top10_calmar_full):
        print(f"#{i+1:<3} {r['params']['bb_period']:<8} {r['params']['bbw_ma_period']:<10} "
              f"{r['train']['total_return']*100:>10.2f}% {r['train']['max_drawdown_pct']*100:>10.2f}% "
              f"{r['train']['calmar_ratio']:>8.2f} {r['train']['sharpe_ratio']:>8.2f} "
              f"{r['test']['total_return']*100:>10.2f}% {r['test']['max_drawdown_pct']*100:>10.2f}% "
              f"{r['test']['calmar_ratio']:>8.2f} {r['test']['sharpe_ratio']:>8.2f}")

    print("\n" + "=" * 80)
    print("Top 10 夏普比率参数组合")
    print("=" * 80)
    print(f"{'排名':<4} {'BB周期':<8} {'BBW周期':<10} "
          f"{'训练收益':<12} {'训练回撤':<12} {'训练卡玛':<10} {'训练夏普':<10} "
          f"{'测试收益':<12} {'测试回撤':<12} {'测试卡玛':<10} {'测试夏普':<10}")
    print("-" * 120)

    for i, r in enumerate(top10_sharpe_full):
        print(f"#{i+1:<3} {r['params']['bb_period']:<8} {r['params']['bbw_ma_period']:<10} "
              f"{r['train']['total_return']*100:>10.2f}% {r['train']['max_drawdown_pct']*100:>10.2f}% "
              f"{r['train']['calmar_ratio']:>8.2f} {r['train']['sharpe_ratio']:>8.2f} "
              f"{r['test']['total_return']*100:>10.2f}% {r['test']['max_drawdown_pct']*100:>10.2f}% "
              f"{r['test']['calmar_ratio']:>8.2f} {r['test']['sharpe_ratio']:>8.2f}")

    # 保存结果到JSON
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    result_data = {
        'config': {
            'timeframe': args.timeframe,
            'train_period': f"{args.train_start} ~ {args.train_end}",
            'test_period': f"{args.test_start} ~ {args.test_end}",
            'n_trials': args.n_trials,
            'min_trades': args.min_trades,
        },
        'top10_calmar': [
            {
                'rank': i + 1,
                'bb_period': r['params']['bb_period'],
                'bbw_ma_period': r['params']['bbw_ma_period'],
                'train_return': r['train']['total_return'],
                'train_drawdown': r['train']['max_drawdown_pct'],
                'train_calmar': r['train']['calmar_ratio'],
                'train_sharpe': r['train']['sharpe_ratio'],
                'train_trades': r['train']['total_trades'],
                'train_win_rate': r['train']['win_rate'],
                'test_return': r['test']['total_return'],
                'test_drawdown': r['test']['max_drawdown_pct'],
                'test_calmar': r['test']['calmar_ratio'],
                'test_sharpe': r['test']['sharpe_ratio'],
                'test_trades': r['test']['total_trades'],
                'test_win_rate': r['test']['win_rate'],
            }
            for i, r in enumerate(top10_calmar_full)
        ],
        'top10_sharpe': [
            {
                'rank': i + 1,
                'bb_period': r['params']['bb_period'],
                'bbw_ma_period': r['params']['bbw_ma_period'],
                'train_return': r['train']['total_return'],
                'train_drawdown': r['train']['max_drawdown_pct'],
                'train_calmar': r['train']['calmar_ratio'],
                'train_sharpe': r['train']['sharpe_ratio'],
                'train_trades': r['train']['total_trades'],
                'train_win_rate': r['train']['win_rate'],
                'test_return': r['test']['total_return'],
                'test_drawdown': r['test']['max_drawdown_pct'],
                'test_calmar': r['test']['calmar_ratio'],
                'test_sharpe': r['test']['sharpe_ratio'],
                'test_trades': r['test']['total_trades'],
                'test_win_rate': r['test']['win_rate'],
            }
            for i, r in enumerate(top10_sharpe_full)
        ],
    }

    output_file = output_dir / f"top10_optimization_{timestamp}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)

    print(f"\n结果已保存: {output_file}")

    # 同时保存CSV格式方便查看
    calmar_df = pd.DataFrame([
        {
            '排名': r['rank'],
            'BB周期': r['bb_period'],
            'BBW周期': r['bbw_ma_period'],
            '训练期收益%': r['train_return'] * 100,
            '训练期回撤%': r['train_drawdown'] * 100,
            '训练期卡玛': r['train_calmar'],
            '训练期夏普': r['train_sharpe'],
            '训练期交易数': r['train_trades'],
            '训练期胜率%': r['train_win_rate'] * 100,
            '测试期收益%': r['test_return'] * 100,
            '测试期回撤%': r['test_drawdown'] * 100,
            '测试期卡玛': r['test_calmar'],
            '测试期夏普': r['test_sharpe'],
            '测试期交易数': r['test_trades'],
            '测试期胜率%': r['test_win_rate'] * 100,
        }
        for r in result_data['top10_calmar']
    ])

    sharpe_df = pd.DataFrame([
        {
            '排名': r['rank'],
            'BB周期': r['bb_period'],
            'BBW周期': r['bbw_ma_period'],
            '训练期收益%': r['train_return'] * 100,
            '训练期回撤%': r['train_drawdown'] * 100,
            '训练期卡玛': r['train_calmar'],
            '训练期夏普': r['train_sharpe'],
            '训练期交易数': r['train_trades'],
            '训练期胜率%': r['train_win_rate'] * 100,
            '测试期收益%': r['test_return'] * 100,
            '测试期回撤%': r['test_drawdown'] * 100,
            '测试期卡玛': r['test_calmar'],
            '测试期夏普': r['test_sharpe'],
            '测试期交易数': r['test_trades'],
            '测试期胜率%': r['test_win_rate'] * 100,
        }
        for r in result_data['top10_sharpe']
    ])

    calmar_csv = output_dir / f"top10_calmar_{timestamp}.csv"
    sharpe_csv = output_dir / f"top10_sharpe_{timestamp}.csv"
    calmar_df.to_csv(calmar_csv, index=False, encoding='utf-8-sig')
    sharpe_df.to_csv(sharpe_csv, index=False, encoding='utf-8-sig')

    print(f"CSV文件已保存: {calmar_csv}")
    print(f"CSV文件已保存: {sharpe_csv}")

    print("\n" + "=" * 80)
    print("优化完成!")
    print("=" * 80)

    return 0


if __name__ == '__main__':
    sys.exit(main())
