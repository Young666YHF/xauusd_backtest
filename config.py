"""
XAUUSD 量化交易回测系统 - 配置文件
"""

# 交易品种配置
SYMBOL = "GC=F"  # yfinance黄金期货代码
TIMEFRAME = "15m"  # 15分钟周期（用户要求）
CONTRACT_SIZE = 100  # 每手100盎司
SPREAD_PER_LOT = 60  # 每手点差60美元
SPREAD_PER_OUNCE = 0.6  # 每盎司点差0.6美元

# 交易时段（北京时间 UTC+8）
ASIAN_SESSION_START = 6   # 亚盘开始
ASIAN_SESSION_END = 14    # 亚盘结束
EUROPEAN_SESSION_START = 15  # 欧美盘开始
EUROPEAN_SESSION_END = 24    # 欧美盘结束（次日02:00）

# 默认策略参数
# 来源: Tick级贝叶斯优化 (Optuna TPE, 100 trials)
# 数据: 2025-12 至 2026-02, Tick级别, 15分钟周期
# 表现: 收益66.81%, 回撤12.63%, 夏普1.21, 胜率30.77%
DEFAULT_PARAMS = {
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

# 回测配置
INITIAL_CAPITAL = 100000  # 初始资金10万美元
POSITION_SIZE = 1.0  # 默认持仓手数
LEVERAGE = 1  # 杠杆倍数

# 遗传算法配置
GA_POPULATION_SIZE = 50
GA_GENERATIONS = 300
GA_CROSSOVER_RATE = 0.8
GA_MUTATION_RATE = 0.1

# 参数优化范围
PARAM_BOUNDS = {
    # 基础指标参数
    'bb_period': (10, 30),
    'bb_std': (1.5, 3.5),
    'kc_period': (10, 30),
    'kc_atr_mult': (1.0, 2.5),
    'atr_period': (7, 21),
    'rsi_period': (7, 21),
    # 策略A参数
    'rsi_oversold': (20, 40),
    'rsi_overbought': (60, 80),
    'stop_loss_atr_mult_a': (1.0, 2.5),
    'max_hold_bars_a': (3, 10),
    # 策略B参数
    'ema_fast': (10, 30),
    'ema_slow': (30, 70),
    'stop_loss_atr_mult_b': (1.0, 3.0),
    'trailing_stop_atr_mult': (2.0, 5.0),
    # 波动率过滤
    'squeeze_threshold': (0.5, 1.5),
    # Module 1: ATR自适应时间止损
    'atr_time_stop_base': (2.0, 5.0),
    'atr_time_stop_mult': (0.2, 1.0),
    # Module 2: 异常波动过滤
    'volatility_filter_period': (10, 30),
    'volatility_filter_mult': (1.2, 2.0),
    # Module 2: 假突破过滤
    'pullback_confirmation_bars': (1, 3),
    'ema_momentum_threshold': (0.0005, 0.002),
}
