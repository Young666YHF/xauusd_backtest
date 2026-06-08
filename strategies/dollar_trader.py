"""
Dollar Trader 策略 - 三线SMA趋势跟踪
=====================================
基于SMA_20, SMA_50, SMA_200的经典趋势跟踪策略

核心逻辑:
1. 多头开仓: C > SMA_20 且 SMA_20 > SMA_50 且 SMA_50 > SMA_200
2. 空头开仓: C < SMA_20 且 SMA_20 < SMA_50 且 SMA_50 < SMA_200
3. 多头平仓: SMA_20 < SMA_50 (短期下穿中期)
4. 空头平仓: SMA_20 > SMA_50 (短期上穿中期)

特点:
- 中长线趋势跟踪，捕捉大趋势
- SMA排列判断趋势方向
- 短期与中期均线交叉作为出场信号
- 严格执行shift(1)避免未来函数

作者: Claude
版本: 2.0.0
"""

from typing import Dict, List, Optional, Any
import pandas as pd

from strategies.dollar_trader_base import DollarTraderBaseStrategy, calculate_dollar_trader_base_indicators
from core.indicators import calculate_sma


class DollarTraderStrategy(DollarTraderBaseStrategy):
    """
    Dollar Trader 趋势跟踪策略

    使用三条SMA(短期20, 中期50, 长期200)判断趋势方向:
    - 多头排列且价格在短期均线上方做多
    - 空头排列且价格在短期均线下方做空
    - 短期与中期均线交叉平仓
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        """
        初始化策略

        Args:
            params: 策略参数，包含:
                - sma_short: 短期SMA周期 (默认20)
                - sma_medium: 中期SMA周期 (默认50)
                - sma_long: 长期SMA周期 (默认200)
                - position_size: 仓位大小 (默认1.0)
            strategy_id: 策略标识
        """
        super().__init__(params, strategy_id or "DollarTrader")

    def get_default_params(self) -> Dict[str, Any]:
        """返回默认参数"""
        return {
            'sma_short': 20,
            'sma_medium': 50,
            'sma_long': 200,
            'position_size': 1.0,  # 固定手数
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        """返回参数优化范围"""
        return {
            'sma_short': (10, 30),
            'sma_medium': (30, 70),
            'sma_long': (100, 300),
        }


def calculate_dollar_trader_indicators(
    df: pd.DataFrame,
    sma_short: int = 20,
    sma_medium: int = 50,
    sma_long: int = 200
) -> pd.DataFrame:
    """
    计算Dollar Trader策略所需的所有指标

    Args:
        df: OHLCV数据
        sma_short: 短期SMA周期
        sma_medium: 中期SMA周期
        sma_long: 长期SMA周期

    Returns:
        添加指标后的DataFrame
    """
    return calculate_dollar_trader_base_indicators(df, sma_short, sma_medium, sma_long)
