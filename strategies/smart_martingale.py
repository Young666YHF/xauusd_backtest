"""
智能自适应马丁策略 (Smart Adaptive Martingale)
==============================================
根据市场状态自动切换策略模式：
1. 趋势市：使用趋势跟踪
2. 震荡市：使用均值回归

核心改进：
- ADX判断趋势强度
- 市场状态检测
- 不同市场使用不同策略参数

作者: Claude
版本: 6.0.0
"""

from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
import numpy as np
from datetime import datetime

from strategies.base import BaseStrategy
from core.types import TradeSignal, TradeDirection, SignalType, ExitReason
from core.indicators import (
    calculate_sma, calculate_atr, calculate_adx,
    calculate_bollinger_bands, calculate_rsi
)


class SmartAdaptiveMartingaleStrategy(BaseStrategy):
    """
    智能自适应马丁策略

    市场状态判断：
    - ADX > 25 且 价格明显偏向一侧 → 趋势市 → 趋势跟踪
    - ADX < 25 或 价格在中轨附近震荡 → 震荡市 → 均值回归
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        super().__init__(params, strategy_id or "SmartAdaptiveMartingale")

        self.current_position: Optional[TradeDirection] = None
        self.entry_price: Optional[float] = None
        self.market_state: str = "neutral"  # trending, ranging
        self.martingale_step: int = 0
        self.consecutive_losses: int = 0

    def get_default_params(self) -> Dict[str, Any]:
        return {
            # 市场状态参数
            'adx_threshold': 25,
            'trend_price_bias': 0.55,  # 价格>SMA的比例阈值

            # 趋势策略参数
            'ema_fast': 20,
            'ema_slow': 50,
            'ema_trend': 100,

            # 均值回归参数
            'bb_period': 20,
            'bb_std': 2.0,
            'rsi_period': 14,
            'rsi_oversold': 30,
            'rsi_overbought': 70,

            # 止损止盈
            'atr_period': 14,
            'trend_sl_atr': 2.0,
            'trend_tp_atr': 4.0,
            'range_sl_atr': 1.5,
            'range_tp_atr': 2.5,

            # 马丁参数
            'position_size': 0.01,
            'martingale_multiplier': 1.5,
            'max_martingale_steps': 4,
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        return {
            'adx_threshold': (20, 30),
            'ema_fast': (15, 30),
            'ema_slow': (40, 70),
            'bb_period': (15, 25),
            'bb_std': (1.8, 2.5),
            'rsi_oversold': (25, 35),
            'rsi_overbought': (65, 75),
            'trend_sl_atr': (1.5, 3.0),
            'trend_tp_atr': (3.0, 6.0),
            'range_sl_atr': (1.0, 2.0),
            'range_tp_atr': (2.0, 4.0),
            'martingale_multiplier': (1.3, 2.0),
            'max_martingale_steps': (2, 6),
        }

    def _calculate_position_size(self) -> float:
        base = self.params['position_size']
        mult = self.params['martingale_multiplier']
        max_steps = self.params['max_martingale_steps']
        step = min(self.martingale_step, max_steps)
        return base * (mult ** step)

    def _detect_market_state(self, df: pd.DataFrame, current_idx: int, lookback: int = 100) -> str:
        """
        检测市场状态

        Returns:
            'trending' 或 'ranging'
        """
        if current_idx < lookback:
            return 'ranging'  # 默认震荡

        recent = df.iloc[current_idx - lookback:current_idx]
        prev_bar = df.iloc[current_idx - 1]

        # 获取指标
        adx = prev_bar.get('ADX', 0)
        ema_fast = prev_bar.get('EMA_fast', 0)
        ema_slow = prev_bar.get('EMA_slow', 0)
        close = prev_bar['Close']

        if pd.isna(adx) or pd.isna(ema_fast) or pd.isna(ema_slow):
            return 'ranging'

        # 判断趋势
        is_trending = adx > self.params['adx_threshold']
        price_above_slow = close > ema_slow
        ema_aligned = ema_fast > ema_slow

        if is_trending and (price_above_slow == ema_aligned):
            return 'trending'
        else:
            return 'ranging'

    def on_trade_completed(self, trade_record: Dict[str, Any]):
        profit = trade_record.get('profit', 0)
        exit_reason = trade_record.get('exit_reason')

        if profit < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= 2 and self.martingale_step < self.params['max_martingale_steps']:
                self.martingale_step += 1
                self.consecutive_losses = 0
        else:
            self.consecutive_losses = 0
            if self.martingale_step > 0:
                self.martingale_step -= 1

        if exit_reason in [ExitReason.SIGNAL_REVERSE, ExitReason.FORCE_CLOSE, ExitReason.END_OF_DATA]:
            self.current_position = None
            self.entry_price = None

    def _generate_trend_signal(self, df, current_idx, prev_bar, current_open, atr, timestamp):
        """趋势跟踪信号"""
        ema_fast = prev_bar.get('EMA_fast', 0)
        ema_slow = prev_bar.get('EMA_slow', 0)
        ema_trend = prev_bar.get('EMA_trend', 0)
        close = prev_bar['Close']

        if pd.isna(ema_fast) or pd.isna(ema_slow):
            return None

        sl_mult = self.params['trend_sl_atr']
        tp_mult = self.params['trend_tp_atr']

        signal = None

        # 无持仓时入场
        if self.current_position is None:
            # 多头排列
            if close > ema_fast > ema_slow:
                sl = current_open - sl_mult * atr
                tp = current_open + tp_mult * atr
                signal = TradeSignal(
                    timestamp=timestamp,
                    signal_type=SignalType.LONG,
                    strategy_id=self.strategy_id,
                    direction=TradeDirection.LONG,
                    entry_price=current_open,
                    stop_loss=sl,
                    take_profit=tp,
                    size=self._calculate_position_size(),
                    reason=f"Trend Long: EMA bullish",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = TradeDirection.LONG
                self.entry_price = current_open

            # 空头排列
            elif close < ema_fast < ema_slow:
                sl = current_open + sl_mult * atr
                tp = current_open - tp_mult * atr
                signal = TradeSignal(
                    timestamp=timestamp,
                    signal_type=SignalType.SHORT,
                    strategy_id=self.strategy_id,
                    direction=TradeDirection.SHORT,
                    entry_price=current_open,
                    stop_loss=sl,
                    take_profit=tp,
                    size=self._calculate_position_size(),
                    reason=f"Trend Short: EMA bearish",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = TradeDirection.SHORT
                self.entry_price = current_open

        # 持仓时出场
        else:
            # EMA交叉平仓
            if self.current_position == TradeDirection.LONG and ema_fast < ema_slow:
                signal = TradeSignal(
                    timestamp=timestamp,
                    signal_type=SignalType.CLOSE_LONG,
                    strategy_id=self.strategy_id,
                    direction=TradeDirection.FLAT,
                    entry_price=current_open,
                    reason="Trend exit: EMA cross",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = None
            elif self.current_position == TradeDirection.SHORT and ema_fast > ema_slow:
                signal = TradeSignal(
                    timestamp=timestamp,
                    signal_type=SignalType.CLOSE_SHORT,
                    strategy_id=self.strategy_id,
                    direction=TradeDirection.FLAT,
                    entry_price=current_open,
                    reason="Trend exit: EMA cross",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = None

        return signal

    def _generate_range_signal(self, df, current_idx, prev_bar, current_open, atr, timestamp):
        """均值回归信号"""
        bb_upper = prev_bar.get('BB_Upper', 0)
        bb_lower = prev_bar.get('BB_Lower', 0)
        bb_middle = prev_bar.get('BB_Middle', 0)
        rsi = prev_bar.get('RSI', 50)
        close = prev_bar['Close']

        if pd.isna(bb_upper) or pd.isna(bb_lower) or pd.isna(rsi):
            return None

        sl_mult = self.params['range_sl_atr']
        tp_mult = self.params['range_tp_atr']
        rsi_lower = self.params['rsi_oversold']
        rsi_upper = self.params['rsi_overbought']

        signal = None

        # 无持仓时入场
        if self.current_position is None:
            # 超卖做多
            if close <= bb_lower and rsi < rsi_lower:
                sl = current_open - sl_mult * atr
                tp = current_open + tp_mult * atr
                signal = TradeSignal(
                    timestamp=timestamp,
                    signal_type=SignalType.LONG,
                    strategy_id=self.strategy_id,
                    direction=TradeDirection.LONG,
                    entry_price=current_open,
                    stop_loss=sl,
                    take_profit=tp,
                    size=self._calculate_position_size(),
                    reason=f"Range Long: BB lower, RSI={rsi:.0f}",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = TradeDirection.LONG
                self.entry_price = current_open

            # 超买卖空
            elif close >= bb_upper and rsi > rsi_upper:
                sl = current_open + sl_mult * atr
                tp = current_open - tp_mult * atr
                signal = TradeSignal(
                    timestamp=timestamp,
                    signal_type=SignalType.SHORT,
                    strategy_id=self.strategy_id,
                    direction=TradeDirection.SHORT,
                    entry_price=current_open,
                    stop_loss=sl,
                    take_profit=tp,
                    size=self._calculate_position_size(),
                    reason=f"Range Short: BB upper, RSI={rsi:.0f}",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = TradeDirection.SHORT
                self.entry_price = current_open

        # 持仓时出场
        else:
            # 回到中轨平仓
            if self.current_position == TradeDirection.LONG and close >= bb_middle:
                signal = TradeSignal(
                    timestamp=timestamp,
                    signal_type=SignalType.CLOSE_LONG,
                    strategy_id=self.strategy_id,
                    direction=TradeDirection.FLAT,
                    entry_price=current_open,
                    reason="Range exit: back to middle",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = None
            elif self.current_position == TradeDirection.SHORT and close <= bb_middle:
                signal = TradeSignal(
                    timestamp=timestamp,
                    signal_type=SignalType.CLOSE_SHORT,
                    strategy_id=self.strategy_id,
                    direction=TradeDirection.FLAT,
                    entry_price=current_open,
                    reason="Range exit: back to middle",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = None

        return signal

    def generate_signal(self, df: pd.DataFrame, current_idx: int, **kwargs) -> Optional[TradeSignal]:
        min_bars = 150  # 需要足够数据检测市场状态
        if current_idx < min_bars:
            return None

        prev_bar = df.iloc[current_idx - 1]
        current_bar = df.iloc[current_idx]
        timestamp = df.index[current_idx]
        current_open = current_bar['Open']

        # ATR
        atr = prev_bar.get('ATR', 0)
        if pd.isna(atr) or atr <= 0:
            return None

        # 检测市场状态
        self.market_state = self._detect_market_state(df, current_idx)

        # 根据市场状态选择策略
        if self.market_state == 'trending':
            return self._generate_trend_signal(df, current_idx, prev_bar, current_open, atr, timestamp)
        else:
            return self._generate_range_signal(df, current_idx, prev_bar, current_open, atr, timestamp)

    def reset(self):
        super().reset()
        self.current_position = None
        self.entry_price = None
        self.market_state = "neutral"
        self.martingale_step = 0
        self.consecutive_losses = 0


def calculate_smart_indicators(
    df: pd.DataFrame,
    ema_fast: int = 20,
    ema_slow: int = 50,
    ema_trend: int = 100,
    bb_period: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
    atr_period: int = 14,
    adx_period: int = 14
) -> pd.DataFrame:
    """计算智能策略所需指标"""
    result = df.copy()

    # EMA
    result['EMA_fast'] = calculate_sma(result['Close'], ema_fast)
    result['EMA_slow'] = calculate_sma(result['Close'], ema_slow)
    result['EMA_trend'] = calculate_sma(result['Close'], ema_trend)

    # BB
    upper, middle, lower = calculate_bollinger_bands(result['Close'], bb_period, bb_std)
    result['BB_Upper'] = upper
    result['BB_Middle'] = middle
    result['BB_Lower'] = lower

    # RSI
    result['RSI'] = calculate_rsi(result['Close'], rsi_period)

    # ATR
    result['ATR'] = calculate_atr(result, atr_period)

    # ADX
    adx, plus_di, minus_di = calculate_adx(result, adx_period)
    result['ADX'] = adx

    return result
