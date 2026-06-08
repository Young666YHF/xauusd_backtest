"""
突破网格策略 - Breakout Grid Strategy (市价单无限网格版)
======================================================

以5美元为间隔，从0-10000美元建立虚拟网格的区间突破策略。
突破时直接市价入场，不再使用挂单，所有网格均可触发交易。

核心逻辑:
1. 网格范围: 0-10000美元，间隔5美元，共2000个网格
2. 初始仓位: 策略启动时，根据当前价格建立初始仓位0.01手
3. 突破入场: 价格向上突破任意网格线时市价做多，向下突破时市价做空
4. 无限监控: 所有网格都监控，不再限制上下范围
5. 止盈止损: 止盈5美元，无止损

动态网格管理:
- 价格穿越任意网格线时立即市价入场
- 每个网格独立管理，互不影响
- 已持仓网格不会重复开仓

仓位平衡逻辑:
- 空单仓位 > 多单仓位: 多单数量 = 差额 + 0.01，空单数量 = 0.01
- 多单仓位 > 空单仓位: 多单数量 = 0.01，空单数量 = 差额 + 0.01

特点:
- 突破交易: 当价格突破任意网格时立即市价入场
- 动态平衡: 根据多空仓位差异调整入场手数
- 无限覆盖: 所有2000个网格都参与交易
- 无止损设计: 依赖仓位平衡和止盈实现风险控制

作者: Claude
版本: 3.0.0
"""

from typing import Dict, List, Optional, Any, Tuple, Set
import pandas as pd
import numpy as np
from datetime import datetime
from dataclasses import dataclass, field

from strategies.base import BaseStrategy
from core.types import TradeSignal, TradeDirection, SignalType, TickData


@dataclass
class GridLevel:
    """网格级别数据"""
    price: float           # 网格价格
    level_index: int       # 网格索引
    long_position: float = 0.0   # 当前多单持仓
    short_position: float = 0.0  # 当前空单持仓
    long_entry_price: float = 0.0  # 多单实际入场价
    short_entry_price: float = 0.0 # 空单实际入场价
    long_entry_time: Optional[datetime] = None  # 多单入场时间
    short_entry_time: Optional[datetime] = None # 空单入场时间


class BreakoutGridStrategy(BaseStrategy):
    """
    突破网格策略 - 市价单版本

    以5美元为间隔的网格交易，价格穿越网格线时市价入场。
    """

    # 网格配置常量
    GRID_SPACING = 5.0          # 网格间隔5美元
    GRID_MIN = 0.0              # 最小网格价格
    GRID_MAX = 10000.0          # 最大网格价格
    COVERAGE_COUNT = 5          # 上下各覆盖5个网格
    INITIAL_POSITION = 0.01     # 初始仓位
    TAKE_PROFIT_DISTANCE = 5.0  # 止盈距离5美元
    DEFAULT_MAX_HOLD_DAYS = 3   # 默认最大持仓天数

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        """
        初始化策略

        Args:
            params: 策略参数
                - grid_spacing: 网格间隔 (默认5.0)
                - coverage_count: 覆盖网格数量 (默认5)
                - initial_position: 初始仓位 (默认0.01)
                - take_profit: 止盈距离 (默认5.0)
                - max_hold_days: 最大持仓天数 (默认3)
            strategy_id: 策略标识
        """
        super().__init__(params, strategy_id or "BreakoutGrid")

        # 根据参数计算网格数量
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        self.max_grid_levels = int(self.GRID_MAX / spacing) + 1

        # 网格状态
        self.grids: Dict[int, GridLevel] = {}  # level_index -> GridLevel
        self._init_grids()

        # 仓位统计
        self.total_long_position = 0.0
        self.total_short_position = 0.0

        # 当前价格追踪
        self.current_price: Optional[float] = None
        self.prev_price: Optional[float] = None
        self.current_center_level: Optional[int] = None

        # 已激活标志
        self.is_initialized = False

    def _init_grids(self):
        """初始化所有网格"""
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        for i in range(self.max_grid_levels):
            price = i * spacing
            self.grids[i] = GridLevel(price=price, level_index=i)

    def get_default_params(self) -> Dict[str, Any]:
        """返回默认参数"""
        return {
            'grid_spacing': self.GRID_SPACING,
            'coverage_count': self.COVERAGE_COUNT,
            'initial_position': self.INITIAL_POSITION,
            'take_profit': self.TAKE_PROFIT_DISTANCE,
            'max_hold_days': self.DEFAULT_MAX_HOLD_DAYS,
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        """返回参数优化范围"""
        return {
            'grid_spacing': (3.0, 10.0),
            'coverage_count': (3, 10),
            'initial_position': (0.01, 0.05),
            'take_profit': (3.0, 10.0),
            'max_hold_days': (1, 7),
        }

    def get_position_size(self) -> float:
        """获取当前仓位大小（用于回测引擎）"""
        return self.params.get('initial_position', self.INITIAL_POSITION)

    def generate_signal(
        self,
        df: pd.DataFrame,
        current_idx: int,
        **kwargs
    ) -> List[TradeSignal]:
        """
        生成交易信号 - 基于K线数据
        返回所有触发的网格交易信号
        """
        signals = []
        if current_idx < 0 or current_idx >= len(df):
            return signals

        current_bar = df.iloc[current_idx]
        price = current_bar['Close']
        timestamp = df.index[current_idx]

        # K线模式下使用high/low检测穿越
        if self.is_initialized and current_idx > 0:
            prev_bar = df.iloc[current_idx - 1]
            prev_price = prev_bar['Close']
            high = current_bar['High']
            low = current_bar['Low']

            new_signals = self._check_grid_crossings(
                prev_price, price, high, low, timestamp, current_idx
            )
            signals.extend(new_signals)

        # 更新价格并处理网格中心变化
        self._on_price_update(price, timestamp)
        return signals

    def on_tick(self, tick: TickData, timestamp: datetime) -> List[TradeSignal]:
        """
        处理tick数据 - 策略核心逻辑
        返回所有触发的网格交易信号
        """
        price = tick.mid
        signals = []

        if self.is_initialized and self.prev_price is not None:
            # 检测价格穿越 - 可能产生多个信号
            new_signals = self._check_grid_crossings(
                self.prev_price, price, price, price, timestamp, 0
            )
            signals.extend(new_signals)

        # 更新价格
        self._on_price_update(price, timestamp)
        self.prev_price = price
        return signals

    def _on_price_update(self, price: float, timestamp: datetime):
        """
        价格更新时的处理
        """
        self.current_price = price

        # 计算当前价格所在的网格索引
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        center_level = int(price / spacing)
        center_level = max(0, min(center_level, self.max_grid_levels - 1))

        # 首次运行或网格中心变化时，更新状态
        if not self.is_initialized:
            self._initialize_strategy(price, timestamp, center_level)
            self.is_initialized = True
            self.current_center_level = center_level
        elif center_level != self.current_center_level:
            self.current_center_level = center_level

    def _initialize_strategy(self, price: float, timestamp: datetime, center_level: int):
        """
        初始化策略
        """
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        initial_size = self.params.get('initial_position', self.INITIAL_POSITION)

        # 设置当前中心网格
        self.current_center_level = center_level

        # 确定初始方向（价格在网格上方则持有多单，下方则持有空单）
        grid_price = center_level * spacing

        if price >= grid_price:
            # 价格高于网格中心，建立多单
            self.total_long_position = initial_size
            self.grids[center_level].long_position = initial_size
            self.grids[center_level].long_entry_price = price
            self.grids[center_level].long_entry_time = timestamp
        else:
            # 价格低于网格中心，建立空单
            self.total_short_position = initial_size
            self.grids[center_level].short_position = initial_size
            self.grids[center_level].short_entry_price = price
            self.grids[center_level].short_entry_time = timestamp

    def _check_grid_crossings(
        self,
        prev_price: float,
        curr_price: float,
        high: float,
        low: float,
        timestamp: datetime,
        bar_idx: int
    ) -> List[TradeSignal]:
        """
        检查价格是否穿越了监控范围内的网格线

        向上穿越 -> 市价做多
        向下穿越 -> 市价做空

        返回所有触发的交易信号列表
        """
        signals = []
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        long_lot_size, short_lot_size = self._calculate_lot_sizes()

        # 确定需要检查的价格范围
        min_price = min(prev_price, curr_price, low)
        max_price = max(prev_price, curr_price, high)

        # 计算涉及的网格范围
        min_level = int(min_price / spacing)
        max_level = int(max_price / spacing) + 1
        min_level = max(0, min(min_level, self.max_grid_levels - 1))
        max_level = max(0, min(max_level, self.max_grid_levels - 1))

        # 只检查价格穿越范围内的网格
        levels_to_check = range(min_level, max_level + 1)

        # 检查每个相关网格级别
        for level in levels_to_check:
            if level < 0 or level >= self.max_grid_levels:
                continue

            grid_price = level * spacing
            grid = self.grids[level]

            # 向上突破网格线 -> 做多（无论网格在哪个位置）
            if grid.long_position == 0:
                # 检查是否向上突破网格线
                if prev_price < grid_price and curr_price >= grid_price:
                    signal = self._execute_market_order(
                        level, TradeDirection.LONG, long_lot_size,
                        curr_price, timestamp, bar_idx
                    )
                    if signal:
                        signals.append(signal)
                        long_lot_size, short_lot_size = self._calculate_lot_sizes()
                # K线模式下检查high是否突破
                elif high >= grid_price and low < grid_price:
                    signal = self._execute_market_order(
                        level, TradeDirection.LONG, long_lot_size,
                        curr_price, timestamp, bar_idx
                    )
                    if signal:
                        signals.append(signal)
                        long_lot_size, short_lot_size = self._calculate_lot_sizes()

            # 向下突破网格线 -> 做空（无论网格在哪个位置）
            if grid.short_position == 0:
                # 检查是否向下突破网格线
                if prev_price > grid_price and curr_price <= grid_price:
                    signal = self._execute_market_order(
                        level, TradeDirection.SHORT, short_lot_size,
                        curr_price, timestamp, bar_idx
                    )
                    if signal:
                        signals.append(signal)
                        long_lot_size, short_lot_size = self._calculate_lot_sizes()
                # K线模式下检查low是否跌破
                elif low <= grid_price and high > grid_price:
                    signal = self._execute_market_order(
                        level, TradeDirection.SHORT, short_lot_size,
                        curr_price, timestamp, bar_idx
                    )
                    if signal:
                        signals.append(signal)
                        long_lot_size, short_lot_size = self._calculate_lot_sizes()

        return signals

    def _calculate_lot_sizes(self) -> Tuple[float, float]:
        """
        计算多空入场手数（基于仓位平衡）
        最大手数不超过初始仓位的10倍
        """
        initial_size = self.params.get('initial_position', self.INITIAL_POSITION)
        max_size = initial_size * 10  # 最大手数限制

        if self.total_short_position > self.total_long_position:
            # 空单多于多单：多单入场数量 = 差额 + 0.01，空单入场数量 = 0.01
            long_lot_size = self.total_short_position - self.total_long_position + initial_size
            short_lot_size = initial_size
        elif self.total_long_position > self.total_short_position:
            # 多单多于空单：多单入场数量 = 0.01，空单入场数量 = 差额 + 0.01
            long_lot_size = initial_size
            short_lot_size = self.total_long_position - self.total_short_position + initial_size
        else:
            # 平衡状态
            long_lot_size = initial_size
            short_lot_size = initial_size

        # 限制最大手数
        long_lot_size = min(long_lot_size, max_size)
        short_lot_size = min(short_lot_size, max_size)

        return long_lot_size, short_lot_size

    def _execute_market_order(
        self,
        level: int,
        direction: TradeDirection,
        size: float,
        price: float,
        timestamp: datetime,
        bar_idx: int
    ) -> TradeSignal:
        """执行市价订单"""
        grid = self.grids[level]
        tp_distance = self.params.get('take_profit', self.TAKE_PROFIT_DISTANCE)

        # 更新网格状态
        if direction == TradeDirection.LONG:
            grid.long_position += size
            grid.long_entry_price = price
            grid.long_entry_time = timestamp  # 记录入场时间
            self.total_long_position += size

            # 计算止盈价格（上方5美元）
            take_profit = price + tp_distance

            reason = f"Grid Long Entry (Market): Level {level} ({grid.price:.2f}), Size {size:.2f}"
        else:
            grid.short_position += size
            grid.short_entry_price = price
            grid.short_entry_time = timestamp  # 记录入场时间
            self.total_short_position += size

            # 计算止盈价格（下方5美元）
            take_profit = price - tp_distance

            reason = f"Grid Short Entry (Market): Level {level} ({grid.price:.2f}), Size {size:.2f}"

        return self._create_signal(
            timestamp=timestamp,
            direction=direction,
            entry_price=price,
            stop_loss=None,  # 无止损
            take_profit=take_profit,
            reason=reason,
            signal_bar_idx=bar_idx,
            execution_bar_idx=bar_idx,
            size=size,
            metadata={
                'grid_level': level,
                'grid_price': grid.price,
                'total_long': self.total_long_position,
                'total_short': self.total_short_position,
            }
        )

    def on_trade_completed(self, trade_record: Dict[str, Any]):
        """
        交易完成回调（止盈平仓时）
        """
        metadata = trade_record.get('metadata', {})
        grid_level = metadata.get('grid_level')
        direction = trade_record.get('direction')
        size = trade_record.get('size', 0)

        # 处理方向可能是整数或枚举的情况
        is_long = False
        if isinstance(direction, TradeDirection):
            is_long = direction == TradeDirection.LONG
        elif isinstance(direction, int):
            is_long = direction == TradeDirection.LONG.value

        if grid_level is not None and grid_level in self.grids:
            grid = self.grids[grid_level]

            if is_long:
                grid.long_position = max(0, grid.long_position - size)
                self.total_long_position = max(0, self.total_long_position - size)
                if grid.long_position <= 0:
                    grid.long_entry_price = 0.0
                    grid.long_entry_time = None
            else:
                grid.short_position = max(0, grid.short_position - size)
                self.total_short_position = max(0, self.total_short_position - size)
                if grid.short_position <= 0:
                    grid.short_entry_price = 0.0
                    grid.short_entry_time = None

    def check_take_profit(self, price: float, timestamp: datetime) -> List[TradeSignal]:
        """
        检查止盈条件和时间平仓条件（3天）
        """
        signals = []
        tp_distance = self.params.get('take_profit', self.TAKE_PROFIT_DISTANCE)
        max_hold_days = self.params.get('max_hold_days', self.DEFAULT_MAX_HOLD_DAYS)

        for level, grid in self.grids.items():
            # 检查多单止盈
            if grid.long_position > 0 and grid.long_entry_price > 0:
                # 止盈检查
                take_profit_price = grid.long_entry_price + tp_distance
                if price >= take_profit_price:
                    signal = self._create_exit_signal(
                        level, TradeDirection.LONG, grid.long_position,
                        price, timestamp, f"Long Take Profit @ {take_profit_price:.2f}"
                    )
                    signals.append(signal)
                    continue

                # 时间平仓检查
                if grid.long_entry_time is not None:
                    hold_time = timestamp - grid.long_entry_time
                    if hold_time.total_seconds() / 86400 >= max_hold_days:
                        signal = self._create_exit_signal(
                            level, TradeDirection.LONG, grid.long_position,
                            price, timestamp, f"Long Time Exit ({max_hold_days} days)",
                            is_time_exit=True
                        )
                        signals.append(signal)
                        continue

            # 检查空单止盈
            if grid.short_position > 0 and grid.short_entry_price > 0:
                # 止盈检查
                take_profit_price = grid.short_entry_price - tp_distance
                if price <= take_profit_price:
                    signal = self._create_exit_signal(
                        level, TradeDirection.SHORT, grid.short_position,
                        price, timestamp, f"Short Take Profit @ {take_profit_price:.2f}"
                    )
                    signals.append(signal)
                    continue

                # 时间平仓检查
                if grid.short_entry_time is not None:
                    hold_time = timestamp - grid.short_entry_time
                    if hold_time.total_seconds() / 86400 >= max_hold_days:
                        signal = self._create_exit_signal(
                            level, TradeDirection.SHORT, grid.short_position,
                            price, timestamp, f"Short Time Exit ({max_hold_days} days)",
                            is_time_exit=True
                        )
                        signals.append(signal)
                        continue

        return signals

    def _create_exit_signal(
        self,
        level: int,
        direction: TradeDirection,
        size: float,
        price: float,
        timestamp: datetime,
        reason: str,
        is_time_exit: bool = False
    ) -> TradeSignal:
        """创建平仓信号"""
        grid = self.grids[level]

        exit_direction = TradeDirection.SHORT if direction == TradeDirection.LONG else TradeDirection.LONG

        return self._create_signal(
            timestamp=timestamp,
            direction=exit_direction,
            entry_price=price,
            stop_loss=None,
            take_profit=None,
            reason=reason,
            signal_bar_idx=0,
            execution_bar_idx=0,
            size=size,
            metadata={
                'grid_level': level,
                'close_position': True,
                'original_direction': direction,
                'is_time_exit': is_time_exit,
            }
        )

    def reset(self):
        """重置策略状态"""
        super().reset()
        self.grids.clear()
        self._init_grids()
        self.total_long_position = 0.0
        self.total_short_position = 0.0
        self.current_price = None
        self.prev_price = None
        self.current_center_level = None
        self.is_initialized = False

    def get_state(self) -> Dict[str, Any]:
        """获取策略当前状态"""
        state = super().get_state()
        state.update({
            'total_long_position': self.total_long_position,
            'total_short_position': self.total_short_position,
            'current_price': self.current_price,
            'current_center_level': self.current_center_level,
            'is_initialized': self.is_initialized,
            'net_position': self.total_long_position - self.total_short_position,
        })
        return state
