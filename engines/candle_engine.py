"""
K线级回测引擎
=============
基于OHLCV数据的回测引擎
"""

from typing import Dict, List, Optional, Any
from collections import defaultdict
import pandas as pd
import numpy as np
from datetime import datetime

from .base import BaseBacktestEngine, ExecutionModel, StrategyCategory
from core.types import TradeSignal, ExitReason, BacktestResult, TradeDirection
from core.config import TradingConfig


class CandleBacktestEngine(BaseBacktestEngine):
    """
    K线级回测引擎

    特点：
    - 基于OHLCV数据
    - 支持前视偏差防护
    - 精确的滑点模型
    """

    # 类常量
    DEFAULT_MAX_BARS = 10  # 默认最大持仓K线数

    def __init__(
        self,
        config: TradingConfig,
        execution_model: Optional[ExecutionModel] = None,
        max_bars: Optional[int] = None,
        risk_manager=None,
    ):
        super().__init__(config, execution_model, risk_manager)

        # 信号队列
        self._pending_signals: Dict[int, TradeSignal] = {}
        self.max_bars = max_bars if max_bars is not None else self.DEFAULT_MAX_BARS

    def run(self, df: pd.DataFrame, signals: List[TradeSignal]) -> BacktestResult:
        """
        执行回测

        Args:
            df: OHLCV数据（必须包含指标）
            signals: 交易信号列表

        Returns:
            BacktestResult
        """
        self.reset()
        self._df = df

        # 按执行索引排序信号 - 使用defaultdict优化
        signal_dict = defaultdict(list)
        for sig in signals:
            signal_dict[sig.execution_bar_index].append(sig)

        # 遍历K线
        for i in range(len(df)):
            self._current_bar_idx = i
            bar = df.iloc[i]
            timestamp = df.index[i]

            # 处理持仓
            if self.position:
                self._process_position(bar, timestamp)

            # 处理入场信号
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

    def _process_position(self, bar: pd.Series, timestamp: datetime):
        """处理持仓状态"""
        pos = self.position

        # 更新时间持仓
        pos.bars_held = self._current_bar_idx - pos.entry_bar_index

        # 检查最大持仓时间
        if pos.bars_held >= self.max_bars:
            self._close_position(
                bar["Close"],
                ExitReason.TIME_STOP,
                self.execution.calculate_exit_slippage(
                    bar["Close"], bar.get("ATR", 0), ExitReason.TIME_STOP
                ),
            )
            return

        # 检查出场条件
        exit_reason = self._check_exit_conditions(bar["High"], bar["Low"], bar["Close"])

        if exit_reason:
            slippage = self.execution.calculate_exit_slippage(
                bar["Close"],
                bar.get("ATR", 0),
                exit_reason,
                (
                    StrategyCategory.MEAN_REVERSION
                    if "MeanReversion" in pos.strategy_id
                    else StrategyCategory.MOMENTUM_BREAKOUT
                ),
            )
            self._close_position(bar["Close"], exit_reason, slippage)

    def _process_entry(self, signal: TradeSignal, bar: pd.Series):
        """处理入场信号"""
        # 价格行为确认
        entry_price = self._calculate_entry_price(signal, bar)
        if entry_price is None:
            return

        # 计算滑点
        atr = bar.get("ATR", 0)
        strategy_category = (
            StrategyCategory.MEAN_REVERSION
            if "MeanReversion" in signal.strategy_id
            else StrategyCategory.MOMENTUM_BREAKOUT
        )
        slippage = self.execution.calculate_entry_slippage(
            entry_price, atr, strategy_category
        )

        # 调整入场价格
        if signal.direction == TradeDirection.LONG:
            filled_price = entry_price + slippage
        else:
            filled_price = entry_price - slippage

        # 检查止损是否立即触发（开盘跳空）
        if signal.stop_loss:
            if (
                signal.direction == TradeDirection.LONG
                and bar["Open"] <= signal.stop_loss
            ):
                return  # 跳过此交易
            if (
                signal.direction == TradeDirection.SHORT
                and bar["Open"] >= signal.stop_loss
            ):
                return  # 跳过此交易

        self._open_position(signal, filled_price, slippage)

    def _calculate_entry_price(
        self, signal: TradeSignal, bar: pd.Series
    ) -> Optional[float]:
        """
        计算入场价格

        如果信号价格在K线范围内，使用信号价格
        否则使用开盘价
        """
        if signal.entry_price is None:
            return bar["Open"]

        target = signal.entry_price
        high = bar["High"]
        low = bar["Low"]

        # 检查价格是否可达
        if signal.direction == TradeDirection.LONG:
            if target <= high:
                return max(target, bar["Open"])
        elif signal.direction == TradeDirection.SHORT:
            if target >= low:
                return min(target, bar["Open"])

        return bar["Open"]

    def run_with_strategy(
        self, df: pd.DataFrame, strategy, warmup_bars: int = 100, tick_df=None
    ) -> BacktestResult:
        """
        使用策略对象运行回测

        Args:
            df: 价格数据（必须已添加指标）
            strategy: 策略对象
            warmup_bars: 预热K线数

        Returns:
            BacktestResult
        """
        signals = []

        # 生成信号
        for i in range(warmup_bars, len(df)):
            result = strategy.generate_signal(df, i)
            if result is None:
                continue
            if isinstance(result, list):
                signals.extend(result)
            else:
                signals.append(result)

        return self.run(df, signals)
