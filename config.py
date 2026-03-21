"""
XAUUSD 双策略配置文件
=====================
包含默认参数和参数边界定义
"""

# 默认参数 (Tick级贝叶斯优化最优参数)
DEFAULT_PARAMS = {
    # 基础指标参数
    'bb_period': 15,
    'bb_std': 2.31,
    'kc_period': 18,
    'kc_atr_mult': 2.37,
    'atr_period': 13,
    'rsi_period': 10,
    'rsi_oversold': 20,
    'rsi_overbought': 77,

    # 策略A参数 (均值回归)
    'stop_loss_atr_mult_a': 1.31,
    'max_hold_bars_a': 6,

    # 策略B参数 (动量突破)
    'ema_fast': 28,
    'ema_slow': 64,
    'stop_loss_atr_mult_b': 2.11,
    'trailing_stop_atr_mult': 4.89,

    # 波动率过滤器
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

# 参数边界 (用于优化)
PARAM_BOUNDS = {
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
}
