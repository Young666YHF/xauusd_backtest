"""
Dollar Trader 基类策略
======================
提取 Dollar Trader 系列策略的公共信号生成逻辑:
- SMA 20/50/200 排列判断
- SMA 交叉检测
- 基础入场/出场信号生成

子类只需实现特有逻辑（仓位管理、过滤条件、止损等）。

作者: Claude
版本: 1.0.0
"""

from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
import numpy as np
from datetime import datetime

from strategies.base import BaseStrategy
from core.types import TradeSignal, TradeDirection, SignalType, ExitReason
from core.indicators import calculate_sma


class DollarTraderBaseStrategy(BaseStrategy):
    """
    Dollar Trader 系列策略的抽象基类。

    公共逻辑:
    - 使用三条 SMA(短期, 中期, 长期) 判断趋势方向
    - SMA 排列判断多头/空头趋势
    - SMA 短期与中期交叉作为出场信号
    - 严格执行 shift(1) 避免未来函数

    子类需重写以下方法以添加特有逻辑:
    - `_check_entry_filters`: 入场过滤条件 (如 BBW、ADX)
    - `_modify_entry_signal`: 修改入场信号 (如添加止损止盈、仓位)
    - `_modify_exit_signal`: 修改出场信号
    - `on_trade_completed`: 交易完成后的状态更新 (如马丁格尔)
    - `get_position_size`: 返回动态仓位大小
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        """
        初始化策略。

        Args:
            params: 策略参数，公共参数包含:
                - sma_short: 短期 SMA 周期 (默认 20)
                - sma_medium: 中期 SMA 周期 (默认 50)
                - sma_long: 长期 SMA 周期 (默认 200)
                - position_size: 仓位大小 (默认 1.0)
            strategy_id: 策略标识
        """
        super().__init__(params, strategy_id or "DollarTraderBase")
        self.current_position: Optional[TradeDirection] = None

    def get_default_params(self) -> Dict[str, Any]:
        """返回默认参数。"""
        return {
            'sma_short': 20,
            'sma_medium': 50,
            'sma_long': 200,
            'position_size': 1.0,
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        """返回参数优化范围。"""
        return {
            'sma_short': (10, 30),
            'sma_medium': (30, 70),
            'sma_long': (100, 300),
        }

    # ------------------------------------------------------------------
    # 公共指标提取方法
    # ------------------------------------------------------------------

    def _get_sma_column_names(self) -> Tuple[str, str, str]:
        """
        获取当前参数对应的 SMA 列名。

        Returns:
            (短期 SMA 列名, 中期 SMA 列名, 长期 SMA 列名)
        """
        return (
            f"SMA_{self.params['sma_short']}",
            f"SMA_{self.params['sma_medium']}",
            f"SMA_{self.params['sma_long']}",
        )

    def _check_sma_alignment(
        self,
        df: pd.DataFrame,
        current_idx: int
    ) -> Tuple[bool, bool, pd.Series, pd.Series]:
        """
        检查 SMA 多头排列和空头排列。

        基于上一根已收盘 K 线的指标值判断，避免未来函数。

        Args:
            df: 包含指标的 DataFrame
            current_idx: 当前 K 线索引

        Returns:
            (prev_bullish, prev_bearish, prev_bar, current_bar)
            - prev_bullish: 上一根 K 线是否多头排列
            - prev_bearish: 上一根 K 线是否空头排列
            - prev_bar: 上一根 K 线的 Series
            - current_bar: 当前 K 线的 Series
        """
        prev_bar = df.iloc[current_idx - 1]
        current_bar = df.iloc[current_idx]

        sma_s_col, sma_m_col, sma_l_col = self._get_sma_column_names()

        prev_close = prev_bar['Close']
        prev_sma_s = prev_bar[sma_s_col]
        prev_sma_m = prev_bar[sma_m_col]
        prev_sma_l = prev_bar[sma_l_col]

        # 多头排列: C > SMA_S > SMA_M > SMA_L
        prev_bullish = (
            prev_close > prev_sma_s and
            prev_sma_s > prev_sma_m and
            prev_sma_m > prev_sma_l
        )

        # 空头排列: C < SMA_S < SMA_M < SMA_L
        prev_bearish = (
            prev_close < prev_sma_s and
            prev_sma_s < prev_sma_m and
            prev_sma_m < prev_sma_l
        )

        return prev_bullish, prev_bearish, prev_bar, current_bar

    def _check_crossover(
        self,
        df: pd.DataFrame,
        current_idx: int
    ) -> Tuple[bool, bool]:
        """
        检测 SMA 短期与中期均线的交叉。

        需要前两根 K 线的 SMA 状态来判断交叉。

        Args:
            df: 包含指标的 DataFrame
            current_idx: 当前 K 线索引

        Returns:
            (sma_bearish_cross, sma_bullish_cross)
            - sma_bearish_cross: 短期下穿中期 (死叉)
            - sma_bullish_cross: 短期上穿中期 (金叉)
        """
        if current_idx < 2:
            return False, False

        sma_s_col, sma_m_col, _ = self._get_sma_column_names()

        prev_bar = df.iloc[current_idx - 1]
        prev2_bar = df.iloc[current_idx - 2]

        prev_sma_s = prev_bar[sma_s_col]
        prev_sma_m = prev_bar[sma_m_col]
        prev2_sma_s = prev2_bar[sma_s_col]
        prev2_sma_m = prev2_bar[sma_m_col]

        # 短期下穿中期 (死叉) - 多头平仓信号
        sma_bearish_cross = (prev2_sma_s >= prev2_sma_m) and (prev_sma_s < prev_sma_m)
        # 短期上穿中期 (金叉) - 空头平仓信号
        sma_bullish_cross = (prev2_sma_s <= prev2_sma_m) and (prev_sma_s > prev_sma_m)

        return sma_bearish_cross, sma_bullish_cross

    def _validate_data(
        self,
        df: pd.DataFrame,
        current_idx: int
    ) -> Optional[Tuple[str, str, str]]:
        """
        验证数据充足性和指标列存在性。

        Args:
            df: 包含指标的 DataFrame
            current_idx: 当前 K 线索引

        Returns:
            验证通过返回 (sma_s_col, sma_m_col, sma_l_col)，
            否则返回 None。
        """
        min_bars_needed = self.params['sma_long'] + 5
        if current_idx < min_bars_needed:
            return None

        sma_s_col, sma_m_col, sma_l_col = self._get_sma_column_names()

        for col in [sma_s_col, sma_m_col, sma_l_col]:
            if col not in df.columns:
                raise ValueError(
                    f"Missing required column: {col}. "
                    "Please ensure SMA indicators are calculated."
                )

        prev_bar = df.iloc[current_idx - 1]
        if (
            pd.isna(prev_bar[sma_s_col]) or
            pd.isna(prev_bar[sma_m_col]) or
            pd.isna(prev_bar[sma_l_col])
        ):
            return None

        return sma_s_col, sma_m_col, sma_l_col

    # ------------------------------------------------------------------
    # 子类可重写的方法
    # ------------------------------------------------------------------

    def _check_entry_filters(
        self,
        df: pd.DataFrame,
        current_idx: int,
        prev_bar: pd.Series
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        检查入场过滤条件。

        子类重写此方法添加过滤逻辑 (如 BBW、ADX)。

        Args:
            df: 包含指标的 DataFrame
            current_idx: 当前 K 线索引
            prev_bar: 上一根 K 线的数据

        Returns:
            (是否允许入场, 附加信息字典)
        """
        return True, {}

    def _modify_entry_signal(
        self,
        signal: TradeSignal,
        **kwargs
    ) -> TradeSignal:
        """
        修改入场信号。

        子类重写此方法添加特有属性 (如止损止盈、仓位大小)。

        Args:
            signal: 基础入场信号
            **kwargs: 额外上下文

        Returns:
            修改后的信号
        """
        return signal

    def _modify_exit_signal(
        self,
        signal: TradeSignal,
        **kwargs
    ) -> TradeSignal:
        """
        修改出场信号。

        子类重写此方法添加特有属性。

        Args:
            signal: 基础出场信号
            **kwargs: 额外上下文

        Returns:
            修改后的信号
        """
        return signal

    def _get_position_size_for_signal(self) -> Optional[float]:
        """
        获取当前信号应使用的仓位大小。

        子类重写此方法实现动态仓位 (如马丁格尔)。

        Returns:
            仓位大小或 None (使用默认)
        """
        return None

    # ------------------------------------------------------------------
    # 信号生成主流程
    # ------------------------------------------------------------------

    def generate_signal(
        self,
        df: pd.DataFrame,
        current_idx: int,
        **kwargs
    ) -> Optional[TradeSignal]:
        """
        生成交易信号。

        Args:
            df: 包含指标的 DataFrame
            current_idx: 当前 K 线索引
            **kwargs: 额外上下文

        Returns:
            TradeSignal 对象或 None
        """
        # 数据验证
        validated = self._validate_data(df, current_idx)
        if validated is None:
            return None

        # SMA 排列和交叉检测
        prev_bullish, prev_bearish, prev_bar, current_bar = self._check_sma_alignment(
            df, current_idx
        )
        sma_bearish_cross, sma_bullish_cross = self._check_crossover(df, current_idx)

        current_timestamp = df.index[current_idx]
        current_open = current_bar['Open']
        sma_s_col, sma_m_col, sma_l_col = self._get_sma_column_names()
        prev_close = prev_bar['Close']
        prev_sma_s = prev_bar[sma_s_col]
        prev_sma_m = prev_bar[sma_m_col]
        prev_sma_l = prev_bar[sma_l_col]

        # 入场过滤
        allow_entry, filter_info = self._check_entry_filters(df, current_idx, prev_bar)

        # 生成基础信号
        signal = self._generate_base_signal(
            prev_bullish=prev_bullish,
            prev_bearish=prev_bearish,
            timestamp=current_timestamp,
            entry_price=current_open,
            prev_close=prev_close,
            prev_sma_s=prev_sma_s,
            prev_sma_m=prev_sma_m,
            prev_sma_l=prev_sma_l,
            current_idx=current_idx,
            allow_entry=allow_entry,
            sma_bearish_cross=sma_bearish_cross,
            sma_bullish_cross=sma_bullish_cross,
            filter_info=filter_info,
        )

        return signal

    def _generate_base_signal(
        self,
        prev_bullish: bool,
        prev_bearish: bool,
        timestamp: datetime,
        entry_price: float,
        prev_close: float,
        prev_sma_s: float,
        prev_sma_m: float,
        prev_sma_l: float,
        current_idx: int,
        allow_entry: bool = True,
        sma_bearish_cross: bool = False,
        sma_bullish_cross: bool = False,
        filter_info: Optional[Dict[str, Any]] = None,
    ) -> Optional[TradeSignal]:
        """
        生成基础交易信号 (不含仓位管理等特有逻辑)。

        处理三种场景:
        1. 持有多头 + SMA 死叉 -> 平多或反向开空
        2. 持有空头 + SMA 金叉 -> 平空或反向开多
        3. 无持仓 + 趋势排列 + 允许入场 -> 新开仓

        Args:
            prev_bullish: 上一根 K 线是否多头排列
            prev_bearish: 上一根 K 线是否空头排列
            timestamp: 信号时间戳
            entry_price: 入场价格 (当前 K 线开盘价)
            prev_close: 上一根 K 线收盘价
            prev_sma_s: 上一根 K 线短期 SMA
            prev_sma_m: 上一根 K 线中期 SMA
            prev_sma_l: 上一根 K 线长期 SMA
            current_idx: 当前 K 线索引
            allow_entry: 是否允许入场 (过滤条件)
            sma_bearish_cross: 短期 SMA 是否下穿中期 SMA
            sma_bullish_cross: 短期 SMA 是否上穿中期 SMA
            filter_info: 过滤条件的附加信息

        Returns:
            TradeSignal 对象或 None
        """
        if filter_info is None:
            filter_info = {}

        signal = None

        # ====================================
        # 持有多头时的处理
        # ====================================
        if self.current_position == TradeDirection.LONG:
            if sma_bearish_cross:
                if prev_bearish and allow_entry:
                    # 反向开空
                    signal = self._create_signal(
                        timestamp=timestamp,
                        direction=TradeDirection.SHORT,
                        entry_price=entry_price,
                        stop_loss=None,
                        take_profit=None,
                        reason=self._format_reverse_reason(
                            TradeDirection.SHORT, prev_sma_s, prev_sma_m, filter_info
                        ),
                        signal_bar_idx=current_idx - 1,
                        execution_bar_idx=current_idx,
                        size=self._get_position_size_for_signal(),
                    )
                    self.current_position = TradeDirection.SHORT
                else:
                    # 只平仓
                    signal = TradeSignal(
                        timestamp=timestamp,
                        signal_type=SignalType.CLOSE_LONG,
                        strategy_id=self.strategy_id,
                        direction=TradeDirection.FLAT,
                        entry_price=entry_price,
                        reason=f"Long Exit: SMA_20 crossed below SMA_50 (no reverse)",
                        signal_bar_index=current_idx - 1,
                        execution_bar_index=current_idx,
                    )
                    self.current_position = None

        # ====================================
        # 持有空头时的处理
        # ====================================
        elif self.current_position == TradeDirection.SHORT:
            if sma_bullish_cross:
                if prev_bullish and allow_entry:
                    # 反向开多
                    signal = self._create_signal(
                        timestamp=timestamp,
                        direction=TradeDirection.LONG,
                        entry_price=entry_price,
                        stop_loss=None,
                        take_profit=None,
                        reason=self._format_reverse_reason(
                            TradeDirection.LONG, prev_sma_s, prev_sma_m, filter_info
                        ),
                        signal_bar_idx=current_idx - 1,
                        execution_bar_idx=current_idx,
                        size=self._get_position_size_for_signal(),
                    )
                    self.current_position = TradeDirection.LONG
                else:
                    # 只平仓
                    signal = TradeSignal(
                        timestamp=timestamp,
                        signal_type=SignalType.CLOSE_SHORT,
                        strategy_id=self.strategy_id,
                        direction=TradeDirection.FLAT,
                        entry_price=entry_price,
                        reason=f"Short Exit: SMA_20 crossed above SMA_50 (no reverse)",
                        signal_bar_index=current_idx - 1,
                        execution_bar_index=current_idx,
                    )
                    self.current_position = None

        # ====================================
        # 无持仓时的入场检查
        # ====================================
        if signal is None and self.current_position is None and allow_entry:
            signal = self._generate_new_entry_signal(
                prev_bullish=prev_bullish,
                prev_bearish=prev_bearish,
                timestamp=timestamp,
                entry_price=entry_price,
                prev_close=prev_close,
                prev_sma_s=prev_sma_s,
                prev_sma_m=prev_sma_m,
                prev_sma_l=prev_sma_l,
                current_idx=current_idx,
                filter_info=filter_info,
            )

        # 子类修改信号
        if signal is not None:
            if signal.signal_type in (SignalType.LONG, SignalType.SHORT):
                signal = self._modify_entry_signal(
                    signal,
                    prev_bullish=prev_bullish,
                    prev_bearish=prev_bearish,
                    filter_info=filter_info,
                )
            elif signal.signal_type in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT):
                signal = self._modify_exit_signal(
                    signal,
                    filter_info=filter_info,
                )

        return signal

    def _generate_new_entry_signal(
        self,
        prev_bullish: bool,
        prev_bearish: bool,
        timestamp: datetime,
        entry_price: float,
        prev_close: float,
        prev_sma_s: float,
        prev_sma_m: float,
        prev_sma_l: float,
        current_idx: int,
        filter_info: Optional[Dict[str, Any]] = None,
    ) -> Optional[TradeSignal]:
        """
        生成新开仓入场信号。

        Args:
            prev_bullish: 上一根 K 线是否多头排列
            prev_bearish: 上一根 K 线是否空头排列
            timestamp: 信号时间戳
            entry_price: 入场价格
            prev_close: 上一根 K 线收盘价
            prev_sma_s: 上一根 K 线短期 SMA
            prev_sma_m: 上一根 K 线中期 SMA
            prev_sma_l: 上一根 K 线长期 SMA
            current_idx: 当前 K 线索引
            filter_info: 过滤条件附加信息

        Returns:
            TradeSignal 对象或 None
        """
        if prev_bullish:
            direction = TradeDirection.LONG
            reason = (
                f"Long Entry: C({prev_close:.2f})>"
                f"SMA_20({prev_sma_s:.2f})>"
                f"SMA_50({prev_sma_m:.2f})>"
                f"SMA_200({prev_sma_l:.2f})"
            )
            if filter_info:
                reason += f" {self._format_filter_info(filter_info)}"
            self.current_position = TradeDirection.LONG

        elif prev_bearish:
            direction = TradeDirection.SHORT
            reason = (
                f"Short Entry: C({prev_close:.2f})<"
                f"SMA_20({prev_sma_s:.2f})<"
                f"SMA_50({prev_sma_m:.2f})<"
                f"SMA_200({prev_sma_l:.2f})"
            )
            if filter_info:
                reason += f" {self._format_filter_info(filter_info)}"
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
            size=self._get_position_size_for_signal(),
        )

    def _format_reverse_reason(
        self,
        direction: TradeDirection,
        prev_sma_s: float,
        prev_sma_m: float,
        filter_info: Dict[str, Any]
    ) -> str:
        """
        格式化反向开仓信号的原因字符串。

        Args:
            direction: 开仓方向
            prev_sma_s: 上一根 K 线短期 SMA
            prev_sma_m: 上一根 K 线中期 SMA
            filter_info: 过滤条件信息

        Returns:
            原因字符串
        """
        if direction == TradeDirection.SHORT:
            reason = (
                f"Reverse to Short: SMA_20({prev_sma_s:.2f}) "
                f"crossed below SMA_50({prev_sma_m:.2f})"
            )
        else:
            reason = (
                f"Reverse to Long: SMA_20({prev_sma_s:.2f}) "
                f"crossed above SMA_50({prev_sma_m:.2f})"
            )
        if filter_info:
            reason += f" {self._format_filter_info(filter_info)}"
        return reason

    def _format_filter_info(self, filter_info: Dict[str, Any]) -> str:
        """
        格式化过滤条件信息为字符串。

        子类可重写以自定义格式。

        Args:
            filter_info: 过滤信息字典

        Returns:
            格式化字符串
        """
        parts = []
        for key, value in filter_info.items():
            if isinstance(value, float):
                parts.append(f"{key}={value:.2f}")
            else:
                parts.append(f"{key}={value}")
        return "|".join(parts) if parts else ""

    def on_trade_completed(self, trade_record: Dict[str, Any]):
        """
        交易完成回调。

        基类实现: 当持仓被平仓时重置 current_position。
        子类应调用 super().on_trade_completed(trade_record)。

        Args:
            trade_record: 交易记录
        """
        if trade_record.get('exit_reason') in [
            ExitReason.SIGNAL_REVERSE,
            ExitReason.FORCE_CLOSE,
            ExitReason.END_OF_DATA,
        ]:
            self.current_position = None

    def reset(self):
        """重置策略状态。"""
        super().reset()
        self.current_position = None


def calculate_dollar_trader_base_indicators(
    df: pd.DataFrame,
    sma_short: int = 20,
    sma_medium: int = 50,
    sma_long: int = 200
) -> pd.DataFrame:
    """
    计算 Dollar Trader 基类策略所需的所有指标。

    Args:
        df: OHLCV 数据
        sma_short: 短期 SMA 周期
        sma_medium: 中期 SMA 周期
        sma_long: 长期 SMA 周期

    Returns:
        添加指标后的 DataFrame
    """
    result = df.copy()
    result[f'SMA_{sma_short}'] = calculate_sma(result['Close'], sma_short)
    result[f'SMA_{sma_medium}'] = calculate_sma(result['Close'], sma_medium)
    result[f'SMA_{sma_long}'] = calculate_sma(result['Close'], sma_long)
    return result
