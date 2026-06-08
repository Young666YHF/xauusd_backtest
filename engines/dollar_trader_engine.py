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
        execution_model: Optional[ExecutionModel] = None,
        risk_manager=None
    ):
        # 【重要】强制使用零佣金模型（点差已包含佣金）
        # 避免入场时重复扣除佣金
        if execution_model is None:
            execution_model = ExecutionModel(commission_per_lot=0.0)

        super().__init__(config, execution_model, risk_manager)

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
        signals: List[TradeSignal] = None,
        tick_df: Optional[pd.DataFrame] = None,
        strategy=None  # 添加策略参数，用于回调和实时信号生成
    ) -> BacktestResult:
        """
        执行回测

        Args:
            df: OHLCV数据
            signals: 交易信号列表(可选，如果提供strategy则优先使用实时生成)
            tick_df: Tick数据(可选，用于更精确的入场价格)
            strategy: 策略实例(可选，用于交易完成回调和实时信号生成)

        Returns:
            BacktestResult
        """
        self.reset()
        self._df = df
        self._strategy = strategy  # 保存策略引用

        # 准备Tick映射(如果有)
        bar_idx_to_ticks = None
        if tick_df is not None:
            bar_idx_to_ticks = self._prepare_tick_mapping(tick_df, df.index)

        # 如果提供了策略，使用实时信号生成模式
        if strategy is not None and hasattr(strategy, 'generate_signal'):
            # 实时信号生成模式
            warmup_bars = max(
                strategy.params.get('sma_long', 200),
                strategy.params.get('bb_period', 20) + strategy.params.get('bbw_ma_period', 50)
            ) + 5

            for i in range(len(df)):
                self._current_bar_idx = i
                bar = df.iloc[i]
                timestamp = df.index[i]

                # 处理持仓检查
                if self.position:
                    self._check_position_exit(bar, timestamp)

                # 【关键】实时生成信号（策略状态会根据实际交易结果更新）
                if i >= warmup_bars:
                    signal = strategy.generate_signal(df, i)
                    if signal:
                        self._process_signal(signal, bar, timestamp, bar_idx_to_ticks)

                # 记录权益
                equity = self.get_current_equity()
                self.equity_curve.append(equity)
                self.equity_timestamps.append(timestamp)
        else:
            # 传统模式：使用预生成的信号列表
            signal_dict = defaultdict(list)
            if signals:
                for sig in signals:
                    signal_dict[sig.execution_bar_index].append(sig)

            for i in range(len(df)):
                self._current_bar_idx = i
                bar = df.iloc[i]
                timestamp = df.index[i]

                if self.position:
                    self._check_position_exit(bar, timestamp)

                if i in signal_dict:
                    for signal in signal_dict[i]:
                        self._process_signal(signal, bar, timestamp, bar_idx_to_ticks)

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

        # 【修复】与Pine一致：执行滑点固定为0.1美元（10点）
        # 不再把点差的一半作为滑点，点差成本在平仓时扣除
        slippage = 0.1  # 与Pine的slippage=10点一致

        # 【关键】从策略获取当前仓位大小（支持马丁格尔动态调整）
        # 必须在平仓前获取，确保反向开仓时使用相同的仓位大小
        if hasattr(self, '_strategy') and self._strategy is not None and hasattr(self._strategy, 'get_position_size'):
            signal.size = self._strategy.get_position_size()

        if self.position:
            # 检查是否是反向信号
            if signal.direction != self.position.direction:
                # 【修复】反向开仓时，保存当前仓位大小
                # Pine的马丁格尔状态在下一根K线才更新，反向开仓应使用原仓位
                saved_position_size = signal.size

                # 反向信号: 先平仓
                exit_slippage = slippage  # 使用固定滑点
                self._close_position(bar['Close'], ExitReason.SIGNAL_REVERSE, exit_slippage)
                self.signal_exits += 1

                # 【修复】反向开仓使用平仓前的仓位大小，不重新获取
                # 这样与Pine的行为一致：反向开仓时马丁格尔状态还没更新
                signal.size = saved_position_size

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
        # 【修复】与Pine一致：固定滑点0.1美元
        return 0.1

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

        # 【Bug修复】点差成本按仓位比例计算
        # 每0.01手往返成本=0.6美元，即每手成本=60美元
        # 成本 = 每手成本 × 仓位大小
        total_spread_cost = self.config.spread_per_ounce * self.config.contract_size * pos.size

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

        # 【关键】调用策略的on_trade_completed回调，更新马丁格尔状态
        if hasattr(self, '_strategy') and self._strategy is not None:
            self._strategy.on_trade_completed({
                'profit': pnl,
                'direction': pos.direction,
                'entry_price': pos.entry_price,
                'exit_price': exit_price_adjusted,
                'size': pos.size,
                'exit_reason': exit_reason,
            })

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
