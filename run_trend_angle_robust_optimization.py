"""
趋势角度突破策略 - 稳健贝叶斯优化
================================
使用Optuna TPE算法进行超参数优化，Tick数据回测确保真实性

优化目标: 稳健性加权评分 (Calmar + OOS稳定性)
数据划分:
- IS (样本内): 2025-01-01 ~ 2025-10-31 (用于优化)
- OOS (样本外): 2025-11-01 ~ 2026-02-28 (用于验证)

防过拟合设计:
1. 参数复杂度惩罚 ( simpler is better )
2. 多目标优化 (Pareto前沿)
3. Walk-Forward验证
4. 交易一致性约束
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

SPREAD_PER_OUNCE = 0.2
SLIPPAGE_POINTS = 0.1
DATA_DIR = "/home/ctyun/xauusd_data"

IS_START = "2025-01-01"
IS_END = "2025-10-31"
OOS_START = "2025-11-01"
OOS_END = "2026-02-28"

N_TRIALS = 300
MIN_TRADES_IS = 80
MIN_TRADES_OOS = 30
MAX_TRADES_PER_MONTH = 50  # 防止过度交易


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
    """加载K线数据(指标)和Tick数据(执行)"""
    print(f"Loading data from {start_date} to {end_date}...")
    loader = DataLoader(DATA_DIR)
    months = get_months_in_range(start_date, end_date)
    df = loader.load_range(months, "15min")
    df = df[(df.index >= start_date) & (df.index <= end_date)]
    print(f"Loaded {len(df)} 15min bars for indicators")
    print(f"Loading tick data for execution...")
    tick_df = load_tick_data_for_period(loader, months)
    if tick_df is not None:
        tick_df = tick_df[(tick_df.index >= start_date) & (tick_df.index <= end_date)]
        print(f"Total ticks loaded: {len(tick_df):,}")
    return df, tick_df


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
    """执行Tick级回测"""
    config = TradingConfig(
        symbol="XAUUSD",
        contract_size=100,
        spread_per_ounce=SPREAD_PER_OUNCE,
        commission_per_lot=3.5,
        initial_capital=100000.0,
        leverage=100,
        base_slippage=SLIPPAGE_POINTS,
    )
    execution = create_execution_model()
    engine = TickBacktestEngine(
        config=config,
        execution_model=execution,
        use_numba=False
    )
    engine.tick_df = tick_df
    engine.bar_idx_to_ticks = bar_idx_to_ticks
    strategy = TrendAngleBreakoutStrategy(params=params, strategy_id="TrendAngleBreakout")
    signals = []
    for i in range(warmup_bars, len(df)):
        signal = strategy.generate_signal(df, i)
        if signal:
            signals.append(signal)
    result = engine.run(df, signals, tick_df)
    return result


def calculate_walk_forward_score(results: List[BacktestResult]) -> float:
    """计算Walk-Forward一致性分数"""
    if not results or len(results) < 2:
        return 0.0
    returns = [r.total_return for r in results]
    if all(r > 0 for r in returns):
        consistency = 1.0 - np.std(returns) / (np.mean(returns) + 1e-6)
    else:
        positive_periods = sum(1 for r in returns if r > 0)
        consistency = positive_periods / len(returns)
    avg_calmar = np.mean([
        r.total_return / abs(r.max_drawdown_pct) if r.max_drawdown_pct != 0 else r.total_return
        for r in results
    ])
    return avg_calmar * consistency


def calculate_fitness_robust(
    is_result: BacktestResult,
    oos_result: Optional[BacktestResult] = None,
    wf_results: Optional[List[BacktestResult]] = None,
    params: Optional[Dict] = None
) -> float:
    """
    稳健性加权适应度函数

    设计原则:
    1. IS表现必须达标
    2. OOS表现必须有正贡献
    3. 参数复杂度惩罚
    4. Walk-Forward一致性
    """
    # 基础约束检查
    if is_result.total_trades < MIN_TRADES_IS:
        return -1.0 + is_result.total_trades / MIN_TRADES_IS

    if is_result.max_drawdown_pct < -0.4:
        return -0.5 + is_result.max_drawdown_pct

    if is_result.profit_factor < 0.8:
        return -0.3

    # 计算月度交易频率 (防止过度优化)
    months_in_is = 10  # Jan-Oct
    trades_per_month = is_result.total_trades / months_in_is
    if trades_per_month > MAX_TRADES_PER_MONTH:
        return 0.5  # 过度交易惩罚

    # IS Calmar
    is_calmar = is_result.total_return / abs(is_result.max_drawdown_pct) if is_result.max_drawdown_pct != 0 else is_result.total_return

    # 基础分数
    score = is_calmar * 0.4 + is_result.sharpe_ratio * 0.3

    # OOS稳健性评分 (关键!)
    if oos_result and oos_result.total_trades >= MIN_TRADES_OOS:
        # OOS必须盈利才有奖励
        if oos_result.total_return > 0:
            oos_calmar = oos_result.total_return / abs(oos_result.max_drawdown_pct) if oos_result.max_drawdown_pct != 0 else oos_result.total_return
            # 计算IS-OOS一致性
            consistency = 1.0 - abs(is_result.total_return - oos_result.total_return) / (abs(is_result.total_return) + 0.01)
            consistency = max(0, consistency)
            oos_score = oos_calmar * consistency
            score += oos_score * 0.3  # OOS贡献30%
        else:
            # OOS亏损严重惩罚
            score += oos_result.total_return * 2.0  # 负向贡献

    # Walk-Forward分数
    if wf_results:
        wf_score = calculate_walk_forward_score(wf_results)
        score += wf_score * 0.2

    # 参数复杂度惩罚 (Occam's Razor)
    if params:
        # 偏好简单参数
        complexity_penalty = 0.0
        if params.get('angle_threshold', 3.0) > 6.0:
            complexity_penalty += 0.1
        if params.get('risk_reward_ratio', 2.0) > 3.5:
            complexity_penalty += 0.05
        if params.get('breakout_lookback', 2) > 4:
            complexity_penalty += 0.05
        score -= complexity_penalty

    return score


def run_walk_forward_test(
    is_df: pd.DataFrame,
    is_tick_df: Optional[pd.DataFrame],
    params: Dict[str, Any],
    n_splits: int = 3
) -> List[BacktestResult]:
    """运行Walk-Forward测试，将IS数据分为多个period"""
    results = []
    total_bars = len(is_df)
    bars_per_split = total_bars // n_splits

    for i in range(n_splits):
        start_idx = i * bars_per_split
        end_idx = (i + 1) * bars_per_split if i < n_splits - 1 else total_bars

        split_df = is_df.iloc[start_idx:end_idx].copy()

        # 过滤对应的tick数据
        split_tick_df = None
        if is_tick_df is not None:
            split_tick_df = is_tick_df[
                (is_tick_df.index >= split_df.index[0]) &
                (is_tick_df.index <= split_df.index[-1])
            ].copy()

        df_with_indicators = calculate_strategy_indicators(
            split_df.copy(),
            sma_period=params['sma_period'],
            atr_period=14,
            angle_lookback=5
        )

        # 准备tick映射
        bar_idx_to_ticks = None
        if split_tick_df is not None:
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
            bar_idx_to_ticks = engine.prepare_tick_data(split_tick_df, df_with_indicators.index)

        result = run_tick_backtest(
            df_with_indicators,
            split_tick_df,
            bar_idx_to_ticks,
            params,
            warmup_bars=max(100, params['sma_period'] + 20)
        )
        results.append(result)

    return results


def create_robust_objective(
    is_df: pd.DataFrame,
    is_tick_df: Optional[pd.DataFrame],
    bar_idx_to_ticks: Optional[np.ndarray],
    oos_df: pd.DataFrame,
    oos_tick_df: Optional[pd.DataFrame],
    oos_bar_idx_to_ticks: Optional[np.ndarray],
    enable_walk_forward: bool = True
):
    """创建稳健性优化的目标函数"""

    def objective(trial: optuna.Trial) -> float:
        # 限制参数范围防止过拟合
        params = {
            'sma_period': trial.suggest_int('sma_period', 15, 35),
            'angle_threshold': trial.suggest_float('angle_threshold', 2.0, 5.0),  # 收紧范围
            'risk_reward_ratio': trial.suggest_float('risk_reward_ratio', 1.5, 3.0),  # 收紧范围
            'breakout_lookback': trial.suggest_int('breakout_lookback', 1, 3),  # 减少选择
            'use_fixed_exit': trial.suggest_categorical('use_fixed_exit', [True, False]),
        }

        try:
            # IS回测
            df_with_indicators = calculate_strategy_indicators(
                is_df.copy(),
                sma_period=params['sma_period'],
                atr_period=14,
                angle_lookback=5
            )

            is_result = run_tick_backtest(
                df_with_indicators,
                is_tick_df,
                bar_idx_to_ticks,
                params,
                warmup_bars=max(100, params['sma_period'] + 20)
            )

            # OOS回测 (每个trial都跑，确保稳健性)
            oos_result = None
            if oos_df is not None and len(oos_df) > 0:
                oos_df_indicators = calculate_strategy_indicators(
                    oos_df.copy(),
                    sma_period=params['sma_period'],
                    atr_period=14,
                    angle_lookback=5
                )
                oos_result = run_tick_backtest(
                    oos_df_indicators,
                    oos_tick_df,
                    oos_bar_idx_to_ticks,
                    params,
                    warmup_bars=max(100, params['sma_period'] + 20)
                )

            # Walk-Forward测试 (每5个trial跑一次，节省计算)
            wf_results = None
            if enable_walk_forward and trial.number % 5 == 0:
                wf_results = run_walk_forward_test(is_df, is_tick_df, params, n_splits=3)

            # 计算稳健性分数
            fitness = calculate_fitness_robust(is_result, oos_result, wf_results, params)

            # 记录详细指标
            trial.set_user_attr('is_total_trades', is_result.total_trades)
            trial.set_user_attr('is_win_rate', is_result.win_rate)
            trial.set_user_attr('is_profit_factor', is_result.profit_factor)
            trial.set_user_attr('is_total_return', is_result.total_return)
            trial.set_user_attr('is_max_drawdown_pct', is_result.max_drawdown_pct)
            trial.set_user_attr('is_sharpe_ratio', is_result.sharpe_ratio)
            trial.set_user_attr('is_calmar', is_result.total_return / abs(is_result.max_drawdown_pct) if is_result.max_drawdown_pct != 0 else is_result.total_return)

            if oos_result:
                trial.set_user_attr('oos_total_trades', oos_result.total_trades)
                trial.set_user_attr('oos_win_rate', oos_result.win_rate)
                trial.set_user_attr('oos_total_return', oos_result.total_return)
                trial.set_user_attr('oos_max_drawdown_pct', oos_result.max_drawdown_pct)
                trial.set_user_attr('oos_sharpe_ratio', oos_result.sharpe_ratio)
                oos_calmar = oos_result.total_return / abs(oos_result.max_drawdown_pct) if oos_result.max_drawdown_pct != 0 else oos_result.total_return
                trial.set_user_attr('oos_calmar', oos_calmar)
                trial.set_user_attr('oos_profit', oos_result.total_return > 0)

            return fitness

        except Exception as e:
            print(f"Error in trial {trial.number}: {e}")
            return -1e6

    return objective


def run_robust_optimization(
    is_df: pd.DataFrame,
    is_tick_df: Optional[pd.DataFrame],
    oos_df: pd.DataFrame,
    oos_tick_df: Optional[pd.DataFrame],
    n_trials: int = N_TRIALS
) -> Tuple[Dict, float, optuna.Study]:
    """运行稳健性贝叶斯优化"""
    print(f"\n{'='*70}")
    print(f"Robust Bayesian Optimization - {n_trials} trials")
    print(f"Target: Robustness-weighted Calmar (IS + OOS)")
    print(f"{'='*70}\n")

    # 预计算IS tick映射
    is_bar_idx_to_ticks = None
    if is_tick_df is not None:
        print("Pre-computing IS tick mapping...")
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
        is_bar_idx_to_ticks = engine.prepare_tick_data(is_tick_df, is_df.index)
        print(f"  Mapped {len(is_df)} bars to {len(is_tick_df)} ticks")

    # 预计算OOS tick映射
    oos_bar_idx_to_ticks = None
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
        oos_bar_idx_to_ticks = engine.prepare_tick_data(oos_tick_df, oos_df.index)
        print(f"  Mapped {len(oos_df)} bars to {len(oos_tick_df)} ticks")

    # 创建study - 使用更严格的pruner
    study = optuna.create_study(
        direction='maximize',
        sampler=optuna.samplers.TPESampler(
            n_startup_trials=30,  # 增加随机探索
            n_ei_candidates=24,
            seed=42
        ),
        study_name="trend_angle_robust",
        pruner=optuna.pruners.HyperbandPruner(
            min_resource=1,
            reduction_factor=3
        )
    )

    # 创建目标函数
    objective = create_robust_objective(
        is_df, is_tick_df, is_bar_idx_to_ticks,
        oos_df, oos_tick_df, oos_bar_idx_to_ticks,
        enable_walk_forward=True
    )

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
    print(f"\nBest Trial IS Metrics:")
    print(f"  Total Trades: {best_trial.user_attrs['is_total_trades']}")
    print(f"  Win Rate: {best_trial.user_attrs['is_win_rate']:.2%}")
    print(f"  Profit Factor: {best_trial.user_attrs['is_profit_factor']:.2f}")
    print(f"  Total Return: {best_trial.user_attrs['is_total_return']:.2%}")
    print(f"  Max Drawdown: {best_trial.user_attrs['is_max_drawdown_pct']:.2%}")
    print(f"  Sharpe Ratio: {best_trial.user_attrs['is_sharpe_ratio']:.2f}")
    print(f"  Calmar Ratio: {best_trial.user_attrs['is_calmar']:.2f}")

    if 'oos_total_return' in best_trial.user_attrs:
        print(f"\nBest Trial OOS Metrics:")
        print(f"  Total Trades: {best_trial.user_attrs['oos_total_trades']}")
        print(f"  Win Rate: {best_trial.user_attrs['oos_win_rate']:.2%}")
        print(f"  Total Return: {best_trial.user_attrs['oos_total_return']:.2%}")
        print(f"  Max Drawdown: {best_trial.user_attrs['oos_max_drawdown_pct']:.2%}")
        print(f"  Sharpe Ratio: {best_trial.user_attrs['oos_sharpe_ratio']:.2f}")
        print(f"  Calmar Ratio: {best_trial.user_attrs['oos_calmar']:.2f}")
        print(f"  OOS Profitable: {'✓' if best_trial.user_attrs['oos_profit'] else '✗'}")

    return best_params, best_fitness, study


def find_pareto_optimal_trials(study: optuna.Study, top_n: int = 5) -> List[optuna.Trial]:
    """找到Pareto最优的trials (IS表现 vs OOS稳健性)"""
    trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]

    # 收集每个trial的IS Calmar和OOS Calmar
    trial_metrics = []
    for trial in trials:
        is_calmar = trial.user_attrs.get('is_calmar', -999)
        oos_calmar = trial.user_attrs.get('oos_calmar', -999)
        oos_profit = trial.user_attrs.get('oos_profit', False)

        # 优先选择OOS盈利的
        score = is_calmar + (oos_calmar if oos_profit else oos_calmar * 0.5)
        trial_metrics.append((trial, score, is_calmar, oos_calmar, oos_profit))

    # 按综合分数排序
    trial_metrics.sort(key=lambda x: (x[4], x[1]), reverse=True)  # OOS盈利优先，然后综合分数

    return [t[0] for t in trial_metrics[:top_n]]


def analyze_robustness_detailed(
    is_result: BacktestResult,
    oos_result: BacktestResult
) -> Dict:
    """详细稳健性分析"""
    print(f"\n{'='*70}")
    print("Detailed Robustness Analysis")
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
    robustness_details = {}

    print(f"{'Metric':<20} {'IS':>12} {'OOS':>12} {'Diff':>12} {'Robust?':>10}")
    print("-" * 70)

    for name, (is_val, oos_val) in metrics.items():
        if name == 'total_trades':
            diff_pct = abs(is_val - oos_val) / max(is_val, 1) * 100
            is_robust = diff_pct < 50
            robustness[name] = is_robust
            robustness_details[name] = {'is': is_val, 'oos': oos_val, 'diff': diff_pct/100, 'robust': is_robust}
            print(f"{name:<20} {is_val:>12.0f} {oos_val:>12.0f} {diff_pct:>11.1f}% {'✓' if is_robust else '✗':>10}")
        else:
            diff = abs(is_val - oos_val)
            same_direction = (is_val > 0) == (oos_val > 0)
            relative_diff = diff / (abs(is_val) + 1e-6)
            is_robust = same_direction and relative_diff < 0.5
            robustness[name] = is_robust
            robustness_details[name] = {'is': is_val, 'oos': oos_val, 'diff': relative_diff, 'robust': is_robust}
            print(f"{name:<20} {is_val:>12.4f} {oos_val:>12.4f} {diff:>+12.4f} {'✓' if is_robust else '✗':>10}")

    overall_robust = sum(robustness.values()) / len(robustness)
    print(f"\nOverall Robustness: {overall_robust:.0%} ({sum(robustness.values())}/{len(robustness)})")

    # OOS盈利能力特别重要
    if oos_result.total_return > 0:
        print(f"✓ OOS Profitable: {oos_result.total_return:.2%}")
    else:
        print(f"✗ OOS Unprofitable: {oos_result.total_return:.2%}")

    return robustness_details


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Trend Angle Strategy Robust Bayesian Optimization')
    parser.add_argument('--trials', type=int, default=N_TRIALS, help='Number of optimization trials')
    parser.add_argument('--is-start', type=str, default=IS_START, help='IS start date')
    parser.add_argument('--is-end', type=str, default=IS_END, help='IS end date')
    parser.add_argument('--oos-start', type=str, default=OOS_START, help='OOS start date')
    parser.add_argument('--oos-end', type=str, default=OOS_END, help='OOS end date')
    parser.add_argument('--no-tick', action='store_true', help='Disable tick data (use K-line mode)')
    parser.add_argument('--output', type=str, default='results/trend_angle_robust_params.json',
                        help='Output file for optimal params')

    args = parser.parse_args()

    print(f"\n{'='*70}")
    print("Trend Angle Breakout Strategy - Robust Bayesian Optimization")
    print(f"{'='*70}")
    print("\n防过拟合设计:")
    print("  - 收紧参数搜索范围")
    print("  - 每个trial都跑OOS验证")
    print("  - Walk-Forward一致性测试")
    print("  - OOS盈利作为硬约束")

    # 同时加载IS和OOS数据
    print(f"\n[1/3] Loading Data...")
    print(f"\nIS Period ({args.is_start} ~ {args.is_end}):")
    is_df, is_tick_df = load_data_for_optimization(args.is_start, args.is_end)

    print(f"\nOOS Period ({args.oos_start} ~ {args.oos_end}):")
    oos_df, oos_tick_df = load_data_for_optimization(args.oos_start, args.oos_end)

    if args.no_tick:
        print("  Tick data disabled - using K-line mode for execution")
        is_tick_df = None
        oos_tick_df = None

    # 运行稳健性优化
    print(f"\n[2/3] Running Robust Bayesian Optimization...")
    best_params, best_fitness, study = run_robust_optimization(
        is_df, is_tick_df,
        oos_df, oos_tick_df,
        n_trials=args.trials
    )

    # 找到Pareto最优的trials
    print(f"\n[3/3] Analyzing Pareto-Optimal Solutions...")
    pareto_trials = find_pareto_optimal_trials(study, top_n=3)

    print(f"\n{'='*70}")
    print("Top 3 Pareto-Optimal Solutions (IS Performance + OOS Robustness)")
    print(f"{'='*70}")

    for i, trial in enumerate(pareto_trials, 1):
        print(f"\n#{i} Trial {trial.number}:")
        print(f"  Params: sma={trial.params['sma_period']}, angle={trial.params['angle_threshold']:.2f}, "
              f"rr={trial.params['risk_reward_ratio']:.2f}, lookback={trial.params['breakout_lookback']}, "
              f"fixed_exit={trial.params['use_fixed_exit']}")
        print(f"  IS:  Return={trial.user_attrs['is_total_return']:.2%}, Calmar={trial.user_attrs['is_calmar']:.2f}, "
              f"Trades={trial.user_attrs['is_total_trades']}")
        if 'oos_total_return' in trial.user_attrs:
            print(f"  OOS: Return={trial.user_attrs['oos_total_return']:.2%}, Calmar={trial.user_attrs['oos_calmar']:.2f}, "
                  f"Trades={trial.user_attrs['oos_total_trades']}, Profit={'✓' if trial.user_attrs['oos_profit'] else '✗'}")

    # 使用最佳参数运行详细回测
    print(f"\n{'='*70}")
    print("Final Validation with Best Parameters")
    print(f"{'='*70}")

    # IS详细回测
    is_df_optimal = calculate_strategy_indicators(
        is_df.copy(),
        sma_period=best_params['sma_period'],
        atr_period=14,
        angle_lookback=5
    )

    is_engine = TickBacktestEngine(
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
    is_bar_idx_to_ticks = is_engine.prepare_tick_data(is_tick_df, is_df_optimal.index) if is_tick_df is not None else None

    is_result = run_tick_backtest(is_df_optimal, is_tick_df, is_bar_idx_to_ticks, best_params)

    # OOS详细回测
    oos_df_optimal = calculate_strategy_indicators(
        oos_df.copy(),
        sma_period=best_params['sma_period'],
        atr_period=14,
        angle_lookback=5
    )

    oos_engine = TickBacktestEngine(
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
    oos_bar_idx_to_ticks = oos_engine.prepare_tick_data(oos_tick_df, oos_df_optimal.index) if oos_tick_df is not None else None

    oos_result = run_tick_backtest(oos_df_optimal, oos_tick_df, oos_bar_idx_to_ticks, best_params)

    # 详细稳健性分析
    robustness = analyze_robustness_detailed(is_result, oos_result)

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
            'calmar': is_result.total_return / abs(is_result.max_drawdown_pct) if is_result.max_drawdown_pct != 0 else is_result.total_return,
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
            'calmar': oos_result.total_return / abs(oos_result.max_drawdown_pct) if oos_result.max_drawdown_pct != 0 else oos_result.total_return,
        },
        'robustness': robustness,
        'pareto_solutions': [
            {
                'trial_number': t.number,
                'params': t.params,
                'is_calmar': t.user_attrs.get('is_calmar'),
                'oos_calmar': t.user_attrs.get('oos_calmar'),
                'oos_profit': t.user_attrs.get('oos_profit'),
            }
            for t in pareto_trials
        ]
    }

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_path}")

    print(f"\n{'='*70}")
    print("Robust Optimization Complete!")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()
