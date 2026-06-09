"""
均值回归马丁策略 (Mean Reversion Martingale)
============================================
核心逻辑：
1. 当价格偏离均值过大时入场（买低卖高）
2. 使用BB和RSI确认超买超卖
3. ATR止损保护
4. 阶梯式马丁

适合震荡市场，在趋势市场表现可能不佳

作者: Claude
版本: 5.0.0
"""

from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
import numpy as np
from datetime import datetime

from strategies.base import BaseStrategy
from core.types import TradeSignal, TradeDirection, SignalType, ExitReason
from core.indicators import (
    calculate_sma,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_rsi,
)


class MeanReversionMartingaleStrategy(BaseStrategy):
    """
    均值回归马丁策略

    入场条件（做多）：
    1. 价格触及下布林带或以下
    2. RSI < 超卖阈值
    3. 价格开始回升确认

    入场条件（做空）：
    1. 价格触及上布林带或以上
    2. RSI > 超买阈值
    3. 价格开始回落确认

    出场：
    1. 价格回到中轨
    2. 止损
    3. 止盈
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        super().__init__(params, strategy_id or "MeanReversionMartingale")

        self.current_position: Optional[TradeDirection] = None
        self.entry_price: Optional[float] = None
        self.martingale_step: int = 0
        self.consecutive_losses: int = 0

    def get_default_params(self) -> Dict[str, Any]:
        return {
            # 布林带参数
            "bb_period": 20,
            "bb_std": 2.0,
            # RSI参数
            "rsi_period": 14,
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            # 止损止盈
            "atr_period": 14,
            "stop_loss_atr": 2.0,
            "take_profit_atr": 3.0,
            # 马丁参数
            "position_size": 0.01,
            "martingale_multiplier": 1.5,
            "max_martingale_steps": 5,
            # 确认K线数
            "confirmation_bars": 1,
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        return {
            "bb_period": (15, 30),
            "bb_std": (1.5, 2.5),
            "rsi_oversold": (20, 35),
            "rsi_overbought": (65, 80),
            "stop_loss_atr": (1.5, 3.0),
            "take_profit_atr": (2.0, 5.0),
            "martingale_multiplier": (1.3, 2.0),
            "max_martingale_steps": (3, 7),
        }

    def _calculate_position_size(self) -> float:
        base = self.params["position_size"]
        mult = self.params["martingale_multiplier"]
        max_steps = self.params["max_martingale_steps"]
        step = min(self.martingale_step, max_steps)
        return base * (mult**step)

    def on_trade_completed(self, trade_record: Dict[str, Any]):
        profit = trade_record.get("profit", 0)
        exit_reason = trade_record.get("exit_reason")

        if profit < 0:
            self.consecutive_losses += 1
            if (
                self.consecutive_losses >= 2
                and self.martingale_step < self.params["max_martingale_steps"]
            ):
                self.martingale_step += 1
                self.consecutive_losses = 0
        else:
            self.consecutive_losses = 0
            if self.martingale_step > 0:
                self.martingale_step -= 1

        if exit_reason in [
            ExitReason.SIGNAL_REVERSE,
            ExitReason.FORCE_CLOSE,
            ExitReason.END_OF_DATA,
        ]:
            self.current_position = None
            self.entry_price = None

    def generate_signal(
        self, df: pd.DataFrame, current_idx: int, **kwargs
    ) -> Optional[TradeSignal]:
        min_bars = (
            max(
                self.params["bb_period"],
                self.params["rsi_period"],
                self.params["atr_period"],
            )
            + 10
        )
        if current_idx < min_bars:
            return None

        prev_bar = df.iloc[current_idx - 1]
        current_bar = df.iloc[current_idx]
        timestamp = df.index[current_idx]
        current_open = current_bar["Open"]

        # 获取指标
        bb_upper = prev_bar.get("BB_Upper", 0)
        bb_lower = prev_bar.get("BB_Lower", 0)
        bb_middle = prev_bar.get("BB_Middle", 0)
        rsi = prev_bar.get("RSI", 50)
        close = prev_bar["Close"]
        atr = prev_bar.get("ATR", 0)

        if (
            pd.isna(bb_upper)
            or pd.isna(bb_lower)
            or pd.isna(rsi)
            or pd.isna(atr)
            or atr <= 0
        ):
            return None

        signal = None
        sl_mult = self.params["stop_loss_atr"]
        tp_mult = self.params["take_profit_atr"]
        rsi_lower = self.params["rsi_oversold"]
        rsi_upper = self.params["rsi_overbought"]

        # === 无持仓时入场 ===
        if self.current_position is None:
            # 做多条件：价格触及下轨 + RSI超卖
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
                    reason=f"Long: Price<{bb_lower:.1f}, RSI={rsi:.1f}",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = TradeDirection.LONG
                self.entry_price = current_open

            # 做空条件：价格触及上轨 + RSI超买
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
                    reason=f"Short: Price>{bb_upper:.1f}, RSI={rsi:.1f}",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = TradeDirection.SHORT
                self.entry_price = current_open

        # === 有持仓时出场 ===
        else:
            # 价格回到中轨附近，平仓
            if self.current_position == TradeDirection.LONG:
                if close >= bb_middle:
                    signal = TradeSignal(
                        timestamp=timestamp,
                        signal_type=SignalType.CLOSE_LONG,
                        strategy_id=self.strategy_id,
                        direction=TradeDirection.FLAT,
                        entry_price=current_open,
                        reason=f"Long exit: Price back to middle BB",
                        signal_bar_index=current_idx - 1,
                        execution_bar_index=current_idx,
                    )
                    self.current_position = None

            elif self.current_position == TradeDirection.SHORT:
                if close <= bb_middle:
                    signal = TradeSignal(
                        timestamp=timestamp,
                        signal_type=SignalType.CLOSE_SHORT,
                        strategy_id=self.strategy_id,
                        direction=TradeDirection.FLAT,
                        entry_price=current_open,
                        reason=f"Short exit: Price back to middle BB",
                        signal_bar_index=current_idx - 1,
                        execution_bar_index=current_idx,
                    )
                    self.current_position = None

        return signal

    def reset(self):
        super().reset()
        self.current_position = None
        self.entry_price = None
        self.martingale_step = 0
        self.consecutive_losses = 0


def calculate_mean_reversion_indicators(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
    atr_period: int = 14,
) -> pd.DataFrame:
    """计算均值回归策略所需指标"""
    result = df.copy()

    # BB
    upper, middle, lower = calculate_bollinger_bands(result["Close"], bb_period, bb_std)
    result["BB_Upper"] = upper
    result["BB_Middle"] = middle
    result["BB_Lower"] = lower

    # RSI
    result["RSI"] = calculate_rsi(result["Close"], rsi_period)

    # ATR
    result["ATR"] = calculate_atr(result, atr_period)

    return result
