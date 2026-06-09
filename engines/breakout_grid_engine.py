"""
突破网格策略专用回测引擎
============================
支持网格策略的复杂挂单和止盈逻辑

特点:
- Tick级精确执行
- 多挂单管理（上下各5个网格）
- 止盈平仓（5美元固定止盈）
- 仓位平衡调整
"""

from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import pandas as pd
import numpy as np
from datetime import datetime

from engines.base import BaseBacktestEngine, ExecutionModel
from core.types import (
    TradeSignal, TradeRecord, TradeDirection,
    ExitReason, BacktestResult, TickData
)
from core.config import TradingConfig
from core.events import EventType


class BreakoutGridEngine(BaseBacktestEngine):
    """
    突破网格策略专用引擎

    专为网格策略设计，支持:
    - 多挂单同时管理
    - 固定距离止盈
    - 突破触发入场
    """

    def __init__(
        self,
        config: TradingConfig,
        execution_model: Optional[ExecutionModel] = None,
        max_total_loss_pct: float = 0.05,
        risk_manager=None
    ):
        # 使用零佣金模型（点差成本在平仓时计算）
        if execution_model is None:
            execution_model = ExecutionModel(commission_per_lot=0.0)

        super().__init__(config, execution_model, risk_manager)

        # 全局止损配置
        self.max_total_loss_pct = max_total_loss_pct

        # 网格状态追踪
        self.grid_positions: Dict[int, Dict[str, Any]] = {}  # level -> {direction, size, entry_price, tp_price}
        self.pending_orders: Dict[int, Tuple[TradeDirection, float]] = {}  # level -> (direction, size)

        # 统计信息
        self.long_entries = 0
        self.short_entries = 0
        self.long_exits = 0
        self.short_exits = 0
        self.take_profit_exits = 0
        self.time_stop_exits = 0
        self.global_stop_loss_exits = 0

        # 策略引用
        self._strategy = None
        self._tick_df = None

    def reset(self):
        """重置引擎状态"""
        super().reset()
        self.grid_positions.clear()
        self.pending_orders.clear()
        self.long_entries = 0
        self.short_entries = 0
        self.long_exits = 0
        self.short_exits = 0
        self.take_profit_exits = 0
        self.time_stop_exits = 0
        self.global_stop_loss_exits = 0
        self._strategy = None
        self._tick_df = None

    def run(
        self,
        df: pd.DataFrame,
        signals: List[TradeSignal] = None,
        tick_df: Optional[pd.DataFrame] = None,
        strategy=None
    ) -> BacktestResult:
        """
        执行网格策略回测

        Args:
            df: OHLCV数据
            signals: 交易信号列表（网格策略不使用预生成信号）
            tick_df: Tick数据（推荐用于精确回测）
            strategy: BreakoutGridStrategy实例

        Returns:
            BacktestResult
        """
        self.reset()
        self._df = df
        self._strategy = strategy
        self._tick_df = tick_df

        if strategy is None:
            raise ValueError("BreakoutGridEngine requires a strategy instance")

        # 准备Tick映射
        bar_idx_to_ticks = None
        if tick_df is not None:
            bar_idx_to_ticks = self._prepare_tick_mapping(tick_df, df.index)

        # 回测主循环
        for i in range(len(df)):
            self._current_bar_idx = i
            bar = df.iloc[i]
            timestamp = df.index[i]

            # 获取当前价格
            current_price = bar['Close']

            # 初始化策略（首次运行）
            if i == 0 and not strategy.is_initialized:
                self._initialize_grid_strategy(bar, timestamp)

            # 使用tick数据精确执行
            if bar_idx_to_ticks is not None:
                self._process_ticks_for_bar(i, bar, timestamp, bar_idx_to_ticks)
            else:
                # 使用K线数据简化执行
                self._process_bar(bar, timestamp)

            # 记录权益
            equity = self.get_current_equity()
            self.equity_curve.append(equity)
            self.equity_timestamps.append(timestamp)

        # 强制平仓所有剩余持仓
        self._close_all_positions(df.iloc[-1], df.index[-1])

        return self._build_result()

    def _initialize_grid_strategy(self, bar: pd.Series, timestamp: datetime):
        """初始化网格策略并同步初始仓位"""
        if self._strategy is None:
            return

        price = bar['Close']
        tick_data = TickData(timestamp=timestamp, bid=price-0.05, ask=price+0.05)
        self._strategy.on_tick(tick_data, timestamp)

        # 同步策略的初始仓位到引擎
        if self._strategy.is_initialized:
            for level, grid in self._strategy.grids.items():
                if grid.long_position > 0:
                    tp_price = price + self._strategy.params.get('take_profit', 5.0)
                    self._open_grid_position(level, TradeDirection.LONG, grid.long_position, price, tp_price, timestamp)
                elif grid.short_position > 0:
                    tp_price = price - self._strategy.params.get('take_profit', 5.0)
                    self._open_grid_position(level, TradeDirection.SHORT, grid.short_position, price, tp_price, timestamp)

    def _prepare_tick_mapping(
        self,
        tick_df: pd.DataFrame,
        bar_timestamps: pd.DatetimeIndex
    ) -> Dict[int, Tuple[int, int]]:
        """准备Tick数据映射 - 使用高效的一次性遍历"""
        tick_times = tick_df.index
        bar_times = bar_timestamps
        n_bars = len(bar_times)
        n_ticks = len(tick_times)

        mapping = {}
        tick_idx = 0

        # 高效的一次性遍历: O(n+m) 而非 O(n*m)
        for bar_idx in range(n_bars):
            bar_time = bar_times[bar_idx]

            # 跳过当前bar之前的ticks
            while tick_idx < n_ticks and tick_times[tick_idx] < bar_time:
                tick_idx += 1

            start_idx = tick_idx

            # 找到属于当前bar的所有ticks
            if bar_idx < n_bars - 1:
                next_bar_time = bar_times[bar_idx + 1]
                while tick_idx < n_ticks and tick_times[tick_idx] < next_bar_time:
                    tick_idx += 1

            if start_idx < tick_idx:
                mapping[bar_idx] = (start_idx, tick_idx)

        return mapping

    def _process_ticks_for_bar(
        self,
        bar_idx: int,
        bar: pd.Series,
        timestamp: datetime,
        bar_idx_to_ticks: Dict[int, Tuple[int, int]]
    ):
        """处理单个bar内的所有tick"""
        if bar_idx not in bar_idx_to_ticks:
            return

        tick_start, tick_end = bar_idx_to_ticks[bar_idx]
        if tick_start >= tick_end or self._tick_df is None:
            return

        # 逐个处理tick
        for i in range(tick_start, tick_end):
            tick = self._tick_df.iloc[i]
            tick_data = TickData(
                timestamp=tick.name,
                bid=tick['bid'],
                ask=tick['ask']
            )

            # 检查止盈
            self._check_take_profit(tick_data.mid, tick.name)

            # 检查全局止损
            if self._check_global_stop_loss(tick_data.mid, tick.name):
                break  # 全局止损触发，停止处理该bar的后续tick

            # 更新策略并检查信号
            signals = self._strategy.on_tick(tick_data, tick.name)
            for signal in signals:
                self._execute_signal(signal, tick_data, tick.name)

    def _process_bar(self, bar: pd.Series, timestamp: datetime):
        """使用K线数据处理（简化模式）"""
        price = bar['Close']
        high = bar['High']
        low = bar['Low']

        # 检查止盈（使用高低价）
        self._check_take_profit_bar(bar, timestamp)

        # 检查全局止损
        self._check_global_stop_loss(price, timestamp)

        # 更新策略
        if self._strategy:
            # 先更新价格（这会更新挂单布局）
            self._strategy._on_price_update(price, timestamp)

            # 检查是否有挂单被触发（使用K线高低价模拟价格穿越）
            triggered_signals = self._check_pending_orders_with_ohlc(bar, timestamp)

            for signal in triggered_signals:
                mid_price = (bar['High'] + bar['Low']) / 2
                tick_data = TickData(timestamp=timestamp, bid=mid_price-0.05, ask=mid_price+0.05)
                self._execute_signal(signal, tick_data, timestamp)

    def _check_global_stop_loss(self, current_price: float, timestamp: datetime) -> bool:
        """检查全局止损

        计算所有网格持仓的总未实现盈亏，当亏损超过账户权益的阈值时，
        强制平掉所有持仓。

        Args:
            current_price: 当前价格
            timestamp: 当前时间戳

        Returns:
            bool: 是否触发了全局止损
        """
        if not self.grid_positions:
            return False

        # 计算总未实现盈亏
        total_unrealized_pnl = 0.0
        for level, pos in self.grid_positions.items():
            if pos['direction'] == TradeDirection.LONG:
                unrealized = (current_price - pos['entry_price']) * self.config.contract_size * pos['size']
            else:
                unrealized = (pos['entry_price'] - current_price) * self.config.contract_size * pos['size']
            total_unrealized_pnl += unrealized

        # 计算当前权益（包含未实现盈亏）
        current_equity = self.capital + total_unrealized_pnl

        # 计算最大允许亏损金额（基于当前权益）
        max_loss_amount = current_equity * self.max_total_loss_pct

        # 检查是否超过止损阈值（未实现亏损为负值）
        if total_unrealized_pnl < -max_loss_amount:
            # 强制平掉所有持仓
            for level in list(self.grid_positions.keys()):
                self._close_grid_position(level, current_price, timestamp, ExitReason.STOP_LOSS)
            self.global_stop_loss_exits += 1
            return True

        return False

    def _check_take_profit(self, price: float, timestamp: datetime):
        """检查止盈条件"""
        if self._strategy is None:
            return

        # 调用策略的止盈检查
        exit_signals = self._strategy.check_take_profit(price, timestamp)

        for signal in exit_signals:
            self._execute_exit_signal(signal, price, timestamp)

    def _execute_signal(self, signal: TradeSignal, tick: TickData, timestamp: datetime):
        """执行交易信号"""
        if signal.direction == TradeDirection.LONG:
            entry_price = tick.ask
        else:
            entry_price = tick.bid

        # 获取或计算止盈价格
        take_profit = signal.take_profit
        if take_profit is None and self._strategy:
            tp_distance = self._strategy.params.get('take_profit', 5.0)
            if signal.direction == TradeDirection.LONG:
                take_profit = entry_price + tp_distance
            else:
                take_profit = entry_price - tp_distance

        # 执行入场
        grid_level = signal.metadata.get('grid_level', 0)

        # 如果该网格已有反向持仓，先平仓
        if grid_level in self.grid_positions:
            existing = self.grid_positions[grid_level]
            if existing['direction'] != signal.direction:
                self._close_grid_position(grid_level, entry_price, timestamp, ExitReason.SIGNAL_REVERSE)

        # 开仓
        self._open_grid_position(grid_level, signal.direction, signal.size or 0.01, entry_price, take_profit, timestamp)

    def _execute_exit_signal(self, signal: TradeSignal, price: float, timestamp: datetime):
        """执行平仓信号"""
        grid_level = signal.metadata.get('grid_level', 0)
        original_direction = signal.metadata.get('original_direction')
        is_time_exit = signal.metadata.get('is_time_exit', False)

        if grid_level in self.grid_positions:
            exit_reason = ExitReason.TIME_STOP if is_time_exit else ExitReason.TAKE_PROFIT
            self._close_grid_position(grid_level, price, timestamp, exit_reason)

    def _open_grid_position(
        self,
        level: int,
        direction: TradeDirection,
        size: float,
        entry_price: float,
        take_profit: float,
        timestamp: datetime
    ):
        """开网格仓位"""
        self.grid_positions[level] = {
            'direction': direction,
            'size': size,
            'entry_price': entry_price,
            'take_profit': take_profit,
            'entry_time': timestamp,
            'entry_bar_index': self._current_bar_idx,
        }

        # 更新统计
        if direction == TradeDirection.LONG:
            self.long_entries += 1
        else:
            self.short_entries += 1

    def _close_grid_position(
        self,
        level: int,
        exit_price: float,
        timestamp: datetime,
        exit_reason: ExitReason
    ) -> Optional[TradeRecord]:
        """平仓网格仓位"""
        if level not in self.grid_positions:
            return None

        pos = self.grid_positions[level]
        direction = pos['direction']
        size = pos['size']
        entry_price = pos['entry_price']

        # 计算盈亏
        if direction == TradeDirection.LONG:
            pnl_points = exit_price - entry_price
        else:
            pnl_points = entry_price - exit_price

        # 点差成本
        spread_cost = self.config.spread_per_ounce * self.config.contract_size * size

        # 总盈亏
        pnl = pnl_points * self.config.contract_size * size - spread_cost

        # 更新资金
        self.capital += pnl

        # 创建交易记录
        trade = TradeRecord(
            entry_time=pos['entry_time'],
            exit_time=timestamp,
            direction=direction,
            size=size,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            pnl_pct=pnl_points / entry_price if entry_price != 0 else 0,
            strategy_id="BreakoutGrid",
            exit_reason=exit_reason,
            bars_held=self._current_bar_idx - pos.get('entry_bar_index', self._current_bar_idx),
            entry_slippage=0.0,
            exit_slippage=0.0,
            commission=spread_cost,
            metadata={'grid_level': level}
        )

        self.trades.append(trade)
        self.total_trades += 1

        if trade.is_win:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

        # 更新统计
        if direction == TradeDirection.LONG:
            self.long_exits += 1
        else:
            self.short_exits += 1

        if exit_reason == ExitReason.TAKE_PROFIT:
            self.take_profit_exits += 1
        elif exit_reason == ExitReason.TIME_STOP:
            self.time_stop_exits += 1
        elif exit_reason == ExitReason.STOP_LOSS:
            self.global_stop_loss_exits += 1

        # 通知策略 - 关键修复：确保策略知道持仓已被平掉
        if self._strategy:
            self._strategy.on_trade_completed({
                'profit': pnl,
                'direction': direction,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'size': size,
                'exit_reason': exit_reason,
                'metadata': {'grid_level': level, 'is_exit': True}
            })

        # 移除网格仓位
        del self.grid_positions[level]

        return trade

    def _check_take_profit_bar(self, bar: pd.Series, timestamp: datetime):
        """使用K线数据检查止盈（检查高低价是否触及止盈位）"""
        high = bar['High']
        low = bar['Low']

        for level, pos in list(self.grid_positions.items()):
            tp_price = pos['take_profit']
            direction = pos['direction']

            # 多单止盈：高价触及或超过止盈位
            if direction == TradeDirection.LONG and high >= tp_price:
                self._close_grid_position(level, tp_price, timestamp, ExitReason.TAKE_PROFIT)
            # 空单止盈：低价触及或低于止盈位
            elif direction == TradeDirection.SHORT and low <= tp_price:
                self._close_grid_position(level, tp_price, timestamp, ExitReason.TAKE_PROFIT)

    def _check_pending_orders_with_ohlc(self, bar: pd.Series, timestamp: datetime) -> List[TradeSignal]:
        """使用K线高低价检查网格穿越并生成信号"""
        if not self._strategy:
            return []

        # 调用策略的generate_signal获取K线模式下触发的信号
        return self._strategy.generate_signal(self._df, self._current_bar_idx)

    def _close_all_positions(self, last_bar: pd.Series, timestamp: datetime):
        """强制平仓所有剩余持仓"""
        exit_price = last_bar['Close']

        for level in list(self.grid_positions.keys()):
            self._close_grid_position(level, exit_price, timestamp, ExitReason.END_OF_DATA)

    def get_current_equity(self) -> float:
        """计算当前权益（包含未实现盈亏）"""
        equity = self.capital

        if self._df is None or self._current_bar_idx >= len(self._df):
            return equity

        current_price = self._df.iloc[self._current_bar_idx]['Close']

        # 计算未实现盈亏
        for level, pos in self.grid_positions.items():
            if pos['direction'] == TradeDirection.LONG:
                unrealized = (current_price - pos['entry_price']) * self.config.contract_size * pos['size']
            else:
                unrealized = (pos['entry_price'] - current_price) * self.config.contract_size * pos['size']
            equity += unrealized

        return equity

    def _build_result(self) -> BacktestResult:
        """构建回测结果"""
        result = super()._build_result()

        # 添加网格策略特有统计
        result.strategy_stats = {
            'long_entries': self.long_entries,
            'short_entries': self.short_entries,
            'long_exits': self.long_exits,
            'short_exits': self.short_exits,
            'take_profit_exits': self.take_profit_exits,
            'time_stop_exits': self.time_stop_exits,
            'global_stop_loss_exits': self.global_stop_loss_exits,
            'max_total_loss_pct': self.max_total_loss_pct,
            'final_long_position': sum(1 for p in self.grid_positions.values() if p['direction'] == TradeDirection.LONG),
            'final_short_position': sum(1 for p in self.grid_positions.values() if p['direction'] == TradeDirection.SHORT),
        }

        return result
