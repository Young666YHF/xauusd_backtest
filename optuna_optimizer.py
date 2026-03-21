"""
Optuna TPE 优化器
=================
使用TPE (Tree-structured Parzen Estimator) 算法进行参数优化
支持Walk-Forward验证
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass
import warnings
from datetime import datetime

try:
    import optuna
    from optuna.samplers import TPESampler
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False
    warnings.warn("Optuna not available. Install with: pip install optuna")

from strategy import TradingStrategy, SignalType
from tick_engine import TickBacktestEngine
from indicators import add_all_indicators


# 简化版优化参数边界 (10个核心参数)
OPTIMIZATION_BOUNDS = {
    # 布林带参数
    'bb_period': (10, 30),
    'bb_std': (1.5, 3.5),

    # ATR参数
    'atr_period': (7, 21),

    # RSI参数
    'rsi_oversold': (20, 40),
    'rsi_overbought': (60, 80),

    # 策略A止损
    'stop_loss_mult_a': (1.0, 1.5),

    # 策略B参数
    'stop_loss_mult_b': (1.5, 3.0),
    'trailing_stop_mult': (2.0, 5.0),

    # EMA参数
    'ema_fast': (10, 30),
    'ema_slow': (30, 70),
}

# 默认参数
DEFAULT_PARAMS = {
    'bb_period': 20,
    'bb_std': 2.5,
    'kc_period': 20,
    'kc_atr_mult': 1.5,
    'atr_period': 14,
    'rsi_period': 14,
    'rsi_oversold': 30,
    'rsi_overbought': 70,
    'stop_loss_mult_a': 1.5,
    'max_hold_bars_a': 6,
    'ema_fast': 20,
    'ema_slow': 50,
    'stop_loss_mult_b': 2.0,
    'trailing_stop_mult': 3.0,
    'squeeze_threshold': 0.8,
    'atr_time_stop_base': 5.0,
    'atr_time_stop_mult': 0.5,
    'volatility_filter_period': 17,
    'volatility_filter_mult': 1.5,
    'pullback_confirmation_bars': 3,
    'ema_momentum_threshold': 0.0005,
}


def expand_simplified_params(simplified_params: Dict) -> Dict:
    """
    将简化参数扩展为完整参数集

    Args:
        simplified_params: 简化版参数字典 (10个参数)

    Returns:
        完整参数字典
    """
    params = DEFAULT_PARAMS.copy()
    params.update(simplified_params)

    # 派生参数
    # 策略A止损ATR倍数
    params['stop_loss_atr_mult_a'] = params['stop_loss_mult_a']

    # 策略B止损ATR倍数
    params['stop_loss_atr_mult_b'] = params['stop_loss_mult_b']

    # 追踪止损ATR倍数
    params['trailing_stop_atr_mult'] = params['trailing_stop_mult']

    return params


def calculate_custom_fitness(stats: Dict, weights: Optional[Dict] = None) -> float:
    """
    计算自定义适应度函数

    综合考虑: 收益率、夏普比率、最大回撤、胜率、交易次数

    Args:
        stats: 回测统计结果
        weights: 权重配置

    Returns:
        适应度值
    """
    if weights is None:
        weights = {
            'return': 0.3,
            'sharpe': 0.25,
            'drawdown': 0.2,
            'win_rate': 0.15,
            'trades': 0.1,
        }

    total_return = stats.get('total_return', 0)
    sharpe = stats.get('sharpe_ratio', 0)
    max_dd = stats.get('max_drawdown', 0)
    win_rate = stats.get('win_rate', 0)
    total_trades = stats.get('total_trades', 0)

    # 收益率得分 (归一化)
    return_score = np.tanh(total_return / 100)  # 限制在[-1, 1]

    # 夏普比率得分
    sharpe_score = np.tanh(sharpe / 3)  # 夏普>3接近满分

    # 回撤惩罚
    dd_penalty = np.tanh(max_dd / 30)  # 回撤>30%重罚

    # 胜率得分
    win_score = (win_rate - 50) / 50  # 50%胜率为0分

    # 交易次数得分 (需要足够的样本)
    trades_score = np.tanh((total_trades - 30) / 50)  # 30笔以上开始得分

    # 综合得分
    fitness = (
        weights['return'] * return_score +
        weights['sharpe'] * sharpe_score -
        weights['drawdown'] * dd_penalty +
        weights['win_rate'] * win_score +
        weights['trades'] * trades_score
    )

    return fitness


@dataclass
class OptimizationResult:
    """优化结果"""
    best_params: Dict
    best_value: float
    best_stats: Dict
    study: Optional[object] = None
    all_trials: Optional[pd.DataFrame] = None


def create_tick_optuna_objective(
    ticks_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    split_ratios: Optional[List[float]] = None
) -> Callable:
    """
    创建Tick级别Optuna优化目标函数

    Args:
        ticks_df: Tick数据
        ohlcv_df: OHLCV数据
        split_ratios: WFO分割比例 [训练, 验证]

    Returns:
        目标函数
    """
    if split_ratios is None:
        split_ratios = [0.7, 0.3]

    # 数据分割
    n_ticks = len(ticks_df)
    train_end = int(n_ticks * split_ratios[0])

    train_ticks = ticks_df.iloc[:train_end]
    val_ticks = ticks_df.iloc[train_end:]

    # 对应的OHLCV分割
    train_end_time = ticks_df.index[train_end]
    train_ohlcv = ohlcv_df[ohlcv_df.index < train_end_time]
    val_ohlcv = ohlcv_df[ohlcv_df.index >= train_end_time]

    def objective(trial) -> float:
        """优化目标函数"""

        # 采样简化参数
        simplified_params = {
            'bb_period': trial.suggest_int('bb_period', *OPTIMIZATION_BOUNDS['bb_period']),
            'bb_std': trial.suggest_float('bb_std', *OPTIMIZATION_BOUNDS['bb_std']),
            'atr_period': trial.suggest_int('atr_period', *OPTIMIZATION_BOUNDS['atr_period']),
            'rsi_oversold': trial.suggest_int('rsi_oversold', *OPTIMIZATION_BOUNDS['rsi_oversold']),
            'rsi_overbought': trial.suggest_int('rsi_overbought', *OPTIMIZATION_BOUNDS['rsi_overbought']),
            'stop_loss_mult_a': trial.suggest_float('stop_loss_mult_a', *OPTIMIZATION_BOUNDS['stop_loss_mult_a']),
            'stop_loss_mult_b': trial.suggest_float('stop_loss_mult_b', *OPTIMIZATION_BOUNDS['stop_loss_mult_b']),
            'trailing_stop_mult': trial.suggest_float('trailing_stop_mult', *OPTIMIZATION_BOUNDS['trailing_stop_mult']),
            'ema_fast': trial.suggest_int('ema_fast', *OPTIMIZATION_BOUNDS['ema_fast']),
            'ema_slow': trial.suggest_int('ema_slow', *OPTIMIZATION_BOUNDS['ema_slow']),
        }

        # 扩展为完整参数
        params = expand_simplified_params(simplified_params)

        # 创建策略
        strategy = TradingStrategy(params)

        # 在训练集上生成信号
        train_ohlcv_with_indicators = strategy.prepare_indicators(train_ohlcv)

        # 生成信号
        signals = []
        for i in range(max(params['bb_period'], params['ema_slow']) + 1, len(train_ohlcv_with_indicators)):
            # 策略A信号
            sig_a = strategy.generate_strategy_a_signal(train_ohlcv_with_indicators, i)
            if sig_a:
                signals.append({
                    'timestamp': sig_a.timestamp,
                    'direction': 1 if sig_a.signal_type == SignalType.LONG else -1,
                    'stop_loss': sig_a.stop_loss,
                    'strategy': 'A',
                })

            # 策略B信号
            sig_b = strategy.generate_strategy_b_signal(train_ohlcv_with_indicators, i)
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
            stop_loss_mult_b=params['stop_loss_mult_b'],
            trailing_stop_mult=params['trailing_stop_mult'],
            max_hold_bars_a=params['max_hold_bars_a'],
            atr_time_stop_base=params['atr_time_stop_base'],
            atr_time_stop_mult=params['atr_time_stop_mult'],
        )

        # 运行回测
        try:
            stats = engine.run(train_ticks, signals, train_ohlcv)
        except Exception as e:
            return -1000  # 出错返回极低值

        # 计算适应度
        fitness = calculate_custom_fitness(stats)

        return fitness

    return objective


def run_tick_optuna_optimization(
    ticks_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    n_trials: int = 100,
    n_jobs: int = 1,
    split_ratios: Optional[List[float]] = None,
    study_name: Optional[str] = None,
    storage: Optional[str] = None,
    load_if_exists: bool = True,
    verbose: bool = True
) -> OptimizationResult:
    """
    运行Tick级别Optuna优化

    Args:
        ticks_df: Tick数据
        ohlcv_df: OHLCV数据
        n_trials: 优化轮数
        n_jobs: 并行数
        split_ratios: WFO分割比例
        study_name: 研究名称
        storage: 存储路径
        load_if_exists: 是否加载已有研究
        verbose: 是否打印进度

    Returns:
        OptimizationResult
    """
    if not OPTUNA_AVAILABLE:
        raise ImportError("Optuna not installed. Run: pip install optuna")

    # 创建目标函数
    objective = create_tick_optuna_objective(ticks_df, ohlcv_df, split_ratios)

    # 创建或加载研究
    sampler = TPESampler(
        seed=42,
        n_startup_trials=20,  # 随机探索轮数
        multivariate=True,  # 多变量优化
    )

    if storage and study_name:
        study = optuna.create_study(
            study_name=study_name,
            storage=storage,
            load_if_exists=load_if_exists,
            direction='maximize',
            sampler=sampler,
        )
    else:
        study = optuna.create_study(
            direction='maximize',
            sampler=sampler,
        )

    # 运行优化
    if verbose:
        print(f"开始Optuna优化, n_trials={n_trials}")
        print(f"数据范围: {ticks_df.index[0]} ~ {ticks_df.index[-1]}")
        print(f"Tick数量: {len(ticks_df):,}")

    study.optimize(
        objective,
        n_trials=n_trials,
        n_jobs=n_jobs,
        show_progress_bar=verbose,
    )

    # 获取最佳参数
    best_params = expand_simplified_params(study.best_params)
    best_value = study.best_value

    # 用最佳参数运行完整回测
    strategy = TradingStrategy(best_params)
    ohlcv_with_indicators = strategy.prepare_indicators(ohlcv_df)

    signals = []
    for i in range(max(best_params['bb_period'], best_params['ema_slow']) + 1, len(ohlcv_with_indicators)):
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

    engine = TickBacktestEngine(
        initial_capital=100000,
        position_size=1.0,
        contract_size=100,
        stop_loss_mult_b=best_params['stop_loss_mult_b'],
        trailing_stop_mult=best_params['trailing_stop_mult'],
        max_hold_bars_a=best_params['max_hold_bars_a'],
        atr_time_stop_base=best_params['atr_time_stop_base'],
        atr_time_stop_mult=best_params['atr_time_stop_mult'],
    )

    best_stats = engine.run(ticks_df, signals, ohlcv_df)

    # 收集所有试验结果
    trials_data = []
    for trial in study.trials:
        if trial.state == optuna.trial.TrialState.COMPLETE:
            trials_data.append({
                'trial': trial.number,
                'value': trial.value,
                **trial.params,
            })

    all_trials = pd.DataFrame(trials_data) if trials_data else pd.DataFrame()

    if verbose:
        print(f"\n优化完成!")
        print(f"最佳适应度: {best_value:.4f}")
        print(f"最佳参数: {study.best_params}")
        print(f"\n最佳参数回测结果:")
        print(f"  总收益: {best_stats['total_return']:.2f}%")
        print(f"  夏普比率: {best_stats['sharpe_ratio']:.2f}")
        print(f"  最大回撤: {best_stats['max_drawdown']:.2f}%")
        print(f"  胜率: {best_stats['win_rate']:.2f}%")
        print(f"  交易次数: {best_stats['total_trades']}")

    return OptimizationResult(
        best_params=best_params,
        best_value=best_value,
        best_stats=best_stats,
        study=study,
        all_trials=all_trials,
    )


def run_walk_forward_optimization(
    ticks_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    n_splits: int = 5,
    n_trials: int = 50,
    train_ratio: float = 0.7,
    verbose: bool = True
) -> List[Dict]:
    """
    运行Walk-Forward优化验证

    Args:
        ticks_df: Tick数据
        ohlcv_df: OHLCV数据
        n_splits: 分割数
        n_trials: 每个分割的优化轮数
        train_ratio: 训练集比例
        verbose: 是否打印进度

    Returns:
        每个fold的结果列表
    """
    results = []
    n_ticks = len(ticks_df)

    # 计算每个fold的大小
    fold_size = n_ticks // n_splits

    for fold in range(n_splits):
        if verbose:
            print(f"\n{'='*50}")
            print(f"Fold {fold + 1}/{n_splits}")
            print(f"{'='*50}")

        # 计算训练和验证范围
        train_start = fold * fold_size
        train_end = train_start + int(fold_size * train_ratio)
        val_start = train_end
        val_end = (fold + 1) * fold_size

        # 分割数据
        train_ticks = ticks_df.iloc[train_start:train_end]
        val_ticks = ticks_df.iloc[val_start:val_end]

        train_end_time = ticks_df.index[train_end]
        val_start_time = ticks_df.index[val_start]
        train_ohlcv = ohlcv_df[(ohlcv_df.index >= ticks_df.index[train_start]) &
                               (ohlcv_df.index < train_end_time)]
        val_ohlcv = ohlcv_df[(ohlcv_df.index >= val_start_time) &
                             (ohlcv_df.index < ticks_df.index[min(val_end, n_ticks - 1)])]

        # 运行优化
        result = run_tick_optuna_optimization(
            train_ticks,
            train_ohlcv,
            n_trials=n_trials,
            n_jobs=1,
            verbose=False,
        )

        # 在验证集上测试
        strategy = TradingStrategy(result.best_params)
        val_ohlcv_with_indicators = strategy.prepare_indicators(val_ohlcv)

        signals = []
        for i in range(max(result.best_params['bb_period'], result.best_params['ema_slow']) + 1,
                       len(val_ohlcv_with_indicators)):
            sig_a = strategy.generate_strategy_a_signal(val_ohlcv_with_indicators, i)
            if sig_a:
                signals.append({
                    'timestamp': sig_a.timestamp,
                    'direction': 1 if sig_a.signal_type == SignalType.LONG else -1,
                    'stop_loss': sig_a.stop_loss,
                    'strategy': 'A',
                })

            sig_b = strategy.generate_strategy_b_signal(val_ohlcv_with_indicators, i)
            if sig_b:
                signals.append({
                    'timestamp': sig_b.timestamp,
                    'direction': 1 if sig_b.signal_type == SignalType.LONG else -1,
                    'stop_loss': sig_b.stop_loss,
                    'strategy': 'B',
                })

        engine = TickBacktestEngine(
            initial_capital=100000,
            position_size=1.0,
            contract_size=100,
            stop_loss_mult_b=result.best_params['stop_loss_mult_b'],
            trailing_stop_mult=result.best_params['trailing_stop_mult'],
            max_hold_bars_a=result.best_params['max_hold_bars_a'],
            atr_time_stop_base=result.best_params['atr_time_stop_base'],
            atr_time_stop_mult=result.best_params['atr_time_stop_mult'],
        )

        val_stats = engine.run(val_ticks, signals, val_ohlcv)

        fold_result = {
            'fold': fold + 1,
            'train_start': ticks_df.index[train_start],
            'train_end': ticks_df.index[train_end - 1],
            'val_start': ticks_df.index[val_start],
            'val_end': ticks_df.index[min(val_end - 1, n_ticks - 1)],
            'best_params': result.best_params,
            'train_stats': result.best_stats,
            'val_stats': val_stats,
        }

        results.append(fold_result)

        if verbose:
            print(f"训练集: {fold_result['train_start']} ~ {fold_result['train_end']}")
            print(f"验证集: {fold_result['val_start']} ~ {fold_result['val_end']}")
            print(f"训练收益率: {result.best_stats['total_return']:.2f}%")
            print(f"验证收益率: {val_stats['total_return']:.2f}%")

    if verbose:
        print(f"\n{'='*50}")
        print("Walk-Forward验证汇总")
        print(f"{'='*50}")

        avg_train_return = np.mean([r['train_stats']['total_return'] for r in results])
        avg_val_return = np.mean([r['val_stats']['total_return'] for r in results])
        avg_val_sharpe = np.mean([r['val_stats']['sharpe_ratio'] for r in results])
        avg_val_dd = np.mean([r['val_stats']['max_drawdown'] for r in results])

        print(f"平均训练收益: {avg_train_return:.2f}%")
        print(f"平均验证收益: {avg_val_return:.2f}%")
        print(f"平均验证夏普: {avg_val_sharpe:.2f}")
        print(f"平均验证回撤: {avg_val_dd:.2f}%")

    return results
