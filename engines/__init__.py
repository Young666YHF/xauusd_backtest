"""
回测引擎模块
============
提供K线级和Tick级回测引擎
"""

from .base import BaseBacktestEngine, ExecutionModel
from .candle_engine import CandleBacktestEngine
from .tick_engine import TickBacktestEngine
from .dollar_trader_engine import DollarTraderBacktestEngine
from .breakout_grid_engine import BreakoutGridEngine

__all__ = [
    "BaseBacktestEngine",
    "ExecutionModel",
    "CandleBacktestEngine",
    "TickBacktestEngine",
    "DollarTraderBacktestEngine",
    "BreakoutGridEngine",
]
