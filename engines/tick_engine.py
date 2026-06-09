"""
Tick级别回测引擎 - Numba加速版
===============================
基于Tick数据的高精度回测引擎，核心循环使用Numba JIT编译加速

特性：
- Numba JIT加速（核心tick循环）
- 非对称滑点模型
- 保证金和爆仓检测
- 新闻事件过滤
"""

from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import pandas as pd
import numpy as np
from datetime import datetime

from .base import BaseBacktestEngine, ExecutionModel, StrategyCategory
from core.types import TradeSignal, ExitReason, BacktestResult, TradeDirection
from core.config import TradingConfig

# =============================================================================
# Numba JIT编译的核心函数 - 放在模块顶层以便编译
# =============================================================================

try:
    from numba import njit, prange

    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False

    # 创建虚拟装饰器
    def njit(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    prange = range


@njit(cache=True, fastmath=True)
def _check_ticks_for_exit_numba(
    tick_mids: np.ndarray,
    tick_bids: np.ndarray,
    tick_asks: np.ndarray,
    tick_start: int,
    tick_end: int,
    is_long: bool,
    stop_loss: float,
    take_profit: float,
    entry_price: float,
    entry_bar: int,
    max_bars: int,
    current_bar: int,
) -> Tuple[int, float, int]:  # (exit_code, exit_price, tick_idx)
    """
    Numba加速的tick出场检查

    Returns:
        exit_code: 0=无出场, 1=止损, 2=止盈, 3=时间止损
        exit_price: 出场价格
        tick_idx: 出场tick索引
    """
    bars_held = current_bar - entry_bar

    for tick_idx in range(tick_start, tick_end):
        tick_bid = tick_bids[tick_idx]
        tick_ask = tick_asks[tick_idx]

        if is_long:
            # 多头止损：Bid <= StopLoss
            if stop_loss > 0 and tick_bid <= stop_loss:
                return 1, stop_loss, tick_idx
            # 多头止盈：Bid >= TakeProfit
            if take_profit > 0 and tick_bid >= take_profit:
                return 2, take_profit, tick_idx
        else:
            # 空头止损：Ask >= StopLoss
            if stop_loss > 0 and tick_ask >= stop_loss:
                return 1, stop_loss, tick_idx
            # 空头止盈：Ask <= TakeProfit
            if take_profit > 0 and tick_ask <= take_profit:
                return 2, take_profit, tick_idx

    return 0, 0.0, tick_end


@njit(cache=True, fastmath=True)
def _find_entry_in_ticks_numba(
    tick_bids: np.ndarray,
    tick_asks: np.ndarray,
    tick_start: int,
    tick_end: int,
    is_long: bool,
    target_price: float,
) -> Tuple[bool, float, int]:  # (found, price, tick_idx)
    """
    Numba加速的入场价格查找

    Returns:
        found: 是否找到
        price: 成交价格
        tick_idx: 成交tick索引
    """
    for tick_idx in range(tick_start, tick_end):
        if is_long:
            # 多头：Ask <= Target时成交
            if tick_asks[tick_idx] <= target_price:
                return True, target_price, tick_idx
        else:
            # 空头：Bid >= Target时成交
            if tick_bids[tick_idx] >= target_price:
                return True, target_price, tick_idx

    return False, 0.0, tick_start


class TickBacktestEngine(BaseBacktestEngine):
    """
    Tick级别回测引擎 - 强制Numba加速版

    特点：
    - Tick级精度
    - 强制Numba JIT加速（无Python回退）
    - 非对称滑点
    - 保证金检测
    """

    def __init__(
        self,
        config: TradingConfig,
        execution_model: Optional[ExecutionModel] = None,
        risk_manager=None,
        max_bars: Optional[int] = None,
    ):
        super().__init__(config, execution_model, risk_manager)
        # 强制使用Numba，Numba不可用时报错
        if not NUMBA_AVAILABLE:
            raise RuntimeError(
                "Numba is required for TickBacktestEngine. "
                "Please install: pip install numba"
            )

        # 最大持仓K线数（从策略参数传入，默认10）
        self.max_bars = max_bars or 10

        # Tick数据
        self.tick_df: Optional[pd.DataFrame] = None
        self.bar_idx_to_ticks: Optional[np.ndarray] = None
        self._adjusted_entries: List[Dict] = []

        # 缓存numpy数组引用
        self._tick_mids: Optional[np.ndarray] = None
        self._tick_bids: Optional[np.ndarray] = None
        self._tick_asks: Optional[np.ndarray] = None

    def reset(self):
        """重置引擎状态"""
        super().reset()
        self.tick_df = None
        self.bar_idx_to_ticks = None
        self._adjusted_entries = []
        self._tick_mids = None
        self._tick_bids = None
        self._tick_asks = None

    def prepare_tick_data(
        self, tick_df: pd.DataFrame, bar_timestamps: pd.DatetimeIndex
    ) -> np.ndarray:
        """
        准备Tick数据，建立K线索引到Tick索引的映射

        Args:
            tick_df: Tick数据
            bar_timestamps: K线时间戳

        Returns:
            映射数组 bar_idx -> [start_tick_idx, end_tick_idx]
        """
        n_bars = len(bar_timestamps)
        mapping = np.zeros((n_bars, 2), dtype=np.int32)

        tick_times = tick_df.index
        tick_idx = 0
        n_ticks = len(tick_df)

        for bar_idx in range(n_bars):
            bar_time = bar_timestamps[bar_idx]

            # 找到当前K线范围内的第一个Tick
            start_idx = tick_idx
            while tick_idx < n_ticks and tick_times[tick_idx] < bar_time:
                tick_idx += 1
            start_idx = tick_idx

            # 找到下一个K线之前的所有Tick
            if bar_idx < n_bars - 1:
                next_bar_time = bar_timestamps[bar_idx + 1]
                while tick_idx < n_ticks and tick_times[tick_idx] < next_bar_time:
                    tick_idx += 1
            else:
                tick_idx = n_ticks

            mapping[bar_idx] = [start_idx, tick_idx]

        return mapping

    def run(
        self,
        df: pd.DataFrame,
        signals: List[TradeSignal],
        tick_df: Optional[pd.DataFrame] = None,
    ) -> BacktestResult:
        """
        执行Tick级回测

        Args:
            df: OHLCV数据（用于信号生成和参考）
            signals: 交易信号列表
            tick_df: Tick数据（可选，如果提供则使用Tick级精度）

        Returns:
            BacktestResult
        """
        self.reset()
        self._df = df
        self.tick_df = tick_df

        # 准备Tick映射
        if tick_df is not None:
            self.bar_idx_to_ticks = self.prepare_tick_data(tick_df, df.index)
            # 缓存numpy数组引用，避免重复访问
            self._tick_mids = tick_df["Mid"].values
            self._tick_bids = tick_df["Bid"].values
            self._tick_asks = tick_df["Ask"].values

        # 按执行索引排序信号 - 使用defaultdict优化
        signal_dict = defaultdict(list)
        for sig in signals:
            signal_dict[sig.execution_bar_index].append(sig)

        # 遍历K线
        for i in range(len(df)):
            self._current_bar_idx = i
            bar = df.iloc[i]
            timestamp = df.index[i]

            # 处理持仓（强制使用Numba加速Tick处理）
            if self.position:
                self._process_position_tick(i, bar, timestamp)

            # 处理入场
            if i in signal_dict and not self.position:
                for signal in signal_dict[i]:
                    self._process_entry(signal, bar)

            # 记录权益
            equity = self.get_current_equity()
            self.equity_curve.append(equity)
            self.equity_timestamps.append(timestamp)

        # 强制平仓
        if self.position:
            last_bar = df.iloc[-1]
            self._close_position(last_bar["Close"], ExitReason.END_OF_DATA, 0.0)

        return self._build_result()

    def _process_position_tick(self, bar_idx: int, bar: pd.Series, timestamp: datetime):
        """使用Numba加速的tick持仓处理"""
        if self.bar_idx_to_ticks is None or self._tick_mids is None:
            return

        pos = self.position
        pos.bars_held = bar_idx - pos.entry_bar_index

        tick_start, tick_end = self.bar_idx_to_ticks[bar_idx]

        # 调用Numba加速函数检查出场条件
        exit_code, exit_price, _ = _check_ticks_for_exit_numba(
            self._tick_mids,
            self._tick_bids,
            self._tick_asks,
            tick_start,
            tick_end,
            pos.is_long,
            pos.stop_loss if pos.stop_loss else 0.0,
            pos.take_profit if pos.take_profit else 0.0,
            pos.entry_price,
            pos.entry_bar_index,
            self.max_bars,
            bar_idx,
        )

        atr = bar.get("ATR", 0)

        # 处理出场
        if exit_code == 1:  # 止损
            slippage = self._calculate_exit_slippage(
                exit_price, atr, ExitReason.STOP_LOSS
            )
            self._close_position(exit_price, ExitReason.STOP_LOSS, slippage)
            return
        elif exit_code == 2:  # 止盈
            self._close_position(exit_price, ExitReason.TAKE_PROFIT, 0.0)
            return

        # 检查时间止损（在K线结束时）
        if pos.bars_held >= self.max_bars:
            slippage = self._calculate_exit_slippage(
                bar["Close"], atr, ExitReason.TIME_STOP
            )
            self._close_position(bar["Close"], ExitReason.TIME_STOP, slippage)
            return

    def _process_entry(self, signal: TradeSignal, bar: pd.Series):
        """
        处理入场 - 灵活入场模式（强制Numba加速）

        当信号入场价超出当前K线范围时，以开盘价追单成交。
        不使用未来数据，只使用当前K线的 OHLC。
        """
        atr = bar.get("ATR", 0)
        strategy_category = (
            StrategyCategory.MEAN_REVERSION
            if "MeanReversion" in signal.strategy_id
            else StrategyCategory.MOMENTUM_BREAKOUT
        )

        # 确定入场价格（强制使用Numba加速）
        entry_price = self._find_entry_price_tick(signal)

        if entry_price is None:
            entry_price = bar["Open"]

        # 灵活入场：调整超出K线范围的入场价
        # 不使用未来数据，只使用当前K线的 Open/High/Low
        original_price = entry_price
        adjusted = False

        if signal.direction == TradeDirection.LONG:
            # 做多：入场价不能高于High，不能低于Low
            if entry_price > bar["High"]:
                # 跳空高开：以开盘价追入（模拟开盘市价单）
                entry_price = bar["Open"]
                adjusted = True
            elif entry_price < bar["Low"]:
                # 低于最低价：使用Low（价格已经到过）
                entry_price = bar["Low"]
                adjusted = True
        else:
            # 做空：入场价不能低于Low，不能高于High
            if entry_price < bar["Low"]:
                # 跳空低开：以开盘价追入
                entry_price = bar["Open"]
                adjusted = True
            elif entry_price > bar["High"]:
                # 高于最高价：使用High（价格已经到过）
                entry_price = bar["High"]
                adjusted = True

        # 记录调整（调试用）
        if adjusted:
            if not hasattr(self, "_adjusted_entries"):
                self._adjusted_entries = []
            self._adjusted_entries.append(
                {
                    "timestamp": signal.timestamp,
                    "direction": signal.direction.name,
                    "original": original_price,
                    "adjusted": entry_price,
                    "bar_ohlc": (bar["Open"], bar["High"], bar["Low"], bar["Close"]),
                }
            )

        # 计算滑点
        slippage = self.execution.calculate_entry_slippage(
            entry_price, atr, strategy_category
        )

        # 调整入场价格（加滑点）
        if signal.direction == TradeDirection.LONG:
            filled_price = entry_price + slippage
        else:
            filled_price = entry_price - slippage

        self._open_position(signal, filled_price, slippage)

    def _find_entry_price_tick(self, signal: TradeSignal) -> Optional[float]:
        """使用Numba加速的入场价格查找"""
        if self.bar_idx_to_ticks is None or self._tick_bids is None:
            return None

        bar_idx = signal.execution_bar_index
        bar_idx_to_ticks_len = len(self.bar_idx_to_ticks)
        if bar_idx >= bar_idx_to_ticks_len:
            return None

        tick_start, tick_end = self.bar_idx_to_ticks[bar_idx]
        tick_end = min(tick_end, len(self._tick_bids))

        if signal.entry_price is None:
            # 使用第一个Tick的价格
            if tick_start < len(self._tick_bids):
                return self._tick_mids[tick_start]
            return None

        # 调用Numba加速函数
        is_long = signal.direction == TradeDirection.LONG
        found, price, _ = _find_entry_in_ticks_numba(
            self._tick_bids,
            self._tick_asks,
            tick_start,
            tick_end,
            is_long,
            signal.entry_price,
        )

        if found:
            return price

        # 未达到目标价格，使用开盘价
        if tick_start < len(self._tick_bids):
            return self._tick_mids[tick_start]

        return None

    def _calculate_exit_slippage(
        self, price: float, atr: float, exit_reason: ExitReason
    ) -> float:
        """计算出场滑点"""
        strategy_category = StrategyCategory.MEAN_REVERSION
        if self.position and "Momentum" in self.position.strategy_id:
            strategy_category = StrategyCategory.MOMENTUM_BREAKOUT

        return self.execution.calculate_exit_slippage(
            price, atr, exit_reason, strategy_category
        )

    def run_with_strategy(
        self,
        df: pd.DataFrame,
        strategy,
        warmup_bars: int = 100,
        tick_df: Optional[pd.DataFrame] = None,
    ) -> BacktestResult:
        """
        使用策略对象运行回测

        Args:
            df: 价格数据
            strategy: 策略对象
            warmup_bars: 预热K线数
            tick_df: Tick数据（可选）

        Returns:
            BacktestResult
        """
        signals = []

        for i in range(warmup_bars, len(df)):
            result = strategy.generate_signal(df, i)
            if result is None:
                continue
            if isinstance(result, list):
                signals.extend(result)
            else:
                signals.append(result)

        return self.run(df, signals, tick_df)
