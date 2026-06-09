"""
策略基类模块
============
定义所有策略的抽象基类和注册机制
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Type, Callable, Union
from dataclasses import dataclass
import pandas as pd
from datetime import datetime

from core.types import TradeSignal, SignalType, TradeDirection, MarketData


class BaseStrategy(ABC):
    """
    策略抽象基类

    所有具体策略必须继承此类并实现以下方法:
    - generate_signal: 生成交易信号
    - get_default_params: 获取默认参数
    - get_param_bounds: 获取参数优化范围
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        """
        初始化策略

        Args:
            params: 策略参数字典
            strategy_id: 策略唯一标识
        """
        self.strategy_id = strategy_id or self.__class__.__name__
        self.params = self.get_default_params()
        if params:
            self.params.update(params)

        # 状态追踪
        self.is_active = True
        self.last_signal_time: Optional[datetime] = None
        self.signal_history: List[TradeSignal] = []

        # 性能统计
        self.total_signals = 0
        self.long_signals = 0
        self.short_signals = 0

    @abstractmethod
    def generate_signal(
        self,
        df: pd.DataFrame,
        current_idx: int,
        **kwargs
    ) -> Union[TradeSignal, List[TradeSignal], None]:
        """
        生成交易信号

        Args:
            df: 包含指标的完整DataFrame
            current_idx: 当前K线索引
            **kwargs: 额外上下文信息

        Returns:
            TradeSignal对象、TradeSignal列表或None（无信号）
        """
        pass

    @abstractmethod
    def get_default_params(self) -> Dict[str, Any]:
        """返回策略默认参数字典"""
        pass

    @abstractmethod
    def get_param_bounds(self) -> Dict[str, tuple]:
        """
        返回参数优化范围

        Returns:
            {参数名: (最小值, 最大值)} 的字典
        """
        pass

    def validate_params(self, params: Dict[str, Any]) -> bool:
        """
        验证参数有效性

        Args:
            params: 待验证的参数

        Returns:
            参数是否有效
        """
        try:
            bounds = self.get_param_bounds()
            for key, value in params.items():
                if key in bounds:
                    min_val, max_val = bounds[key]
                    if not (min_val <= value <= max_val):
                        return False
            return True
        except Exception:
            return False

    def update_params(self, params: Dict[str, Any]):
        """更新策略参数"""
        if self.validate_params(params):
            self.params.update(params)
        else:
            raise ValueError("Invalid parameters provided")

    def reset(self):
        """重置策略状态"""
        self.is_active = True
        self.last_signal_time = None
        self.signal_history.clear()
        self.total_signals = 0
        self.long_signals = 0
        self.short_signals = 0

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        为策略准备指标数据。

        子类可以重写此方法以计算策略特有的指标。
        默认实现直接返回原DataFrame（假设指标已在外部计算）。

        Args:
            df: 原始OHLCV数据

        Returns:
            添加指标后的DataFrame
        """
        return df

    def on_bar_close(self, bar: MarketData):
        """
        K线关闭时的回调

        子类可以重写此方法执行K线级别的操作
        """
        pass

    def on_trade_completed(self, trade_record: Dict[str, Any]):
        """
        交易完成时的回调

        Args:
            trade_record: 交易记录
        """
        pass

    def get_state(self) -> Dict[str, Any]:
        """获取策略当前状态"""
        return {
            'strategy_id': self.strategy_id,
            'is_active': self.is_active,
            'params': self.params.copy(),
            'total_signals': self.total_signals,
            'long_signals': self.long_signals,
            'short_signals': self.short_signals,
        }

    def _create_signal(
        self,
        timestamp: datetime,
        direction: TradeDirection,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reason: str = "",
        signal_bar_idx: int = 0,
        execution_bar_idx: int = 0,
        size: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **extra_metadata,
    ) -> TradeSignal:
        """
        创建交易信号

        Args:
            timestamp: 信号时间
            direction: 方向
            entry_price: 入场价格
            stop_loss: 止损价格
            take_profit: 止盈价格
            reason: 信号原因
            signal_bar_idx: 信号K线索引
            execution_bar_idx: 执行K线索引
            **metadata: 额外元数据

        Returns:
            TradeSignal对象
        """
        if direction == TradeDirection.LONG:
            signal_type = SignalType.LONG
        elif direction == TradeDirection.SHORT:
            signal_type = SignalType.SHORT
        else:
            signal_type = SignalType.NONE

        # Handle default values
        if metadata is None:
            metadata = {}
        if extra_metadata:
            metadata.update(extra_metadata)
        if size is None:
            size = metadata.get('size', self.params.get('position_size', 1.0)) if metadata else self.params.get('position_size', 1.0)

        signal = TradeSignal(
            timestamp=timestamp,
            signal_type=signal_type,
            strategy_id=self.strategy_id,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            size=size,
            risk_per_trade=self.params.get('risk_per_trade', 0.01),
            reason=reason,
            metadata=metadata,
            signal_bar_index=signal_bar_idx,
            execution_bar_index=execution_bar_idx
        )

        # 更新统计
        self.total_signals += 1
        if direction == TradeDirection.LONG:
            self.long_signals += 1
        elif direction == TradeDirection.SHORT:
            self.short_signals += 1

        self.last_signal_time = timestamp
        self.signal_history.append(signal)

        return signal

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.strategy_id}, active={self.is_active})"


class StrategyRegistry:
    """策略注册器 - 支持动态策略加载"""

    _strategies: Dict[str, Type[BaseStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: Type[BaseStrategy]):
        """注册策略"""
        if not issubclass(strategy_class, BaseStrategy):
            raise ValueError(f"Strategy class must inherit from BaseStrategy")
        cls._strategies[name] = strategy_class

    @classmethod
    def unregister(cls, name: str):
        """注销策略"""
        if name in cls._strategies:
            del cls._strategies[name]

    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseStrategy]]:
        """获取策略类"""
        return cls._strategies.get(name)

    @classmethod
    def create(
        cls,
        name: str,
        params: Optional[Dict[str, Any]] = None,
        strategy_id: str = ""
    ) -> BaseStrategy:
        """
        创建策略实例

        Args:
            name: 策略名称
            params: 策略参数
            strategy_id: 策略ID

        Returns:
            策略实例
        """
        strategy_class = cls.get(name)
        if strategy_class is None:
            raise ValueError(f"Unknown strategy: {name}. Available: {list(cls._strategies.keys())}")

        return strategy_class(params=params, strategy_id=strategy_id)

    @classmethod
    def list_strategies(cls) -> List[str]:
        """列出所有可用策略"""
        return list(cls._strategies.keys())

    @classmethod
    def get_info(cls, name: str) -> Optional[Dict[str, Any]]:
        """获取策略信息"""
        strategy_class = cls.get(name)
        if strategy_class is None:
            return None

        # 创建临时实例获取信息
        try:
            temp_instance = strategy_class()
            return {
                'name': name,
                'class': strategy_class.__name__,
                'default_params': temp_instance.get_default_params(),
                'param_bounds': temp_instance.get_param_bounds(),
                'doc': strategy_class.__doc__
            }
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to get strategy info for {name}: {e}")
            return {
                'name': name,
                'class': strategy_class.__name__,
                'doc': strategy_class.__doc__
            }
