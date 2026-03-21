"""
Optuna贝叶斯优化模块
========================================
替换原有的遗传算法，使用TPE算法进行参数优化

主要特性:
1. TPE (Tree-structured Parzen Estimator) 贝叶斯优化
2. 基于Calmar比率的适应度函数
3. Walk-Forward Optimization (WFO) 交叉验证
4. 交易次数不足的惩罚机制
5. Numba Tick 引擎集成 (100x 性能提升)

【性能优化】
- Tick 数据只序列化一次，Optuna 多次 Trial 复用
- 通过引用传递给每次参数评估函数
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Callable, Optional
from dataclasses import dataclass
import warnings

warnings.filterwarnings('ignore')


# =============================================================================
# 优化参数边界定义（降维版本）
# =============================================================================
# 维度灾难修复：将18个参数降至10个关键参数
# 原则：保持策略逻辑不变，但减少优化空间

# 完整版参数边界（用于参考，不推荐直接使用）
OPTIMIZATION_BOUNDS_FULL = {
    'bb_period': (10, 30),
    'bb_std': (1.5, 3.5),
    'kc_period': (10, 30),
    'kc_atr_mult': (1.0, 2.5),
    'atr_period': (7, 21),
    'rsi_period': (7, 21),
    'rsi_oversold': (20, 40),
    'rsi_overbought': (60, 80),
    'stop_loss_atr_mult_a': (1.0, 1.5),
    'max_hold_bars_a': (3, 10),
    'ema_fast': (10, 30),
    'ema_slow': (30, 70),
    'stop_loss_atr_mult_b': (1.5, 3.0),
    'trailing_stop_atr_mult': (2.0, 5.0),
    'squeeze_threshold': (0.5, 1.5),
    'atr_time_stop_base': (2.0, 5.0),
    'atr_time_stop_mult': (0.2, 1.0),
    'volatility_filter_period': (10, 30),
    'volatility_filter_mult': (1.2, 2.0),
    'pullback_confirmation_bars': (1, 3),
    'ema_momentum_threshold': (0.0005, 0.002),
}

# 简化版参数边界（推荐使用）
# 关键优化参数：10个，n_trials建议 >= 300
OPTIMIZATION_BOUNDS = {
    # 基础指标参数（合并bb和kc周期）
    'channel_period': (10, 25),      # bb_period = kc_period = channel_period
    'bb_std': (1.8, 3.0),            # 布林带标准差
    'kc_atr_mult': (1.5, 2.5),       # 肯特纳通道ATR倍数
    'atr_period': (10, 18),          # ATR周期
    'rsi_threshold': (20, 35),       # RSI阈值：oversold=threshold, overbought=100-threshold

    # 策略A参数（核心）
    'stop_loss_atr_mult_a': (1.0, 1.5),
    'max_hold_bars_a': (4, 8),

    # 策略B参数（核心）
    'ema_ratio': (0.3, 0.6),         # ema_fast = ema_slow * ema_ratio
    'ema_slow': (40, 65),            # 慢速EMA
    'stop_loss_atr_mult_b': (1.5, 2.5),
    'trailing_stop_atr_mult': (3.0, 5.0),
}


def expand_simplified_params(simplified_params: Dict) -> Dict:
    """
    将简化版参数展开为完整版参数

    这是解决维度灾难的关键：
    - 优化时只搜索10个参数
    - 运行时展开为完整21个参数
    """
    full_params = DEFAULT_PARAMS.copy()

    # 合并周期参数
    period = int(simplified_params.get('channel_period', 15))
    full_params['bb_period'] = period
    full_params['kc_period'] = period

    # 直接传递的参数
    full_params['bb_std'] = simplified_params.get('bb_std', 2.31)
    full_params['kc_atr_mult'] = simplified_params.get('kc_atr_mult', 2.37)
    full_params['atr_period'] = int(simplified_params.get('atr_period', 13))

    # RSI对称阈值
    rsi_threshold = simplified_params.get('rsi_threshold', 25)
    full_params['rsi_period'] = 14  # 固定RSI周期
    full_params['rsi_oversold'] = int(rsi_threshold)
    full_params['rsi_overbought'] = int(100 - rsi_threshold)

    # 策略A参数
    full_params['stop_loss_atr_mult_a'] = simplified_params.get('stop_loss_atr_mult_a', 1.31)
    full_params['max_hold_bars_a'] = int(simplified_params.get('max_hold_bars_a', 6))

    # 策略B参数（EMA比例）
    ema_slow = int(simplified_params.get('ema_slow', 64))
    ema_ratio = simplified_params.get('ema_ratio', 0.44)
    full_params['ema_slow'] = ema_slow
    full_params['ema_fast'] = int(ema_slow * ema_ratio)
    full_params['ema_fast'] = max(10, full_params['ema_fast'])  # 确保最小值

    full_params['stop_loss_atr_mult_b'] = simplified_params.get('stop_loss_atr_mult_b', 2.11)
    full_params['trailing_stop_atr_mult'] = simplified_params.get('trailing_stop_atr_mult', 4.89)

    return full_params


DEFAULT_PARAMS = {
    # Tick级贝叶斯优化最优参数 (2026-03-19)
    # 数据: 2025-12 至 2026-02, Tick级别, 15分钟周期
    # 表现: 收益66.81%, 回撤12.63%, 夏普1.21
    'bb_period': 15,
    'bb_std': 2.31,
    'kc_period': 18,
    'kc_atr_mult': 2.37,
    'atr_period': 13,
    'rsi_period': 10,
    'rsi_oversold': 20,
    'rsi_overbought': 77,
    'stop_loss_atr_mult_a': 1.31,
    'max_hold_bars_a': 6,
    'ema_fast': 28,
    'ema_slow': 64,
    'stop_loss_atr_mult_b': 2.11,
    'trailing_stop_atr_mult': 4.89,
    'squeeze_threshold': 0.74,
    'atr_time_stop_base': 4.99,
    'atr_time_stop_mult': 0.74,
    'volatility_filter_period': 17,
    'volatility_filter_mult': 1.47,
    'pullback_confirmation_bars': 3,
    'ema_momentum_threshold': 0.00067,
}


# =============================================================================
# 适应度函数
# =============================================================================

def calculate_calmar_ratio(
    returns: pd.Series,
    max_drawdown: float,
    timeframe: str = '15m'
) -> float:
    """
    计算卡玛比率 (Calmar Ratio) - 精确版

    Calmar = 年化收益率 / 最大回撤

    修复:
    - 使用日度收益率序列计算年化收益
    - 避免单值收益率导致的指数爆炸

    Args:
        returns: 日度收益率序列（或K线收益率序列）
        max_drawdown: 最大回撤百分比（正数）
        timeframe: K线周期 ('1m', '5m', '15m', '1h', '4h', '1d')

    Returns:
        Calmar比率，越大越好
    """
    if len(returns) < 2:
        return 0.0

    if max_drawdown <= 0:
        # 无回撤时，返回收益率作为参考
        total_return = (1 + returns).prod() - 1
        return total_return * 100 if total_return > 0 else 0.0

    # ========== 使用复合收益率计算年化收益 ==========
    # 计算总收益率
    total_return = (1 + returns).prod() - 1

    # 计算实际交易天数
    n_days = len(returns)

    if n_days <= 0:
        return 0.0

    # 年化因子（假设252个交易日）
    # 使用复合年化: (1 + r)^{252/n_days} - 1
    # 防止极端值：限制年化因子范围
    annual_factor = min(252 / max(n_days, 1), 10.0)  # 上限10年

    if total_return > -1:  # 防止负收益导致数值错误
        annualized_return = (1 + total_return) ** annual_factor - 1
    else:
        annualized_return = total_return  # 极端亏损情况

    # ========== Calmar比率计算 ==========
    # 添加 epsilon 防止分母过小
    epsilon = 1.0  # 假设最小回撤1%
    calmar = annualized_return * 100 / (max_drawdown + epsilon)  # 转换为百分比

    # 限制极端值
    calmar = min(max(calmar, -100.0), 100.0)

    return calmar


def calculate_calmar_from_equity(
    equity_curve: pd.DataFrame,
    max_drawdown: float,
    timeframe: str = '15m'
) -> float:
    """
    从权益曲线计算Calmar比率（精确版本）

    Args:
        equity_curve: 包含 'equity' 列的DataFrame，索引为时间戳
        max_drawdown: 最大回撤百分比（正数）
        timeframe: K线周期

    Returns:
        Calmar比率
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return 0.0

    # 计算每期收益率
    equity = equity_curve['equity']
    returns = equity.pct_change().dropna()

    if len(returns) < 2:
        return 0.0

    return calculate_calmar_ratio(returns, max_drawdown, timeframe)


def calculate_custom_fitness(
    stats: Dict,
    min_trades: int = 100,
    verbose: bool = False,
    equity_curve: pd.DataFrame = None,
    timeframe: str = '15m',
    spread_per_ounce: float = 0.6
) -> float:
    """
    计算自定义适应度函数（加固版）

    修复点:
    1. 使用真实equity_curve计算Calmar，而非简化模拟
    2. 平滑惩罚函数，避免断崖式惩罚撕裂贝叶斯模型

    【加固3.1】利润质量评分
    - 引入"利润分布一致性"指标：总盈亏除以盈利的标准差
    - 惩罚依靠1-2笔大单获利的参数

    【加固3.2】夏普率回撤比惩罚
    - 增加对"单次最大回撤持续时间"的惩罚
    - 回撤超过15天给予0.5权重惩罚

    【加固3.3】微利策略过滤（严格执行）
    - 平均每笔盈利 < 2 * 平均点差成本，Fitness直接设为负值
    - 不需要看起来胜率高的剥头皮策略

    设计理念:
    1. Calmar比率作为核心指标（收益/风险）
    2. 交易次数不足时使用平滑衰减因子
    3. 胜率作为次要调整因子
    4. 夏普比率作为补充
    5. 利润质量评分（防止运气交易）

    Args:
        stats: 回测统计字典
        min_trades: 最小交易次数阈值（统计显著性）
        verbose: 是否打印调试信息
        equity_curve: 权益曲线DataFrame（可选，用于精确计算）
        timeframe: K线周期
        spread_per_ounce: 每盎司点差（XAUUSD 典型值为 $0.6）

    Returns:
        适应度值（越高越好）
    """
    total_trades = stats.get('total_trades', 0)
    total_return = stats.get('total_return', 0)
    max_drawdown = stats.get('max_drawdown', 0)
    win_rate = stats.get('win_rate', 0)
    sharpe_ratio = stats.get('sharpe_ratio', 0)
    profit_factor = stats.get('profit_factor', 1)
    total_pnl = stats.get('total_pnl', 0)

    # 获取平均盈利
    avg_win = stats.get('avg_win', 0)
    avg_loss = stats.get('avg_loss', 0)

    # 计算佣金后净利润（每手双边 $7）
    commission_per_lot = 7.0  # 双边佣金
    net_profit_after_commission = total_pnl - (total_trades * commission_per_lot / 2)

    # 平均点差成本（每笔交易）
    avg_spread_cost = spread_per_ounce * 100  # $0.6 * 100盎司 = $60/手

    # ========== 【加固3.3】微利策略过滤（严格执行）==========
    # 如果平均每笔盈利 < 2 * 平均点差成本，该 Trial 的 Fitness 直接设为负值
    min_profitable_win = avg_spread_cost * 2  # $120/手

    if avg_win > 0 and avg_win < min_profitable_win:
        if verbose:
            print(f"  [微利策略拒绝] 平均盈利 ${avg_win:.2f} < 2倍点差成本 ${min_profitable_win:.2f}")
        # 直接返回负值，拒绝该参数组合
        return -1000.0 - (min_profitable_win - avg_win)

    # ========== 平滑惩罚函数 ==========
    # 修复: 使用连续平滑衰减，而非断崖式惩罚
    # 这样贝叶斯模型的代理函数空间更平滑

    # 交易次数衰减因子 (平滑)
    trade_factor = min(1.0, (total_trades / min_trades) ** 0.5) if min_trades > 0 else 1.0

    # 回撤衰减因子 (平滑)
    dd_factor = max(0.1, 1.0 - max_drawdown / 100) if max_drawdown > 0 else 1.0

    # ========== 核心适应度计算 ==========

    # 基础收益
    base_fitness = total_return

    # ========== 修复：使用日度收益率计算 Calmar ==========
    daily_returns = stats.get('daily_returns', None)

    if daily_returns is not None and len(daily_returns) >= 2:
        # 使用真实的日度收益率序列
        calmar = calculate_calmar_ratio(daily_returns, max_drawdown, timeframe)
    elif equity_curve is not None and not equity_curve.empty:
        # 后备方案：从权益曲线计算
        calmar = calculate_calmar_from_equity(equity_curve, max_drawdown, timeframe)
    else:
        # 最后的后备：简化估算
        if total_trades > 0 and max_drawdown > 0:
            calmar = total_return / max_drawdown
        else:
            calmar = 0

    # 综合适应度 = 收益 * 平滑衰减因子 + Calmar奖励
    fitness = base_fitness * trade_factor * dd_factor

    # Calmar奖励（如果Calmar>0，额外加分）
    if calmar > 0:
        fitness += calmar * 10  # Calmar奖励

    # ========== 【加固3.1】利润质量评分 ==========
    # 引入"利润分布一致性"指标：总盈亏 / 盈利标准差
    # 惩罚依靠1-2笔大单获利的参数
    trades_df = stats.get('trades_df', None)
    profit_consistency_score = 0.0

    if trades_df is not None and len(trades_df) > 1:
        profits = trades_df['pnl'].values
        wins = profits[profits > 0]

        if len(wins) > 1:
            win_std = np.std(wins)
            if win_std > 0:
                # 利润分布一致性 = 总盈利 / 盈利标准差
                # 值越大表示盈利越均匀，越小表示依靠少数大单
                profit_consistency = np.sum(wins) / win_std
                # 归一化并加入适应度
                profit_consistency_score = min(profit_consistency / 10.0, 20.0)  # 最高20分
                fitness += profit_consistency_score

                if verbose and profit_consistency < 5:
                    print(f"  [利润质量警告] 一致性得分 {profit_consistency:.2f} 偏低，可能依靠少数大单")
        elif len(wins) == 1:
            # 只有一笔盈利，严重惩罚
            fitness -= 30
            if verbose:
                print(f"  [利润质量惩罚] 仅1笔盈利，严重依赖运气")

    # ========== 【加固3.2】夏普率回撤比惩罚 ==========
    # 增加对"单次最大回撤持续时间"的惩罚
    # 如果资金曲线横盘或回撤超过15天，给予惩罚
    if daily_returns is not None and len(daily_returns) >= 15:
        # 计算回撤持续期
        cumulative = (1 + daily_returns).cumprod()
        rolling_max = cumulative.expanding().max()
        in_drawdown = cumulative < rolling_max

        # 计算最大回撤持续天数
        drawdown_durations = []
        current_duration = 0
        for is_dd in in_drawdown:
            if is_dd:
                current_duration += 1
            else:
                if current_duration > 0:
                    drawdown_durations.append(current_duration)
                current_duration = 0
        if current_duration > 0:
            drawdown_durations.append(current_duration)

        max_dd_duration = max(drawdown_durations) if drawdown_durations else 0

        # 如果回撤持续超过15天，惩罚
        if max_dd_duration > 15:
            dd_duration_penalty = (max_dd_duration - 15) * 0.5  # 每超1天惩罚0.5分
            fitness -= dd_duration_penalty
            if verbose:
                print(f"  [回撤持续惩罚] 最大回撤持续 {max_dd_duration} 天，惩罚: -{dd_duration_penalty:.2f}")

    # ========== 调整因子 ==========

    # 1. 胜率调整（平滑）
    win_factor = (win_rate - 50) / 50 if win_rate > 50 else (win_rate - 50) / 100
    fitness *= (1 + win_factor * 0.2)  # 胜率影响±20%

    # 2. 夏普比率奖励
    if sharpe_ratio > 1:
        fitness += sharpe_ratio * 5

    # 3. 盈亏比奖励
    if profit_factor > 1.5:
        fitness += (profit_factor - 1.5) * 10

    # 极端情况处理
    if total_trades < 5:
        # 交易次数过少，返回负值但保持平滑
        fitness = -100 * (1 - total_trades / 5)

    if verbose:
        print(f"  Return: {total_return:.2f}%, DD: {max_drawdown:.1f}%, "
              f"Trades: {total_trades}, Win: {win_rate:.1f}%, "
              f"TradeFactor: {trade_factor:.2f}, Calmar: {calmar:.2f}, "
              f"Fitness: {fitness:.2f}")
        print(f"  [利润质量] 一致性得分: {profit_consistency_score:.2f}")
        print(f"  [佣金后净利润] 扣除每手 ${commission_per_lot:.1f} 佣金后: ${net_profit_after_commission:.2f}")

    return fitness


# =============================================================================
# Optuna目标函数
# =============================================================================

def create_optuna_objective(
    df: pd.DataFrame,
    min_trades: int = 100,
    verbose: bool = False,
    use_simplified_params: bool = True
) -> Callable:
    """
    创建Optuna目标函数

    Args:
        df: 回测数据
        min_trades: 最小交易次数阈值
        verbose: 是否打印详细信息
        use_simplified_params: 是否使用简化版参数空间（推荐True）

    Returns:
        Optuna目标函数
    """

    def objective(trial) -> float:
        """Optuna目标函数"""
        from strategy import TradingStrategy
        from backtest import BacktestEngine
        from indicators import add_all_indicators

        # ========== 1. 参数采样 ==========
        if use_simplified_params:
            # 简化版：采样10个核心参数
            simplified_params = {}

            for param_name, (low, high) in OPTIMIZATION_BOUNDS.items():
                if isinstance(low, int) and isinstance(high, int):
                    simplified_params[param_name] = trial.suggest_int(param_name, low, high)
                else:
                    simplified_params[param_name] = trial.suggest_float(param_name, low, high)

            # 展开为完整参数
            params = expand_simplified_params(simplified_params)
        else:
            # 完整版：采样所有参数（需要更多trials）
            params = DEFAULT_PARAMS.copy()
            for param_name, (low, high) in OPTIMIZATION_BOUNDS_FULL.items():
                if isinstance(low, int) and isinstance(high, int):
                    params[param_name] = trial.suggest_int(param_name, low, high)
                else:
                    params[param_name] = trial.suggest_float(param_name, low, high)

        # ========== 2. 参数约束检查 ==========
        if params['ema_fast'] >= params['ema_slow']:
            return -1e6
        if params['rsi_oversold'] >= params['rsi_overbought']:
            return -1e6
        if params['stop_loss_atr_mult_a'] >= params['stop_loss_atr_mult_b']:
            return -1e6

        # ========== 3. 运行回测 ==========
        # 注意：开发阶段不捕获异常，让错误暴露出来便于调试
        df_ind = add_all_indicators(df, params)
        strategy = TradingStrategy(params)

        engine = BacktestEngine(
            initial_capital=100000,
            position_size=1.0,
            spread_per_ounce=0.6
        )

        stats = engine.run_backtest(df_ind, strategy, verbose=False)

        # ========== 4. 计算适应度 ==========
        fitness = calculate_custom_fitness(stats, min_trades, verbose)

        # 记录属性
        trial.set_user_attr('total_trades', stats.get('total_trades', 0))
        trial.set_user_attr('total_return', stats.get('total_return', 0))
        trial.set_user_attr('max_drawdown', stats.get('max_drawdown', 0))
        trial.set_user_attr('win_rate', stats.get('win_rate', 0))
        trial.set_user_attr('sharpe_ratio', stats.get('sharpe_ratio', 0))

        return fitness

    return objective


# =============================================================================
# Walk-Forward Optimization
# =============================================================================

def run_walk_forward_optimization(
    df: pd.DataFrame,
    n_splits: int = 3,
    n_trials: int = 100,
    min_trades: int = 100,
    verbose: bool = True
) -> Dict:
    """
    步进式向前优化 (Walk-Forward Optimization, WFO)

    这是一种稳健的参数优化方法，能有效检测过拟合:
    1. 将数据分为n个连续的周期
    2. 每个周期包含IS（样本内）和OOS（样本外）
    3. 在IS上优化参数，在OOS上验证
    4. 最终选择OOS表现最好的参数

    Args:
        df: 完整数据
        n_splits: WFO分割数（建议3-5）
        n_trials: 每轮Optuna优化次数
        min_trades: 最小交易次数
        verbose: 是否打印详细信息

    Returns:
        优化结果字典，包含最佳参数和所有分割的结果
    """
    try:
        import optuna
    except ImportError:
        raise ImportError("请先安装optuna: pip install optuna")

    n_bars = len(df)
    bars_per_split = n_bars // n_splits

    # ========== 预热垫片大小 ==========
    # 指标计算需要历史数据，例如EMA_slow最大70，加上其他指标需要约100根
    WARMUP_BARS = 100

    all_results = []
    oos_performances = []

    if verbose:
        print(f"\n{'='*70}")
        print(f"开始 Walk-Forward Optimization (带预热垫片)")
        print(f"总数据量: {n_bars} 根K线, 分割数: {n_splits}, 每轮试验: {n_trials}")
        print(f"预热垫片: {WARMUP_BARS} 根K线")
        print(f"{'='*70}\n")

    for i in range(n_splits - 1):
        # ========== 数据分割（带预热垫片）==========
        # IS数据: 当前split
        is_start = i * bars_per_split
        is_end = (i + 1) * bars_per_split

        # 带垫片切分：向左扩展WARMUP_BARS根K线用于指标预热
        is_padded_start = max(0, is_start - WARMUP_BARS)
        is_df_padded = df.iloc[is_padded_start:is_end].copy()

        # OOS数据: 下一个split
        oos_start = is_end
        oos_end = (i + 2) * bars_per_split if i < n_splits - 2 else n_bars

        # OOS同样需要垫片（使用IS末尾数据）
        oos_padded_start = max(0, oos_start - WARMUP_BARS)
        oos_df_padded = df.iloc[oos_padded_start:oos_end].copy()

        # 计算垫片偏移量（用于后续剔除预热数据）
        is_warmup_offset = is_start - is_padded_start
        oos_warmup_offset = oos_start - oos_padded_start

        if verbose:
            print(f"\n--- WFO Split {i+1}/{n_splits-1} ---")
            print(f"IS:  {df.index[is_start]} to {df.index[is_end-1]} ({is_end - is_start} bars, padded: {len(is_df_padded)}, warmup_offset: {is_warmup_offset})")
            print(f"OOS: {df.index[oos_start]} to {df.index[min(oos_end-1, n_bars-1)]} ({oos_end - oos_start} bars, padded: {len(oos_df_padded)}, warmup_offset: {oos_warmup_offset})")

        # ========== IS优化（带预热垫片的目标函数）==========
        def create_wfo_objective(df_padded, warmup_offset, eval_bars, min_trades):
            """
            创建WFO目标函数（正确处理预热垫片）

            关键：传入完整垫片数据，在内部计算指标后再剔除预热部分
            """
            def objective(trial):
                from strategy import TradingStrategy
                from backtest import BacktestEngine
                from indicators import add_all_indicators

                # 参数采样（简化版）
                simplified_params = {}
                for param_name, (low, high) in OPTIMIZATION_BOUNDS.items():
                    if isinstance(low, int) and isinstance(high, int):
                        simplified_params[param_name] = trial.suggest_int(param_name, low, high)
                    else:
                        simplified_params[param_name] = trial.suggest_float(param_name, low, high)

                params = expand_simplified_params(simplified_params)

                # 参数约束检查
                if params['ema_fast'] >= params['ema_slow']:
                    return -1e6
                if params['rsi_oversold'] >= params['rsi_overbought']:
                    return -1e6

                # ========== 关键：在完整垫片数据上计算指标 ==========
                df_ind = add_all_indicators(df_padded, params)

                # ========== 剔除预热部分 ==========
                df_eval = df_ind.iloc[warmup_offset:warmup_offset + eval_bars]

                if len(df_eval) < 50:
                    return -1e6

                strategy = TradingStrategy(params)
                engine = BacktestEngine(initial_capital=100000)
                stats = engine.run_backtest(df_eval, strategy, verbose=False)

                return calculate_custom_fitness(stats, min_trades, verbose=False)

            return objective

        study = optuna.create_study(
            direction='maximize',
            sampler=optuna.samplers.TPESampler(seed=42 + i, n_startup_trials=max(10, n_trials // 7)),
            pruner=optuna.pruners.MedianPruner()
        )

        # 使用带预热垫片的目标函数
        is_eval_bars = is_end - is_start  # 实际评估的K线数
        objective = create_wfo_objective(is_df_padded, is_warmup_offset, is_eval_bars, min_trades)
        study.optimize(objective, n_trials=n_trials, show_progress_bar=verbose)

        best_params = study.best_params

        # ========== OOS验证（带垫片）==========
        from strategy import TradingStrategy
        from backtest import BacktestEngine
        from indicators import add_all_indicators

        # 展开简化参数
        if 'channel_period' in best_params:
            best_params = expand_simplified_params(best_params)

        # 在完整垫片数据上计算指标
        oos_df_ind = add_all_indicators(oos_df_padded, best_params)

        # 剔除预热部分
        oos_eval_bars = oos_end - oos_start
        oos_df_eval = oos_df_ind.iloc[oos_warmup_offset:oos_warmup_offset + oos_eval_bars]

        strategy = TradingStrategy(best_params)
        engine = BacktestEngine(initial_capital=100000)
        oos_stats = engine.run_backtest(oos_df_eval, strategy, verbose=False)

        oos_fitness = calculate_custom_fitness(oos_stats, min_trades // 2, False)

        if verbose:
            print(f"  IS Best: {study.best_value:.2f}")
            print(f"  OOS: Calmar-like={oos_fitness:.2f}, "
                  f"Return={oos_stats['total_return']:.2f}%, "
                  f"DD={oos_stats['max_drawdown']:.2f}%, "
                  f"Trades={oos_stats['total_trades']}")

        all_results.append({
            'split': i + 1,
            'best_params': best_params,
            'is_fitness': study.best_value,
            'oos_stats': oos_stats,
            'oos_fitness': oos_fitness
        })

        oos_performances.append(oos_fitness)

    # ========== 【修复3.1】跨周期参数稳定性检验 ==========
    # 原代码直接取最后一次IS参数作为最终参数，这是不稳定的
    # 新逻辑：提取OOS表现前20%的参数交集，验证稳定性

    # 1. 找出OOS表现前20%的splits
    oos_fitness_threshold = np.percentile(oos_performances, 80)
    top_splits = [i for i, fitness in enumerate(oos_performances) if fitness >= oos_fitness_threshold]

    if verbose:
        print(f"\n{'='*70}")
        print(f"【参数稳定性检验】")
        print(f"OOS Fitness 80%分位数: {oos_fitness_threshold:.2f}")
        print(f"表现前20%的Splits: {top_splits}")
        print(f"对应OOS Fitness: {[f'{oos_performances[i]:.2f}' for i in top_splits]}")

    # 2. 如果没有splits进入前20%（所有表现都很差），警告策略不稳定
    if len(top_splits) == 0:
        if verbose:
            print(f"\n⚠️  【警告】所有WFO分割的OOS表现均低于阈值！")
            print(f"   策略在当前维度下可能根本不稳定，建议停止实盘！")
            print(f"   回退使用最近一次IS参数，但请谨慎评估。")
        final_params = all_results[-1]['best_params']
        is_stable = False
        param_stability = {}
    else:
        # 3. 提取前20% splits的参数
        top_params = [all_results[i]['best_params'] for i in top_splits]

        # 4. 计算参数稳定性：关键参数的方差
        key_params = ['stop_loss_atr_mult_a', 'stop_loss_atr_mult_b', 'trailing_stop_atr_mult']
        param_stability = {}

        for param in key_params:
            values = [p.get(param, 0) for p in top_params if param in p]
            if values:
                mean_val = np.mean(values)
                std_val = np.std(values)
                cv = std_val / abs(mean_val) if mean_val != 0 else 0
                param_stability[param] = {
                    'mean': mean_val,
                    'std': std_val,
                    'cv': cv,  # 变异系数
                    'stable': cv < 0.3  # CV < 30% 认为稳定
                }

        # 5. 判断整体稳定性
        is_stable = all(ps.get('stable', False) for ps in param_stability.values())

        if verbose:
            print(f"\n关键参数稳定性分析:")
            for param, stats in param_stability.items():
                status = "✓ 稳定" if stats['stable'] else "✗ 不稳定"
                print(f"  {param}: 均值={stats['mean']:.3f}, 标准差={stats['std']:.3f}, CV={stats['cv']:.2%} {status}")

        # 6. 选择最终参数
        if is_stable:
            # 稳定：使用OOS表现最好的split的参数
            best_oos_idx = np.argmax(oos_performances)
            final_params = all_results[best_oos_idx]['best_params']
            if verbose:
                print(f"\n✓ 参数稳定，使用OOS表现最好的Split {best_oos_idx + 1}参数")
        else:
            # 不稳定：发出警告，但仍使用最近参数
            if verbose:
                print(f"\n⚠️  【警告】关键参数不稳定（CV > 30%）！")
                print(f"   策略可能过拟合，实盘风险较高。")
                print(f"   使用最近一次IS参数作为最终参数。")
            final_params = all_results[-1]['best_params']

    # 计算拼接后的全局OOS表现
    combined_equity = [100000]
    for result in all_results:
        oos_return = result['oos_stats']['total_return']
        combined_equity.append(combined_equity[-1] * (1 + oos_return / 100))

    combined_return = (combined_equity[-1] / combined_equity[0] - 1) * 100
    combined_sharpe = np.mean(oos_performances) / (np.std(oos_performances) + 1e-6) * np.sqrt(n_splits)

    if verbose:
        print(f"\n{'='*70}")
        print(f"WFO 完成（参数稳定性检验版）")
        print(f"策略稳定性: {'✓ 稳定' if is_stable else '✗ 不稳定'}")
        print(f"最终参数来源: {('OOS最佳Split' if is_stable else '最近Split')}")
        print(f"拼接后全局收益: {combined_return:.2f}%")
        print(f"平均OOS Fitness: {np.mean(oos_performances):.2f}")
        print(f"OOS Fitness标准差: {np.std(oos_performances):.2f}")
        print(f"各Split OOS表现: {[f'{p:.2f}' for p in oos_performances]}")
        print(f"{'='*70}\n")

    return {
        'best_params': final_params,
        'all_results': all_results,
        'combined_return': combined_return,
        'combined_sharpe': combined_sharpe,
        'avg_oos_fitness': float(np.mean(oos_performances)),
        'std_oos_fitness': float(np.std(oos_performances)),
        'oos_performances': [float(p) for p in oos_performances],
        # 【修复3.1】新增稳定性指标
        'is_stable': is_stable,
        'param_stability': param_stability,
        'top_splits': top_splits
    }


# =============================================================================
# 主优化函数
# =============================================================================

def run_optuna_optimization(
    df: pd.DataFrame,
    n_trials: int = 300,
    min_trades: int = 100,
    use_wfo: bool = False,
    n_splits: int = 3,
    study_name: str = "xauusd_optimization",
    storage: Optional[str] = None,
    verbose: bool = True,
    use_simplified_params: bool = True
) -> Dict:
    """
    使用Optuna进行参数优化（主入口）

    维度灾难修复：
    - 简化版参数：10个核心参数，n_trials >= 300
    - 完整版参数：21个参数，n_trials >= 1500

    Args:
        df: 回测数据
        n_trials: Optuna优化次数（简化版建议>=300，完整版建议>=1500）
        min_trades: 最小交易次数阈值
        use_wfo: 是否使用Walk-Forward Optimization
        n_splits: WFO分割数
        study_name: Optuna研究名称（用于持久化）
        storage: Optuna存储路径（None表示不持久化）
        verbose: 是否打印详细信息
        use_simplified_params: 是否使用简化版参数空间（推荐True）

    Returns:
        优化结果字典
    """
    try:
        import optuna
    except ImportError:
        raise ImportError("请先安装optuna: pip install optuna")

    # 参数数量检查与警告
    n_params = len(OPTIMIZATION_BOUNDS) if use_simplified_params else len(OPTIMIZATION_BOUNDS_FULL)
    recommended_trials = n_params * 30  # 每个参数至少30次采样

    if n_trials < recommended_trials:
        if verbose:
            print(f"⚠️  警告: 当前参数数={n_params}, n_trials={n_trials}")
            print(f"   建议n_trials >= {recommended_trials} 以获得有效优化结果")

    # 如果使用WFO，调用专门的WFO函数
    if use_wfo:
        return run_walk_forward_optimization(
            df, n_splits, n_trials, min_trades, verbose
        )

    if verbose:
        print(f"\n{'='*70}")
        print(f"开始 Optuna TPE 优化")
        print(f"迭代次数: {n_trials}, 最小交易次数: {min_trades}")
        print(f"{'='*70}\n")

    # 创建或加载研究
    if storage:
        study = optuna.create_study(
            direction='maximize',
            study_name=study_name,
            storage=storage,
            load_if_exists=True,
            sampler=optuna.samplers.TPESampler(seed=42, n_startup_trials=max(30, n_trials // 7)),
            pruner=optuna.pruners.MedianPruner()
        )
    else:
        study = optuna.create_study(
            direction='maximize',
            sampler=optuna.samplers.TPESampler(seed=42, n_startup_trials=max(30, n_trials // 7)),
            pruner=optuna.pruners.MedianPruner()
        )

    # 创建目标函数
    objective = create_optuna_objective(df, min_trades, verbose=False)

    # 优化
    study.optimize(objective, n_trials=n_trials, show_progress_bar=verbose)

    # 获取最佳试验的详细信息
    best_trial = study.best_trial

    if verbose:
        print(f"\n{'='*70}")
        print(f"优化完成!")
        print(f"最佳适应度: {study.best_value:.4f}")
        print(f"\n最佳参数:")
        for name, value in study.best_params.items():
            print(f"  {name}: {value}")
        print(f"\n最佳试验统计:")
        print(f"  交易次数: {best_trial.user_attrs.get('total_trades', 'N/A')}")
        print(f"  总收益: {best_trial.user_attrs.get('total_return', 'N/A'):.2f}%")
        print(f"  最大回撤: {best_trial.user_attrs.get('max_drawdown', 'N/A'):.2f}%")
        print(f"  胜率: {best_trial.user_attrs.get('win_rate', 'N/A'):.2f}%")
        print(f"{'='*70}\n")

    return {
        'best_params': study.best_params,
        'best_fitness': study.best_value,
        'study': study,
        'n_trials': n_trials,
        'best_trial_stats': {
            'total_trades': best_trial.user_attrs.get('total_trades'),
            'total_return': best_trial.user_attrs.get('total_return'),
            'max_drawdown': best_trial.user_attrs.get('max_drawdown'),
            'win_rate': best_trial.user_attrs.get('win_rate'),
            'sharpe_ratio': best_trial.user_attrs.get('sharpe_ratio'),
        }
    }


def get_param_importance(study) -> Dict[str, float]:
    """
    获取参数重要性分析

    Args:
        study: Optuna研究对象

    Returns:
        参数重要性字典
    """
    try:
        import optuna
        importance = optuna.importance.get_param_importances(study)
        return importance
    except Exception as e:
        print(f"参数重要性分析失败: {e}")
        return {}


# =============================================================================
# 多目标优化（Pareto Front）
# =============================================================================

def create_multi_objective(
    df: pd.DataFrame,
    min_trades: int = 100,
    verbose: bool = False
) -> Callable:
    """
    创建多目标优化函数（返回帕累托前沿）

    目标：
    1. 最大化收益（total_return）
    2. 最小化回撤（max_drawdown）

    使用NSGA-II算法自动找到帕累托最优解集

    Args:
        df: 回测数据
        min_trades: 最小交易次数阈值
        verbose: 是否打印详细信息

    Returns:
        多目标函数
    """
    from strategy import TradingStrategy
    from backtest import BacktestEngine
    from indicators import add_all_indicators

    def multi_objective(trial):
        """多目标函数：返回(收益, -回撤)"""
        # 参数采样（简化版）
        simplified_params = {}
        for param_name, (low, high) in OPTIMIZATION_BOUNDS.items():
            if isinstance(low, int) and isinstance(high, int):
                simplified_params[param_name] = trial.suggest_int(param_name, low, high)
            else:
                simplified_params[param_name] = trial.suggest_float(param_name, low, high)

        params = expand_simplified_params(simplified_params)

        # 参数约束检查
        if params['ema_fast'] >= params['ema_slow']:
            return -1000.0, 0.0  # (收益, 负回撤)
        if params['rsi_oversold'] >= params['rsi_overbought']:
            return -1000.0, 0.0

        # 计算指标和回测
        df_ind = add_all_indicators(df, params)
        strategy = TradingStrategy(params)
        engine = BacktestEngine(initial_capital=100000)
        stats = engine.run_backtest(df_ind, strategy, verbose=False)

        # 记录属性
        trial.set_user_attr('total_trades', stats.get('total_trades', 0))
        trial.set_user_attr('sharpe_ratio', stats.get('sharpe_ratio', 0))
        trial.set_user_attr('win_rate', stats.get('win_rate', 0))

        # 多目标返回值
        total_return = stats.get('total_return', -1000)
        max_drawdown = stats.get('max_drawdown', 100)

        # 交易次数惩罚
        if stats.get('total_trades', 0) < min_trades:
            total_return = -1000
            max_drawdown = 100

        return total_return, -max_drawdown  # 最大化收益，最大化负回撤=最小化回撤

    return multi_objective


def run_multi_objective_optimization(
    df: pd.DataFrame,
    n_trials: int = 500,
    min_trades: int = 100,
    verbose: bool = True
) -> Dict:
    """
    运行多目标优化（返回帕累托前沿）

    使用NSGA-II算法，返回多个帕累托最优解，
    让用户在收益-风险之间做选择

    Args:
        df: 回测数据
        n_trials: 优化次数
        min_trades: 最小交易次数
        verbose: 是否打印详细信息

    Returns:
        包含帕累托前沿的结果字典
    """
    try:
        import optuna
    except ImportError:
        raise ImportError("请先安装optuna: pip install optuna")

    if verbose:
        print(f"\n{'='*70}")
        print(f"开始多目标优化 (NSGA-II)")
        print(f"目标: 最大化收益, 最小化回撤")
        print(f"迭代次数: {n_trials}")
        print(f"{'='*70}\n")

    study = optuna.create_study(
        directions=['maximize', 'maximize'],  # 最大化收益，最大化负回撤
        sampler=optuna.samplers.NSGAIISampler(seed=42),
        pruner=optuna.pruners.MedianPruner()
    )

    objective = create_multi_objective(df, min_trades, verbose=False)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=verbose)

    # 获取帕累托前沿
    pareto_trials = study.best_trials

    if verbose:
        print(f"\n{'='*70}")
        print(f"多目标优化完成!")
        print(f"帕累托前沿: {len(pareto_trials)} 个最优解")
        print(f"{'='*70}")

        print(f"\n{'帕累托最优解':^70}")
        print("-" * 70)
        print(f"{'收益%':>12} | {'回撤%':>12} | {'交易数':>10} | {'夏普':>10}")
        print("-" * 70)

        for trial in pareto_trials[:10]:  # 最多显示10个
            ret = trial.values[0]
            dd = -trial.values[1]
            trades = trial.user_attrs.get('total_trades', 'N/A')
            sharpe = trial.user_attrs.get('sharpe_ratio', 'N/A')
            print(f"{ret:>12.2f} | {dd:>12.2f} | {trades:>10} | {sharpe:>10.2f}")

    return {
        'study': study,
        'pareto_trials': pareto_trials,
        'n_pareto_solutions': len(pareto_trials),
        'best_trials': [
            {
                'params': trial.params,
                'total_return': trial.values[0],
                'max_drawdown': -trial.values[1],
                'total_trades': trial.user_attrs.get('total_trades'),
                'sharpe_ratio': trial.user_attrs.get('sharpe_ratio'),
            }
            for trial in pareto_trials
        ]
    }


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print("="*70)
    print("Optuna优化器测试")
    print("="*70)

    # 检查optuna是否安装
    try:
        import optuna
        print(f"Optuna版本: {optuna.__version__}")
    except ImportError:
        print("请先安装optuna: pip install optuna")
        exit(1)

    # 测试数据
    from data_loader import generate_sample_data
    from indicators import add_all_indicators

    print("\n生成测试数据...")
    df = generate_sample_data(days=60)
    df = add_all_indicators(df, DEFAULT_PARAMS)
    print(f"数据量: {len(df)} 根K线")

    # 测试普通优化
    print("\n" + "="*70)
    print("测试1: 普通Optuna优化 (50 trials)")
    print("="*70)

    result = run_optuna_optimization(
        df,
        n_trials=50,
        min_trades=20,  # 测试时用较小的阈值
        use_wfo=False,
        verbose=True
    )

    print(f"\n最佳参数:")
    for k, v in result['best_params'].items():
        print(f"  {k}: {v}")

    # 测试WFO
    print("\n" + "="*70)
    print("测试2: Walk-Forward Optimization")
    print("="*70)

    wfo_result = run_walk_forward_optimization(
        df,
        n_splits=3,
        n_trials=30,
        min_trades=15,
        verbose=True
    )

    print(f"\nWFO最佳参数:")
    for k, v in wfo_result['best_params'].items():
        print(f"  {k}: {v}")

    print("\n测试完成!")


# =============================================================================
# Task 3: Numba Tick 引擎集成 - 高性能优化入口
# =============================================================================

def create_tick_optuna_objective(
    tick_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    min_trades: int = 100,
    verbose: bool = False,
    use_simplified_params: bool = True
) -> Callable:
    """
    创建基于 Numba Tick 引擎的 Optuna 目标函数

    【性能优化关键】
    1. Tick 数据在优化启动前只序列化一次
    2. 信号数组在每次 Trial 中重新生成 (因为参数影响信号)
    3. Numba JIT 编译的核心撮合循环

    【使用示例】
    >>> # 1. 加载 Tick 数据
    >>> tick_df = load_tick_data('2025-12-01', '2026-02-28')
    >>> ohlcv_df = resample_to_ohlcv(tick_df, '15min')
    >>> ohlcv_df = add_all_indicators(ohlcv_df, DEFAULT_PARAMS)
    >>>
    >>> # 2. 创建目标函数 (Tick 数据只序列化一次)
    >>> objective = create_tick_optuna_objective(tick_df, ohlcv_df)
    >>>
    >>> # 3. 运行优化
    >>> study = optuna.create_study(direction='maximize')
    >>> study.optimize(objective, n_trials=300)

    Args:
        tick_df: Tick 数据 DataFrame (包含 bid, ask, timestamp)
        ohlcv_df: OHLCV 数据 DataFrame (包含 ATR, VWAP 等指标)
        min_trades: 最小交易次数阈值
        verbose: 是否打印详细信息
        use_simplified_params: 是否使用简化版参数空间

    Returns:
        Optuna 目标函数
    """
    from tick_engine import NumbaTickBacktestEngine, prepare_tick_data, prepare_bar_stats
    from strategy import TradingStrategy
    from indicators import add_all_indicators

    # ═══════════════════════════════════════════════════════════════════════
    # 关键优化: Tick 数据只序列化一次
    # ═══════════════════════════════════════════════════════════════════════
    print("[Optuna] 预序列化 Tick 数据...")
    ticks_array = prepare_tick_data(tick_df, ohlcv_df)
    bar_stats = prepare_bar_stats(ohlcv_df)
    print(f"[Optuna] Tick 数据序列化完成: {len(ticks_array):,} ticks")

    # 创建引擎实例 (不缓存，因为我们已经预序列化了)
    # 【Task 2 修复】删除 spread 参数，Tick 引擎已通过 Bid/Ask 差值处理点差
    engine = NumbaTickBacktestEngine(
        initial_capital=100000,
        position_size=1.0,
        contract_size=100
    )

    # 预缓存数据
    engine._cached_ticks_array = ticks_array
    engine._cached_bar_stats = bar_stats
    engine._cache_key = "pre_serialized"

    def objective(trial) -> float:
        """基于 Numba Tick 引擎的目标函数"""
        # ========== 1. 参数采样 ==========
        if use_simplified_params:
            simplified_params = {}

            for param_name, (low, high) in OPTIMIZATION_BOUNDS.items():
                if isinstance(low, int) and isinstance(high, int):
                    simplified_params[param_name] = trial.suggest_int(param_name, low, high)
                else:
                    simplified_params[param_name] = trial.suggest_float(param_name, low, high)

            params = expand_simplified_params(simplified_params)
        else:
            params = DEFAULT_PARAMS.copy()
            for param_name, (low, high) in OPTIMIZATION_BOUNDS_FULL.items():
                if isinstance(low, int) and isinstance(high, int):
                    params[param_name] = trial.suggest_int(param_name, low, high)
                else:
                    params[param_name] = trial.suggest_float(param_name, low, high)

        # ========== 2. 参数约束检查 ==========
        if params['ema_fast'] >= params['ema_slow']:
            return -1e6
        if params['rsi_oversold'] >= params['rsi_overbought']:
            return -1e6

        # ========== 3. 计算指标 ==========
        df_ind = add_all_indicators(ohlcv_df.copy(), params)

        # ========== 4. 生成信号 ==========
        strategy = TradingStrategy(params)
        signals = strategy.generate_signals(df_ind)

        # ========== 5. 运行 Tick 回测 (核心优化点) ==========
        # 直接使用预序列化的 ticks_array 和 bar_stats
        stats = engine.run_backtest(signals, params, df_ind, verbose=False)

        # ========== 6. 计算适应度 ==========
        fitness = calculate_custom_fitness(stats, min_trades, verbose)

        # 记录属性
        trial.set_user_attr('total_trades', stats.get('total_trades', 0))
        trial.set_user_attr('total_return', stats.get('total_return', 0))
        trial.set_user_attr('max_drawdown', stats.get('max_drawdown', 0))
        trial.set_user_attr('win_rate', stats.get('win_rate', 0))
        trial.set_user_attr('sharpe_ratio', stats.get('sharpe_ratio', 0))
        trial.set_user_attr('ticks_processed', stats.get('total_ticks_processed', 0))
        trial.set_user_attr('execution_time', stats.get('execution_time', 0))

        return fitness

    return objective


def run_tick_optuna_optimization(
    tick_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    n_trials: int = 300,
    min_trades: int = 100,
    study_name: str = "xauusd_tick_optimization",
    storage: Optional[str] = None,
    verbose: bool = True,
    use_simplified_params: bool = True
) -> Dict:
    """
    使用 Numba Tick 引擎进行参数优化 (主入口)

    【性能对比】
    - 传统 K 线回测: ~1000 evaluations/s
    - Numba Tick 回测: ~100,000 evaluations/s (100x 提升)

    【使用流程】
    >>> from data_loader import load_tick_data
    >>> from indicators import add_all_indicators
    >>>
    >>> # 加载 Tick 数据
    >>> tick_df = load_tick_data('2025-12-01', '2026-02-28')
    >>>
    >>> # 转换为 K 线并计算指标
    >>> ohlcv_df = tick_df.resample('15min').agg({
    ...     'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
    ... })
    >>> ohlcv_df = add_all_indicators(ohlcv_df, DEFAULT_PARAMS)
    >>>
    >>> # 运行优化
    >>> result = run_tick_optuna_optimization(tick_df, ohlcv_df, n_trials=300)

    Args:
        tick_df: Tick 数据 DataFrame
        ohlcv_df: OHLCV 数据 DataFrame
        n_trials: Optuna 优化次数
        min_trades: 最小交易次数阈值
        study_name: Optuna 研究名称
        storage: Optuna 存储路径
        verbose: 是否打印详细信息
        use_simplified_params: 是否使用简化版参数空间

    Returns:
        优化结果字典
    """
    try:
        import optuna
    except ImportError:
        raise ImportError("请先安装 optuna: pip install optuna")

    # 检测 Numba 是否可用
    try:
        from tick_engine import NUMBA_AVAILABLE
        if NUMBA_AVAILABLE:
            print("✅ Numba JIT 已启用 (预计 100x 性能提升)")
        else:
            print("⚠️ Numba 未安装，使用纯 Python 模式")
    except ImportError:
        print("⚠️ tick_engine 模块未找到")

    if verbose:
        n_params = len(OPTIMIZATION_BOUNDS) if use_simplified_params else len(OPTIMIZATION_BOUNDS_FULL)
        print(f"\n{'='*70}")
        print(f"开始 Numba Tick 级别优化")
        print(f"迭代次数: {n_trials}, 参数数: {n_params}, 最小交易次数: {min_trades}")
        print(f"Tick 数据量: {len(tick_df):,}")
        print(f"{'='*70}\n")

    # 创建或加载研究
    sampler = optuna.samplers.TPESampler(
        seed=42,
        n_startup_trials=max(30, n_trials // 7)
    )
    pruner = optuna.pruners.MedianPruner()

    if storage:
        study = optuna.create_study(
            direction='maximize',
            study_name=study_name,
            storage=storage,
            load_if_exists=True,
            sampler=sampler,
            pruner=pruner
        )
    else:
        study = optuna.create_study(
            direction='maximize',
            sampler=sampler,
            pruner=pruner
        )

    # 创建目标函数 (Tick 数据只序列化一次)
    objective = create_tick_optuna_objective(
        tick_df, ohlcv_df, min_trades, verbose=False, use_simplified_params=use_simplified_params
    )

    # 优化
    study.optimize(objective, n_trials=n_trials, show_progress_bar=verbose)

    # 获取最佳试验的详细信息
    best_trial = study.best_trial

    if verbose:
        print(f"\n{'='*70}")
        print(f"优化完成!")
        print(f"最佳适应度: {study.best_value:.4f}")
        print(f"\n最佳参数:")
        for name, value in study.best_params.items():
            print(f"  {name}: {value}")
        print(f"\n最佳试验统计:")
        print(f"  交易次数: {best_trial.user_attrs.get('total_trades', 'N/A')}")
        print(f"  总收益: {best_trial.user_attrs.get('total_return', 'N/A'):.2f}%")
        print(f"  最大回撤: {best_trial.user_attrs.get('max_drawdown', 'N/A'):.2f}%")
        print(f"  胜率: {best_trial.user_attrs.get('win_rate', 'N/A'):.2f}%")
        print(f"  处理 Tick 数: {best_trial.user_attrs.get('ticks_processed', 'N/A'):,}")
        print(f"{'='*70}\n")

    return {
        'best_params': study.best_params,
        'best_fitness': study.best_value,
        'study': study,
        'n_trials': n_trials,
        'best_trial_stats': {
            'total_trades': best_trial.user_attrs.get('total_trades'),
            'total_return': best_trial.user_attrs.get('total_return'),
            'max_drawdown': best_trial.user_attrs.get('max_drawdown'),
            'win_rate': best_trial.user_attrs.get('win_rate'),
            'sharpe_ratio': best_trial.user_attrs.get('sharpe_ratio'),
            'ticks_processed': best_trial.user_attrs.get('ticks_processed'),
            'execution_time': best_trial.user_attrs.get('execution_time'),
        }
    }


# =============================================================================
# 【Critical Fix 4】蒙特卡洛噪音注入防过拟合
# =============================================================================

@dataclass
class MonteCarloResult:
    """蒙特卡洛噪音注入测试结果"""
    original_sharpe: float
    original_calmar: float
    noise_sharpe_mean: float
    noise_sharpe_std: float
    noise_calmar_mean: float
    noise_calmar_std: float
    sharpe_degradation: float  # 夏普劣化百分比
    calmar_degradation: float  # Calmar劣化百分比
    is_fragile: bool           # 是否脆弱
    rejection_reason: str


def inject_slippage_noise(
    trades_df: pd.DataFrame,
    noise_ratio: float = 0.2,
    seed: Optional[int] = None
) -> pd.DataFrame:
    """
    对交易序列注入滑点噪音
    
    Args:
        trades_df: 交易记录 DataFrame
        noise_ratio: 噪音比例 (默认 0.2 = ±20%)
        seed: 随机种子
    
    Returns:
        注入噪音后的交易记录 DataFrame
    """
    if seed is not None:
        np.random.seed(seed)
    
    noisy_trades = trades_df.copy()
    base_slippage = 0.15
    
    for idx in noisy_trades.index:
        direction = 1 if noisy_trades.loc[idx, 'direction'] == 'LONG' else -1
        entry_price = noisy_trades.loc[idx, 'entry_price']
        exit_price = noisy_trades.loc[idx, 'exit_price']
        
        entry_noise = np.random.uniform(-noise_ratio, noise_ratio)
        exit_noise = np.random.uniform(-noise_ratio, noise_ratio)
        
        if direction == 1:
            noisy_entry = entry_price * (1 + entry_noise * base_slippage / entry_price)
            noisy_exit = exit_price * (1 - exit_noise * base_slippage / exit_price)
        else:
            noisy_entry = entry_price * (1 - entry_noise * base_slippage / entry_price)
            noisy_exit = exit_price * (1 + exit_noise * base_slippage / exit_price)
        
        noisy_trades.loc[idx, 'entry_price'] = noisy_entry
        noisy_trades.loc[idx, 'exit_price'] = noisy_exit
        
        price_diff = (noisy_exit - noisy_entry) * direction
        noisy_trades.loc[idx, 'pnl'] = price_diff * 100
    
    return noisy_trades


def run_monte_carlo_validation(
    trades_df: pd.DataFrame,
    n_simulations: int = 100,
    noise_ratio: float = 0.2,
    degradation_threshold: float = 0.5,
    initial_capital: float = 100000,
    verbose: bool = True
) -> MonteCarloResult:
    """
    运行蒙特卡洛噪音注入验证
    
    如果劣化超过阈值，判定参数脆弱，拒绝该参数组合
    """
    if len(trades_df) < 5:
        return MonteCarloResult(
            original_sharpe=0, original_calmar=0,
            noise_sharpe_mean=0, noise_sharpe_std=0,
            noise_calmar_mean=0, noise_calmar_std=0,
            sharpe_degradation=1.0, calmar_degradation=1.0,
            is_fragile=True, rejection_reason="交易次数过少 (<5)"
        )
    
    pnls = trades_df['pnl'].values
    returns = pnls / initial_capital
    
    # 原始指标
    mean_return = np.mean(returns)
    std_return = np.std(returns)
    original_sharpe = (mean_return / std_return * np.sqrt(252 * 10)) if std_return > 0 else 0
    
    equity = np.cumsum(pnls) + initial_capital
    rolling_max = np.maximum.accumulate(equity)
    drawdown = (equity - rolling_max) / rolling_max * 100
    max_drawdown = abs(np.min(drawdown))
    total_return = (equity[-1] - initial_capital) / initial_capital * 100
    annual_return = total_return * (252 / 63)
    original_calmar = annual_return / max_drawdown if max_drawdown > 0 else float('inf')
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"【蒙特卡洛噪音注入验证】模拟次数: {n_simulations}")
        print(f"原始夏普: {original_sharpe:.4f}, 原始 Calmar: {original_calmar:.4f}")
    
    # 噪音模拟
    noise_sharpes = []
    noise_calmars = []
    
    for i in range(n_simulations):
        noisy_trades = inject_slippage_noise(trades_df, noise_ratio, seed=i)
        noisy_pnls = noisy_trades['pnl'].values
        noisy_returns = noisy_pnls / initial_capital
        
        mean_ret = np.mean(noisy_returns)
        std_ret = np.std(noisy_returns)
        noise_sharpe = (mean_ret / std_ret * np.sqrt(252 * 10)) if std_ret > 0 else 0
        
        noisy_equity = np.cumsum(noisy_pnls) + initial_capital
        noisy_rolling_max = np.maximum.accumulate(noisy_equity)
        noisy_drawdown = (noisy_equity - noisy_rolling_max) / noisy_rolling_max * 100
        noisy_max_dd = abs(np.min(noisy_drawdown))
        noisy_total_ret = (noisy_equity[-1] - initial_capital) / initial_capital * 100
        noise_calmar = (noisy_total_ret * (252 / 63) / noisy_max_dd) if noisy_max_dd > 0 else float('inf')
        
        noise_sharpes.append(noise_sharpe)
        noise_calmars.append(noise_calmar)
    
    noise_sharpe_mean = np.mean(noise_sharpes)
    noise_sharpe_std = np.std(noise_sharpes)
    noise_calmar_mean = np.mean(noise_calmars)
    noise_calmar_std = np.std(noise_calmars)
    
    sharpe_degradation = max(0, (original_sharpe - noise_sharpe_mean) / abs(original_sharpe)) if original_sharpe != 0 else 1.0
    calmar_degradation = max(0, (original_calmar - noise_calmar_mean) / abs(original_calmar)) if original_calmar != 0 else 1.0
    
    is_fragile = (sharpe_degradation > degradation_threshold or calmar_degradation > degradation_threshold)
    rejection_reason = f"参数脆弱: 夏普劣化 {sharpe_degradation*100:.1f}%, Calmar劣化 {calmar_degradation*100:.1f}%" if is_fragile else ""
    
    if verbose:
        print(f"噪音环境: 夏普 {noise_sharpe_mean:.4f}±{noise_sharpe_std:.4f}, Calmar {noise_calmar_mean:.4f}±{noise_calmar_std:.4f}")
        print(f"劣化程度: 夏普 {sharpe_degradation*100:.1f}%, Calmar {calmar_degradation*100:.1f}%")
        print(f"判定: {'❌ 脆弱 - 拒绝' if is_fragile else '✓ 稳健 - 接受'}")
        print(f"{'='*60}")
    
    return MonteCarloResult(
        original_sharpe=original_sharpe, original_calmar=original_calmar,
        noise_sharpe_mean=noise_sharpe_mean, noise_sharpe_std=noise_sharpe_std,
        noise_calmar_mean=noise_calmar_mean, noise_calmar_std=noise_calmar_std,
        sharpe_degradation=sharpe_degradation, calmar_degradation=calmar_degradation,
        is_fragile=is_fragile, rejection_reason=rejection_reason
    )
