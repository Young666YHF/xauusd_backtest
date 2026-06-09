"""
策略模块
========
提供策略基类和具体策略实现
"""

from .base import BaseStrategy, StrategyRegistry
from .dollar_trader_base import (
    DollarTraderBaseStrategy,
    calculate_dollar_trader_base_indicators,
)
from .mean_reversion import MeanReversionStrategy
from .momentum_breakout import MomentumBreakoutStrategy
from .trend_angle_breakout import TrendAngleBreakoutStrategy
from .dollar_trader import DollarTraderStrategy
from .dollar_trader_martingale import DollarTraderMartingaleStrategy
from .dollar_trader_martingale_adx import DollarTraderMartingaleBBWStepStrategy
from .dollar_trader_martingale_sl import (
    DollarTraderMartingaleSLStrategy,
    calculate_dollar_trader_martingale_sl_indicators,
)
from .adaptive_trend_strategy import (
    AdaptiveTrendMartingaleStrategy,
    calculate_adaptive_trend_indicators,
)
from .mean_reversion_martingale import (
    MeanReversionMartingaleStrategy,
    calculate_mean_reversion_indicators,
)
from .smart_martingale import (
    SmartAdaptiveMartingaleStrategy,
    calculate_smart_indicators,
)

from .breakout_grid import BreakoutGridStrategy

__all__ = [
    "BaseStrategy",
    "StrategyRegistry",
    "DollarTraderBaseStrategy",
    "MeanReversionStrategy",
    "MomentumBreakoutStrategy",
    "TrendAngleBreakoutStrategy",
    "DollarTraderStrategy",
    "DollarTraderMartingaleStrategy",
    "DollarTraderMartingaleBBWStepStrategy",
    "DollarTraderMartingaleSLStrategy",
    "AdaptiveTrendMartingaleStrategy",
    "MeanReversionMartingaleStrategy",
    "SmartAdaptiveMartingaleStrategy",
    "BreakoutGridStrategy",
    "calculate_dollar_trader_base_indicators",
    "calculate_dollar_trader_martingale_sl_indicators",
    "calculate_adaptive_trend_indicators",
    "calculate_mean_reversion_indicators",
    "calculate_smart_indicators",
]

# 注册内置策略
StrategyRegistry.register("mean_reversion", MeanReversionStrategy)
StrategyRegistry.register("momentum_breakout", MomentumBreakoutStrategy)
StrategyRegistry.register("trend_angle_breakout", TrendAngleBreakoutStrategy)
StrategyRegistry.register("dollar_trader", DollarTraderStrategy)
StrategyRegistry.register("dollar_trader_martingale", DollarTraderMartingaleStrategy)
StrategyRegistry.register(
    "dollar_trader_martingale_adx", DollarTraderMartingaleBBWStepStrategy
)
StrategyRegistry.register(
    "dollar_trader_martingale_sl", DollarTraderMartingaleSLStrategy
)
StrategyRegistry.register("adaptive_trend", AdaptiveTrendMartingaleStrategy)
StrategyRegistry.register("mean_reversion_martingale", MeanReversionMartingaleStrategy)
StrategyRegistry.register("smart_martingale", SmartAdaptiveMartingaleStrategy)
StrategyRegistry.register("breakout_grid", BreakoutGridStrategy)
