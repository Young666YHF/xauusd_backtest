"""
Dollar Trader Martingale 策略 - 三线SMA趋势跟踪 + 马丁格尔仓位管理
=============================================
基于SMA_20, SMA_50, SMA_200的经典趋势跟踪策略，引入马丁格尔仓位管理

核心逻辑:
1. 多头开仓: C > SMA_20 且 SMA_20 > SMA_50 且 SMA_50 > SMA_200
2. 空头开仓: C < SMA_20 且 SMA_20 < SMA_50 且 SMA_50 < SMA_200
3. 多头平仓: SMA_20 < SMA_50 (短期下穿中期)
4. 空头平仓: SMA_20 > SMA_50 (短期上穿中期)

马丁格尔特性:
- 基础仓位: position_size
- 亏损后翻倍: 第N次交易仓位 = position_size * multiplier^(N-1)
- 盈利后重置: 回到基础仓位
- 最大连续亏损次数限制: max_martingale_steps

特点:
- 中长线趋势跟踪，捕捉大趋势
- SMA排列判断趋势方向
- 短期与中期均线交叉作为出场信号
- 马丁格尔仓位管理，快速回收亏损

作者: Claude
版本: 2.0.0
"""

from typing import Dict, List, Optional, Any
import pandas as pd

from strategies.dollar_trader_base import (
    DollarTraderBaseStrategy,
    calculate_dollar_trader_base_indicators,
)
from core.types import TradeSignal, TradeDirection, ExitReason
from core.indicators import calculate_sma


class DollarTraderMartingaleStrategy(DollarTraderBaseStrategy):
    """
    Dollar Trader Martingale 趋势跟踪策略

    使用三条SMA(短期20, 中期50, 长期200)判断趋势方向:
    - 多头排列且价格在短期均线上方做多
    - 空头排列且价格在短期均线下方做空
    - 短期与中期均线交叉平仓

    马丁格尔仓位管理:
    - 可配置翻倍倍数 (默认2.0倍)
    - 记录连续亏损次数
    - 盈利后重置仓位
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        """
        初始化策略

        Args:
            params: 策略参数，包含:
                - sma_short: 短期SMA周期 (默认20)
                - sma_medium: 中期SMA周期 (默认50)
                - sma_long: 长期SMA周期 (默认200)
                - position_size: 基础仓位大小 (默认1.0)
                - martingale_multiplier: 马丁格尔倍数 (默认2.0)
                - max_martingale_steps: 最大连续翻倍次数 (默认5)
            strategy_id: 策略标识
        """
        super().__init__(params, strategy_id or "DollarTraderMartingale")

        # 马丁格尔状态
        self.consecutive_losses: int = 0  # 连续亏损次数
        self.current_position_size: float = self.params["position_size"]  # 当前实际仓位
        self.last_trade_profit: Optional[float] = None  # 上次交易盈亏

    def get_default_params(self) -> Dict[str, Any]:
        """返回默认参数"""
        return {
            "sma_short": 20,
            "sma_medium": 50,
            "sma_long": 200,
            "position_size": 1.0,  # 基础仓位
            "martingale_multiplier": 2.0,  # 马丁格尔倍数 (可配置)
            "max_martingale_steps": 5,  # 最大连续翻倍次数
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        """返回参数优化范围"""
        return {
            "sma_short": (10, 30),
            "sma_medium": (30, 70),
            "sma_long": (100, 300),
            "martingale_multiplier": (1.5, 3.0),
            "max_martingale_steps": (3, 8),
        }

    def _calculate_martingale_position_size(self) -> float:
        """
        计算马丁格尔仓位大小

        Returns:
            当前应使用的仓位大小
        """
        base_size = self.params["position_size"]
        multiplier = self.params["martingale_multiplier"]
        max_steps = self.params["max_martingale_steps"]

        # 限制最大翻倍次数
        effective_losses = min(self.consecutive_losses, max_steps)

        # 计算仓位: base * multiplier^losses
        position_size = base_size * (multiplier**effective_losses)

        return position_size

    def _update_martingale_state(self, trade_record: Dict[str, Any]):
        """
        更新马丁格尔状态

        Args:
            trade_record: 交易记录
        """
        profit = trade_record.get("profit", 0)
        self.last_trade_profit = profit

        if profit > 0:
            # 盈利: 重置连续亏损计数
            if self.consecutive_losses > 0:
                self.consecutive_losses = 0
        else:
            # 亏损: 增加连续亏损计数
            self.consecutive_losses += 1

        # 更新当前仓位大小
        self.current_position_size = self._calculate_martingale_position_size()

    def _get_position_size_for_signal(self) -> Optional[float]:
        """
        获取当前信号应使用的仓位大小 (马丁格尔调整后的)

        Returns:
            当前应使用的仓位大小
        """
        return self.current_position_size

    def on_trade_completed(self, trade_record: Dict[str, Any]):
        """
        交易完成回调

        Args:
            trade_record: 交易记录
        """
        # 更新马丁格尔状态
        self._update_martingale_state(trade_record)

        # 当持仓被平仓时，重置当前持仓状态
        if trade_record.get("exit_reason") in [
            ExitReason.SIGNAL_REVERSE,
            ExitReason.FORCE_CLOSE,
            ExitReason.END_OF_DATA,
        ]:
            self.current_position = None

    def reset(self):
        """重置策略状态"""
        super().reset()
        self.current_position = None
        self.consecutive_losses = 0
        self.current_position_size = self.params["position_size"]
        self.last_trade_profit = None

    def get_position_size(self) -> float:
        """
        获取当前仓位大小 (马丁格尔调整后的)

        Returns:
            当前应使用的仓位大小
        """
        return self.current_position_size


def calculate_dollar_trader_martingale_indicators(
    df: pd.DataFrame, sma_short: int = 20, sma_medium: int = 50, sma_long: int = 200
) -> pd.DataFrame:
    """
    计算Dollar Trader Martingale策略所需的所有指标

    Args:
        df: OHLCV数据
        sma_short: 短期SMA周期
        sma_medium: 中期SMA周期
        sma_long: 长期SMA周期

    Returns:
        添加指标后的DataFrame
    """
    return calculate_dollar_trader_base_indicators(df, sma_short, sma_medium, sma_long)
