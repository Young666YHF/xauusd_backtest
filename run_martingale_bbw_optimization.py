#!/usr/bin/env python3
"""
Dollar Trader Martingale BBW 策略贝叶斯优化
===========================================
基于Optuna TPE算法的超参数优化

优化参数:
- bb_period: 布林带周期 (10-30)
- bbw_ma_period: BBW均线周期 (30-100)

优化目标:
- 卡玛比率 (Calmar Ratio)
- 夏普比率 (Sharpe Ratio)

数据划分:
- 训练集: 2017-2022年
- 测试集: 2023-2026年2月

用法:
    # 优化卡玛比率
    python run_martingale_bbw_optimization.py --target calmar --n-trials 200

    # 优化夏普比率
    python run_martingale_bbw_optimization.py --target sharpe --n-trials 200

    # 完整流程（训练+测试）
    python run_martingale_bbw_optimization.py --target calmar --walk-forward
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta

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
        description='Dollar Trader Martingale BBW 策略贝叶斯优化',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 卡玛比率优化 (默认)
  python run_martingale_bbw_optimization.py --target calmar --n-trials 300

  # 夏普比率优化
  python run_martingale_bbw_optimization.py --target sharpe --n-trials 300

  # 带Walk-Forward验证
  python run_martingale_bbw_optimization.py --target calmar --walk-forward
        """
    )

    parser.add_argument('--target', type=str, default='calmar',
                        choices=['calmar', 'sharpe', 'profit_factor', 'total_return'],
                        help='优化目标 (默认: calmar)')

    parser.add_argument('--data-path', type=str, default='/home/ctyun/xauusd_data',
                        help='数据目录路径 (默认: /home/ctyun/xauusd_data)')

    parser.add_argument('--timeframe', type=str, default='30m',
                        help='K线周期 (默认: 30m)')

    parser.add_argument('--train-start', type=str, default='2017-01-01',
                        help='训练集开始日期 (默认: 2017-01-01)')

    parser.add_argument('--train-end', type=str, default='2022-12-31',
                        help='训练集结束日期 (默认: 2022-12-31)')

    parser.add_argument('--test-start', type=str, default='2023-01-01',
                        help='测试集开始日期 (默认: 2023-01-01)')

    parser.add_argument('--test-end', type=str, default='2026-02-28',
                        help='测试集结束日期 (默认: 2026-02-28)')

    parser.add_argument('--n-trials', type=int, default=300,
                        help='优化迭代次数 (默认: 300)')

    parser.add_argument('--walk-forward', action='store_true',
                        help='启用Walk-Forward验证')

    parser.add_argument('--min-trades', type=int, default=50,
                        help='最小交易次数要求 (默认: 50)')

    parser.add_argument('--output-dir', type=str, default='./optimization_results',
                        help='结果输出目录')

    parser.add_argument('--seed', type=int, default=42,
                        help='随机种子 (默认: 42)')

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
        # 尝试两种文件名格式
        # 格式1: XAUUSD_YYYY-MM.csv (旧格式)
        # 格式2: XAUUSD_BID_30m_YYYYMM.csv (新格式)
        year = month_str.split('-')[0]
        month = month_str.split('-')[1]

        filepath_v1 = kline_dir / f"XAUUSD_{month_str}.csv"
        filepath_v2 = kline_dir / f"XAUUSD_BID_{timeframe}_{year}{month}.csv"

        if filepath_v1.exists():
            df = pd.read_csv(filepath_v1, index_col=0, parse_dates=True)
            dfs.append(df)
        elif filepath_v2.exists():
            df = pd.read_csv(filepath_v2, index_col=0, parse_dates=True)
            # 转换毫秒时间戳为 datetime
            if df.index.dtype == 'int64' or str(df.index.dtype).startswith('int'):
                df.index = pd.to_datetime(df.index, unit='ms')
            # 标准化列名为大写
            df.columns = [c.capitalize() for c in df.columns]
            dfs.append(df)
        else:
            if verbose:
                print(f"Warning: 文件不存在: {filepath_v1} 或 {filepath_v2}")

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


def prepare_data_with_indicators(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """准备带指标的数据"""
    return calculate_dollar_trader_martingale_bbw_indicators(
        df,
        sma_short=params.get('sma_short', 20),
        sma_medium=params.get('sma_medium', 50),
        sma_long=params.get('sma_long', 200),
        bb_period=params.get('bb_period', 20),
        bb_std=params.get('bb_std', 2.0),
        bbw_ma_period=params.get('bbw_ma_period', 50)
    )


def run_backtest_with_params(df: pd.DataFrame, params: Dict[str, Any],
                             config: TradingConfig, verbose: bool = False) -> Dict[str, Any]:
    """使用给定参数运行回测"""

    # 准备数据
    df_with_indicators = prepare_data_with_indicators(df, params)

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

    if verbose:
        print(f"  生成信号: {len(signals)} 个")

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
        'sharpe_ratio': result.sharpe_ratio,
        'sortino_ratio': result.sortino_ratio,
        'calmar_ratio': result.calmar_ratio if hasattr(result, 'calmar_ratio') else 0,
        'profit_factor': result.profit_factor,
        'avg_pnl': result.avg_pnl,
        'avg_win': result.avg_win,
        'avg_loss': result.avg_loss,
        'equity_curve': result.equity_curve,
        'trades': result.trades
    }


def create_objective_function(df: pd.DataFrame, config: TradingConfig,
                              target: str, min_trades: int, verbose: bool = False):
    """创建优化目标函数"""

    def objective(trial) -> float:
        # 定义参数搜索空间（只优化布林带周期和BBW均线周期）
        params = {
            'sma_short': 20,  # 固定值
            'sma_medium': 50,  # 固定值
            'sma_long': 200,  # 固定值
            'position_size': 1.0,  # 固定值
            'martingale_multiplier': 2.0,  # 固定值
            'max_martingale_steps': 5,  # 固定值
            'bb_std': 2.0,  # 固定值
            'enable_overshoot': True,  # 固定值
            'enable_undershoot': True,  # 固定值

            # 待优化参数
            'bb_period': trial.suggest_int('bb_period', 10, 30),
            'bbw_ma_period': trial.suggest_int('bbw_ma_period', 30, 100),
        }

        try:
            # 运行回测
            result = run_backtest_with_params(df, params, config, verbose=False)

            # 检查最小交易次数
            if result['total_trades'] < min_trades:
                return -1e6 + result['total_trades']

            # 返回目标值
            if target == 'calmar':
                return result['calmar_ratio'] if result['calmar_ratio'] else -1e6
            elif target == 'sharpe':
                return result['sharpe_ratio'] if result['sharpe_ratio'] is not None else -1e6
            elif target == 'profit_factor':
                return result['profit_factor'] if result['profit_factor'] is not None else -1e6
            elif target == 'total_return':
                return result['total_return']
            else:
                return result['calmar_ratio'] if result['calmar_ratio'] else -1e6

        except Exception as e:
            if verbose:
                print(f"  Error in trial: {e}")
            return -1e9

    return objective


def run_optimization(args) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """运行贝叶斯优化"""

    print("=" * 80)
    print(f"Dollar Trader Martingale BBW 策略贝叶斯优化")
    print(f"优化目标: {args.target.upper()}")
    print("=" * 80)

    # 创建配置
    config = TradingConfig(
        symbol='XAUUSD',
        spread_points=20.0,
        slippage_points=10,
        initial_capital=100000,
    )

    # 加载训练数据
    print(f"\n[1/4] 加载训练数据 ({args.train_start} ~ {args.train_end})...")
    train_df = load_data(args.data_path, args.timeframe,
                         args.train_start, args.train_end, args.verbose)

    # 加载测试数据（如果需要Walk-Forward）
    test_df = None
    if args.walk_forward:
        print(f"\n[2/4] 加载测试数据 ({args.test_start} ~ {args.test_end})...")
        test_df = load_data(args.data_path, args.timeframe,
                           args.test_start, args.test_end, args.verbose)
    else:
        print(f"\n[2/4] 跳过测试数据加载 (Walk-Forward未启用)")

    # 创建优化器
    print(f"\n[3/4] 配置Optuna优化器...")
    print(f"  算法: TPE (Tree-structured Parzen Estimator)")
    print(f"  迭代次数: {args.n_trials}")
    print(f"  随机种子: {args.seed}")
    print(f"  最小交易次数: {args.min_trades}")

    # 创建Study
    sampler = TPESampler(seed=args.seed)
    study = optuna.create_study(
        direction='maximize',
        sampler=sampler,
        study_name=f"martingale_bbw_{args.target}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    # 创建目标函数
    train_objective = create_objective_function(
        train_df, config, args.target, args.min_trades, args.verbose
    )

    # 运行优化
    print(f"\n[4/4] 开始优化...")
    print("-" * 80)

    study.optimize(
        train_objective,
        n_trials=args.n_trials,
        show_progress_bar=True
    )

    # 获取最佳参数
    best_params = study.best_params
    best_value = study.best_value

    # 合并固定参数
    full_params = {
        'sma_short': 20,
        'sma_medium': 50,
        'sma_long': 200,
        'position_size': 1.0,
        'martingale_multiplier': 2.0,
        'max_martingale_steps': 5,
        'bb_std': 2.0,
        'enable_overshoot': True,
        'enable_undershoot': True,
        **best_params
    }

    print("\n" + "=" * 80)
    print("优化完成!")
    print("=" * 80)

    # 使用最佳参数运行完整回测
    print(f"\n训练集回测 (最佳参数):")
    print(f"  布林带周期: {best_params['bb_period']}")
    print(f"  BBW均线周期: {best_params['bbw_ma_period']}")

    train_result = run_backtest_with_params(train_df, full_params, config, args.verbose)

    print(f"\n  交易统计:")
    print(f"    总交易次数: {train_result['total_trades']}")
    print(f"    胜率: {train_result['win_rate']*100:.2f}%")
    print(f"    总盈亏: ${train_result['total_pnl']:,.2f}")
    print(f"    总收益率: {train_result['total_return']*100:.2f}%")

    print(f"\n  风险指标:")
    print(f"    最大回撤: ${train_result['max_drawdown']:,.2f} ({train_result['max_drawdown_pct']*100:.2f}%)")
    print(f"    夏普比率: {train_result['sharpe_ratio']:.2f}")
    print(f"    卡玛比率: {train_result['calmar_ratio']:.2f}" if train_result['calmar_ratio'] else "    卡玛比率: N/A")
    print(f"    盈利因子: {train_result['profit_factor']:.2f}")

    # Walk-Forward测试
    test_result = None
    if test_df is not None and args.walk_forward:
        print(f"\n测试集回测 (样本外数据 {args.test_start} ~ {args.test_end}):")
        test_result = run_backtest_with_params(test_df, full_params, config, args.verbose)

        print(f"\n  交易统计:")
        print(f"    总交易次数: {test_result['total_trades']}")
        print(f"    胜率: {test_result['win_rate']*100:.2f}%")
        print(f"    总盈亏: ${test_result['total_pnl']:,.2f}")
        print(f"    总收益率: {test_result['total_return']*100:.2f}%")

        print(f"\n  风险指标:")
        print(f"    最大回撤: ${test_result['max_drawdown']:,.2f} ({test_result['max_drawdown_pct']*100:.2f}%)")
        print(f"    夏普比率: {test_result['sharpe_ratio']:.2f}")
        print(f"    卡玛比率: {test_result['calmar_ratio']:.2f}" if test_result['calmar_ratio'] else "    卡玛比率: N/A")
        print(f"    盈利因子: {test_result['profit_factor']:.2f}")

    return {
        'best_params': best_params,
        'full_params': full_params,
        'best_fitness': best_value,
        'target': args.target,
        'train_result': train_result,
        'test_result': test_result,
        'study': study
    }


def save_results(results: Dict[str, Any], args):
    """保存优化结果"""

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"martingale_bbw_optimization_{args.target}_{timestamp}.json"
    filepath = output_dir / filename

    # 序列化结果
    result_data = {
        'target': results['target'],
        'best_params': results['best_params'],
        'full_params': results['full_params'],
        'best_fitness': results['best_fitness'],
        'train_result': {
            'total_trades': results['train_result']['total_trades'],
            'win_rate': results['train_result']['win_rate'],
            'total_pnl': results['train_result']['total_pnl'],
            'total_return': results['train_result']['total_return'],
            'max_drawdown': results['train_result']['max_drawdown'],
            'max_drawdown_pct': results['train_result']['max_drawdown_pct'],
            'sharpe_ratio': results['train_result']['sharpe_ratio'],
            'calmar_ratio': results['train_result']['calmar_ratio'],
            'profit_factor': results['train_result']['profit_factor'],
        },
        'config': {
            'train_start': args.train_start,
            'train_end': args.train_end,
            'test_start': args.test_start,
            'test_end': args.test_end,
            'timeframe': args.timeframe,
            'n_trials': args.n_trials,
        }
    }

    if results['test_result']:
        result_data['test_result'] = {
            'total_trades': results['test_result']['total_trades'],
            'win_rate': results['test_result']['win_rate'],
            'total_pnl': results['test_result']['total_pnl'],
            'total_return': results['test_result']['total_return'],
            'max_drawdown': results['test_result']['max_drawdown'],
            'max_drawdown_pct': results['test_result']['max_drawdown_pct'],
            'sharpe_ratio': results['test_result']['sharpe_ratio'],
            'calmar_ratio': results['test_result']['calmar_ratio'],
            'profit_factor': results['test_result']['profit_factor'],
        }

    with open(filepath, 'w') as f:
        json.dump(result_data, f, indent=2, default=str)

    print(f"\n结果已保存: {filepath}")

    return filepath


def main():
    """主函数"""
    args = parse_args()

    try:
        # 运行优化
        results = run_optimization(args)

        # 保存结果
        save_results(results, args)

        print("\n" + "=" * 80)
        print("优化流程完成!")
        print("=" * 80)

        return 0

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
