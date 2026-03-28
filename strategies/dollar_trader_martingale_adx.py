"""
Dollar Trader Martingale BBW 增强策略 (阶梯式马丁)
===================================================
基于SMA_20/50/200趋势跟踪 + BBW波动率过滤 + 阶梯式马丁格尔仓位管理

核心逻辑:
1. 入场逻辑: SMA多头排列/空头排列 + BBW自适应过滤
   - BBW = (Upper - Lower) / Middle × 100
   - 当前BBW > 过去50根K线平均BBW时，认为波动率足够，允许开仓
2. 出场逻辑: 与原策略相同 (SMA_20/50交叉)
3. 阶梯式马丁管理:
   - 仓位 = 基础仓位 × multiplier^martingale_step
   - 亏损2次 → 阶梯+1（仓位加倍）
   - 盈利1次 → 阶梯-1（仓位减半）
   - 达到最大层数继续亏损：累积超调计数
   - 超调状态下盈利：消耗计数保持仓位（不下降）

特点:
- BBW自适应过滤，避免低波动率时期交易
- 阶梯式马丁，更精细的仓位管理
- 超调计数机制，避免最大层数后立即降仓

作者: Claude
版本: 2.0.0
"""

from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
import numpy as np
from datetime import datetime

from strategies.base import BaseStrategy
from core.types import TradeSignal, TradeDirection, SignalType, ExitReason
from core.indicators import calculate_sma, calculate_bollinger_bands, calculate_bbw


class DollarTraderMartingaleBBWStepStrategy(BaseStrategy):
    """
    Dollar Trader Martingale BBW 阶梯式增强策略

    BBW波动率过滤:
    - 当前BBW > BBW_MA(50) 时允许开仓

    阶梯式马丁管理:
    - 亏损2次 → 阶梯+1
    - 盈利1次 → 阶梯-1
    - 最大层数时累积超调计数
    - 超调计数>0时盈利先消耗计数
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        """
        初始化策略

        Args:
            params: 策略参数，包含:
                - sma_short: 短期SMA周期 (默认20)
                - sma_medium: 中期SMA周期 (默认50)
                - sma_long: 长期SMA周期 (默认200)
                - position_size: 基础仓位大小 (默认1.0)
                - martingale_multiplier: 马丁格尔倍数 (默认2.0)
                - max_martingale_steps: 最大阶梯层级 (默认5)
                - bb_period: 布林带周期 (默认20)
                - bb_std: 布林带标准差倍数 (默认2.0)
                - bbw_ma_period: BBW均线周期 (默认50)
            strategy_id: 策略标识
        """
        super().__init__(params, strategy_id or "DollarTraderMartingaleBBWStep")

        # 追踪当前持仓方向
        self.current_position: Optional[TradeDirection] = None

        # 马丁格尔阶梯状态
        self.martingale_step: int = 0
        self.last_trade_profit: Optional[float] = None

        # 阶梯转换计数器
        self.loss_count_in_step: int = 0
        self.overshoot_count: int = 0
        self.undershoot_count: int = 0

        # BBW状态
        self.last_bbw_value: Optional[float] = None
        self.last_bbw_ma: Optional[float] = None

    def get_default_params(self) -> Dict[str, Any]:
        """返回默认参数"""
        return {
            'sma_short': 20,
            'sma_medium': 50,
            'sma_long': 200,
            'position_size': 0.01,  # 基础仓位（0.01手）
            'martingale_multiplier': 2.0,  # 马丁格尔倍数
            'max_martingale_steps': 5,  # 最大阶梯层级
            'bb_period': 20,  # 布林带周期
            'bb_std': 2.0,  # 布林带标准差倍数
            'bbw_ma_period': 50,  # BBW均线周期
            'enable_overshoot': True,  # 启用超调计数（默认开启）
            'enable_undershoot': True,  # 启用欠调计数（默认开启）
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        """返回参数优化范围（布尔开关不提供边界）"""
        return {
            'sma_short': (10, 30),
            'sma_medium': (30, 70),
            'sma_long': (100, 300),
            'martingale_multiplier': (1.5, 3.0),
            'max_martingale_steps': (3, 8),
            'bb_period': (10, 30),
            'bb_std': (1.5, 3.0),
            'bbw_ma_period': (30, 100),
        }

    def _calculate_position_size(self) -> float:
        """计算当前仓位大小"""
        base_size = self.params['position_size']
        multiplier = self.params['martingale_multiplier']
        return base_size * (multiplier ** self.martingale_step)

    @property
    def current_position_size(self) -> float:
        """当前仓位大小 (动态计算)"""
        return self._calculate_position_size()

    def _update_martingale_state(self, trade_record: Dict[str, Any]):
        """
        更新马丁格尔阶梯状态
        核心规则:
        - 亏损2次 → 阶梯+1
        - 盈利1次 → 阶梯-1
        - 最大层数继续亏损 → 超调计数+1（如果启用）
        - 超调计数>0时盈利 → 消耗计数（不降阶梯）（如果启用）
        - 0层继续盈利 → 欠调计数+1（如果启用）

        Args:
            trade_record: 交易记录
        """
        profit = trade_record.get('profit', 0)
        self.last_trade_profit = profit
        max_steps = self.params['max_martingale_steps']
        enable_overshoot = self.params.get('enable_overshoot', True)
        enable_undershoot = self.params.get('enable_undershoot', True)

        if profit < 0:
            # ========== 亏损处理 ==========
            self.loss_count_in_step += 1

            if self.loss_count_in_step >= 2:
                # 需要上升阶梯
                if self.martingale_step < max_steps:
                    # 正常上升
                    self.martingale_step += 1
                    self.loss_count_in_step = 0
                    # 如果有欠调计数且启用，消耗一个
                    if enable_undershoot and self.undershoot_count > 0:
                        self.undershoot_count -= 1
                else:
                    # 已经在最大层数
                    if enable_overshoot:
                        # 启用超调计数，累积超调计数
                        self.overshoot_count += 1
                        self.loss_count_in_step = 0
                    # 如果未启用超调，保持当前状态（不再计数）

        else:
            # ========== 盈利处理 ==========
            self.loss_count_in_step = 0  # 重置当前阶梯亏损计数

            if enable_overshoot and self.overshoot_count > 0:
                # 有超调计数且启用，先消耗计数（不降阶梯）
                self.overshoot_count -= 1
            elif self.martingale_step > 0:
                # 正常下降阶梯
                self.martingale_step -= 1
                # 如果下降后还有欠调计数且启用，消耗一个
                if enable_undershoot and self.undershoot_count > 0 and self.martingale_step == 0:
                    self.undershoot_count -= 1
            else:
                # 已经在0层
                if enable_undershoot:
                    # 启用欠调计数，累积欠调计数
                    self.undershoot_count += 1
                # 如果未启用欠调，不做任何操作

    def _check_bbw_for_entry(self, df: pd.DataFrame, current_idx: int) -> Tuple[bool, float, float]:
        """
        检查BBW是否满足开仓条件

        Args:
            df: DataFrame包含BBW数据
            current_idx: 当前索引

        Returns:
            (是否允许开仓, 当前BBW值, BBW均线值)
        """
        bbw_col = 'BBW'
        bbw_ma_col = f"BBW_MA_{self.params['bbw_ma_period']}"

        # 确保BBW列存在
        if bbw_col not in df.columns or bbw_ma_col not in df.columns:
            # 如果没有BBW数据，默认允许开仓（保守策略）
            return True, 0.0, 0.0

        # 获取当前BBW值（上一根已收盘K线）
        if current_idx - 1 < len(df):
            prev_bar = df.iloc[current_idx - 1]
            bbw_value = prev_bar[bbw_col]
            bbw_ma = prev_bar[bbw_ma_col]

            self.last_bbw_value = bbw_value
            self.last_bbw_ma = bbw_ma

        # 【Bug修复】数据无效时应该拒绝开仓，与Pine保持一致
        # bbwAllowEntry = not na(prevBBW) and not na(prevBBW_MA) and (prevBBW > prevBBW_MA)
        if pd.notna(bbw_value) and pd.notna(bbw_ma):
            allow_entry = bbw_value > bbw_ma
            return allow_entry, bbw_value, bbw_ma

        # 数据无效，拒绝开仓（与Pine一致）
        return False, 0.0, 0.0

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
            self.params['sma_long'],
            self.params['bb_period'] + self.params['bbw_ma_period']
        ) + 5

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
        # 检查BBW是否允许开仓（入场时才检查）
        allow_entry, bbw_value, bbw_ma = self._check_bbw_for_entry(df, current_idx)

        # 【Bug修复】严格按照Pine逻辑顺序：
        # 1. 先处理出场信号（含反向开仓判断）
        # 2. 再处理新开仓信号
        # Pine中反向开仓条件: hasPosition + isBearish/Bullish + smaCross + bbwAllowEntry

        signal = None

        # ====================================
        # 第一步: 出场信号检查 (含反向开仓)
        # ====================================
        if self.current_position == TradeDirection.LONG and sma_bearish_cross:
            # 多头平仓: SMA_20下穿SMA_50
            # Pine: 先平仓，再检查是否反向开仓
            # 反向开仓条件: 空头排列 + BBW允许 (交叉条件已满足)
            if prev_bearish and allow_entry:
                # 满足反向开仓条件，创建做空信号（引擎会先平多再开空）
                signal = self._create_exit_signal(
                    current_timestamp, TradeDirection.SHORT, current_open,
                    prev_sma_s, prev_sma_m, current_idx, is_long_exit=True
                )
                self.current_position = TradeDirection.SHORT
            else:
                # 仅平仓，不反向开仓
                signal = TradeSignal(
                    timestamp=current_timestamp,
                    signal_type=SignalType.CLOSE_LONG,
                    strategy_id=self.strategy_id,
                    direction=TradeDirection.FLAT,
                    entry_price=current_open,
                    reason=f"Long Exit (no reverse): BBW not allowed or not bearish",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = None

        elif self.current_position == TradeDirection.SHORT and sma_bullish_cross:
            # 空头平仓: SMA_20上穿SMA_50
            # 反向开仓条件: 多头排列 + BBW允许 (交叉条件已满足)
            if prev_bullish and allow_entry:
                # 满足反向开仓条件，创建做多信号（引擎会先平空再开多）
                signal = self._create_exit_signal(
                    current_timestamp, TradeDirection.LONG, current_open,
                    prev_sma_s, prev_sma_m, current_idx, is_long_exit=False
                )
                self.current_position = TradeDirection.LONG
            else:
                # 仅平仓，不反向开仓
                signal = TradeSignal(
                    timestamp=current_timestamp,
                    signal_type=SignalType.CLOSE_SHORT,
                    strategy_id=self.strategy_id,
                    direction=TradeDirection.FLAT,
                    entry_price=current_open,
                    reason=f"Short Exit (no reverse): BBW not allowed or not bullish",
                    signal_bar_index=current_idx - 1,
                    execution_bar_index=current_idx,
                )
                self.current_position = None

        # ====================================
        # 第二步: 新开仓信号 (仅当无持仓时)
        # ====================================
        if signal is None and self.current_position is None:
            signal = self._generate_entry_signal(
                prev_bullish, prev_bearish, current_timestamp, current_open,
                prev_close, prev_sma_s, prev_sma_m, prev_sma_l, current_idx,
                allow_entry, bbw_value, bbw_ma
            )

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
        current_idx: int,
        allow_entry: bool,
        bbw_value: float,
        bbw_ma: float
    ) -> Optional[TradeSignal]:
        """
        生成新开仓入场信号

        【重要】此方法仅处理新开仓，反向开仓已在主方法中处理
        新开仓条件: 无持仓 + 趋势排列 + BBW允许
        """
        # 只处理新开仓（无持仓）
        if self.current_position is not None:
            return None

        if prev_bullish:
            # 多头入场: 多头排列 + BBW允许
            if not allow_entry:
                return None
            direction = TradeDirection.LONG
            reason = f"Long Entry: BBW({bbw_value:.2f})>MA({bbw_ma:.2f}) Step={self.martingale_step}"
            self.current_position = TradeDirection.LONG

        elif prev_bearish:
            # 空头入场: 空头排列 + BBW允许
            if not allow_entry:
                return None
            direction = TradeDirection.SHORT
            reason = f"Short Entry: BBW({bbw_value:.2f})>MA({bbw_ma:.2f}) Step={self.martingale_step}"
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
            size=self._calculate_position_size(),
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
            size=self._calculate_position_size(),
        )

    def on_trade_completed(self, trade_record: Dict[str, Any]):
        """
        交易完成回调

        Args:
            trade_record: 交易记录
        """
        # 更新马丁格尔阶梯状态
        self._update_martingale_state(trade_record)

        # 当持仓被平仓时，重置当前持仓状态
        if trade_record.get('exit_reason') in [ExitReason.SIGNAL_REVERSE, ExitReason.FORCE_CLOSE, ExitReason.END_OF_DATA]:
            self.current_position = None

    def reset(self):
        """重置策略状态"""
        super().reset()
        self.current_position = None
        self.martingale_step = 0
        self.last_trade_profit = None
        self.loss_count_in_step = 0
        self.overshoot_count = 0
        self.undershoot_count = 0
        self.last_bbw_value = None
        self.last_bbw_ma = None

    def get_position_size(self) -> float:
        """
        获取当前仓位大小 (阶梯式马丁调整后的)

        Returns:
            当前应使用的仓位大小
        """
        return self.current_position_size

    def get_status_info(self) -> Dict[str, Any]:
        """
        获取策略状态信息（用于调试和监控）

        Returns:
            状态字典
        """
        return {
            'martingale_step': self.martingale_step,
            'current_position_size': self.current_position_size,
            'loss_count_in_step': self.loss_count_in_step,
            'overshoot_count': self.overshoot_count,
            'undershoot_count': self.undershoot_count,
            'enable_overshoot': self.params.get('enable_overshoot', True),
            'enable_undershoot': self.params.get('enable_undershoot', True),
            'last_bbw_value': self.last_bbw_value,
            'last_bbw_ma': self.last_bbw_ma,
            'last_trade_profit': self.last_trade_profit,
        }


def calculate_dollar_trader_martingale_bbw_indicators(
    df: pd.DataFrame,
    sma_short: int = 20,
    sma_medium: int = 50,
    sma_long: int = 200,
    bb_period: int = 20,
    bb_std: float = 2.0,
    bbw_ma_period: int = 50
) -> pd.DataFrame:
    """
    计算Dollar Trader Martingale BBW策略所需的所有指标

    Args:
        df: OHLCV数据
        sma_short: 短期SMA周期
        sma_medium: 中期SMA周期
        sma_long: 长期SMA周期
        bb_period: 布林带周期
        bb_std: 布林带标准差倍数
        bbw_ma_period: BBW均线周期

    Returns:
        添加指标后的DataFrame
    """
    result = df.copy()

    # 计算三条SMA
    result[f'SMA_{sma_short}'] = calculate_sma(result['Close'], sma_short)
    result[f'SMA_{sma_medium}'] = calculate_sma(result['Close'], sma_medium)
    result[f'SMA_{sma_long}'] = calculate_sma(result['Close'], sma_long)

    # 计算布林带
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(
        result['Close'], bb_period, bb_std
    )
    result['BB_Upper'] = bb_upper
    result['BB_Middle'] = bb_middle
    result['BB_Lower'] = bb_lower

    # 计算BBW
    result['BBW'] = calculate_bbw(result['Close'], bb_period, bb_std)

    # 计算BBW的移动平均
    result[f'BBW_MA_{bbw_ma_period}'] = calculate_sma(result['BBW'], bbw_ma_period)

    return result
