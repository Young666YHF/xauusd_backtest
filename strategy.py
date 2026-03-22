"""
XAUUSD 量化交易策略 - 重构版本
========================================
针对黄金高噪音、假突破和厚尾风险特性优化

主要改进:
- Module 1: 修复前视偏差、静态止盈、止损时间悖论
- Module 2: 增加异常流动性过滤和假突破过滤
- Module 3: 集成Optuna贝叶斯优化框架

作者: Quant Dev
日期: 2026-03-18
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import warnings

warnings.filterwarnings('ignore')


# =============================================================================
# 基础数据结构和枚举
# =============================================================================

class SignalType(Enum):
    """信号类型枚举"""
    NONE = 0
    LONG = 1
    SHORT = -1
    CLOSE_LONG = 2
    CLOSE_SHORT = -2


@dataclass
class TradeSignal:
    """交易信号数据结构"""
    timestamp: pd.Timestamp
    signal_type: SignalType
    strategy: str  # 'A' 或 'B'
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""
    # Module 1新增: 信号生成时的元数据，用于避免前视偏差
    signal_bar_index: int = 0  # 信号生成的K线索引
    execution_bar_index: int = 0  # 计划执行的K线索引（下一根）


@dataclass
class PendingSignal:
    """待确认信号数据结构（价格行为确认版本）"""
    breakout_bar_index: int           # 突破发生的K线索引
    direction: int                    # 1=做多, -1=做空
    breakout_price: float             # 突破价格
    bb_upper: float                   # 突破时的布林带上轨
    bb_lower: float                   # 突破时的布林带下轨
    atr: float                        # 突破时的ATR
    ema_diff: float                   # 突破时的EMA差值
    prev_low: float                   # 前一根K线低点
    prev_high: float                  # 前一根K线高点
    breakout_high: float              # 突破K线的最高价（用于价格行为确认）
    breakout_low: float               # 突破K线的最低价（用于价格行为确认）
    max_confirmation_bars: int        # 最大确认K线数（超时失败）
    bars_passed: int = 0              # 已经过的K线数
    triggered: bool = False           # 是否已触发（价格行为确认成功）
    failed: bool = False              # 是否已失败


@dataclass
class StrategyState:
    """策略状态跟踪（用于过滤逻辑）"""
    last_breakout_bar: Optional[int] = None  # 策略B：上次突破的K线索引
    breakout_direction: int = 0  # 1=向上突破, -1=向下突破
    pending_confirmation: bool = False  # 是否在等待回踩确认
    pending_signal: Optional[PendingSignal] = None  # 待确认的信号详情

    # 【加固3】信号时效性统计 - 记录失效机会
    expired_signals_count: int = 0  # 因超时失效的信号数量
    total_pending_signals: int = 0  # 总共产生的待确认信号数量


# =============================================================================
# 主策略类
# =============================================================================

class TradingStrategy:
    """
    XAUUSD 双策略交易系统

    策略A: 亚盘均值回归（Mean Reversion）
    - 适用于震荡市场，亚盘时段
    - 修复: 动态VWAP止盈、异常波动过滤、ATR自适应时间止损

    策略B: 动量突破（Momentum Breakout）
    - 适用于趋势市场
    - 修复: 回踩确认机制、EMA动能过滤
    """

    def __init__(self, params: Dict):
        """
        初始化策略

        Args:
            params: 策略参数字典，包含所有可优化参数
        """
        self.params = params
        self.state = StrategyState()

        # Module 2新增: 异常波动检测参数
        self.volatility_filter_period = params.get('volatility_filter_period', 20)
        self.volatility_filter_mult = params.get('volatility_filter_mult', 1.5)

        # Module 1新增: ATR自适应时间止损参数
        self.atr_time_stop_base = params.get('atr_time_stop_base', 3.0)
        self.atr_time_stop_mult = params.get('atr_time_stop_mult', 0.5)

        # Module 2新增: 假突破过滤参数
        self.pullback_confirmation_bars = params.get('pullback_confirmation_bars', 2)
        self.ema_momentum_threshold = params.get('ema_momentum_threshold', 0.001)

    # ========================================================================
    # Module 2: 异常流动性过滤 - 波动率检测
    # ========================================================================

    def check_abnormal_volatility(
        self,
        df: pd.DataFrame,
        current_idx: int,
        direction: int
    ) -> bool:
        """
        检查当前K线是否出现异常波动（Module 2 - 异常流动性过滤）

        逻辑:
        1. 计算前N根K线的平均ATR
        2. 如果当前K线的ATR超过均值 * 倍数，判定为极端波动
        3. 在极端波动时放弃均值回归信号（避免被恶意扫损）

        Args:
            df: 完整DataFrame
            current_idx: 当前K线索引
            direction: 1=多头信号, -1=空头信号

        Returns:
            True = 出现异常波动（应拦截信号）
            False = 正常波动
        """
        # 确保有足够的历史数据
        period = self.volatility_filter_period
        if current_idx < period + 1:
            return False  # 数据不足，不拦截

        # 获取前N根K线的ATR
        prev_atrs = df['ATR'].iloc[current_idx - period:current_idx]
        avg_atr = prev_atrs.mean()

        # 当前K线的波动范围
        current_bar = df.iloc[current_idx]
        current_range = current_bar['High'] - current_bar['Low']

        # 如果当前波动显著高于历史平均，判定为异常
        if avg_atr > 0 and current_range > avg_atr * self.volatility_filter_mult:
            return True  # 异常波动，拦截信号

        return False

    def calculate_dynamic_time_stop(
        self,
        df: pd.DataFrame,
        entry_idx: int,
        current_atr: float
    ) -> int:
        """
        计算基于ATR的动态时间止损（Module 1 - 止损时间悖论修复）

        逻辑:
        - ATR越大（波动越大），允许的持仓时间越短
        - ATR越小（波动越小），可以持仓更长时间等待回归
        - 公式: base_bars - (ATR / avg_ATR - 1) * multiplier

        Args:
            df: 完整DataFrame
            entry_idx: 入场K线索引
            current_atr: 当前ATR值

        Returns:
            动态计算的最大持仓K线数
        """
        base_bars = self.params.get('max_hold_bars_a', 5)

        # 计算近期平均ATR
        if entry_idx > 20:
            avg_atr = df['ATR'].iloc[entry_idx - 20:entry_idx].mean()
        else:
            avg_atr = current_atr

        if avg_atr <= 0:
            return base_bars

        # ATR比率
        atr_ratio = current_atr / avg_atr

        # 动态调整: ATR越大，持仓时间越短
        # 当ATR是平均的2倍时，持仓时间减半
        adjustment = (atr_ratio - 1) * self.atr_time_stop_mult * base_bars
        dynamic_bars = int(base_bars - adjustment)

        # 限制范围: 最少2根，最多原设定
        return max(2, min(base_bars, dynamic_bars))

    # ========================================================================
    # 市场状态检测
    # ========================================================================

    def detect_regime(self, row: pd.Series) -> str:
        """
        检测当前市场状态（震荡/趋势）

        Args:
            row: 包含所有指标的单行数据

        Returns:
            'range': 震荡市场（策略A适用）
            'trend': 趋势市场（策略B适用）
            'none': 无明确状态
        """
        squeeze_ratio = row['Squeeze_Ratio']
        threshold = self.params.get('squeeze_threshold', 0.8)

        is_asian = row['Is_Asian']
        is_european = row['Is_European']

        # 震荡状态: 布林带收缩在肯特纳通道内，且在亚盘
        if squeeze_ratio < threshold and is_asian:
            return 'range'

        # 趋势状态: 布林带扩张突破肯特纳通道，且在欧美盘
        if squeeze_ratio >= threshold and is_european:
            return 'trend'

        return 'none'

    # ========================================================================
    # Module 1 & 2: 策略A - 亚盘均值回归（修复版）
    # ========================================================================

    def generate_strategy_a_signal(
        self,
        df: pd.DataFrame,
        idx: int
    ) -> Optional[TradeSignal]:
        """
        策略A: 亚盘均值回归策略（重构版）

        核心修复:
        1. 止损锚定信号生成时的技术位，不锚定未知的开盘价
        2. 策略只输出订单意图，不访问下一根K线数据
        3. 回测引擎负责处理开盘价和滑点

        做多条件:
        - 亚盘时段
        - 价格触及布林带下轨
        - RSI < 超卖阈值
        - 无异常波动

        止损逻辑（关键修复）:
        - 止损锚定信号K线的Close或布林带下轨
        - 如果下一根K线开盘价击穿止损，放弃交易
        """
        row = df.iloc[idx]

        # 只在亚盘时段生效
        if not row['Is_Asian']:
            return None

        # 获取参数
        rsi_oversold = self.params.get('rsi_oversold', 21)
        rsi_overbought = self.params.get('rsi_overbought', 75)
        stop_loss_mult = self.params.get('stop_loss_atr_mult_a', 1.2)

        close = row['Close']
        bb_lower = row['BB_Lower']
        bb_upper = row['BB_Upper']
        rsi = row['RSI']
        atr = row['ATR']

        direction = 0

        # 做多信号检测
        if close <= bb_lower and rsi < rsi_oversold:
            direction = 1

        # 做空信号检测
        elif close >= bb_upper and rsi > rsi_overbought:
            direction = -1

        if direction == 0:
            return None

        # Module 2新增: 异常波动过滤
        if self.check_abnormal_volatility(df, idx, direction):
            return None  # 异常波动，放弃信号

        # ========== 关键修复：止损锚定信号生成时的技术位 ==========
        # 止损不再锚定未知的开盘价，而是锚定当前已知的技术位
        # 这样即使开盘价跳空，止损线也不会"滑坡"
        if direction == 1:
            # 多头：止损锚定布林带下轨或收盘价较低者
            # 这是最坏情况下的技术支撑位
            stop_loss = min(close, bb_lower) - stop_loss_mult * atr
            reason = f"均值回归做多: 价格{close:.2f}触及下轨, RSI={rsi:.1f}"
        else:
            # 空头：止损锚定布林带上轨或收盘价较高者
            stop_loss = max(close, bb_upper) + stop_loss_mult * atr
            reason = f"均值回归做空: 价格{close:.2f}触及上轨, RSI={rsi:.1f}"

        # ========== 策略解耦：只输出订单意图 ==========
        # 不再访问 next_bar['Open']
        # entry_price 设为 None，由回测引擎填充实际开盘价
        # signal_bar_index 和 execution_bar_index 告诉引擎何时执行
        signal = TradeSignal(
            timestamp=df.index[idx],
            signal_type=SignalType.LONG if direction == 1 else SignalType.SHORT,
            strategy='A',
            entry_price=None,  # 由回测引擎填充开盘价
            stop_loss=stop_loss,  # 锚定信号时的技术位
            take_profit=None,  # 动态VWAP止盈
            reason=reason,
            signal_bar_index=idx,
            execution_bar_index=idx + 1  # 下一根K线开盘执行
        )

        return signal

    # ========================================================================
    # Module 2: 策略B - 动量突破（假突破过滤版）
    # ========================================================================

    def check_pullback_confirmation(
        self,
        df: pd.DataFrame,
        current_idx: int,
        pending: PendingSignal
    ) -> Tuple[bool, bool, str]:
        """
        检查当前K线是否满足价格行为确认条件（修复"接盘"问题）

        【修复3.1】放宽价格行为确认条件
        - 多头: 只要不跌破布林带中轨，且价格突破 breakout_high 即可入场
        - 空头: 只要不突破布林带中轨，且价格跌破 breakout_low 即可入场

        原逻辑过于严苛：
        - 要求收盘价始终在布林带外（导致大量有效突破被过滤）
        - 只在创新高/低时触发（错过了很多趋势初期机会）

        新逻辑：
        - 使用布林带中轨作为"趋势生存线"
        - 价格行为确认改为"突破触发"而非"等待回调"

        Args:
            df: 完整DataFrame
            current_idx: 当前K线索引
            pending: 待确认信号

        Returns:
            (确认是否完成, 确认是否失败, 原因说明)
        """
        current_bar = df.iloc[current_idx]
        high = current_bar['High']
        low = current_bar['Low']
        close = current_bar['Close']

        # 获取布林带中轨（趋势生存线）
        bb_middle = current_bar['BB_Middle']

        # 更新已过K线数
        pending.bars_passed += 1

        # 检查是否超时
        if pending.bars_passed > pending.max_confirmation_bars:
            return False, True, f"确认超时: {pending.bars_passed}根K线未触发价格行为确认"

        # ═══════════════════════════════════════════════════════════════════════
        # 【修复3.1】放宽的价格行为确认逻辑
        # ═══════════════════════════════════════════════════════════════════════

        if pending.direction == 1:  # 向上突破
            # 【放宽】条件1: 价格突破突破K线最高价 → 触发入场
            if high > pending.breakout_high:
                pending.triggered = True
                return True, False, f"价格行为确认成功: 最高价{high:.2f}突破{pending.breakout_high:.2f}"

            # 【放宽】条件2: 收盘价跌破布林带中轨 → 趋势失败
            # 原逻辑: 收盘价 < bb_upper 就失败（太严苛）
            # 新逻辑: 收盘价 < bb_middle 才失败（允许回调）
            if close < bb_middle:
                return False, True, f"确认失败: 收盘价{close:.2f}跌破中轨{bb_middle:.2f}"

        else:  # 向下突破
            # 【放宽】条件1: 价格跌破突破K线最低价 → 触发入场
            if low < pending.breakout_low:
                pending.triggered = True
                return True, False, f"价格行为确认成功: 最低价{low:.2f}跌破{pending.breakout_low:.2f}"

            # 【放宽】条件2: 收盘价突破布林带中轨 → 趋势失败
            if close > bb_middle:
                return False, True, f"确认失败: 收盘价{close:.2f}突破中轨{bb_middle:.2f}"

        # 继续等待
        return False, False, f"等待价格行为确认: {pending.bars_passed}/{pending.max_confirmation_bars}"

    def generate_strategy_b_signal(
        self,
        df: pd.DataFrame,
        idx: int
    ) -> Optional[TradeSignal]:
        """
        策略B: 动量突破策略（延迟确认版本 - 消除前视偏差）

        改进点:
        1. Module 2: 不再在突破K线立即入场
        2. Module 2: 延迟确认机制 - 在后续K线检查确认条件
        3. Module 1: 使用确认后下一根K线Open作为入场价

        入场条件:
        1. 价格突破布林带
        2. 波动率爆发（布林带突破肯特纳通道）
        3. EMA多头排列/空头排列
        4. 后续N根K线回踩确认通过

        延迟确认机制（消除前视偏差）:
        - 突破K线idx: 检测到突破 → 创建PendingSignal
        - K线idx+1: 检查确认条件1
        - K线idx+2: 检查确认条件2
        - K线idx+confirmation_bars: 如果所有条件通过 → 生成信号
        - K线idx+confirmation_bars+1: 执行入场
        """
        row = df.iloc[idx]

        # ========================================
        # 步骤1: 检查是否有待确认的信号
        # ========================================
        if self.state.pending_signal is not None and not self.state.pending_signal.failed:
            pending = self.state.pending_signal

            # 检查当前K线是否是预期的确认K线
            expected_idx = pending.breakout_bar_index + pending.bars_passed + 1

            if idx == expected_idx:
                # 执行确认检查
                confirmed, failed, reason = self.check_pullback_confirmation(df, idx, pending)

                if failed:
                    # 【加固3】记录失效机会
                    self.state.expired_signals_count += 1
                    # 确认失败，清除待确认状态
                    self.state.pending_signal = None
                    self.state.pending_confirmation = False
                    return None

                if confirmed:
                    # 确认通过，生成交易信号
                    signal = self._create_signal_from_pending(df, idx, pending)

                    # 清除待确认状态
                    self.state.pending_signal = None
                    self.state.pending_confirmation = False

                    return signal

                # 确认继续，等待下一根K线
                return None

            elif idx > expected_idx:
                # 跳过了某些K线，清除待确认状态
                self.state.pending_signal = None
                self.state.pending_confirmation = False

        # ========================================
        # 步骤2: 检查是否有新的突破信号
        # ========================================
        if self.state.pending_signal is not None:
            return None  # 已有待确认信号，不检测新突破

        # 检查市场状态
        regime = self.detect_regime(row)
        squeeze_release = row.get('Squeeze_Release', False)

        if regime != 'trend' and not squeeze_release:
            return None

        close = row['Close']
        bb_lower = row['BB_Lower']
        bb_upper = row['BB_Upper']
        kc_lower = row['KC_Lower']
        kc_upper = row['KC_Upper']
        atr = row['ATR']
        ema_fast = row['EMA_Fast']
        ema_slow = row['EMA_Slow']

        direction = 0

        # ═══════════════════════════════════════════════════════════════════════
        # 【修复3.2】EMA 动能过滤 - 激活幽灵参数 ema_momentum_threshold
        # ═══════════════════════════════════════════════════════════════════════

        # 计算 EMA 发散动能
        ema_momentum = abs(ema_fast - ema_slow) / ema_slow
        ema_momentum_threshold = self.ema_momentum_threshold  # 从 params 获取

        # 向上突破检测 - 增加 EMA 动能过滤
        if close > bb_upper and bb_upper > kc_upper:
            # 原条件: 仅 ema_fast > ema_slow
            # 新条件: ema_fast > ema_slow 且发散动能足够
            if ema_fast > ema_slow:
                # 【激活】EMA 动能过滤
                if ema_momentum > ema_momentum_threshold:
                    direction = 1
                # else: EMA 虽然金叉但发散不足，不入场

        # 向下突破检测 - 增加 EMA 动能过滤
        elif close < bb_lower and bb_lower < kc_lower:
            # 原条件: 仅 ema_fast < ema_slow
            # 新条件: ema_fast < ema_slow 且发散动能足够
            if ema_fast < ema_slow:
                # 【激活】EMA 动能过滤
                if ema_momentum > ema_momentum_threshold:
                    direction = -1
                # else: EMA 虽然死叉但发散不足，不入场

        if direction == 0:
            return None

        # ========================================
        # 步骤3: 创建待确认信号（价格行为确认机制）
        # ========================================
        prev_low = df.iloc[idx - 1]['Low'] if idx > 0 else row['Low']
        prev_high = df.iloc[idx - 1]['High'] if idx > 0 else row['High']

        pending = PendingSignal(
            breakout_bar_index=idx,
            direction=direction,
            breakout_price=close,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            atr=atr,
            ema_diff=ema_fast - ema_slow if direction == 1 else ema_slow - ema_fast,
            prev_low=prev_low,
            prev_high=prev_high,
            breakout_high=row['High'],  # 突破K线最高价（用于价格行为确认）
            breakout_low=row['Low'],    # 突破K线最低价（用于价格行为确认）
            max_confirmation_bars=self.pullback_confirmation_bars,  # 最大确认K线数
            bars_passed=0,
            triggered=False,
            failed=False
        )

        self.state.pending_signal = pending
        self.state.pending_confirmation = True
        self.state.last_breakout_bar = idx
        self.state.breakout_direction = direction

        # 【加固3】统计待确认信号数量
        self.state.total_pending_signals += 1

        return None  # 暂不生成信号，等待确认

    def _create_signal_from_pending(
        self,
        df: pd.DataFrame,
        current_idx: int,
        pending: PendingSignal
    ) -> Optional[TradeSignal]:
        """
        从待确认信号创建实际交易信号

        【架构重构说明】
        策略模块现在只输出"纯理论订单意图"，不处理任何微观结构问题：
        - 滑点扣除：由 tick_engine.py 在 Tick 级撮合时处理
        - 跳空检测：由 tick_engine.py 通过 Bid/Ask 验证处理
        - 入场价格：直接使用突破价格，不加减滑点

        这样设计的原因：
        1. 避免双重滑点（策略层扣一次，引擎层又扣一次）
        2. 让 Tick 引擎掌握完整的微观成交信息
        3. 策略层专注于信号逻辑，引擎层专注于撮合逻辑

        Args:
            df: 完整DataFrame
            current_idx: 当前K线索引（确认通过的K线）
            pending: 待确认信号

        Returns:
            TradeSignal 或 None
        """
        # 【Task 1 修复】精简入场逻辑
        # 直接使用突破价格，不再处理滑点和跳空
        # 所有微观结构问题交由 tick_engine.py 处理
        if pending.direction == 1:
            # 多头: 入场价 = 突破高点 (纯理论意图)
            entry_price = pending.breakout_high
        else:
            # 空头: 入场价 = 突破低点 (纯理论意图)
            entry_price = pending.breakout_low

        stop_loss_mult = self.params.get('stop_loss_atr_mult_b', 2.11)

        # 止损计算（基于纯净的入场价）
        if pending.direction == 1:
            atr_stop = entry_price - stop_loss_mult * pending.atr
            price_stop = pending.prev_low
            stop_loss = max(atr_stop, price_stop)
            reason = f"动量突破做多: 入场@{entry_price:.2f}, 止损@{stop_loss:.2f}"
        else:
            atr_stop = entry_price + stop_loss_mult * pending.atr
            price_stop = pending.prev_high
            stop_loss = min(atr_stop, price_stop)
            reason = f"动量突破做空: 入场@{entry_price:.2f}, 止损@{stop_loss:.2f}"

        return TradeSignal(
            timestamp=df.index[current_idx],
            signal_type=SignalType.LONG if pending.direction == 1 else SignalType.SHORT,
            strategy='B',
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=None,  # 策略B使用追踪止损
            reason=reason,
            signal_bar_index=current_idx,
            execution_bar_index=current_idx
        )

    # ========================================================================
    # 信号生成主函数
    # ========================================================================

    def generate_signals(
        self,
        df: pd.DataFrame
    ) -> List[TradeSignal]:
        """
        生成所有交易信号

        Args:
            df: 包含所有指标的DataFrame

        Returns:
            交易信号列表
        """
        signals = []

        # 跳过预热期
        start_idx = max(100, self.params.get('ema_slow', 64))

        # 确保有足够数据用于策略B的回踩确认
        start_idx = max(start_idx, self.volatility_filter_period + 5)

        for idx in range(start_idx, len(df) - 1):  # -1确保有下一根K线
            # 策略A信号
            signal_a = self.generate_strategy_a_signal(df, idx)
            if signal_a:
                signals.append(signal_a)
                continue

            # 策略B信号
            signal_b = self.generate_strategy_b_signal(df, idx)
            if signal_b:
                signals.append(signal_b)

        return signals

    # ========================================================================
    # Module 1: 出场条件检查（重构版 - 修复出场价格幽灵化 + VWAP时间旅行）
    # ========================================================================

    def check_exit_conditions(
        self,
        position: Dict,
        current_bar: pd.Series,
        bars_held: int,
        df: pd.DataFrame = None,
        current_idx: int = None
    ) -> Tuple[bool, str, Optional[float]]:
        """
        检查出场条件（重构版）

        核心修复:
        1. 返回实际出场价格 (exit_price)，而非由回测引擎臆测
        2. VWAP使用前一根K线的值，避免时间旅行偏差
        3. 跳空越过止盈/止损时，使用开盘价出场（加滑点惩罚）

        Args:
            position: 当前持仓信息
            current_bar: 当前K线数据
            bars_held: 持仓K线数
            df: 完整DataFrame
            current_idx: 当前K线索引

        Returns:
            (是否出场, 出场原因, 实际出场价格)
        """
        if not position:
            return False, "", None

        direction = position['direction']
        entry_price = position['entry_price']
        stop_loss = position['stop_loss']
        strategy = position['strategy']

        high = current_bar['High']
        low = current_bar['Low']
        open_price = current_bar['Open']
        close = current_bar['Close']
        atr = current_bar['ATR']

        # ========== 滑点常量 ==========
        BASE_SLIPPAGE = 0.15
        ATR_SLIPPAGE_RATIO = 0.03
        slippage = BASE_SLIPPAGE + atr * ATR_SLIPPAGE_RATIO

        # ========== 【加固1】跳空惩罚性滑点 ==========
        # 当开盘价跳空越过止损时，流动性枯竭，滑点应加倍惩罚
        GAP_SLIPPAGE_MULTIPLIER = 2.0  # 跳空时滑点翻倍

        # ====================================================================
        # 策略A出场逻辑（重构版）
        # ====================================================================
        if strategy == 'A':
            # ========== 止损检查 ==========
            if direction == 1:  # 多头
                if low <= stop_loss:
                    # 检查是否跳空击穿（开盘价已在止损以下）
                    if open_price <= stop_loss:
                        # 【加固1】跳空击穿：使用开盘价 + 惩罚性滑点强制平仓
                        # 严禁等待价格回调，流动性枯竭时必须认赔
                        gap_slippage = slippage * GAP_SLIPPAGE_MULTIPLIER
                        exit_price = open_price - gap_slippage
                        return True, f"止损跳空: 开盘{open_price:.2f}击穿止损{stop_loss:.2f} (惩罚滑点{gap_slippage:.2f})", exit_price
                    else:
                        # 正常触及：使用止损价
                        exit_price = stop_loss
                        return True, f"止损: 最低价{low:.2f}触及止损{stop_loss:.2f}", exit_price
            else:  # 空头
                if high >= stop_loss:
                    if open_price >= stop_loss:
                        # 【加固1】跳空击穿：使用开盘价 + 惩罚性滑点强制平仓
                        gap_slippage = slippage * GAP_SLIPPAGE_MULTIPLIER
                        exit_price = open_price + gap_slippage
                        return True, f"止损跳空: 开盘{open_price:.2f}击穿止损{stop_loss:.2f} (惩罚滑点{gap_slippage:.2f})", exit_price
                    else:
                        exit_price = stop_loss
                        return True, f"止损: 最高价{high:.2f}触及止损{stop_loss:.2f}", exit_price

            # ========== VWAP止盈检查（修复时间旅行偏差）==========
            # 关键修复：使用前一根K线的VWAP，避免使用当前K线收盘后的值
            prev_vwap = None
            if df is not None and current_idx is not None and current_idx > 0:
                prev_vwap = df.iloc[current_idx - 1]['VWAP']

            # 如果没有前一根K线的VWAP，使用当前K线的作为后备
            vwap = prev_vwap if prev_vwap is not None else current_bar['VWAP']

            if direction == 1:  # 多头
                if high >= vwap:
                    # 检查是否跳空越过VWAP
                    if open_price >= vwap:
                        # 跳空越过：使用开盘价出场（更差的价格）
                        exit_price = open_price
                        return True, f"止盈跳空: 开盘{open_price:.2f}越过VWAP{vwap:.2f}", exit_price
                    else:
                        # 正常触及：使用VWAP价格
                        exit_price = vwap
                        return True, f"止盈: 最高价{high:.2f}触及VWAP{vwap:.2f}", exit_price
            else:  # 空头
                if low <= vwap:
                    if open_price <= vwap:
                        exit_price = open_price
                        return True, f"止盈跳空: 开盘{open_price:.2f}越过VWAP{vwap:.2f}", exit_price
                    else:
                        exit_price = vwap
                        return True, f"止盈: 最低价{low:.2f}触及VWAP{vwap:.2f}", exit_price

            # ========== 时间止损 ==========
            if df is not None and current_idx is not None:
                dynamic_max_bars = self.calculate_dynamic_time_stop(
                    df, current_idx - bars_held, atr
                )
            else:
                dynamic_max_bars = self.params.get('max_hold_bars_a', 5)

            if bars_held >= dynamic_max_bars:
                # 时间止损使用收盘价
                exit_price = close
                return True, f"时间止损: 持仓{bars_held}根K线(动态上限{dynamic_max_bars})", exit_price

        # ====================================================================
        # 策略B出场逻辑（修复版）
        # ====================================================================
        elif strategy == 'B':
            trailing_mult = self.params.get('trailing_stop_atr_mult', 3.5)

            # 【加固2】策略B滑点动态化：突破行情流动性真空，滑点加大
            # 基础滑点 + ATR * 0.1 (比策略A更大的滑点压力测试)
            strategy_b_slippage = BASE_SLIPPAGE + atr * 0.1

            # 更新最高/最低价
            if direction == 1:  # 多头
                if 'highest_price' not in position:
                    position['highest_price'] = entry_price
                position['highest_price'] = max(position['highest_price'], high)

                # 初始止损检查
                if low <= stop_loss:
                    if open_price <= stop_loss:
                        # 【加固1】跳空击穿：惩罚性滑点
                        gap_slippage = strategy_b_slippage * GAP_SLIPPAGE_MULTIPLIER
                        exit_price = open_price - gap_slippage
                        return True, f"初始止损跳空: 开盘{open_price:.2f}击穿止损{stop_loss:.2f} (惩罚滑点{gap_slippage:.2f})", exit_price
                    else:
                        exit_price = stop_loss
                        return True, f"初始止损: 最低价{low:.2f}触及止损{stop_loss:.2f}", exit_price

                # 追踪止损检查
                trailing_stop = position['highest_price'] - trailing_mult * atr
                if low <= trailing_stop and position['highest_price'] > entry_price:
                    if open_price <= trailing_stop:
                        # 【加固1】跳空击穿：惩罚性滑点
                        gap_slippage = strategy_b_slippage * GAP_SLIPPAGE_MULTIPLIER
                        exit_price = open_price - gap_slippage
                        return True, f"追踪止损跳空: 开盘{open_price:.2f}击穿{trailing_stop:.2f} (惩罚滑点{gap_slippage:.2f})", exit_price
                    else:
                        exit_price = trailing_stop
                        return True, f"追踪止损: 最低价{low:.2f}触及追踪止损{trailing_stop:.2f}", exit_price

            else:  # 空头
                if 'lowest_price' not in position:
                    position['lowest_price'] = entry_price
                position['lowest_price'] = min(position['lowest_price'], low)

                # 初始止损检查
                if high >= stop_loss:
                    if open_price >= stop_loss:
                        # 【加固1】跳空击穿：惩罚性滑点
                        gap_slippage = strategy_b_slippage * GAP_SLIPPAGE_MULTIPLIER
                        exit_price = open_price + gap_slippage
                        return True, f"初始止损跳空: 开盘{open_price:.2f}击穿止损{stop_loss:.2f} (惩罚滑点{gap_slippage:.2f})", exit_price
                    else:
                        exit_price = stop_loss
                        return True, f"初始止损: 最高价{high:.2f}触及止损{stop_loss:.2f}", exit_price

                # 追踪止损检查
                trailing_stop = position['lowest_price'] + trailing_mult * atr
                if high >= trailing_stop and position['lowest_price'] < entry_price:
                    if open_price >= trailing_stop:
                        # 【加固1】跳空击穿：惩罚性滑点
                        gap_slippage = strategy_b_slippage * GAP_SLIPPAGE_MULTIPLIER
                        exit_price = open_price + gap_slippage
                        return True, f"追踪止损跳空: 开盘{open_price:.2f}击穿{trailing_stop:.2f} (惩罚滑点{gap_slippage:.2f})", exit_price
                    else:
                        exit_price = trailing_stop
                        return True, f"追踪止损: 最高价{high:.2f}触及追踪止损{trailing_stop:.2f}", exit_price

        return False, "", None


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print("="*70)
    print("XAUUSD 重构策略测试")
    print("="*70)

    # 测试参数
    # 贝叶斯优化参数 (Optuna TPE 200次, 2025-12至2026-02)
    # 表现: 收益191.91%, 回撤7.20%, 夏普5.25
    test_params = {
        # 基础参数
        'bb_period': 13,
        'bb_std': 1.62,
        'kc_period': 25,
        'kc_atr_mult': 1.30,
        'atr_period': 19,
        'rsi_period': 21,

        # 策略A参数
        'rsi_oversold': 23,
        'rsi_overbought': 77,
        'stop_loss_atr_mult_a': 1.36,
        'max_hold_bars_a': 7,

        # 策略B参数
        'ema_fast': 17,
        'ema_slow': 32,
        'stop_loss_atr_mult_b': 1.69,
        'trailing_stop_atr_mult': 4.54,

        # 波动率过滤器
        'squeeze_threshold': 0.96,

        # Module 1: ATR自适应时间止损参数
        'atr_time_stop_base': 2.71,
        'atr_time_stop_mult': 0.76,

        # Module 2: 异常波动过滤参数
        'volatility_filter_period': 14,
        'volatility_filter_mult': 1.79,

        # Module 2: 假突破过滤参数
        'pullback_confirmation_bars': 3,
        'ema_momentum_threshold': 0.00082,
    }

    print("\n策略参数:")
    for k, v in test_params.items():
        print(f"  {k}: {v}")

    print("\n测试完成。使用 optuna_optimizer.py 中的函数进行参数优化。")
