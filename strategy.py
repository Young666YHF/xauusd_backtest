"""
双策略交易模块
==============
策略A: 均值回归 (亚盘时段) - RSI + BB
策略B: 动量突破 (欧美盘时段) - EMA + BB突破
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from indicators import (
    calculate_rsi, calculate_bollinger_bands, calculate_atr,
    calculate_ema, calculate_session_filter, calculate_keltner_channels
)


class SignalType(Enum):
    """信号类型"""
    NONE = 0
    LONG = 1
    SHORT = 2
    EXIT_LONG = 3
    EXIT_SHORT = 4


@dataclass
class TradeSignal:
    """交易信号"""
    signal_type: SignalType
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy: str = ""  # 'A' 或 'B'
    timestamp: Optional[pd.Timestamp] = None
    execution_bar_index: int = 0
    reason: str = ""


@dataclass
class PendingSignal:
    """挂单信号"""
    signal_type: SignalType
    trigger_price: float  # 触发价格
    direction: int  # 1=做多, -1=做空
    stop_loss: float
    take_profit: Optional[float]
    strategy: str
    created_time: pd.Timestamp
    expire_bars: int = 5  # 过期K线数
    bars_elapsed: int = 0


@dataclass
class StrategyState:
    """策略状态"""
    has_position: bool = False
    position_direction: int = 0  # 1=多, -1=空
    entry_price: float = 0.0
    entry_time: Optional[pd.Timestamp] = None
    stop_loss: float = 0.0
    trailing_stop: float = 0.0
    highest_price: float = 0.0
    lowest_price: float = float('inf')
    bars_held: int = 0
    current_strategy: str = ""
    entry_atr: float = 0.0  # 入场时的ATR


class TradingStrategy:
    """
    双策略交易系统

    策略A (均值回归):
    - 适用时段: 亚盘 (北京时间 06:00-14:00)
    - 入场条件: RSI超卖 + 价格触及BB下轨
    - 止损: min(close, bb_lower) - stop_loss_mult * atr

    策略B (动量突破):
    - 适用时段: 欧美盘 (北京时间 15:00-次日00:00)
    - 入场条件: EMA金叉 + BB突破 + 价格行为确认
    - 追踪止损: 使用当前ATR (非入场ATR)
    """

    def __init__(self, params: Optional[Dict] = None):
        """
        初始化策略

        Args:
            params: 策略参数字典
        """
        self.params = params or {}
        self.state = StrategyState()

        # 默认参数
        self.bb_period = self.params.get('bb_period', 20)
        self.bb_std = self.params.get('bb_std', 2.5)
        self.kc_period = self.params.get('kc_period', 20)
        self.kc_atr_mult = self.params.get('kc_atr_mult', 1.5)
        self.atr_period = self.params.get('atr_period', 14)
        self.rsi_period = self.params.get('rsi_period', 14)
        self.rsi_oversold = self.params.get('rsi_oversold', 30)
        self.rsi_overbought = self.params.get('rsi_overbought', 70)

        # 策略A参数
        self.stop_loss_atr_mult_a = self.params.get('stop_loss_atr_mult_a', 1.5)
        self.max_hold_bars_a = self.params.get('max_hold_bars_a', 6)

        # 策略B参数
        self.ema_fast = self.params.get('ema_fast', 20)
        self.ema_slow = self.params.get('ema_slow', 50)
        self.stop_loss_atr_mult_b = self.params.get('stop_loss_atr_mult_b', 2.0)
        self.trailing_stop_atr_mult = self.params.get('trailing_stop_atr_mult', 3.0)

        # 过滤器参数
        self.squeeze_threshold = self.params.get('squeeze_threshold', 0.8)

        # Module 1: ATR自适应时间止损
        self.atr_time_stop_base = self.params.get('atr_time_stop_base', 5.0)
        self.atr_time_stop_mult = self.params.get('atr_time_stop_mult', 0.5)

        # Module 2: 异常波动过滤
        self.volatility_filter_period = self.params.get('volatility_filter_period', 17)
        self.volatility_filter_mult = self.params.get('volatility_filter_mult', 1.5)

        # Module 2: 假突破过滤
        self.pullback_confirmation_bars = self.params.get('pullback_confirmation_bars', 3)
        self.ema_momentum_threshold = self.params.get('ema_momentum_threshold', 0.0005)

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算所有技术指标

        Args:
            df: OHLCV数据

        Returns:
            带指标的数据
        """
        df = df.copy()

        # 布林带
        bb_middle, bb_upper, bb_lower, bb_bandwidth = calculate_bollinger_bands(
            df['Close'], period=self.bb_period, std_dev=self.bb_std
        )
        df['BB_Middle'] = bb_middle
        df['BB_Upper'] = bb_upper
        df['BB_Lower'] = bb_lower
        df['BB_Width'] = bb_bandwidth

        # 肯特纳通道
        kc_middle, kc_upper, kc_lower, kc_bandwidth = calculate_keltner_channels(
            df['High'], df['Low'], df['Close'],
            period=self.kc_period, atr_mult=self.kc_atr_mult
        )
        df['KC_Middle'] = kc_middle
        df['KC_Upper'] = kc_upper
        df['KC_Lower'] = kc_lower

        # ATR
        df['ATR'] = calculate_atr(
            df['High'], df['Low'], df['Close'], period=self.atr_period
        )

        # RSI
        df['RSI'] = calculate_rsi(df['Close'], period=self.rsi_period)

        # EMA
        df['EMA_Fast'] = calculate_ema(df['Close'], period=self.ema_fast)
        df['EMA_Slow'] = calculate_ema(df['Close'], period=self.ema_slow)

        # 交易时段
        is_asian, is_european = calculate_session_filter(df)
        df['Is_Asian'] = is_asian
        df['Is_European'] = is_european

        # 波动率挤压指标
        bb_width = (bb_upper - bb_lower) / bb_middle
        kc_width = (kc_upper - kc_lower) / kc_middle
        df['Squeeze_Ratio'] = bb_width / kc_width

        # EMA动量
        df['EMA_Momentum'] = (df['EMA_Fast'] - df['EMA_Slow']) / df['EMA_Slow']

        # 异常波动过滤
        atr_ma = df['ATR'].rolling(window=self.volatility_filter_period).mean()
        df['Volatility_Filter'] = df['ATR'] > self.volatility_filter_mult * atr_ma

        return df

    def generate_signals(self, df: pd.DataFrame) -> List[TradeSignal]:
        """
        生成所有交易信号

        Args:
            df: OHLCV数据

        Returns:
            信号列表
        """
        df = self.prepare_indicators(df)
        signals = []

        for i in range(max(self.bb_period, self.ema_slow) + 1, len(df)):
            # 策略A信号 (亚盘)
            sig_a = self.generate_strategy_a_signal(df, i)
            if sig_a:
                signals.append(sig_a)

            # 策略B信号 (欧美盘)
            sig_b = self.generate_strategy_b_signal(df, i)
            if sig_b:
                signals.append(sig_b)

        return signals

    def generate_strategy_a_signal(
        self,
        df: pd.DataFrame,
        idx: int
    ) -> Optional[TradeSignal]:
        """
        生成策略A信号 (均值回归 - 亚盘时段)

        入场条件:
        1. 亚盘时段
        2. RSI < 超卖阈值
        3. 价格触及或低于BB下轨

        止损: min(close, bb_lower) - stop_loss_mult * atr
        """
        if idx < self.bb_period + 1:
            return None

        current = df.iloc[idx]
        prev = df.iloc[idx - 1]

        # 检查亚盘时段
        if not current.get('Is_Asian', False):
            return None

        # 检查波动率挤压 - 过低波动时不交易
        squeeze_ratio = current.get('Squeeze_Ratio', 1.0)
        if squeeze_ratio < self.squeeze_threshold:
            return None

        # 异常波动过滤
        if current.get('Volatility_Filter', False):
            return None

        rsi = current['RSI']
        close = current['Close']
        bb_lower = current['BB_Lower']
        atr = current['ATR']

        # 做多条件: RSI超卖 + 价格触及BB下轨
        if rsi < self.rsi_oversold and close <= bb_lower:
            # 计算止损
            # 止损锚定: min(close, bb_lower) - stop_loss_mult * atr
            stop_price = min(close, bb_lower)
            stop_loss = stop_price - self.stop_loss_atr_mult_a * atr

            return TradeSignal(
                signal_type=SignalType.LONG,
                entry_price=close,
                stop_loss=stop_loss,
                strategy='A',
                timestamp=df.index[idx],
                execution_bar_index=idx,
                reason=f'RSI={rsi:.1f} < {self.rsi_oversold}, Close={close:.2f} <= BB_Lower={bb_lower:.2f}'
            )

        # 做空条件: RSI超买 + 价格触及BB上轨
        bb_upper = current['BB_Upper']
        if rsi > self.rsi_overbought and close >= bb_upper:
            # 计算止损
            stop_price = max(close, bb_upper)
            stop_loss = stop_price + self.stop_loss_atr_mult_a * atr

            return TradeSignal(
                signal_type=SignalType.SHORT,
                entry_price=close,
                stop_loss=stop_loss,
                strategy='A',
                timestamp=df.index[idx],
                execution_bar_index=idx,
                reason=f'RSI={rsi:.1f} > {self.rsi_overbought}, Close={close:.2f} >= BB_Upper={bb_upper:.2f}'
            )

        return None

    def generate_strategy_b_signal(
        self,
        df: pd.DataFrame,
        idx: int
    ) -> Optional[TradeSignal]:
        """
        生成策略B信号 (动量突破 - 欧美盘时段)

        入场条件:
        1. 欧美盘时段
        2. EMA金叉/死叉
        3. BB突破
        4. 价格行为确认 (回踩确认)

        追踪止损: 使用当前ATR (非入场ATR)
        """
        if idx < max(self.ema_slow, self.pullback_confirmation_bars) + 1:
            return None

        current = df.iloc[idx]
        prev = df.iloc[idx - 1]

        # 检查欧美盘时段
        if not current.get('Is_European', False):
            return None

        close = current['Close']
        high = current['High']
        low = current['Low']
        atr = current['ATR']
        ema_fast = current['EMA_Fast']
        ema_slow = current['EMA_Slow']
        bb_upper = current['BB_Upper']
        bb_lower = current['BB_Lower']
        ema_momentum = current.get('EMA_Momentum', 0)

        # 检查EMA动量
        if abs(ema_momentum) < self.ema_momentum_threshold:
            return None

        # 价格行为确认: 检查过去N根K线是否有回踩
        def check_pullback_confirmation(direction: int, lookback: int) -> bool:
            """检查价格行为确认"""
            if idx < lookback + 1:
                return False

            recent_highs = df['High'].iloc[idx - lookback:idx].values
            recent_lows = df['Low'].iloc[idx - lookback:idx].values

            if direction == 1:  # 做多
                # 检查是否有回踩到EMA快线附近
                for i in range(lookback):
                    if recent_lows[i] < ema_fast * 1.001:  # 回踩到快线附近
                        return True
            else:  # 做空
                for i in range(lookback):
                    if recent_highs[i] > ema_fast * 0.999:  # 回踩到快线附近
                        return True

            return True  # 默认返回True，不强制要求回踩

        # 做多条件
        if (ema_fast > ema_slow and  # EMA金叉
            close > bb_upper and  # BB突破
            ema_momentum > 0):  # 动量为正

            # 价格行为确认
            if not check_pullback_confirmation(1, self.pullback_confirmation_bars):
                return None

            stop_loss = close - self.stop_loss_atr_mult_b * atr

            return TradeSignal(
                signal_type=SignalType.LONG,
                entry_price=close,
                stop_loss=stop_loss,
                strategy='B',
                timestamp=df.index[idx],
                execution_bar_index=idx,
                reason=f'EMA金叉, Close={close:.2f} > BB_Upper={bb_upper:.2f}'
            )

        # 做空条件
        if (ema_fast < ema_slow and  # EMA死叉
            close < bb_lower and  # BB突破
            ema_momentum < 0):  # 动量为负

            # 价格行为确认
            if not check_pullback_confirmation(-1, self.pullback_confirmation_bars):
                return None

            stop_loss = close + self.stop_loss_atr_mult_b * atr

            return TradeSignal(
                signal_type=SignalType.SHORT,
                entry_price=close,
                stop_loss=stop_loss,
                strategy='B',
                timestamp=df.index[idx],
                execution_bar_index=idx,
                reason=f'EMA死叉, Close={close:.2f} < BB_Lower={bb_lower:.2f}'
            )

        return None

    def check_exit_conditions(
        self,
        position: Dict,
        current_bar: pd.Series,
        bars_held: int,
        df: pd.DataFrame,
        idx: int
    ) -> Tuple[bool, str, Optional[float]]:
        """
        检查出场条件

        Args:
            position: 当前持仓信息
            current_bar: 当前K线数据
            bars_held: 持仓K线数
            df: 完整数据
            idx: 当前索引

        Returns:
            (是否出场, 出场原因, 出场价格)
        """
        direction = position['direction']
        entry_price = position['entry_price']
        stop_loss = position['stop_loss']
        strategy = position['strategy']
        highest_price = position.get('highest_price', entry_price)
        lowest_price = position.get('lowest_price', entry_price)

        high = current_bar['High']
        low = current_bar['Low']
        close = current_bar['Close']
        atr = current_bar['ATR']

        # 策略A出场逻辑
        if strategy == 'A':
            # ATR自适应时间止损
            adaptive_max_bars = int(self.atr_time_stop_base + self.atr_time_stop_mult * atr)

            # 时间止损
            if bars_held >= min(self.max_hold_bars_a, adaptive_max_bars):
                return True, 'time_stop', close

            # 固定止损
            if direction == 1:  # 多头
                if low <= stop_loss:
                    return True, 'stop_loss', stop_loss
            else:  # 空头
                if high >= stop_loss:
                    return True, 'stop_loss', stop_loss

            # RSI反转出场
            rsi = current_bar.get('RSI', 50)
            if direction == 1 and rsi > 50:
                return True, 'rsi_reversal', close
            if direction == -1 and rsi < 50:
                return True, 'rsi_reversal', close

        # 策略B出场逻辑
        elif strategy == 'B':
            # 固定止损
            if direction == 1:  # 多头
                if low <= stop_loss:
                    return True, 'stop_loss', stop_loss

                # 追踪止损 - 使用当前ATR (非入场ATR)
                trailing_stop = highest_price - self.trailing_stop_atr_mult * atr
                if low <= trailing_stop:
                    return True, 'trailing_stop', trailing_stop

            else:  # 空头
                if high >= stop_loss:
                    return True, 'stop_loss', stop_loss

                # 追踪止损 - 使用当前ATR
                trailing_stop = lowest_price + self.trailing_stop_atr_mult * atr
                if high >= trailing_stop:
                    return True, 'trailing_stop', trailing_stop

            # EMA反向交叉出场
            ema_fast = current_bar.get('EMA_Fast', 0)
            ema_slow = current_bar.get('EMA_Slow', 0)
            if direction == 1 and ema_fast < ema_slow:
                return True, 'ema_cross_exit', close
            if direction == -1 and ema_fast > ema_slow:
                return True, 'ema_cross_exit', close

        return False, '', None

    def update_state(self, position: Optional[Dict] = None):
        """
        更新策略状态

        Args:
            position: 当前持仓信息，None表示无持仓
        """
        if position is None:
            self.state = StrategyState()
        else:
            self.state.has_position = True
            self.state.position_direction = position['direction']
            self.state.entry_price = position['entry_price']
            self.state.stop_loss = position['stop_loss']
            self.state.current_strategy = position['strategy']
            self.state.highest_price = position.get('highest_price', position['entry_price'])
            self.state.lowest_price = position.get('lowest_price', position['entry_price'])

    def reset(self):
        """重置策略状态"""
        self.state = StrategyState()
