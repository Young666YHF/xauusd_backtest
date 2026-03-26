"""
Dollar Trader 专用回测引擎
===========================
支持基于信号出场的回测逻辑

特点:
- 当反向信号出现时，自动平仓并可能开仓
- 支持固定点差成本模型
- 完整的交易记录和绩效统计
"""

from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import pandas as pd
import numpy as np
from datetime import datetime

from engines.base import BaseBacktestEngine, ExecutionModel
from core.types import (
    TradeSignal, TradeRecord, TradeDirection,
    ExitReason, BacktestResult
)
from core.config import TradingConfig
from core.events import EventType


class DollarTraderBacktestEngine(BaseBacktestEngine):
    """
    Dollar Trader 专用回测引擎

    特点:
    - 基于信号出场(均线交叉)
    - 反向信号触发平仓+可能的开仓
    - 固定点差成本
    """

    def __init__(
        self,
        config: TradingConfig,
        execution_model: Optional[ExecutionModel] = None
    ):
        super().__init__(config, execution_model)

        # 统计信息
        self.long_trades = 0
        self.short_trades = 0
        self.signal_exits = 0

    def reset(self):
        """重置引擎状态"""
        super().reset()
        self.long_trades = 0
        self.short_trades = 0
        self.signal_exits = 0

    def run(
        self,
        df: pd.DataFrame,
        signals: List[TradeSignal],
        tick_df: Optional[pd.DataFrame] = None
    ) -> BacktestResult:
        """
        执行回测

        Args:
            df: OHLCV数据
            signals: 交易信号列表
            tick_df: Tick数据(可选，用于更精确的入场价格)

        Returns:
            BacktestResult
        """
        self.reset()
        self._df = df

        # 准备Tick映射(如果有)
        bar_idx_to_ticks = None
        if tick_df is not None:
            bar_idx_to_ticks = self._prepare_tick_mapping(tick_df, df.index)

        # 按执行索引排序信号
        signal_dict = defaultdict(list)
        for sig in signals:
            signal_dict[sig.execution_bar_index].append(sig)

        # 遍历K线
        for i in range(len(df)):
            self._current_bar_idx = i
            bar = df.iloc[i]
            timestamp = df.index[i]

            # 处理持仓检查
            if self.position:
                self._check_position_exit(bar, timestamp)

            # 处理信号
            if i in signal_dict:
                for signal in signal_dict[i]:
                    self._process_signal(signal, bar, timestamp, bar_idx_to_ticks)

            # 记录权益
            equity = self.get_current_equity()
            self.equity_curve.append(equity)
            self.equity_timestamps.append(timestamp)

        # 强制平仓
        if self.position:
            last_bar = df.iloc[-1]
            self._close_position(
                last_bar['Close'],
                ExitReason.END_OF_DATA,
                self._calculate_exit_slippage(last_bar['Close'])
            )

        return self._build_result()

    def _prepare_tick_mapping(
        self,
        tick_df: pd.DataFrame,
        bar_timestamps: pd.DatetimeIndex
    ) -> Dict[int, Tuple[int, int]]:
        """准备Tick数据映射 - 使用向量化二分查找优化性能"""
        tick_times = tick_df.index.values
        bar_times = bar_timestamps.values

        # 使用searchsorted进行向量化查找，O(log n) per query instead of O(n)
        start_indices = np.searchsorted(tick_times, bar_times, side='left')
        # 找到下一个bar的起点作为当前bar的终点
        end_indices = np.searchsorted(tick_times, bar_times, side='right')

        return {i: (int(start_indices[i]), int(end_indices[i])) for i in range(len(bar_times))}

    def _get_entry_price_from_ticks(
        self,
        signal: TradeSignal,
        bar: pd.Series,
        tick_df: pd.DataFrame,
        bar_idx_to_ticks: Dict[int, Tuple[int, int]]
    ) -> float:
        """从Tick数据获取入场价格"""
        bar_idx = signal.execution_bar_index
        if bar_idx not in bar_idx_to_ticks:
            return bar['Open']

        tick_start, tick_end = bar_idx_to_ticks[bar_idx]
        if tick_start >= tick_end:
            return bar['Open']

        # 获取第一个Tick的价格
        first_tick_mid = (tick_df['bid'].iloc[tick_start] + tick_df['ask'].iloc[tick_start]) / 2

        # 根据方向调整(买入用Ask, 卖出用Bid)
        if signal.direction == TradeDirection.LONG:
            return tick_df['ask'].iloc[tick_start]
        else:
            return tick_df['bid'].iloc[tick_start]

    def _process_signal(
        self,
        signal: TradeSignal,
        bar: pd.Series,
        timestamp: datetime,
        bar_idx_to_ticks: Optional[Dict[int, Tuple[int, int]]] = None
    ):
        """处理交易信号"""
        # 确定入场价格
        if bar_idx_to_ticks is not None and hasattr(self, '_tick_df'):
            entry_price = self._get_entry_price_from_ticks(signal, bar, self._tick_df, bar_idx_to_ticks)
        else:
            entry_price = signal.entry_price if signal.entry_price else bar['Open']

        # 确保价格在合理范围内
        entry_price = max(bar['Low'], min(bar['High'], entry_price))

        # 计算入场滑点(点差的一半)
        spread_cost = self.config.spread_per_ounce * self.config.contract_size / 2
        slippage = spread_cost / self.config.contract_size  # 转换为价格单位

        if self.position:
            # 检查是否是反向信号
            if signal.direction != self.position.direction:
                # 反向信号: 先平仓
                exit_slippage = self._calculate_exit_slippage(bar['Close'])
                self._close_position(bar['Close'], ExitReason.SIGNAL_REVERSE, exit_slippage)
                self.signal_exits += 1

                # 然后开新仓(如果信号方向明确)
                if signal.direction in [TradeDirection.LONG, TradeDirection.SHORT]:
                    self._open_position(signal, entry_price + slippage if signal.direction == TradeDirection.LONG else entry_price - slippage, slippage)
            # 如果同向信号，忽略
        else:
            # 无持仓，直接开仓
            if signal.direction in [TradeDirection.LONG, TradeDirection.SHORT]:
                adjusted_price = entry_price + slippage if signal.direction == TradeDirection.LONG else entry_price - slippage
                self._open_position(signal, adjusted_price, slippage)

    def _check_position_exit(self, bar: pd.Series, timestamp: datetime):
        """检查持仓出场条件(主要用于时间止损或强制平仓)"""
        # Dollar Trader 主要依靠信号出场
        # 这里可以添加额外的出场逻辑(如最大持仓时间)
        pass

    def _calculate_exit_slippage(self, price: float) -> float:
        """计算出场滑点"""
        # 点差成本
        spread_cost = self.config.spread_per_ounce * self.config.contract_size / 2
        return spread_cost / self.config.contract_size

    def _close_position(
        self,
        exit_price: float,
        exit_reason: ExitReason,
        slippage: float = 0.0
    ) -> TradeRecord:
        """平仓并创建交易记录"""
        if not self.position:
            raise ValueError("No position to close")

        pos = self.position

        # 计算调整后的出场价格
        if pos.direction == TradeDirection.LONG:
            exit_price_adjusted = exit_price - slippage
            pnl_points = exit_price_adjusted - pos.entry_price
        else:
            exit_price_adjusted = exit_price + slippage
            pnl_points = pos.entry_price - exit_price_adjusted

        # 扣除点差成本(双向)
        total_spread_cost = self.config.spread_per_ounce * self.config.contract_size

        # 计算盈亏
        pnl = pnl_points * self.config.contract_size * pos.size - total_spread_cost
        pnl_pct = pnl_points / pos.entry_price if pos.entry_price != 0 else 0

        # 更新资金
        self.capital += pnl

        # 创建交易记录
        trade = TradeRecord(
            entry_time=pos.entry_time,
            exit_time=self._df.index[self._current_bar_idx] if self._df is not None else pos.entry_time,
            direction=pos.direction,
            size=pos.size,
            entry_price=pos.entry_price,
            exit_price=exit_price_adjusted,
            pnl=pnl,
            pnl_pct=pnl_pct,
            strategy_id=pos.strategy_id,
            exit_reason=exit_reason,
            bars_held=self._current_bar_idx - pos.entry_bar_index,
            entry_slippage=0.0,
            exit_slippage=slippage,
            commission=total_spread_cost
        )

        self.trades.append(trade)
        self.total_trades += 1

        if pos.direction == TradeDirection.LONG:
            self.long_trades += 1
        else:
            self.short_trades += 1

        if trade.is_win:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

        # 发送事件
        self.event_bus.emit_new(
            EventType.POSITION_CLOSED,
            source=self.__class__.__name__,
            trade=trade,
            position=pos
        )

        self.position = None
        return trade

    def _build_result(self) -> BacktestResult:
        """构建回测结果"""
        result = super()._build_result()

        # 添加额外统计
        result.strategy_stats = {
            'long_trades': self.long_trades,
            'short_trades': self.short_trades,
            'signal_exits': self.signal_exits,
        }

        return result
