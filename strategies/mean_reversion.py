"""
均值回归策略（策略A）
======================
基于布林带和RSI的亚盘均值回归策略

核心逻辑：
1. 只在亚盘时段（北京时间6:00-14:00）交易
2. 价格触及布林带下轨 + RSI超卖 = 做多信号
3. 价格触及布林带上轨 + RSI超买 = 做空信号
4. 动态VWAP止盈 + ATR自适应止损
"""

from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

from .base import BaseStrategy
from core.types import TradeSignal, TradeDirection


class MeanReversionStrategy(BaseStrategy):
    """
    均值回归策略

    适用市场：震荡市场，亚盘时段
    核心指标：布林带、RSI、VWAP
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = "MeanReversion"):
        super().__init__(params, strategy_id)

        # 提取常用参数为局部变量以提高性能
        self.rsi_oversold = self.params.get('rsi_oversold', 25)
        self.rsi_overbought = self.params.get('rsi_overbought', 75)
        self.stop_loss_mult = self.params.get('stop_loss_atr_mult_a', 1.0)
        self.max_hold_bars = self.params.get('max_hold_bars_a', 5)
        self.use_vwap_exit = self.params.get('use_vwap_exit', True)

    def get_default_params(self) -> Dict[str, Any]:
        """获取默认参数"""
        return {
            'bb_period': 20,
            'bb_std': 2.0,
            'rsi_period': 14,
            'rsi_oversold': 25,
            'rsi_overbought': 75,
            'atr_period': 14,
            'stop_loss_atr_mult_a': 1.0,
            'max_hold_bars_a': 5,
            'volatility_filter_period': 20,
            'volatility_filter_mult': 1.5,
            'use_vwap_exit': True,
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        """获取参数优化范围"""
        return {
            'bb_period': (15, 25),
            'bb_std': (1.5, 2.5),
            'rsi_oversold': (15, 35),
            'rsi_overbought': (65, 85),
            'stop_loss_atr_mult_a': (0.5, 2.0),
            'max_hold_bars_a': (3, 10),
            'volatility_filter_mult': (1.0, 2.5),
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

        Returns:
            TradeSignal或None
        """
        if current_idx < 50:  # 确保有足够的历史数据
            return None

        # 获取当前K线数据
        current_bar = df.iloc[current_idx]
        timestamp = df.index[current_idx]

        # 检查是否为亚盘时段（北京时间6:00-14:00）
        if not self._is_asian_session(timestamp):
            return None

        # 异常波动过滤
        if self._is_abnormal_volatility(df, current_idx):
            return None

        # 获取价格数据
        close = current_bar['Close']
        atr = current_bar.get('ATR', 0)
        rsi = current_bar.get('RSI', 50)
        bb_upper = current_bar.get('BB_Upper', close)
        bb_lower = current_bar.get('BB_Lower', close)
        vwap = current_bar.get('VWAP', close)

        # 获取前一根K线数据（避免前视偏差）
        prev_bar = df.iloc[current_idx - 1]
        prev_close = prev_bar['Close']
        prev_rsi = prev_bar.get('RSI', 50)

        # ========== 做多信号 ==========
        # 条件：价格触及布林带下轨 + RSI从超卖区回升
        if prev_close <= bb_lower and prev_rsi <= self.rsi_oversold:
            # 确认当前RSI已经回升
            if rsi > prev_rsi:
                direction = TradeDirection.LONG
                stop_loss = close - atr * self.stop_loss_mult

                # 动态止盈：VWAP或固定风险回报比
                if self.use_vwap_exit and vwap > close:
                    take_profit = vwap
                else:
                    take_profit = close + abs(close - stop_loss) * 2.0

                return self._create_signal(
                    timestamp=timestamp,
                    direction=direction,
                    entry_price=close,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    reason="MeanReversion_Long: RSI_Oversold+Bollinger_Lower",
                    signal_bar_idx=current_idx,
                    execution_bar_idx=current_idx + 1,
                    max_hold_bars=self.max_hold_bars_a,
                    vwap=vwap
                )

        # ========== 做空信号 ==========
        # 条件：价格触及布林带上轨 + RSI从超买区回落
        if prev_close >= bb_upper and prev_rsi >= self.rsi_overbought:
            # 确认当前RSI已经回落
            if rsi < prev_rsi:
                direction = TradeDirection.SHORT
                stop_loss = close + atr * self.stop_loss_mult

                # 动态止盈：VWAP或固定风险回报比
                if self.use_vwap_exit and vwap < close:
                    take_profit = vwap
                else:
                    take_profit = close - abs(close - stop_loss) * 2.0

                return self._create_signal(
                    timestamp=timestamp,
                    direction=direction,
                    entry_price=close,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    reason="MeanReversion_Short: RSI_Overbought+Bollinger_Upper",
                    signal_bar_idx=current_idx,
                    execution_bar_idx=current_idx + 1,
                    max_hold_bars=self.max_hold_bars_a,
                    vwap=vwap
                )

        return None

    def _is_asian_session(self, timestamp) -> bool:
        """检查是否为亚盘时段（北京时间6:00-14:00）"""
        hour = timestamp.hour
        return 6 <= hour < 14

    def _is_abnormal_volatility(self, df: pd.DataFrame, current_idx: int) -> bool:
        """检查是否出现异常波动"""
        period = self.params.get('volatility_filter_period', 20)
        mult = self.params.get('volatility_filter_mult', 1.5)

        if current_idx < period + 1:
            return False

        # 计算前N根K线的平均ATR
        prev_atrs = df['ATR'].iloc[current_idx - period:current_idx]
        avg_atr = prev_atrs.mean()

        # 当前K线的波动范围
        current_bar = df.iloc[current_idx]
        current_range = current_bar['High'] - current_bar['Low']

        # 如果当前波动显著高于历史平均，判定为异常
        if avg_atr > 0 and current_range > avg_atr * mult:
            return True

        return False
