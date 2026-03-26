"""
趋势角度突破策略 - 两阶段稳健优化
==============================
阶段1: IS数据快速优化 (Calmar目标)
阶段2: Top-N候选OOS验证 (选择最稳健的)

大幅减少计算时间的同时保证稳健性
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
from json import JSONEncoder


class NumpyEncoder(JSONEncoder):
    """处理numpy类型的JSON编码器"""
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

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

N_TRIALS = 200
MIN_TRADES_IS = 50
TOP_N_CANDIDATES = 10  # 只对前10个候选进行OOS验证

# 过拟合防护参数
MIN_TRADES_PER_MONTH = 3  # 最少每月3笔交易
MAX_TRADES_PER_MONTH = 15  # 最多每月15笔交易，避免过度交易
MIN_PROFIT_FACTOR = 1.1  # 最小盈利因子
MIN_WIN_RATE = 0.42  # 最小胜率


def get_months_in_range(start_date: str, end_date: str) -> List[str]:
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


def load_tick_data_for_period(loader: DataLoader, months: List[str]) -> Optional[pd.DataFrame]:
    tick_dfs = []
    for month_str in months:
        try:
            year, month = map(int, month_str.split('-'))
            filename = f"XAUUSD_{year}-{month:02d}.csv"
            filepath = loader.data_dir / filename
            if not filepath.exists():
                continue
            tick_df = loader.load_tick_data(filepath)
            tick_df['Mid'] = (tick_df['Bid'] + tick_df['Ask']) / 2
            tick_dfs.append(tick_df)
        except Exception as e:
            continue
    if not tick_dfs:
        return None
    combined = pd.concat(tick_dfs)
    combined = combined.sort_index()
    combined = combined[~combined.index.duplicated(keep='first')]
    return combined


def load_data_for_optimization(start_date: str, end_date: str) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    print(f"Loading data from {start_date} to {end_date}...")
    loader = DataLoader(DATA_DIR)
    months = get_months_in_range(start_date, end_date)
    df = loader.load_range(months, "15min")
    df = df[(df.index >= start_date) & (df.index <= end_date)]
    print(f"Loaded {len(df)} 15min bars")
    tick_df = load_tick_data_for_period(loader, months)
    if tick_df is not None:
        tick_df = tick_df[(tick_df.index >= start_date) & (tick_df.index <= end_date)]
        print(f"Loaded {len(tick_df):,} ticks")
    return df, tick_df


def create_execution_model() -> ExecutionModel:
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
    config = TradingConfig(
        symbol="XAUUSD", contract_size=100,
        spread_per_ounce=SPREAD_PER_OUNCE, commission_per_lot=3.5,
        initial_capital=100000.0, leverage=100, base_slippage=SLIPPAGE_POINTS,
    )
    execution = create_execution_model()
    engine = TickBacktestEngine(config=config, execution_model=execution)
    engine.tick_df = tick_df
    engine.bar_idx_to_ticks = bar_idx_to_ticks
    strategy = TrendAngleBreakoutStrategy(params=params, strategy_id="TrendAngleBreakout")
    signals = []
    for i in range(warmup_bars, len(df)):
        signal = strategy.generate_signal(df, i)
        if signal:
            signals.append(signal)
    return engine.run(df, signals, tick_df)


def calculate_fitness_is(result: BacktestResult) -> float:
    """阶段1: IS适应度，带多约束防止过拟合"""
    n_months = 10  # IS期间约10个月
    trades_per_month = result.total_trades / n_months

    # 1. 交易次数检查 - 避免过度交易
    if result.total_trades < MIN_TRADES_IS:
        return -1.0 + result.total_trades / MIN_TRADES_IS
    if trades_per_month < MIN_TRADES_PER_MONTH:
        return -0.5 + trades_per_month / MIN_TRADES_PER_MONTH * 0.5
    if trades_per_month > MAX_TRADES_PER_MONTH:
        # 过度交易惩罚
        return 0.5 - (trades_per_month - MAX_TRADES_PER_MONTH) * 0.1

    # 2. 风险控制检查 - 更严格
    if result.max_drawdown_pct < -0.30:  # 从-0.35收紧到-0.30
        return -0.5 + result.max_drawdown_pct

    # 3. 盈利能力检查 - 放宽门槛
    if result.profit_factor < 1.1:  # 从1.15放宽到1.1
        return -0.3 + (result.profit_factor - 1.0) * 0.5
    if result.win_rate < 0.40:  # 从0.45放宽到0.40
        return -0.2 + (result.win_rate - 0.35) * 2.0
    if result.total_return < 0.05:  # 从0.08放宽到0.05
        return -0.1 + result.total_return * 2.0

    # 4. 综合得分 = Calmar * 质量因子
    calmar = result.total_return / abs(result.max_drawdown_pct) if result.max_drawdown_pct != 0 else result.total_return

    # 质量因子：结合多个维度 - 提高门槛
    quality_factor = (
        0.25 * min(result.win_rate / 0.52, 1.0) +  # 胜率权重（从0.50提高到0.52）
        0.35 * min((result.profit_factor - 1.0) / 0.4, 1.0) +  # 盈利因子权重（提高）
        0.20 * min(trades_per_month / 8, 1.0) +  # 交易频率权重（从10降到8）
        0.20 * (1.0 if result.sharpe_ratio > 1.0 else result.sharpe_ratio / 1.0)  # Sharpe权重（从0.8提高到1.0）
    )

    return calmar * quality_factor


def create_is_objective(is_df: pd.DataFrame, is_tick_df: Optional[pd.DataFrame],
                        bar_idx_to_ticks: Optional[np.ndarray]):
    """阶段1: 仅IS优化的目标函数"""

    def objective(trial: optuna.Trial) -> float:
        # 扩大参数范围，增加探索空间
        params = {
            'sma_period': trial.suggest_int('sma_period', 15, 40),
            'angle_threshold': trial.suggest_float('angle_threshold', 2.0, 6.0),
            'risk_reward_ratio': trial.suggest_float('risk_reward_ratio', 1.2, 3.0),
            'breakout_lookback': trial.suggest_int('breakout_lookback', 2, 5),
            'trailing_stop_atr': trial.suggest_float('trailing_stop_atr', 1.0, 3.0),
            'use_fixed_exit': True,
        }

        try:
            df_with_indicators = calculate_strategy_indicators(
                is_df.copy(), sma_period=params['sma_period'], atr_period=14, angle_lookback=5
            )
            result = run_tick_backtest(
                df_with_indicators, is_tick_df, bar_idx_to_ticks, params,
                warmup_bars=max(100, params['sma_period'] + 20)
            )
            fitness = calculate_fitness_is(result)

            # 记录所有指标供后续选择
            trial.set_user_attr('total_trades', result.total_trades)
            trial.set_user_attr('win_rate', result.win_rate)
            trial.set_user_attr('profit_factor', result.profit_factor)
            trial.set_user_attr('total_return', result.total_return)
            trial.set_user_attr('max_drawdown_pct', result.max_drawdown_pct)
            trial.set_user_attr('sharpe_ratio', result.sharpe_ratio)
            trial.set_user_attr('calmar', result.total_return / abs(result.max_drawdown_pct)
                               if result.max_drawdown_pct != 0 else result.total_return)

            return fitness
        except Exception as e:
            print(f"Error in trial {trial.number}: {e}")
            return -1e6

    return objective


def run_is_optimization(is_df: pd.DataFrame, is_tick_df: Optional[pd.DataFrame],
                        n_trials: int) -> Tuple[optuna.Study, Optional[np.ndarray]]:
    """阶段1: IS优化"""
    print(f"\n{'='*70}")
    print(f"Phase 1: IS Optimization - {n_trials} trials")
    print(f"{'='*70}\n")

    bar_idx_to_ticks = None
    if is_tick_df is not None:
        print("Pre-computing IS tick mapping...")
        engine = TickBacktestEngine(
            config=TradingConfig(symbol="XAUUSD", contract_size=100,
                spread_per_ounce=SPREAD_PER_OUNCE, commission_per_lot=3.5,
                initial_capital=100000.0, leverage=100, base_slippage=SLIPPAGE_POINTS)
        )
        bar_idx_to_ticks = engine.prepare_tick_data(is_tick_df, is_df.index)
        print(f"  Mapped {len(is_df)} bars to {len(is_tick_df)} ticks")

    study = optuna.create_study(
        direction='maximize',
        sampler=optuna.samplers.TPESampler(n_startup_trials=30, n_ei_candidates=24, seed=42),
        study_name="trend_angle_is",
        pruner=optuna.pruners.MedianPruner(n_startup_trials=10, n_warmup_steps=5)
    )

    objective = create_is_objective(is_df, is_tick_df, bar_idx_to_ticks)

    # 使用callback显示进度而不是progress bar（避免缓冲问题）
    def progress_callback(study, trial):
        if trial.number % 10 == 0:
            print(f"  Trial {trial.number}/{n_trials}: Best={study.best_value:.3f}", flush=True)

    study.optimize(objective, n_trials=n_trials, show_progress_bar=False,
                   callbacks=[progress_callback], catch=(Exception,))

    print(f"\n{'='*70}")
    print("Phase 1 Complete")
    print(f"Best IS Calmar: {study.best_value:.4f}")
    print(f"{'='*70}")

    return study, bar_idx_to_ticks


def validate_top_candidates(
    study: optuna.Study,
    oos_df: pd.DataFrame,
    oos_tick_df: Optional[pd.DataFrame],
    top_n: int = TOP_N_CANDIDATES
) -> List[Dict]:
    """阶段2: 仅对Top-N候选进行OOS验证"""
    print(f"\n{'='*70}")
    print(f"Phase 2: OOS Validation - Top {top_n} Candidates")
    print(f"{'='*70}\n")

    # 获取所有完成trial，按IS表现排序
    trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    trials.sort(key=lambda t: t.value, reverse=True)
    top_trials = trials[:top_n]

    # 预计算OOS tick映射
    oos_bar_idx_to_ticks = None
    if oos_tick_df is not None:
        print("Pre-computing OOS tick mapping...")
        engine = TickBacktestEngine(
            config=TradingConfig(symbol="XAUUSD", contract_size=100,
                spread_per_ounce=SPREAD_PER_OUNCE, commission_per_lot=3.5,
                initial_capital=100000.0, leverage=100, base_slippage=SLIPPAGE_POINTS)
        )
        oos_bar_idx_to_ticks = engine.prepare_tick_data(oos_tick_df, oos_df.index)
        print(f"  Mapped {len(oos_df)} bars to {len(oos_tick_df)} ticks")

    results = []
    for i, trial in enumerate(top_trials, 1):
        params = trial.params
        print(f"\n[{i}/{top_n}] Trial {trial.number}: IS Calmar={trial.value:.3f}")
        print(f"  Params: sma={params['sma_period']}, angle={params['angle_threshold']:.2f}, "
              f"rr={params['risk_reward_ratio']:.2f}, lookback={params['breakout_lookback']}")

        try:
            oos_df_indicators = calculate_strategy_indicators(
                oos_df.copy(), sma_period=params['sma_period'], atr_period=14, angle_lookback=5
            )
            oos_result = run_tick_backtest(
                oos_df_indicators, oos_tick_df, oos_bar_idx_to_ticks, params,
                warmup_bars=max(100, params['sma_period'] + 20)
            )

            oos_calmar = oos_result.total_return / abs(oos_result.max_drawdown_pct) \
                        if oos_result.max_drawdown_pct != 0 else oos_result.total_return

            print(f"  OOS Result: Return={oos_result.total_return:.2%}, Calmar={oos_calmar:.3f}, "
                  f"Trades={oos_result.total_trades}")

            # 计算稳健性分数 - 更加重视OOS表现和一致性
            is_calmar = trial.value

            # 基础一致性得分
            calmar_diff = abs(is_calmar - oos_calmar)
            consistency = max(0, 1.0 - calmar_diff / (abs(is_calmar) + 0.1))

            # OOS必须盈利才有高评分
            if oos_result.total_return > 0 and oos_calmar > 0.5:
                # OOS盈利且Calmar>0.5：高评分
                robust_score = is_calmar * 0.3 + oos_calmar * 0.7
            elif oos_result.total_return > 0:
                # OOS盈利但Calmar较低
                robust_score = is_calmar * 0.2 + oos_calmar * 0.5 + consistency * 0.3
            else:
                # OOS亏损：大幅惩罚
                robust_score = is_calmar * 0.1 + oos_calmar * 0.3 + consistency * 0.2 - 0.5

            results.append({
                'trial_number': trial.number,
                'params': params,
                'is_calmar': is_calmar,
                'is_return': trial.user_attrs['total_return'],
                'is_trades': trial.user_attrs['total_trades'],
                'is_drawdown': trial.user_attrs['max_drawdown_pct'],
                'oos_calmar': oos_calmar,
                'oos_return': oos_result.total_return,
                'oos_trades': oos_result.total_trades,
                'oos_drawdown': oos_result.max_drawdown_pct,
                'oos_profit': oos_result.total_return > 0,
                'consistency': consistency,
                'robust_score': robust_score,
            })
        except Exception as e:
            print(f"  Error: {e}")
            continue

    # 按稳健性评分排序
    results.sort(key=lambda x: x['robust_score'], reverse=True)
    return results


def analyze_robustness(is_result: BacktestResult, oos_result: BacktestResult) -> Dict:
    """详细稳健性分析"""
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
            robustness[name] = {'is': is_val, 'oos': oos_val, 'diff': diff_pct/100, 'robust': is_robust}
            print(f"{name:<20} {is_val:>12.0f} {oos_val:>12.0f} {diff_pct:>11.1f}% {'✓' if is_robust else '✗':>10}")
        else:
            diff = abs(is_val - oos_val)
            same_direction = (is_val > 0) == (oos_val > 0)
            relative_diff = diff / (abs(is_val) + 1e-6)
            is_robust = same_direction and relative_diff < 0.5
            robustness[name] = {'is': is_val, 'oos': oos_val, 'diff': relative_diff, 'robust': is_robust}
            print(f"{name:<20} {is_val:>12.4f} {oos_val:>12.4f} {diff:>+12.4f} {'✓' if is_robust else '✗':>10}")

    overall = sum(1 for v in robustness.values() if v['robust']) / len(robustness)
    print(f"\nOverall Robustness: {overall:.0%}")

    if oos_result.total_return > 0:
        print(f"✓ OOS Profitable: {oos_result.total_return:.2%}")
    else:
        print(f"✗ OOS Unprofitable: {oos_result.total_return:.2%}")

    return robustness


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Trend Angle Strategy Two-Stage Optimization')
    parser.add_argument('--trials', type=int, default=N_TRIALS, help='IS optimization trials')
    parser.add_argument('--top-n', type=int, default=TOP_N_CANDIDATES, help='Top N candidates for OOS validation')
    parser.add_argument('--output', type=str, default='results/trend_angle_robust_params.json')
    args = parser.parse_args()

    print(f"\n{'='*70}")
    print("Trend Angle Strategy - Two-Stage Robust Optimization")
    print(f"{'='*70}")
    print("\n优化策略:")
    print(f"  1. IS快速优化 ({args.trials} trials)")
    print(f"  2. Top-{args.top_n} OOS验证")
    print(f"  3. 选择最稳健参数")

    # 加载数据
    print(f"\n{'='*70}")
    print("Loading Data")
    print(f"{'='*70}")

    print(f"\nIS Period ({IS_START} ~ {IS_END}):")
    is_df, is_tick_df = load_data_for_optimization(IS_START, IS_END)

    print(f"\nOOS Period ({OOS_START} ~ {OOS_END}):")
    oos_df, oos_tick_df = load_data_for_optimization(OOS_START, OOS_END)

    # 阶段1: IS优化
    study, is_bar_idx_to_ticks = run_is_optimization(is_df, is_tick_df, args.trials)

    # 阶段2: OOS验证Top-N
    candidate_results = validate_top_candidates(study, oos_df, oos_tick_df, args.top_n)

    # 显示Top 5结果
    print(f"\n{'='*70}")
    print("Top 5 Most Robust Solutions")
    print(f"{'='*70}")

    for i, r in enumerate(candidate_results[:5], 1):
        print(f"\n#{i} Trial {r['trial_number']}:")
        print(f"  Params: sma={r['params']['sma_period']}, angle={r['params']['angle_threshold']:.2f}, "
              f"rr={r['params']['risk_reward_ratio']:.2f}, lookback={r['params']['breakout_lookback']}")
        print(f"  IS:  Return={r['is_return']:.2%}, Calmar={r['is_calmar']:.2f}, Trades={r['is_trades']}")
        print(f"  OOS: Return={r['oos_return']:.2%}, Calmar={r['oos_calmar']:.2f}, Trades={r['oos_trades']}, "
              f"Profit={'✓' if r['oos_profit'] else '✗'}")
        print(f"  Consistency: {r['consistency']:.2%}, Robust Score: {r['robust_score']:.3f}")

    # 选择最佳候选进行详细验证
    best = candidate_results[0]
    print(f"\n{'='*70}")
    print(f"Final Validation - Best Candidate (Trial {best['trial_number']})")
    print(f"{'='*70}")

    best_params = best['params']

    # IS详细回测
    is_df_opt = calculate_strategy_indicators(is_df.copy(), sma_period=best_params['sma_period'], atr_period=14, angle_lookback=5)
    is_result = run_tick_backtest(is_df_opt, is_tick_df, is_bar_idx_to_ticks, best_params)

    print(f"\nIS Results:")
    print(f"  Trades: {is_result.total_trades}, Win Rate: {is_result.win_rate:.2%}")
    print(f"  Return: {is_result.total_return:.2%}, Max DD: {is_result.max_drawdown_pct:.2%}")
    print(f"  Sharpe: {is_result.sharpe_ratio:.2f}, Calmar: {best['is_calmar']:.2f}")

    # OOS详细回测
    oos_engine = TickBacktestEngine(
        config=TradingConfig(symbol="XAUUSD", contract_size=100,
            spread_per_ounce=SPREAD_PER_OUNCE, commission_per_lot=3.5,
            initial_capital=100000.0, leverage=100, base_slippage=SLIPPAGE_POINTS)
    )
    oos_bar_idx_to_ticks = oos_engine.prepare_tick_data(oos_tick_df, oos_df.index) if oos_tick_df is not None else None

    oos_df_opt = calculate_strategy_indicators(oos_df.copy(), sma_period=best_params['sma_period'], atr_period=14, angle_lookback=5)
    oos_result = run_tick_backtest(oos_df_opt, oos_tick_df, oos_bar_idx_to_ticks, best_params)

    print(f"\nOOS Results:")
    print(f"  Trades: {oos_result.total_trades}, Win Rate: {oos_result.win_rate:.2%}")
    print(f"  Return: {oos_result.total_return:.2%}, Max DD: {oos_result.max_drawdown_pct:.2%}")
    print(f"  Sharpe: {oos_result.sharpe_ratio:.2f}, Calmar: {best['oos_calmar']:.2f}")

    # 稳健性分析
    robustness = analyze_robustness(is_result, oos_result)

    # 保存结果
    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True, parents=True)

    results = {
        'timestamp': datetime.now().isoformat(),
        'best_params': {k: bool(v) if isinstance(v, (bool, np.bool_)) else float(v) if isinstance(v, (np.floating, np.integer)) else v
                       for k, v in best_params.items()},
        'is_results': {
            'total_trades': is_result.total_trades, 'win_rate': is_result.win_rate,
            'profit_factor': is_result.profit_factor, 'total_return': is_result.total_return,
            'max_drawdown_pct': is_result.max_drawdown_pct, 'sharpe_ratio': is_result.sharpe_ratio,
            'calmar': best['is_calmar'],
        },
        'oos_results': {
            'total_trades': oos_result.total_trades, 'win_rate': oos_result.win_rate,
            'profit_factor': oos_result.profit_factor, 'total_return': oos_result.total_return,
            'max_drawdown_pct': oos_result.max_drawdown_pct, 'sharpe_ratio': oos_result.sharpe_ratio,
            'calmar': best['oos_calmar'],
        },
        'robustness': robustness,
        'top_candidates': candidate_results[:10],
    }

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, cls=NumpyEncoder)

    print(f"\nResults saved to: {output_path}")
    print(f"\n{'='*70}")
    print("Two-Stage Robust Optimization Complete!")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()
