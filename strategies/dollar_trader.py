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
版本: 1.0.0
"""

from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np
from datetime import datetime

from strategies.base import BaseStrategy
from core.types import TradeSignal, TradeDirection, SignalType, ExitReason
from core.indicators import calculate_sma


class DollarTraderStrategy(BaseStrategy):
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

        # 追踪当前持仓方向
        self.current_position: Optional[TradeDirection] = None

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

    def generate_signal(
        self,
        df: pd.DataFrame,
        current_idx: int,
        **kwargs
    ) -> Optional[TradeSignal]:
        """
        生成交易信号

        Args:
            df: 包含指标的DataFrame
            current_idx: 当前K线索引
            **kwargs: 额外上下文

        Returns:
            TradeSignal对象或None
        """
        # 检查数据充足性
        min_bars_needed = self.params['sma_long'] + 5

        if current_idx < min_bars_needed:
            return None

        # 获取指标列名
        sma_s_col = f"SMA_{self.params['sma_short']}"
        sma_m_col = f"SMA_{self.params['sma_medium']}"
        sma_l_col = f"SMA_{self.params['sma_long']}"

        # 检查必要的指标列是否存在
        for col in [sma_s_col, sma_m_col, sma_l_col]:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}. Please ensure SMA indicators are calculated.")

        # 【关键】使用shift(1)获取上一根K线的状态，避免未来函数
        # 获取上一根K线(已收盘)的指标值
        prev_bar = df.iloc[current_idx - 1]
        current_bar = df.iloc[current_idx]
        current_timestamp = df.index[current_idx]

        # 上一根K线的收盘价和均线值(用于信号判断)
        prev_close = prev_bar['Close']
        prev_sma_s = prev_bar[sma_s_col]
        prev_sma_m = prev_bar[sma_m_col]
        prev_sma_l = prev_bar[sma_l_col]

        # 当前K线开盘价(用于入场执行)
        current_open = current_bar['Open']

        # 检查指标有效性
        if pd.isna(prev_sma_s) or pd.isna(prev_sma_m) or pd.isna(prev_sma_l):
            return None

        signal = None

        # === 判断趋势状态(基于上一根K线) ===
        # 多头排列: C > SMA_S > SMA_M > SMA_L
        prev_bullish = (prev_close > prev_sma_s and
                        prev_sma_s > prev_sma_m and
                        prev_sma_m > prev_sma_l)

        # 空头排列: C < SMA_S < SMA_M < SMA_L
        prev_bearish = (prev_close < prev_sma_s and
                        prev_sma_s < prev_sma_m and
                        prev_sma_m < prev_sma_l)

        # SMA交叉判断(用于出场)
        # 需要前两根K线的SMA状态来判断交叉
        if current_idx >= 2:
            prev2_bar = df.iloc[current_idx - 2]
            prev2_sma_s = prev2_bar[sma_s_col]
            prev2_sma_m = prev2_bar[sma_m_col]

            # 短期下穿中期(死叉) - 多头平仓信号
            sma_bearish_cross = (prev2_sma_s >= prev2_sma_m) and (prev_sma_s < prev_sma_m)
            # 短期上穿中期(金叉) - 空头平仓信号
            sma_bullish_cross = (prev2_sma_s <= prev2_sma_m) and (prev_sma_s > prev_sma_m)
        else:
            sma_bearish_cross = False
            sma_bullish_cross = False

        # === 生成交易信号 ===
        signal = self._generate_entry_signal(
            prev_bullish, prev_bearish, current_timestamp, current_open,
            prev_close, prev_sma_s, prev_sma_m, prev_sma_l, current_idx
        )

        # 出场信号检查(仅当持有仓位时)
        if self.current_position == TradeDirection.LONG and sma_bearish_cross:
            # 多头平仓: SMA_20下穿SMA_50
            if signal is None or signal.direction != TradeDirection.SHORT:
                signal = self._create_exit_signal(
                    current_timestamp, TradeDirection.SHORT, current_open,
                    prev_sma_s, prev_sma_m, current_idx, is_long_exit=True
                )
                self.current_position = TradeDirection.SHORT if prev_bearish else None

        elif self.current_position == TradeDirection.SHORT and sma_bullish_cross:
            # 空头平仓: SMA_20上穿SMA_50
            if signal is None or signal.direction != TradeDirection.LONG:
                signal = self._create_exit_signal(
                    current_timestamp, TradeDirection.LONG, current_open,
                    prev_sma_s, prev_sma_m, current_idx, is_long_exit=False
                )
                self.current_position = TradeDirection.LONG if prev_bullish else None

        return signal

    def _generate_entry_signal(
        self,
        prev_bullish: bool,
        prev_bearish: bool,
        timestamp: datetime,
        entry_price: float,
        prev_close: float,
        prev_sma_s: float,
        prev_sma_m: float,
        prev_sma_l: float,
        current_idx: int
    ) -> Optional[TradeSignal]:
        """生成入场信号"""
        if prev_bullish:
            direction = TradeDirection.LONG
            is_reverse = self.current_position == TradeDirection.SHORT

            if self.current_position is None:
                reason = f"Long Entry: C({prev_close:.2f})>SMA_20({prev_sma_s:.2f})>SMA_50({prev_sma_m:.2f})>SMA_200({prev_sma_l:.2f})"
            elif is_reverse:
                reason = "Reverse to Long: SMA排列转多"
            else:
                return None

            self.current_position = TradeDirection.LONG

        elif prev_bearish:
            direction = TradeDirection.SHORT
            is_reverse = self.current_position == TradeDirection.LONG

            if self.current_position is None:
                reason = f"Short Entry: C({prev_close:.2f})<SMA_20({prev_sma_s:.2f})<SMA_50({prev_sma_m:.2f})<SMA_200({prev_sma_l:.2f})"
            elif is_reverse:
                reason = "Reverse to Short: SMA排列转空"
            else:
                return None

            self.current_position = TradeDirection.SHORT
        else:
            return None

        return self._create_signal(
            timestamp=timestamp,
            direction=direction,
            entry_price=entry_price,
            stop_loss=None,
            take_profit=None,
            reason=reason,
            signal_bar_idx=current_idx - 1,
            execution_bar_idx=current_idx,
        )

    def _create_exit_signal(
        self,
        timestamp: datetime,
        direction: TradeDirection,
        entry_price: float,
        prev_sma_s: float,
        prev_sma_m: float,
        current_idx: int,
        is_long_exit: bool
    ) -> TradeSignal:
        """生成出场信号"""
        if is_long_exit:
            reason = f"Long Exit: SMA_20({prev_sma_s:.2f}) crossed below SMA_50({prev_sma_m:.2f})"
        else:
            reason = f"Short Exit: SMA_20({prev_sma_s:.2f}) crossed above SMA_50({prev_sma_m:.2f})"

        return self._create_signal(
            timestamp=timestamp,
            direction=direction,
            entry_price=entry_price,
            stop_loss=None,
            take_profit=None,
            reason=reason,
            signal_bar_idx=current_idx - 1,
            execution_bar_idx=current_idx,
        )

    def on_trade_completed(self, trade_record: Dict[str, Any]):
        """
        交易完成回调

        Args:
            trade_record: 交易记录
        """
        # 当持仓被平仓时，重置当前持仓状态
        if trade_record.get('exit_reason') in [ExitReason.SIGNAL_REVERSE, ExitReason.FORCE_CLOSE, ExitReason.END_OF_DATA]:
            self.current_position = None

    def reset(self):
        """重置策略状态"""
        super().reset()
        self.current_position = None


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
    result = df.copy()

    # 计算三条SMA
    result[f'SMA_{sma_short}'] = calculate_sma(result['Close'], sma_short)
    result[f'SMA_{sma_medium}'] = calculate_sma(result['Close'], sma_medium)
    result[f'SMA_{sma_long}'] = calculate_sma(result['Close'], sma_long)

    return result
