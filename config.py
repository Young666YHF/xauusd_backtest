"""
XAUUSD 量化交易回测系统 - 配置文件
"""

# 交易品种配置
SYMBOL = "GC=F"  # yfinance黄金期货代码
TIMEFRAME = "15m"  # 15分钟周期（用户要求）
CONTRACT_SIZE = 100  # 每手100盎司
SPREAD_PER_LOT = 20  # 每手点差20美元 (ECN实际)
SPREAD_PER_OUNCE = 0.2  # 每盎司点差0.2美元 (ECN实际: 0.15-0.25)

# 交易时段（北京时间 UTC+8）
ASIAN_SESSION_START = 6   # 亚盘开始
ASIAN_SESSION_END = 14    # 亚盘结束
EUROPEAN_SESSION_START = 15  # 欧美盘开始
EUROPEAN_SESSION_END = 24    # 欧美盘结束（次日02:00）

# 默认策略参数
# 来源: 优化版本 v4 (放宽入场条件，提高交易频率)
# 数据: 2025-12 至 2026-02, Tick级别, 15分钟周期
# 优化目标: 提高交易频率，保证统计稳定性
DEFAULT_PARAMS = {
    # 基础指标参数
    'bb_period': 15,
    'bb_std': 1.8,  # 降低：从2.31降到1.8，更容易触及
    'kc_period': 18,
    'kc_atr_mult': 2.0,  # 降低：更易满足BB>KC条件
    'atr_period': 13,
    'rsi_period': 10,

    # 策略A参数（均值回归）- 放宽入场条件
    'rsi_oversold': 30,  # 提高：从20到30，增加超卖触发频率
    'rsi_overbought': 70,  # 降低：从77到70
    'stop_loss_atr_mult_a': 1.31,
    'max_hold_bars_a': 6,

    # 策略B参数（动量突破）- 放宽入场条件
    'ema_fast': 28,
    'ema_slow': 64,
    'stop_loss_atr_mult_b': 2.11,
    'trailing_stop_atr_mult': 4.89,

    # 波动率过滤器 - 放宽
    'squeeze_threshold': 0.6,  # 降低：从0.74到0.6，更容易识别趋势

    # Module 1: ATR自适应时间止损
    'atr_time_stop_base': 4.99,
    'atr_time_stop_mult': 0.74,

    # Module 2: 异常波动过滤 - 放宽
    'volatility_filter_period': 17,
    'volatility_filter_mult': 2.0,  # 提高：从1.47到2.0，减少过滤

    # Module 2: 假突破过滤 - 放宽
    'pullback_confirmation_bars': 2,  # 减少：从3到2，加快确认
    'ema_momentum_threshold': 0.0003,  # 降低：从0.00067到0.0003，更容易满足
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

# 参数优化范围 - 放宽以增加交易频率
PARAM_BOUNDS = {
    # 基础指标参数
    'bb_period': (10, 25),  # 缩短周期
    'bb_std': (1.5, 2.5),  # 降低上限：从3.5到2.5，避免过宽
    'kc_period': (10, 25),
    'kc_atr_mult': (1.5, 2.5),  # 提高下限：确保KC不会太宽
    'atr_period': (7, 21),
    'rsi_period': (7, 21),
    # 策略A参数 - 放宽RSI阈值
    'rsi_oversold': (25, 40),  # 提高下限：从20到25
    'rsi_overbought': (60, 75),  # 降低上限
    'stop_loss_atr_mult_a': (1.0, 2.0),
    'max_hold_bars_a': (3, 8),
    # 策略B参数
    'ema_fast': (8, 25),  # 允许更快的EMA
    'ema_slow': (25, 60),  # 允许更慢的EMA
    'stop_loss_atr_mult_b': (1.5, 3.0),
    'trailing_stop_atr_mult': (2.5, 5.0),
    # 波动率过滤 - 放宽
    'squeeze_threshold': (0.4, 1.0),  # 降低范围
    # Module 1: ATR自适应时间止损
    'atr_time_stop_base': (2.0, 5.0),
    'atr_time_stop_mult': (0.2, 1.0),
    # Module 2: 异常波动过滤 - 放宽
    'volatility_filter_period': (10, 25),
    'volatility_filter_mult': (1.5, 2.5),  # 提高范围：减少过滤
    # Module 2: 假突破过滤 - 缩短确认时间
    'pullback_confirmation_bars': (1, 2),  # 减少确认时间
    'ema_momentum_threshold': (0.0002, 0.001),  # 降低范围
}
