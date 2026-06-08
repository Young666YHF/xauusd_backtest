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
版本: 3.0.0
"""

from typing import Dict, List, Optional, Any, Tuple
import pandas as pd

from strategies.dollar_trader_base import DollarTraderBaseStrategy, calculate_dollar_trader_base_indicators
from core.types import TradeSignal, TradeDirection, SignalType, ExitReason
from core.indicators import calculate_sma, calculate_bollinger_bands, calculate_bbw


class DollarTraderMartingaleBBWStepStrategy(DollarTraderBaseStrategy):
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
                - position_size: 基础仓位大小 (默认0.01)
                - martingale_multiplier: 马丁格尔倍数 (默认2.0)
                - max_martingale_steps: 最大阶梯层级 (默认5)
                - bb_period: 布林带周期 (默认20)
                - bb_std: 布林带标准差倍数 (默认2.0)
                - bbw_ma_period: BBW均线周期 (默认50)
            strategy_id: 策略标识
        """
        super().__init__(params, strategy_id or "DollarTraderMartingaleBBWStep")

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

    def _check_entry_filters(
        self,
        df: pd.DataFrame,
        current_idx: int,
        prev_bar: pd.Series
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        检查BBW是否满足开仓条件

        Args:
            df: DataFrame包含BBW数据
            current_idx: 当前索引
            prev_bar: 上一根K线数据

        Returns:
            (是否允许开仓, 附加信息字典)
        """
        bbw_col = 'BBW'
        bbw_ma_col = f"BBW_MA_{self.params['bbw_ma_period']}"

        # 确保BBW列存在
        if bbw_col not in df.columns or bbw_ma_col not in df.columns:
            # 如果没有BBW数据，默认允许开仓（保守策略）
            return True, {}

        # 获取当前BBW值（上一根已收盘K线）
        bbw_value = prev_bar[bbw_col]
        bbw_ma = prev_bar[bbw_ma_col]

        self.last_bbw_value = bbw_value
        self.last_bbw_ma = bbw_ma

        # 【Bug修复】数据无效时应该拒绝开仓，与Pine保持一致
        # bbwAllowEntry = not na(prevBBW) and not na(prevBBW_MA) and (prevBBW > prevBBW_MA)
        if pd.notna(bbw_value) and pd.notna(bbw_ma):
            allow_entry = bbw_value > bbw_ma
            return allow_entry, {'BBW': bbw_value, 'BBW_MA': bbw_ma, 'Step': self.martingale_step}

        # 数据无效，拒绝开仓（与Pine一致）
        return False, {}

    def _validate_data(self, df: pd.DataFrame, current_idx: int) -> Optional[Tuple[str, str, str]]:
        """验证数据充足性（考虑BBW需要额外数据）"""
        min_bars_needed = max(
            self.params['sma_long'],
            self.params['bb_period'] + self.params['bbw_ma_period']
        ) + 5

        if current_idx < min_bars_needed:
            return None

        return super()._validate_data(df, current_idx)

    def _get_position_size_for_signal(self) -> Optional[float]:
        """获取当前信号应使用的仓位大小"""
        return self.current_position_size

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
    result = calculate_dollar_trader_base_indicators(df, sma_short, sma_medium, sma_long)

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
