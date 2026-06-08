"""
Dollar Trader Martingale with Stop Loss (带止损版)
===================================================
基于SMA趋势跟踪 + BBW过滤 + ATR止损 + 阶梯式马丁

关键改进:
1. 添加ATR动态止损，限制单笔亏损
2. 止损后等待趋势重新确认再入场
3. 优化风险管理

作者: Claude
版本: 4.0.0
"""

from typing import Dict, List, Optional, Any, Tuple
import pandas as pd

from strategies.dollar_trader_base import DollarTraderBaseStrategy, calculate_dollar_trader_base_indicators
from core.types import TradeSignal, TradeDirection, SignalType, ExitReason
from core.indicators import calculate_sma, calculate_bollinger_bands, calculate_bbw, calculate_atr


class DollarTraderMartingaleSLStrategy(DollarTraderBaseStrategy):
    """
    Dollar Trader Martingale 带止损版

    改进:
    - ATR动态止损保护
    - 止损后冷却期
    - 更严格的风险控制
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        super().__init__(params, strategy_id or "DollarTraderMartingaleSL")

        # 持仓状态
        self.entry_price: Optional[float] = None
        self.entry_bar: int = 0

        # 马丁状态
        self.martingale_step: int = 0
        self.loss_count_in_step: int = 0

        # 止损后冷却
        self.cooldown_bars: int = 0
        self.last_stop_loss_bar: int = -1000

    def get_default_params(self) -> Dict[str, Any]:
        return {
            'sma_short': 20,
            'sma_medium': 50,
            'sma_long': 200,
            'position_size': 0.01,
            'martingale_multiplier': 2.0,
            'max_martingale_steps': 5,
            'bb_period': 20,
            'bb_std': 2.0,
            'bbw_ma_period': 50,
            'stop_loss_atr_mult': 2.0,      # ATR止损倍数
            'take_profit_atr_mult': 4.0,    # ATR止盈倍数
            'cooldown_after_sl': 5,          # 止损后冷却K线数
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        return {
            'sma_short': (10, 40),
            'sma_medium': (30, 80),
            'sma_long': (100, 300),
            'martingale_multiplier': (1.5, 2.5),
            'max_martingale_steps': (2, 6),
            'bb_period': (15, 40),
            'bb_std': (1.5, 2.5),
            'bbw_ma_period': (30, 100),
            'stop_loss_atr_mult': (1.5, 3.0),
            'take_profit_atr_mult': (3.0, 6.0),
        }

    def _calculate_position_size(self) -> float:
        base_size = self.params['position_size']
        multiplier = self.params['martingale_multiplier']
        return base_size * (multiplier ** self.martingale_step)

    @property
    def current_position_size(self) -> float:
        return self._calculate_position_size()

    def _update_martingale_state(self, trade_record: Dict[str, Any]):
        profit = trade_record.get('profit', 0)
        exit_reason = trade_record.get('exit_reason')

        if profit < 0:
            self.loss_count_in_step += 1
            if self.loss_count_in_step >= 2:
                max_steps = self.params['max_martingale_steps']
                if self.martingale_step < max_steps:
                    self.martingale_step += 1
                    self.loss_count_in_step = 0
        else:
            self.loss_count_in_step = 0
            if self.martingale_step > 0:
                self.martingale_step -= 1

        # 记录止损
        if exit_reason == ExitReason.STOP_LOSS:
            self.last_stop_loss_bar = self.entry_bar

        # 平仓后重置
        if exit_reason in [ExitReason.SIGNAL_REVERSE, ExitReason.FORCE_CLOSE, ExitReason.END_OF_DATA]:
            self.current_position = None
            self.entry_price = None

    def _validate_data(self, df: pd.DataFrame, current_idx: int) -> Optional[Tuple[str, str, str]]:
        """验证数据充足性（考虑ATR和BBW需要额外数据）"""
        min_bars = max(
            self.params['sma_long'],
            self.params['bb_period'] + self.params['bbw_ma_period'],
            14  # ATR period
        ) + 10

        if current_idx < min_bars:
            return None

        return super()._validate_data(df, current_idx)

    def _check_entry_filters(
        self,
        df: pd.DataFrame,
        current_idx: int,
        prev_bar: pd.Series
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        检查BBW和冷却期是否满足开仓条件

        Args:
            df: DataFrame包含指标数据
            current_idx: 当前索引
            prev_bar: 上一根K线数据

        Returns:
            (是否允许开仓, 附加信息字典)
        """
        # 冷却期检查
        bars_since_sl = current_idx - self.last_stop_loss_bar
        if bars_since_sl < self.params['cooldown_after_sl']:
            return False, {'cooldown': bars_since_sl}

        # ATR值检查
        atr = prev_bar.get('ATR', 0)
        if pd.isna(atr) or atr <= 0:
            atr = prev_bar.get('ATR_14', 0)
        if pd.isna(atr) or atr <= 0:
            return False, {'no_atr': True}

        # BBW检查
        bbw_col = 'BBW'
        bbw_ma_col = f"BBW_MA_{self.params['bbw_ma_period']}"
        allow_entry = True
        bbw_value, bbw_ma = 0.0, 0.0

        if bbw_col in df.columns and bbw_ma_col in df.columns:
            bbw_value = prev_bar[bbw_col]
            bbw_ma = prev_bar[bbw_ma_col]
            if pd.notna(bbw_value) and pd.notna(bbw_ma):
                allow_entry = bbw_value > bbw_ma

        return allow_entry, {
            'ATR': atr,
            'BBW': bbw_value,
            'BBW_MA': bbw_ma,
        }

    def _modify_entry_signal(
        self,
        signal: TradeSignal,
        **kwargs
    ) -> TradeSignal:
        """
        为入场信号添加ATR动态止损止盈

        Args:
            signal: 基础入场信号
            **kwargs: 额外上下文，包含 filter_info

        Returns:
            修改后的信号
        """
        filter_info = kwargs.get('filter_info', {})
        atr = filter_info.get('ATR', 0)
        if not atr or atr <= 0:
            return signal

        sl_mult = self.params['stop_loss_atr_mult']
        tp_mult = self.params['take_profit_atr_mult']

        if signal.direction == TradeDirection.LONG:
            signal.stop_loss = signal.entry_price - sl_mult * atr
            signal.take_profit = signal.entry_price + tp_mult * atr
            signal.reason += f" SL={signal.stop_loss:.2f} TP={signal.take_profit:.2f}"
        elif signal.direction == TradeDirection.SHORT:
            signal.stop_loss = signal.entry_price + sl_mult * atr
            signal.take_profit = signal.entry_price - tp_mult * atr
            signal.reason += f" SL={signal.stop_loss:.2f} TP={signal.take_profit:.2f}"

        return signal

    def _get_position_size_for_signal(self) -> Optional[float]:
        """获取当前信号应使用的仓位大小"""
        return self.current_position_size

    def on_trade_completed(self, trade_record: Dict[str, Any]):
        """交易完成回调"""
        self._update_martingale_state(trade_record)

        if trade_record.get('exit_reason') in [
            ExitReason.SIGNAL_REVERSE, ExitReason.FORCE_CLOSE, ExitReason.END_OF_DATA
        ]:
            self.current_position = None

    def reset(self):
        super().reset()
        self.current_position = None
        self.entry_price = None
        self.entry_bar = 0
        self.martingale_step = 0
        self.loss_count_in_step = 0
        self.cooldown_bars = 0
        self.last_stop_loss_bar = -1000

    def get_position_size(self) -> float:
        """获取当前仓位大小"""
        return self.current_position_size


def calculate_dollar_trader_martingale_sl_indicators(
    df: pd.DataFrame,
    sma_short: int = 20,
    sma_medium: int = 50,
    sma_long: int = 200,
    bb_period: int = 20,
    bb_std: float = 2.0,
    bbw_ma_period: int = 50,
    atr_period: int = 14
) -> pd.DataFrame:
    """计算策略所需指标"""
    result = calculate_dollar_trader_base_indicators(df, sma_short, sma_medium, sma_long)

    # BB & BBW
    result['BB_Upper'], result['BB_Middle'], result['BB_Lower'] = calculate_bollinger_bands(
        result['Close'], bb_period, bb_std
    )
    result['BBW'] = calculate_bbw(result['Close'], bb_period, bb_std)
    result[f'BBW_MA_{bbw_ma_period}'] = calculate_sma(result['BBW'], bbw_ma_period)

    # ATR
    result['ATR'] = calculate_atr(result, atr_period)

    return result
