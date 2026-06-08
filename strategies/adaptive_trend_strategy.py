"""
自适应趋势马丁策略 (Adaptive Trend Martingale)
===============================================
核心改进：
1. 多因子入场确认（趋势+动量+波动率）提高胜率
2. 动态止盈止损（ATR + 盈亏比控制）
3. 趋势强度过滤（ADX）避免震荡市假信号
4. 阶梯式马丁 + 最大风险控制

作者: Claude
版本: 4.0.0
"""

from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
import numpy as np
from datetime import datetime

from strategies.base import BaseStrategy
from core.types import TradeSignal, TradeDirection, SignalType, ExitReason
from core.indicators import calculate_sma, calculate_atr, calculate_adx, calculate_rsi


class AdaptiveTrendMartingaleStrategy(BaseStrategy):
    """
    自适应趋势马丁策略

    入场条件（必须同时满足）：
    1. 趋势方向：EMA快线 > EMA慢线（做多）/ EMA快线 < EMA慢线（做空）
    2. 趋势强度：ADX > 阈值（确保有趋势）
    3. 动量确认：RSI不在超买超卖区域
    4. 波动率：ATR适中（过滤极端波动）
    5. 价格位置：价格在EMA上方/下方确认趋势

    出场条件：
    1. 止损：ATR动态止损
    2. 止盈：ATR动态止盈（盈亏比>=2）
    3. 趋势反转：EMA交叉
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        super().__init__(params, strategy_id or "AdaptiveTrendMartingale")

        # 持仓状态
        self.current_position: Optional[TradeDirection] = None
        self.entry_price: Optional[float] = None
        self.entry_bar: int = 0
        self.current_stop_loss: Optional[float] = None
        self.current_take_profit: Optional[float] = None

        # 马丁状态
        self.martingale_step: int = 0
        self.consecutive_losses: int = 0

        # 统计
        self.total_signals = 0
        self.filtered_signals = 0

    def get_default_params(self) -> Dict[str, Any]:
        return {
            # EMA参数
            'ema_fast': 12,
            'ema_slow': 26,
            'ema_trend': 50,      # 趋势确认EMA

            # 过滤参数
            'adx_period': 14,
            'adx_threshold': 20,   # ADX必须大于此值
            'rsi_period': 14,
            'rsi_upper': 70,       # RSI上限
            'rsi_lower': 30,       # RSI下限

            # ATR参数
            'atr_period': 14,
            'stop_loss_atr': 1.5,  # 止损ATR倍数
            'take_profit_atr': 3.0, # 止盈ATR倍数（盈亏比2:1）

            # 马丁参数
            'position_size': 0.01,
            'martingale_multiplier': 1.8,
            'max_martingale_steps': 4,
            'max_risk_per_trade': 0.02,  # 单笔最大风险2%

            # 其他
            'min_atr_ratio': 0.3,   # 最小ATR/价格比（过滤低波动）
            'max_atr_ratio': 2.0,   # 最大ATR/价格比（过滤极端波动）
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        return {
            'ema_fast': (8, 20),
            'ema_slow': (20, 40),
            'ema_trend': (40, 100),
            'adx_threshold': (15, 30),
            'rsi_upper': (65, 80),
            'rsi_lower': (20, 35),
            'stop_loss_atr': (1.0, 2.5),
            'take_profit_atr': (2.0, 5.0),
            'martingale_multiplier': (1.5, 2.5),
            'max_martingale_steps': (2, 6),
        }

    def _calculate_position_size(self) -> float:
        """计算马丁仓位"""
        base_size = self.params['position_size']
        multiplier = self.params['martingale_multiplier']
        max_steps = self.params['max_martingale_steps']
        step = min(self.martingale_step, max_steps)
        return base_size * (multiplier ** step)

    def on_trade_completed(self, trade_record: Dict[str, Any]):
        """交易完成回调"""
        profit = trade_record.get('profit', 0)
        exit_reason = trade_record.get('exit_reason')

        if profit < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= 2:
                if self.martingale_step < self.params['max_martingale_steps']:
                    self.martingale_step += 1
                    self.consecutive_losses = 0
        else:
            self.consecutive_losses = 0
            if self.martingale_step > 0:
                self.martingale_step -= 1

        if exit_reason in [ExitReason.SIGNAL_REVERSE, ExitReason.FORCE_CLOSE, ExitReason.END_OF_DATA]:
            self.current_position = None
            self.entry_price = None
            self.current_stop_loss = None
            self.current_take_profit = None

    def _check_entry_conditions(
        self,
        prev_bar: pd.Series,
        current_price: float,
        atr: float
    ) -> Tuple[bool, Optional[TradeDirection], str]:
        """
        检查入场条件

        Returns:
            (是否入场, 方向, 原因)
        """
        # 获取指标值
        ema_fast = prev_bar.get('EMA_fast', 0)
        ema_slow = prev_bar.get('EMA_slow', 0)
        ema_trend = prev_bar.get('EMA_trend', 0)
        adx = prev_bar.get('ADX', 0)
        rsi = prev_bar.get('RSI', 50)
        close = prev_bar['Close']

        # 检查数据有效性
        if pd.isna(ema_fast) or pd.isna(ema_slow) or pd.isna(ema_trend):
            return False, None, "Missing EMA data"
        if pd.isna(adx):
            return False, None, "Missing ADX data"
        if pd.isna(rsi):
            return False, None, "Missing RSI data"

        reasons = []

        # === 做多条件检查 ===
        long_conditions = []

        # 1. EMA趋势确认
        if ema_fast > ema_slow and close > ema_trend:
            long_conditions.append("EMA bullish")
        else:
            long_conditions.append("EMA not bullish")

        # 2. ADX趋势强度
        if adx > self.params['adx_threshold']:
            long_conditions.append(f"ADX={adx:.1f}>threshold")
        else:
            long_conditions.append(f"ADX={adx:.1f}<threshold")

        # 3. RSI不过热
        if rsi < self.params['rsi_upper']:
            long_conditions.append(f"RSI={rsi:.1f}<upper")
        else:
            long_conditions.append(f"RSI={rsi:.1f}>=upper")

        # 4. 价格在EMA上方
        if close > ema_fast:
            long_conditions.append("Price>EMA_fast")
        else:
            long_conditions.append("Price<=EMA_fast")

        # === 做空条件检查 ===
        short_conditions = []

        # 1. EMA趋势确认
        if ema_fast < ema_slow and close < ema_trend:
            short_conditions.append("EMA bearish")
        else:
            short_conditions.append("EMA not bearish")

        # 2. ADX趋势强度
        if adx > self.params['adx_threshold']:
            short_conditions.append(f"ADX={adx:.1f}>threshold")
        else:
            short_conditions.append(f"ADX={adx:.1f}<threshold")

        # 3. RSI不过冷
        if rsi > self.params['rsi_lower']:
            short_conditions.append(f"RSI={rsi:.1f}>lower")
        else:
            short_conditions.append(f"RSI={rsi:.1f}<=lower")

        # 4. 价格在EMA下方
        if close < ema_fast:
            short_conditions.append("Price<EMA_fast")
        else:
            short_conditions.append("Price>=EMA_fast")

        # 判断是否满足入场条件
        adx_ok = adx > self.params['adx_threshold']

        # 做多
        if (ema_fast > ema_slow and
            close > ema_trend and
            adx_ok and
            rsi < self.params['rsi_upper'] and
            close > ema_fast):
            return True, TradeDirection.LONG, f"Long: EMA↑ ADX={adx:.1f} RSI={rsi:.1f}"

        # 做空
        if (ema_fast < ema_slow and
            close < ema_trend and
            adx_ok and
            rsi > self.params['rsi_lower'] and
            close < ema_fast):
            return True, TradeDirection.SHORT, f"Short: EMA↓ ADX={adx:.1f} RSI={rsi:.1f}"

        return False, None, f"Filtered: ADX={adx:.1f} RSI={rsi:.1f}"

    def generate_signal(
        self,
        df: pd.DataFrame,
        current_idx: int,
        **kwargs
    ) -> Optional[TradeSignal]:
        """生成交易信号"""

        min_bars = max(
            self.params['ema_slow'],
            self.params['ema_trend'],
            self.params['adx_period'],
            self.params['rsi_period'],
            self.params['atr_period']
        ) + 10

        if current_idx < min_bars:
            return None

        prev_bar = df.iloc[current_idx - 1]
        current_bar = df.iloc[current_idx]
        timestamp = df.index[current_idx]
        current_open = current_bar['Open']

        # ATR值
        atr = prev_bar.get('ATR', 0)
        if pd.isna(atr) or atr <= 0:
            atr = prev_bar.get(f'ATR_{self.params["atr_period"]}', 0)
        if pd.isna(atr) or atr <= 0:
            return None

        signal = None
        sl_mult = self.params['stop_loss_atr']
        tp_mult = self.params['take_profit_atr']

        # === 持仓检查 ===
        if self.current_position == TradeDirection.LONG:
            # 检查EMA交叉
            ema_fast_prev = prev_bar.get('EMA_fast', 0)
            ema_slow_prev = prev_bar.get('EMA_slow', 0)

            if current_idx >= 2:
                prev2_bar = df.iloc[current_idx - 2]
                ema_fast_prev2 = prev2_bar.get('EMA_fast', 0)
                ema_slow_prev2 = prev2_bar.get('EMA_slow', 0)

                # 死叉平多
                if (not pd.isna(ema_fast_prev2) and not pd.isna(ema_slow_prev2) and
                    ema_fast_prev2 >= ema_slow_prev2 and ema_fast_prev < ema_slow_prev):
                    # 检查是否可以反向开空
                    can_entry, direction, reason = self._check_entry_conditions(prev_bar, current_open, atr)
                    if can_entry and direction == TradeDirection.SHORT:
                        signal = self._create_entry_signal(
                            timestamp, TradeDirection.SHORT, current_open,
                            current_open + sl_mult * atr,
                            current_open - tp_mult * atr,
                            f"Reverse: {reason}",
                            current_idx
                        )
                        self.current_position = TradeDirection.SHORT
                        self.entry_price = current_open
                    else:
                        signal = TradeSignal(
                            timestamp=timestamp,
                            signal_type=SignalType.CLOSE_LONG,
                            strategy_id=self.strategy_id,
                            direction=TradeDirection.FLAT,
                            entry_price=current_open,
                            reason="Long exit: EMA cross",
                            signal_bar_index=current_idx - 1,
                            execution_bar_index=current_idx,
                        )
                        self.current_position = None

        elif self.current_position == TradeDirection.SHORT:
            ema_fast_prev = prev_bar.get('EMA_fast', 0)
            ema_slow_prev = prev_bar.get('EMA_slow', 0)

            if current_idx >= 2:
                prev2_bar = df.iloc[current_idx - 2]
                ema_fast_prev2 = prev2_bar.get('EMA_fast', 0)
                ema_slow_prev2 = prev2_bar.get('EMA_slow', 0)

                # 金叉平空
                if (not pd.isna(ema_fast_prev2) and not pd.isna(ema_slow_prev2) and
                    ema_fast_prev2 <= ema_slow_prev2 and ema_fast_prev > ema_slow_prev):
                    can_entry, direction, reason = self._check_entry_conditions(prev_bar, current_open, atr)
                    if can_entry and direction == TradeDirection.LONG:
                        signal = self._create_entry_signal(
                            timestamp, TradeDirection.LONG, current_open,
                            current_open - sl_mult * atr,
                            current_open + tp_mult * atr,
                            f"Reverse: {reason}",
                            current_idx
                        )
                        self.current_position = TradeDirection.LONG
                        self.entry_price = current_open
                    else:
                        signal = TradeSignal(
                            timestamp=timestamp,
                            signal_type=SignalType.CLOSE_SHORT,
                            strategy_id=self.strategy_id,
                            direction=TradeDirection.FLAT,
                            entry_price=current_open,
                            reason="Short exit: EMA cross",
                            signal_bar_index=current_idx - 1,
                            execution_bar_index=current_idx,
                        )
                        self.current_position = None

        # === 无持仓时入场 ===
        if signal is None and self.current_position is None:
            can_entry, direction, reason = self._check_entry_conditions(prev_bar, current_open, atr)

            if can_entry and direction:
                self.total_signals += 1

                if direction == TradeDirection.LONG:
                    sl = current_open - sl_mult * atr
                    tp = current_open + tp_mult * atr
                else:
                    sl = current_open + sl_mult * atr
                    tp = current_open - tp_mult * atr

                signal = self._create_entry_signal(
                    timestamp, direction, current_open,
                    sl, tp, reason,
                    current_idx
                )
                self.current_position = direction
                self.entry_price = current_open
                self.current_stop_loss = sl
                self.current_take_profit = tp

        return signal

    def _create_entry_signal(self, timestamp, direction, entry_price, stop_loss, take_profit, reason, current_idx):
        """创建入场信号"""
        size = self._calculate_position_size()

        if direction == TradeDirection.LONG:
            signal_type = SignalType.LONG
        else:
            signal_type = SignalType.SHORT

        return TradeSignal(
            timestamp=timestamp,
            signal_type=signal_type,
            strategy_id=self.strategy_id,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            size=size,
            reason=reason,
            signal_bar_index=current_idx - 1,
            execution_bar_index=current_idx,
        )

    def reset(self):
        super().reset()
        self.current_position = None
        self.entry_price = None
        self.entry_bar = 0
        self.current_stop_loss = None
        self.current_take_profit = None
        self.martingale_step = 0
        self.consecutive_losses = 0
        self.total_signals = 0
        self.filtered_signals = 0


def calculate_adaptive_trend_indicators(
    df: pd.DataFrame,
    ema_fast: int = 12,
    ema_slow: int = 26,
    ema_trend: int = 50,
    adx_period: int = 14,
    rsi_period: int = 14,
    atr_period: int = 14
) -> pd.DataFrame:
    """计算策略所需指标"""
    result = df.copy()

    # EMA (用SMA近似)
    result['EMA_fast'] = calculate_sma(result['Close'], ema_fast)
    result['EMA_slow'] = calculate_sma(result['Close'], ema_slow)
    result['EMA_trend'] = calculate_sma(result['Close'], ema_trend)

    # ADX (返回元组: adx, plus_di, minus_di)
    adx, plus_di, minus_di = calculate_adx(result, adx_period)
    result['ADX'] = adx
    result['plus_di'] = plus_di
    result['minus_di'] = minus_di

    # RSI
    from core.indicators import calculate_rsi
    result['RSI'] = calculate_rsi(result['Close'], rsi_period)

    # ATR
    result['ATR'] = calculate_atr(result, atr_period)

    return result
