"""
趋势角度突破策略 (Trend Angle Breakout)
=====================================
极简趋势突破模型 - 基于SMA均线角度和K线突破

核心逻辑:
1. 计算SMA均线角度（ATR标准化）
2. 做多：角度 > 阈值 且 突破前2根K线高点
3. 做空：角度 < -阈值 且 跌破前2根K线低点
4. 出场：反向信号或移动止损

作者: Claude
版本: 1.0.0
"""

from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np
from datetime import datetime

from strategies.base import BaseStrategy
from core.types import TradeSignal, TradeDirection, SignalType
from core.indicators import calculate_sma, calculate_atr, calculate_sma_angle


class TrendAngleBreakoutStrategy(BaseStrategy):
    """
    趋势角度突破策略

    特点:
    - 使用ATR标准化的SMA角度计算，解决价格/时间量纲不同问题
    - 突破前2根K线高低点确认趋势
    - 支持固定盈亏比和移动止损出场
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        """
        初始化策略

        Args:
            params: 策略参数，包含:
                - sma_period: SMA周期 (默认20)
                - angle_lookback: 角度回看K线数 (默认5)
                - angle_threshold: 角度阈值度 (默认3.0)
                - breakout_lookback: 突破回看K线数 (默认2)
                - use_fixed_exit: 是否使用固定盈亏比出场 (默认True)
                - risk_reward_ratio: 盈亏比 (默认2.0)
                - trailing_stop_atr: 移动止损ATR倍数 (默认2.0)
                - atr_period: ATR周期 (默认14)
            strategy_id: 策略标识
        """
        super().__init__(params, strategy_id or "TrendAngleBreakout")

        # 追踪当前持仓方向（用于反向信号出场）
        self.current_position: Optional[TradeDirection] = None

    def get_default_params(self) -> Dict[str, Any]:
        """返回默认参数"""
        return {
            'sma_period': 20,
            'angle_lookback': 5,
            'angle_threshold': 3.0,
            'breakout_lookback': 2,
            'use_fixed_exit': True,
            'risk_reward_ratio': 2.0,
            'trailing_stop_atr': 2.0,
            'atr_period': 14,
            'position_size': 1.0,
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        """返回参数优化范围"""
        return {
            'sma_period': (10, 50),
            'angle_lookback': (3, 10),
            'angle_threshold': (1.0, 10.0),
            'breakout_lookback': (1, 10),  # 扩大范围到10根K线
            'risk_reward_ratio': (1.0, 4.0),
            'trailing_stop_atr': (1.0, 4.0),
            'atr_period': (10, 20),
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
        min_bars_needed = max(
            self.params['sma_period'] + self.params['angle_lookback'],
            self.params['breakout_lookback'] + 1,
            self.params['atr_period']
        ) + 5

        if current_idx < min_bars_needed:
            return None

        # 获取当前K线和前序数据
        current_bar = df.iloc[current_idx]
        prev_bar = df.iloc[current_idx - 1]

        # 检查必要的指标列是否存在
        sma_col = f"SMA_{self.params['sma_period']}"
        if sma_col not in df.columns:
            raise ValueError(f"Missing required column: {sma_col}. Please ensure SMA is calculated.")
        if 'ATR' not in df.columns:
            raise ValueError("Missing required column: ATR. Please ensure ATR is calculated.")

        # 获取当前SMA角度
        sma_angle = current_bar.get('SMA_Angle', None)
        if pd.isna(sma_angle):
            return None

        # 计算前N根K线的高低点（不含当前K线）
        lookback = int(self.params['breakout_lookback'])
        start_idx = current_idx - lookback
        end_idx = current_idx  # 不包含当前K线

        recent_highs = df['High'].iloc[start_idx:end_idx]
        recent_lows = df['Low'].iloc[start_idx:end_idx]

        highest_2 = recent_highs.max()
        lowest_2 = recent_lows.min()

        # 当前价格
        current_close = current_bar['Close']
        current_high = current_bar['High']
        current_low = current_bar['Low']

        # 获取ATR用于计算止损
        atr = current_bar['ATR']
        if pd.isna(atr) or atr <= 0:
            return None

        angle_threshold = self.params['angle_threshold']

        # 生成信号逻辑
        signal = None

        # 多头信号：角度 > 阈值 且 突破前2根K线高点
        if sma_angle > angle_threshold and current_high > highest_2:
            # 检查是否有空头持仓（反向信号出场）
            if self.current_position == TradeDirection.SHORT:
                signal = self._create_signal(
                    timestamp=df.index[current_idx],
                    direction=TradeDirection.LONG,
                    entry_price=current_close,
                    stop_loss=None,  # 反向信号出场不需要止损
                    take_profit=None,
                    reason=f"Reverse signal: Angle={sma_angle:.1f}°, Breakout above {highest_2:.2f}",
                    signal_bar_idx=current_idx,
                    execution_bar_idx=current_idx + 1,  # 下一根K线执行（避免前视偏差）
                    sma_angle=sma_angle,
                    breakout_level=highest_2
                )
                self.current_position = TradeDirection.LONG
            elif self.current_position is None:
                # 新开多仓
                stop_loss = current_close - atr * self.params['trailing_stop_atr']
                take_profit = current_close + atr * self.params['risk_reward_ratio'] * self.params['trailing_stop_atr']

                signal = self._create_signal(
                    timestamp=df.index[current_idx],
                    direction=TradeDirection.LONG,
                    entry_price=current_close,
                    stop_loss=stop_loss if self.params['use_fixed_exit'] else None,
                    take_profit=take_profit if self.params['use_fixed_exit'] else None,
                    reason=f"Long: Angle={sma_angle:.1f}°>{angle_threshold}°, Breakout>{highest_2:.2f}",
                    signal_bar_idx=current_idx,
                    execution_bar_idx=current_idx + 1,
                    sma_angle=sma_angle,
                    breakout_level=highest_2,
                    atr=atr
                )
                self.current_position = TradeDirection.LONG

        # 空头信号：角度 < -阈值 且 跌破前2根K线低点
        elif sma_angle < -angle_threshold and current_low < lowest_2:
            # 检查是否有多头持仓（反向信号出场）
            if self.current_position == TradeDirection.LONG:
                signal = self._create_signal(
                    timestamp=df.index[current_idx],
                    direction=TradeDirection.SHORT,
                    entry_price=current_close,
                    stop_loss=None,
                    take_profit=None,
                    reason=f"Reverse signal: Angle={sma_angle:.1f}°, Breakdown below {lowest_2:.2f}",
                    signal_bar_idx=current_idx,
                    execution_bar_idx=current_idx + 1,
                    sma_angle=sma_angle,
                    breakout_level=lowest_2
                )
                self.current_position = TradeDirection.SHORT
            elif self.current_position is None:
                # 新开空仓
                stop_loss = current_close + atr * self.params['trailing_stop_atr']
                take_profit = current_close - atr * self.params['risk_reward_ratio'] * self.params['trailing_stop_atr']

                signal = self._create_signal(
                    timestamp=df.index[current_idx],
                    direction=TradeDirection.SHORT,
                    entry_price=current_close,
                    stop_loss=stop_loss if self.params['use_fixed_exit'] else None,
                    take_profit=take_profit if self.params['use_fixed_exit'] else None,
                    reason=f"Short: Angle={sma_angle:.1f}°<-{angle_threshold}°, Breakdown<{lowest_2:.2f}",
                    signal_bar_idx=current_idx,
                    execution_bar_idx=current_idx + 1,
                    sma_angle=sma_angle,
                    breakout_level=lowest_2,
                    atr=atr
                )
                self.current_position = TradeDirection.SHORT

        return signal

    def on_trade_completed(self, trade_record: Dict[str, Any]):
        """
        交易完成回调

        Args:
            trade_record: 交易记录
        """
        # 当持仓被平仓时，重置当前持仓状态
        if trade_record.get('exit_reason') in ['STOP_LOSS', 'TAKE_PROFIT', 'TRAILING_STOP']:
            self.current_position = None

    def reset(self):
        """重置策略状态"""
        super().reset()
        self.current_position = None


def calculate_strategy_indicators(
    df: pd.DataFrame,
    sma_period: int = 20,
    atr_period: int = 14,
    angle_lookback: int = 5
) -> pd.DataFrame:
    """
    计算策略所需的所有指标

    Args:
        df: OHLCV数据
        sma_period: SMA周期
        atr_period: ATR周期
        angle_lookback: 角度回看K线数

    Returns:
        添加指标后的DataFrame
    """
    result = df.copy()

    # 计算SMA
    sma_col = f"SMA_{sma_period}"
    result[sma_col] = calculate_sma(result['Close'], sma_period)

    # 计算ATR
    result['ATR'] = calculate_atr(result, atr_period)

    # 计算SMA角度（ATR标准化）
    result['SMA_Angle'] = calculate_sma_angle(
        result[sma_col],
        result['ATR'],
        angle_lookback
    )

    return result
