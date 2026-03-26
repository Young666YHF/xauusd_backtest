"""
策略模块
========
提供策略基类和具体策略实现
"""

from .base import BaseStrategy, StrategyRegistry
from .mean_reversion import MeanReversionStrategy
from .momentum_breakout import MomentumBreakoutStrategy
from .trend_angle_breakout import TrendAngleBreakoutStrategy
from .dollar_trader import DollarTraderStrategy
from .dollar_trader_martingale import DollarTraderMartingaleStrategy

__all__ = [
    'BaseStrategy',
    'StrategyRegistry',
    'MeanReversionStrategy',
    'MomentumBreakoutStrategy',
    'TrendAngleBreakoutStrategy',
    'DollarTraderStrategy',
    'DollarTraderMartingaleStrategy',
]

# 注册内置策略
StrategyRegistry.register('mean_reversion', MeanReversionStrategy)
StrategyRegistry.register('momentum_breakout', MomentumBreakoutStrategy)
StrategyRegistry.register('trend_angle_breakout', TrendAngleBreakoutStrategy)
StrategyRegistry.register('dollar_trader', DollarTraderStrategy)
StrategyRegistry.register('dollar_trader_martingale', DollarTraderMartingaleStrategy)
