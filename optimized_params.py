"""
贝叶斯优化最佳参数 (Bayesian Optimized Parameters)
========================================

最新优化结果 (Tick级别):
- 优化日期: 2026-03-19
- 数据周期: 2025-12 至 2026-02
- 回测粒度: Tick级别逐笔计算, 15分钟指标
- 优化算法: Optuna TPE (Tree-structured Parzen Estimator)
- 迭代次数: 100

Tick优化表现:
- 总收益率: 66.81%
- 最大回撤: 12.63%
- 夏普比率: 1.21
- 胜率: 30.77%
- 交易次数: 26
"""

# =============================================================================
# 最新最优参数 - Tick级贝叶斯优化 (推荐使用)
# =============================================================================

TICK_OPTIMIZED_PARAMS = {
    # 基础指标参数
    'bb_period': 15,
    'bb_std': 2.31,
    'kc_period': 18,
    'kc_atr_mult': 2.37,
    'atr_period': 13,
    'rsi_period': 10,

    # 策略A参数（均值回归）
    'rsi_oversold': 20,
    'rsi_overbought': 77,
    'stop_loss_atr_mult_a': 1.31,
    'max_hold_bars_a': 6,

    # 策略B参数（动量突破）
    'ema_fast': 28,
    'ema_slow': 64,
    'stop_loss_atr_mult_b': 2.11,
    'trailing_stop_atr_mult': 4.89,

    # 波动率过滤
    'squeeze_threshold': 0.74,

    # Module 1: ATR自适应时间止损
    'atr_time_stop_base': 4.99,
    'atr_time_stop_mult': 0.74,

    # Module 2: 异常波动过滤
    'volatility_filter_period': 17,
    'volatility_filter_mult': 1.47,

    # Module 2: 假突破过滤
    'pullback_confirmation_bars': 3,
    'ema_momentum_threshold': 0.00067,
}

# =============================================================================
# K线优化结果 (历史参考)
# =============================================================================

KLINE_OPTIMIZED_PARAMS = {
    # 基础指标参数
    'bb_period': 13,
    'bb_std': 1.62,
    'kc_period': 25,
    'kc_atr_mult': 1.30,
    'atr_period': 19,
    'rsi_period': 21,

    # 策略A参数（均值回归）
    'rsi_oversold': 23,
    'rsi_overbought': 77,
    'stop_loss_atr_mult_a': 1.36,
    'max_hold_bars_a': 7,

    # 策略B参数（动量突破）
    'ema_fast': 17,
    'ema_slow': 32,
    'stop_loss_atr_mult_b': 1.69,
    'trailing_stop_atr_mult': 4.54,

    # 波动率过滤
    'squeeze_threshold': 0.96,

    # Module 1: ATR自适应时间止损
    'atr_time_stop_base': 2.71,
    'atr_time_stop_mult': 0.76,

    # Module 2: 异常波动过滤
    'volatility_filter_period': 14,
    'volatility_filter_mult': 1.79,

    # Module 2: 假突破过滤
    'pullback_confirmation_bars': 3,
    'ema_momentum_threshold': 0.00082,
}

# 向后兼容: OPTIMIZED_PARAMS 指向最新最优参数
OPTIMIZED_PARAMS = TICK_OPTIMIZED_PARAMS

# 优化统计信息
OPTIMIZATION_STATS = {
    'tick_optimization': {
        'timestamp': '2026-03-19_21:44:36',
        'data_range': {
            'start': '2025-12-01',
            'end': '2026-02-27',
            'granularity': 'tick',
        },
        'performance': {
            'total_return': 66.81,      # %
            'max_drawdown': 12.63,      # %
            'sharpe_ratio': 1.21,
            'win_rate': 30.77,          # %
            'total_trades': 26,
            'strategy_a_pnl': -12330,   # USD
            'strategy_b_pnl': 79136,    # USD
        }
    },
    'kline_optimization': {
        'timestamp': '2026-03-19_01:13:48',
        'data_range': {
            'start': '2025-12-01',
            'end': '2026-02-27',
            'granularity': '15min_kline',
            'total_bars': 5759,
        },
        'performance': {
            'total_return': 191.91,     # %
            'max_drawdown': 7.20,       # %
            'sharpe_ratio': 5.25,
            'profit_factor': 6.20,
            'win_rate': 50.0,           # %
            'total_trades': 52,
        }
    }
}


# 便捷导入函数
def get_optimized_params():
    """获取优化后的参数 (最新tick优化结果)"""
    return TICK_OPTIMIZED_PARAMS.copy()


def get_kline_params():
    """获取K线优化参数 (历史参考)"""
    return KLINE_OPTIMIZED_PARAMS.copy()


def get_default_params():
    """获取默认参数（与config.py一致）"""
    from config import DEFAULT_PARAMS
    return DEFAULT_PARAMS.copy()


if __name__ == '__main__':
    print("=" * 70)
    print("贝叶斯优化最佳参数")
    print("=" * 70)

    print(f"\n{'=' * 70}")
    print("Tick级优化结果 (推荐)")
    print(f"{'=' * 70}")
    tick_stats = OPTIMIZATION_STATS['tick_optimization']
    print(f"优化日期: {tick_stats['timestamp']}")
    print(f"数据粒度: {tick_stats['data_range']['granularity']}")
    print(f"总收益率: {tick_stats['performance']['total_return']:.2f}%")
    print(f"最大回撤: {tick_stats['performance']['max_drawdown']:.2f}%")
    print(f"夏普比率: {tick_stats['performance']['sharpe_ratio']:.2f}")
    print(f"胜率: {tick_stats['performance']['win_rate']:.2f}%")
    print(f"交易次数: {tick_stats['performance']['total_trades']}")
    print(f"策略A盈亏: ${tick_stats['performance']['strategy_a_pnl']:,}")
    print(f"策略B盈亏: ${tick_stats['performance']['strategy_b_pnl']:,}")

    print(f"\n{'=' * 70}")
    print("K线优化结果 (历史参考)")
    print(f"{'=' * 70}")
    kline_stats = OPTIMIZATION_STATS['kline_optimization']
    print(f"优化日期: {kline_stats['timestamp']}")
    print(f"数据粒度: {kline_stats['data_range']['granularity']}")
    print(f"总收益率: {kline_stats['performance']['total_return']:.2f}%")
    print(f"最大回撤: {kline_stats['performance']['max_drawdown']:.2f}%")
    print(f"夏普比率: {kline_stats['performance']['sharpe_ratio']:.2f}")

    print(f"\n{'=' * 70}")
    print("当前默认参数 (Tick优化)")
    print(f"{'=' * 70}")
    for key, value in sorted(TICK_OPTIMIZED_PARAMS.items()):
        print(f"  {key}: {value}")
