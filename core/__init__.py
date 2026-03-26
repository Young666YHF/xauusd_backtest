"""
XAUUSD 量化交易系统 - 核心组件
================================
提供配置管理、数据类型、事件系统等基础功能
"""

from .config import Config, TradingConfig, StrategyConfig
from .types import (
    SignalType, TradeDirection, OrderType, ExitReason,
    TradeSignal, TradeRecord, Position, MarketData,
    BacktestResult, OptimizationResult
)
from .events import EventBus, EventType, Event
from .risk_manager import RiskManager

__all__ = [
    'Config', 'TradingConfig', 'StrategyConfig',
    'SignalType', 'TradeDirection', 'OrderType', 'ExitReason',
    'TradeSignal', 'TradeRecord', 'Position', 'MarketData',
    'BacktestResult', 'OptimizationResult',
    'EventBus', 'EventType', 'Event',
    'RiskManager',
]
