"""
动量突破策略（策略B）
======================
基于EMA和布林带突破的动量策略

核心逻辑：
1. 适用于欧美盘时段（北京时间15:00-次日2:00）
2. 布林带挤压后突破 + EMA多头排列 = 做多
3. 布林带挤压后突破 + EMA空头排列 = 做空
4. 追踪止损 + 动态止盈
"""

from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

from .base import BaseStrategy
from core.types import TradeSignal, TradeDirection


class MomentumBreakoutStrategy(BaseStrategy):
    """
    动量突破策略

    适用市场：趋势市场，欧美盘时段
    核心指标：EMA、布林带、布林带挤压
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = "MomentumBreakout"):
        super().__init__(params, strategy_id)

        # 提取常用参数
        self.ema_fast = self.params.get('ema_fast', 20)
        self.ema_slow = self.params.get('ema_slow', 50)
        self.stop_loss_mult = self.params.get('stop_loss_atr_mult_b', 1.2)
        self.trailing_mult = self.params.get('trailing_stop_atr_mult', 2.5)
        self.use_trailing_stop = self.params.get('use_trailing_stop', True)
        self.entry_mode = self.params.get('strategy_b_mode', 0)  # 0=自动, 1=强制回踩

        # 状态追踪
        self.pending_signal = None
        self.breakout_bar_idx = None

    def get_default_params(self) -> Dict[str, Any]:
        """获取默认参数"""
        return {
            'ema_fast': 20,
            'ema_slow': 50,
            'bb_period': 20,
            'bb_std': 2.0,
            'kc_period': 20,
            'kc_atr_mult': 1.5,
            'atr_period': 14,
            'stop_loss_atr_mult_b': 1.2,
            'trailing_stop_atr_mult': 2.5,
            'squeeze_threshold': 0.8,
            'pullback_confirmation_bars': 2,
            'ema_momentum_threshold': 0.0005,
            'strategy_b_mode': 0,  # 0=自动, 1=强制回踩
            'use_trailing_stop': True,
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        """获取参数优化范围"""
        return {
            'ema_fast': (10, 30),
            'ema_slow': (35, 70),
            'stop_loss_atr_mult_b': (0.8, 2.0),
            'trailing_stop_atr_mult': (2.0, 4.0),
            'squeeze_threshold': (0.5, 1.0),
            'pullback_confirmation_bars': (1, 4),
            'ema_momentum_threshold': (0.0003, 0.001),
            'strategy_b_mode': (0, 1),
        }

    def reset(self):
        """重置策略状态"""
        super().reset()
        self.pending_signal = None
        self.breakout_bar_idx = None

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

        Returns:
            TradeSignal或None
        """
        if current_idx < max(self.ema_slow, 50):
            return None

        # 获取当前K线数据
        current_bar = df.iloc[current_idx]
        timestamp = df.index[current_idx]

        # 检查是否为欧美盘时段
        if not self._is_european_session(timestamp):
            return None

        # 获取价格数据
        close = current_bar['Close']
        high = current_bar['High']
        low = current_bar['Low']
        atr = current_bar.get('ATR', 0)
        bb_upper = current_bar.get('BB_Upper', close)
        bb_lower = current_bar.get('BB_Lower', close)
        squeeze_on = current_bar.get('Squeeze_On', False)

        # EMA
        ema_fast_val = current_bar.get(f'EMA_{self.ema_fast}', close)
        ema_slow_val = current_bar.get(f'EMA_{self.ema_slow}', close)

        # 前一根K线数据
        prev_bar = df.iloc[current_idx - 1]
        prev_close = prev_bar['Close']
        prev_high = prev_bar['High']
        prev_low = prev_bar['Low']
        prev_bb_upper = prev_bar.get('BB_Upper', prev_close)
        prev_bb_lower = prev_bar.get('BB_Lower', prev_close)

        # EMA趋势判断
        ema_bullish = ema_fast_val > ema_slow_val * (1 + self.params.get('ema_momentum_threshold', 0.0005))
        ema_bearish = ema_fast_val < ema_slow_val * (1 - self.params.get('ema_momentum_threshold', 0.0005))

        # ========== 做多信号 ==========
        # 条件：向上突破布林带 + EMA多头排列
        if prev_close <= prev_bb_upper and close > bb_upper and ema_bullish:
            # 检查是否有挤压（可选过滤）
            direction = TradeDirection.LONG
            stop_loss = close - atr * self.stop_loss_mult
            take_profit = close + abs(close - stop_loss) * 2.5

            return self._create_signal(
                timestamp=timestamp,
                direction=direction,
                entry_price=close,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason="MomentumBreakout_Long: BB_Breakout+EMA_Bullish",
                signal_bar_idx=current_idx,
                execution_bar_idx=current_idx + 1,
                use_trailing=self.use_trailing_stop,
                trailing_mult=self.trailing_mult
            )

        # ========== 做空信号 ==========
        # 条件：向下突破布林带 + EMA空头排列
        if prev_close >= prev_bb_lower and close < bb_lower and ema_bearish:
            direction = TradeDirection.SHORT
            stop_loss = close + atr * self.stop_loss_mult
            take_profit = close - abs(close - stop_loss) * 2.5

            return self._create_signal(
                timestamp=timestamp,
                direction=direction,
                entry_price=close,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason="MomentumBreakout_Short: BB_Breakdown+EMA_Bearish",
                signal_bar_idx=current_idx,
                execution_bar_idx=current_idx + 1,
                use_trailing=self.use_trailing_stop,
                trailing_mult=self.trailing_mult
            )

        return None

    def _is_european_session(self, timestamp) -> bool:
        """检查是否为欧美盘时段（北京时间15:00-次日2:00）"""
        hour = timestamp.hour
        return hour >= 15 or hour < 2
