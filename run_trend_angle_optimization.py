"""
趋势角度突破策略 - Tick级贝叶斯优化
=====================================
使用Optuna TPE算法进行超参数优化，Tick数据回测确保真实性

优化目标: Calmar Ratio (收益/最大回撤)
数据划分:
- IS (样本内): 2025-01-01 ~ 2025-10-31 (用于优化)
- OOS (样本外): 2025-11-01 ~ 2026-02-28 (用于验证)

特点:
- Tick级执行精度
- K线仅用于指标计算
- 防止过拟合设计
"""

import sys
import optuna
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import json
import warnings

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from strategies.trend_angle_breakout import (
    TrendAngleBreakoutStrategy,
    calculate_strategy_indicators
)
from engines.tick_engine import TickBacktestEngine
from engines.base import ExecutionModel
from core.config import TradingConfig
from core.types import BacktestResult
from core.data_loader import DataLoader


# ============================================================================
# 配置常量
# ============================================================================

SPREAD_PER_OUNCE = 0.2
SLIPPAGE_POINTS = 0.1
DATA_DIR = "/home/ctyun/xauusd_data"

# 回测周期
IS_START = "2025-01-01"
IS_END = "2025-10-31"
OOS_START = "2025-11-01"
OOS_END = "2026-02-28"

# 优化配置
N_TRIALS = 200
MIN_TRADES = 50


# ============================================================================
# 数据加载
# ============================================================================

def get_months_in_range(start_date: str, end_date: str) -> List[str]:
    """获取日期范围内的所有月份"""
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    months = []
    current = start.replace(day=1)
    while current <= end:
        months.append(current.strftime('%Y-%m'))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return months


def load_tick_data_for_period(
    loader: DataLoader,
    months: List[str]
) -> Optional[pd.DataFrame]:
    """加载tick数据用于回测执行"""
    tick_dfs = []

    for month_str in months:
        try:
            year, month = map(int, month_str.split('-'))
            filename = f"XAUUSD_{year}-{month:02d}.csv"
            filepath = loader.data_dir / filename

            if not filepath.exists():
                print(f"  Warning: Tick file not found: {filename}")
                continue

            tick_df = loader.load_tick_data(filepath)
            tick_df['Mid'] = (tick_df['Bid'] + tick_df['Ask']) / 2
            tick_dfs.append(tick_df)
            print(f"  Loaded {len(tick_df):,} ticks from {month_str}")

        except Exception as e:
            print(f"  Warning: Failed to load tick data for {month_str}: {e}")
            continue

    if not tick_dfs:
        return None

    combined = pd.concat(tick_dfs)
    combined = combined.sort_index()
    combined = combined[~combined.index.duplicated(keep='first')]
    return combined


def load_data_for_optimization(
    start_date: str,
    end_date: str
) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    """
    加载K线数据(指标)和Tick数据(执行)

    Returns:
        (ohlcv_df, tick_df)
    """
    print(f"Loading data from {start_date} to {end_date}...")

    loader = DataLoader(DATA_DIR)
    months = get_months_in_range(start_date, end_date)

    # 加载K线数据用于指标计算
    df = loader.load_range(months, "15min")
    df = df[(df.index >= start_date) & (df.index <= end_date)]
    print(f"Loaded {len(df)} 15min bars for indicators")

    # 加载tick数据用于回测执行
    print(f"Loading tick data for execution...")
    tick_df = load_tick_data_for_period(loader, months)
    if tick_df is not None:
        tick_df = tick_df[(tick_df.index >= start_date) & (tick_df.index <= end_date)]
        print(f"Total ticks loaded: {len(tick_df):,}")

    return df, tick_df


# ============================================================================
# 回测函数
# ============================================================================

def create_execution_model() -> ExecutionModel:
    """创建执行模型（含成本设定）"""
    return ExecutionModel(
        spread_per_ounce=SPREAD_PER_OUNCE,
        contract_size=100,
        base_slippage=SLIPPAGE_POINTS,
        atr_slippage_ratio=0.03,
        stop_loss_slippage_mult=2.0,
        take_profit_slippage_mult=0.0,
        commission_per_lot=3.5,
    )


def run_tick_backtest(
    df: pd.DataFrame,
    tick_df: Optional[pd.DataFrame],
    bar_idx_to_ticks: Optional[np.ndarray],
    params: Dict[str, Any],
    warmup_bars: int = 100
) -> BacktestResult:
    """
    执行Tick级回测

    Args:
        df: OHLCV数据（已计算指标）
        tick_df: Tick数据（用于执行），如果None则使用K线模式
        bar_idx_to_ticks: 预计算的tick映射
        params: 策略参数
        warmup_bars: 预热K线数
    """
    # 创建配置
    config = TradingConfig(
        symbol="XAUUSD",
        contract_size=100,
        spread_per_ounce=SPREAD_PER_OUNCE,
        commission_per_lot=3.5,
        initial_capital=100000.0,
        leverage=100,
        base_slippage=SLIPPAGE_POINTS,
    )

    # 创建引擎
    execution = create_execution_model()
    engine = TickBacktestEngine(
        config=config,
        execution_model=execution,
        use_numba=False
    )

    # 直接使用预计算的tick映射
    engine.tick_df = tick_df
    engine.bar_idx_to_ticks = bar_idx_to_ticks

    # 创建策略
    strategy = TrendAngleBreakoutStrategy(params=params, strategy_id="TrendAngleBreakout")

    # 生成信号
    signals = []
    for i in range(warmup_bars, len(df)):
        signal = strategy.generate_signal(df, i)
        if signal:
            signals.append(signal)

    # 执行回测
    result = engine.run(df, signals, tick_df)

    return result


def calculate_fitness(result: BacktestResult, target: str = 'calmar') -> float:
    """
    计算优化目标值

    防止过拟合设计:
    1. 最少交易次数要求
    2. 对极端回撤进行惩罚
    3. 综合评分可选
    """
    # 最少交易次数检查
    if result.total_trades < MIN_TRADES:
        return -1.0 + result.total_trades / MIN_TRADES

    # 极端回撤惩罚
    if result.max_drawdown_pct < -0.5:  # 回撤超过50%
        return -0.5 + result.max_drawdown_pct

    # 亏损因子惩罚
    if result.total_trades > 0 and result.profit_factor < 0.5:
        return -0.3

    # 计算目标值
    if target == 'calmar':
        calmar = result.total_return / abs(result.max_drawdown_pct) if result.max_drawdown_pct != 0 else result.total_return
        return calmar
    elif target == 'sharpe':
        return result.sharpe_ratio
    elif target == 'profit_factor':
        return min(result.profit_factor, 5.0)
    elif target == 'total_return':
        return result.total_return
    else:
        # 综合评分
        calmar = result.total_return / abs(result.max_drawdown_pct) if result.max_drawdown_pct != 0 else result.total_return
        return calmar * 0.4 + result.sharpe_ratio * 0.3 + min(result.profit_factor, 3.0) * 0.1 + result.win_rate * 0.2


# ============================================================================
# Optuna 目标函数
# ============================================================================

def create_objective(
    is_df: pd.DataFrame,
    is_tick_df: Optional[pd.DataFrame],
    bar_idx_to_ticks: Optional[np.ndarray],
    target: str = 'calmar'
):
    """创建Optuna目标函数"""

    def objective(trial: optuna.Trial) -> float:
        """优化目标函数"""
        # 定义参数搜索空间
        params = {
            'sma_period': trial.suggest_int('sma_period', 10, 50),
            'angle_threshold': trial.suggest_float('angle_threshold', 1.0, 8.0),
            'risk_reward_ratio': trial.suggest_float('risk_reward_ratio', 1.0, 4.0),
            'breakout_lookback': trial.suggest_int('breakout_lookback', 1, 5),
            'use_fixed_exit': trial.suggest_categorical('use_fixed_exit', [True, False]),
        }

        try:
            # 使用当前参数重新计算指标
            df_with_indicators = calculate_strategy_indicators(
                is_df.copy(),
                sma_period=params['sma_period'],
                atr_period=14,
                angle_lookback=5
            )

            # 运行回测（使用预计算的tick映射）
            result = run_tick_backtest(
                df_with_indicators,
                is_tick_df,
                bar_idx_to_ticks,
                params,
                warmup_bars=max(100, params['sma_period'] + 20)
            )

            # 计算适应度
            fitness = calculate_fitness(result, target)

            # 记录回测指标
            trial.set_user_attr('total_trades', result.total_trades)
            trial.set_user_attr('win_rate', result.win_rate)
            trial.set_user_attr('profit_factor', result.profit_factor)
            trial.set_user_attr('total_return', result.total_return)
            trial.set_user_attr('max_drawdown_pct', result.max_drawdown_pct)
            trial.set_user_attr('sharpe_ratio', result.sharpe_ratio)

            return fitness

        except Exception as e:
            print(f"Error in trial: {e}")
            return -1e6

    return objective


# ============================================================================
# 主优化流程
# ============================================================================

def run_bayesian_optimization(
    is_df: pd.DataFrame,
    is_tick_df: Optional[pd.DataFrame],
    n_trials: int = N_TRIALS,
    target: str = 'calmar'
) -> Tuple[Dict, float, Optional[np.ndarray]]:
    """运行贝叶斯优化"""
    print(f"\n{'='*70}")
    print(f"Bayesian Optimization - {n_trials} trials")
    print(f"Target: {target}")
    print(f"{'='*70}\n")

    # 预计算tick映射（关键优化！）
    bar_idx_to_ticks = None
    if is_tick_df is not None:
        print("Pre-computing tick mapping...")
        engine = TickBacktestEngine(
            config=TradingConfig(
                symbol="XAUUSD",
                contract_size=100,
                spread_per_ounce=SPREAD_PER_OUNCE,
                commission_per_lot=3.5,
                initial_capital=100000.0,
                leverage=100,
                base_slippage=SLIPPAGE_POINTS,
            ),
            use_numba=False
        )
        bar_idx_to_ticks = engine.prepare_tick_data(is_tick_df, is_df.index)
        print(f"  Mapped {len(is_df)} bars to {len(is_tick_df)} ticks")

    # 创建study
    study = optuna.create_study(
        direction='maximize',
        sampler=optuna.samplers.TPESampler(
            n_startup_trials=20,
            n_ei_candidates=24,
            seed=42
        ),
        study_name="trend_angle_optimization",
        pruner=optuna.pruners.MedianPruner(
            n_startup_trials=10,
            n_warmup_steps=5
        )
    )

    # 创建目标函数
    objective = create_objective(is_df, is_tick_df, bar_idx_to_ticks, target)

    # 运行优化
    study.optimize(
        objective,
        n_trials=n_trials,
        show_progress_bar=True,
        catch=(Exception,)
    )

    # 获取最优结果
    best_params = study.best_params
    best_fitness = study.best_value

    print(f"\n{'='*70}")
    print("Optimization Complete")
    print(f"{'='*70}")
    print(f"\nBest Fitness: {best_fitness:.4f}")
    print(f"\nBest Parameters:")
    for param, value in best_params.items():
        print(f"  {param}: {value}")

    # 显示最优结果的详细指标
    best_trial = study.best_trial
    print(f"\nBest Trial Metrics:")
    print(f"  Total Trades: {best_trial.user_attrs['total_trades']}")
    print(f"  Win Rate: {best_trial.user_attrs['win_rate']:.2%}")
    print(f"  Profit Factor: {best_trial.user_attrs['profit_factor']:.2f}")
    print(f"  Total Return: {best_trial.user_attrs['total_return']:.2%}")
    print(f"  Max Drawdown: {best_trial.user_attrs['max_drawdown_pct']:.2%}")
    print(f"  Sharpe Ratio: {best_trial.user_attrs['sharpe_ratio']:.2f}")

    return best_params, best_fitness, bar_idx_to_ticks


def run_oos_validation(
    oos_df: pd.DataFrame,
    oos_tick_df: Optional[pd.DataFrame],
    best_params: Dict
) -> BacktestResult:
    """运行样本外验证"""
    print(f"\n{'='*70}")
    print("Out-of-Sample Validation")
    print(f"{'='*70}\n")

    # 预计算OOS tick映射
    bar_idx_to_ticks = None
    if oos_tick_df is not None:
        print("Pre-computing OOS tick mapping...")
        engine = TickBacktestEngine(
            config=TradingConfig(
                symbol="XAUUSD",
                contract_size=100,
                spread_per_ounce=SPREAD_PER_OUNCE,
                commission_per_lot=3.5,
                initial_capital=100000.0,
                leverage=100,
                base_slippage=SLIPPAGE_POINTS,
            ),
            use_numba=False
        )
        bar_idx_to_ticks = engine.prepare_tick_data(oos_tick_df, oos_df.index)
        print(f"  Mapped {len(oos_df)} bars to {len(oos_tick_df)} ticks")

    # 使用最优参数准备数据
    df_with_indicators = calculate_strategy_indicators(
        oos_df.copy(),
        sma_period=best_params['sma_period'],
        atr_period=14,
        angle_lookback=5
    )

    # 运行回测
    result = run_tick_backtest(
        df_with_indicators,
        oos_tick_df,
        bar_idx_to_ticks,
        best_params,
        warmup_bars=max(100, best_params['sma_period'] + 20)
    )

    print(f"OOS Results:")
    print(f"  Total Trades: {result.total_trades}")
    print(f"  Win Rate: {result.win_rate:.2%}")
    print(f"  Profit Factor: {result.profit_factor:.2f}")
    print(f"  Total Return: {result.total_return:.2%}")
    print(f"  Max Drawdown: {result.max_drawdown_pct:.2%}")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:.2f}")

    return result


def analyze_robustness(
    is_result: BacktestResult,
    oos_result: BacktestResult
) -> Dict:
    """分析策略稳健性"""
    print(f"\n{'='*70}")
    print("Robustness Analysis")
    print(f"{'='*70}\n")

    metrics = {
        'total_trades': (is_result.total_trades, oos_result.total_trades),
        'win_rate': (is_result.win_rate, oos_result.win_rate),
        'profit_factor': (is_result.profit_factor, oos_result.profit_factor),
        'total_return': (is_result.total_return, oos_result.total_return),
        'max_drawdown': (is_result.max_drawdown_pct, oos_result.max_drawdown_pct),
        'sharpe_ratio': (is_result.sharpe_ratio, oos_result.sharpe_ratio),
    }

    robustness = {}
    print(f"{'Metric':<20} {'IS':>12} {'OOS':>12} {'Diff':>12} {'Robust?':>10}")
    print("-" * 70)

    for name, (is_val, oos_val) in metrics.items():
        if name == 'total_trades':
            diff_pct = abs(is_val - oos_val) / max(is_val, 1) * 100
            is_robust = diff_pct < 50
            robustness[name] = is_robust
            print(f"{name:<20} {is_val:>12.0f} {oos_val:>12.0f} {diff_pct:>11.1f}% {'✓' if is_robust else '✗':>10}")
        else:
            diff = abs(is_val - oos_val)
            same_direction = (is_val > 0) == (oos_val > 0)
            is_robust = same_direction and diff < abs(is_val) * 0.5
            robustness[name] = is_robust
            print(f"{name:<20} {is_val:>12.4f} {oos_val:>12.4f} {diff:>+12.4f} {'✓' if is_robust else '✗':>10}")

    overall_robust = sum(robustness.values()) / len(robustness)
    print(f"\nOverall Robustness: {overall_robust:.0%} ({sum(robustness.values())}/{len(robustness)})")

    return robustness


# ============================================================================
# 主函数
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Trend Angle Strategy Bayesian Optimization')
    parser.add_argument('--trials', type=int, default=N_TRIALS, help='Number of optimization trials')
    parser.add_argument('--target', type=str, default='calmar',
                        choices=['calmar', 'sharpe', 'profit_factor', 'total_return', 'composite'],
                        help='Optimization target')
    parser.add_argument('--is-start', type=str, default=IS_START, help='IS start date')
    parser.add_argument('--is-end', type=str, default=IS_END, help='IS end date')
    parser.add_argument('--oos-start', type=str, default=OOS_START, help='OOS start date')
    parser.add_argument('--oos-end', type=str, default=OOS_END, help='OOS end date')
    parser.add_argument('--no-tick', action='store_true', help='Disable tick data (use K-line mode)')
    parser.add_argument('--output', type=str, default='results/trend_angle_optimal_params.json',
                        help='Output file for optimal params')

    args = parser.parse_args()

    print(f"\n{'='*70}")
    print("Trend Angle Breakout Strategy - Tick-Level Bayesian Optimization")
    print(f"{'='*70}")

    # 加载样本内数据
    print(f"\n[1/4] Loading In-Sample Data ({args.is_start} ~ {args.is_end})...")
    is_df, is_tick_df = load_data_for_optimization(args.is_start, args.is_end)

    if args.no_tick:
        print("  Tick data disabled - using K-line mode for execution")
        is_tick_df = None

    # 运行贝叶斯优化
    print(f"\n[2/4] Running Bayesian Optimization...")
    best_params, best_fitness, bar_idx_to_ticks = run_bayesian_optimization(
        is_df,
        is_tick_df,
        n_trials=args.trials,
        target=args.target
    )

    # 使用最优参数运行IS回测（详细结果）
    print(f"\n[3/4] Running IS Backtest with Best Params...")
    is_df_optimal = calculate_strategy_indicators(
        is_df.copy(),
        sma_period=best_params['sma_period'],
        atr_period=14,
        angle_lookback=5
    )
    is_result = run_tick_backtest(is_df_optimal, is_tick_df, bar_idx_to_ticks, best_params)

    print(f"\nIS Detailed Results:")
    print(f"  Total Trades: {is_result.total_trades}")
    print(f"  Win Rate: {is_result.win_rate:.2%}")
    print(f"  Profit Factor: {is_result.profit_factor:.2f}")
    print(f"  Total Return: {is_result.total_return:.2%}")
    print(f"  Max Drawdown: {is_result.max_drawdown_pct:.2%}")
    print(f"  Sharpe Ratio: {is_result.sharpe_ratio:.2f}")

    # 加载样本外数据
    print(f"\n[4/4] Loading Out-of-Sample Data ({args.oos_start} ~ {args.oos_end})...")
    oos_df, oos_tick_df = load_data_for_optimization(args.oos_start, args.oos_end)

    # 运行OOS验证
    oos_result = run_oos_validation(oos_df, oos_tick_df, best_params)

    # 稳健性分析
    robustness = analyze_robustness(is_result, oos_result)

    # 保存结果
    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True, parents=True)

    results = {
        'timestamp': datetime.now().isoformat(),
        'best_params': {
            k: bool(v) if isinstance(v, (bool, np.bool_)) else float(v) if isinstance(v, (np.floating, np.integer)) else v
            for k, v in best_params.items()
        },
        'best_fitness': float(best_fitness),
        'is_results': {
            'total_trades': is_result.total_trades,
            'winning_trades': is_result.winning_trades,
            'losing_trades': is_result.losing_trades,
            'win_rate': is_result.win_rate,
            'profit_factor': is_result.profit_factor,
            'total_pnl': is_result.total_pnl,
            'total_return': is_result.total_return,
            'max_drawdown_pct': is_result.max_drawdown_pct,
            'sharpe_ratio': is_result.sharpe_ratio,
        },
        'oos_results': {
            'total_trades': oos_result.total_trades,
            'winning_trades': oos_result.winning_trades,
            'losing_trades': oos_result.losing_trades,
            'win_rate': oos_result.win_rate,
            'profit_factor': oos_result.profit_factor,
            'total_pnl': oos_result.total_pnl,
            'total_return': oos_result.total_return,
            'max_drawdown_pct': oos_result.max_drawdown_pct,
            'sharpe_ratio': oos_result.sharpe_ratio,
        },
        'robustness': robustness,
    }

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_path}")

    print(f"\n{'='*70}")
    print("Optimization Complete!")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()
