"""
突破网格策略 - Breakout Grid Strategy
======================================

以5美元为间隔，从0-10000美元建立虚拟网格的区间突破策略。

核心逻辑:
1. 网格范围: 0-10000美元，间隔5美元，共2000个网格
2. 初始仓位: 策略启动时，根据当前价格，初始仓位为0.01手
3. 初始挂单: 上方挂5个网格的多单，下方挂5个网格的空单
4. 止盈止损: 止盈5美元，无止损

动态挂单管理 (每次tick检查):
1. 根据当前价格，新增没有的挂单
   - 注意：如果某网格已有持仓，不能挂同向单，但可以挂反向单
2. 删除上下超过5个网格的挂单
3. 更新挂单手数

仓位平衡逻辑:
- 空单仓位 > 多单仓位: 多单挂单数量 = 空单仓位 - 多单仓位 + 0.01，空单挂单数量 = 0.01
- 多单仓位 > 空单仓位: 多单挂单数量 = 0.01，空单挂单数量 = 多单仓位 - 空单仓位 + 0.01

特点:
- 突破交易: 当价格突破网格时触发挂单
- 动态平衡: 根据多空仓位差异调整挂单手数
- 网格覆盖: 持续在当前价格周围保持5个网格的覆盖范围
- 无止损设计: 依赖仓位平衡和止盈实现风险控制

作者: Claude
版本: 1.0.0
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
    long_pending: float = 0.0    # 多单挂单数量
    short_pending: float = 0.0   # 空单挂单数量


class BreakoutGridStrategy(BaseStrategy):
    """
    突破网格策略

    以5美元为间隔的网格交易，突破触发。
    """

    # 网格配置常量
    GRID_SPACING = 5.0          # 网格间隔5美元
    GRID_MIN = 0.0              # 最小网格价格
    GRID_MAX = 10000.0          # 最大网格价格
    MAX_GRID_LEVELS = int(GRID_MAX / GRID_SPACING) + 1  # 2001个网格
    COVERAGE_COUNT = 5          # 上下各覆盖5个网格
    INITIAL_POSITION = 0.01     # 初始仓位
    TAKE_PROFIT_DISTANCE = 5.0  # 止盈距离5美元

    def __init__(self, params: Optional[Dict[str, Any]] = None, strategy_id: str = ""):
        """
        初始化策略

        Args:
            params: 策略参数
                - grid_spacing: 网格间隔 (默认5.0)
                - coverage_count: 覆盖网格数量 (默认5)
                - initial_position: 初始仓位 (默认0.01)
                - take_profit: 止盈距离 (默认5.0)
            strategy_id: 策略标识
        """
        super().__init__(params, strategy_id or "BreakoutGrid")

        # 网格状态
        self.grids: Dict[int, GridLevel] = {}  # level_index -> GridLevel
        self._init_grids()

        # 仓位统计
        self.total_long_position = 0.0
        self.total_short_position = 0.0

        # 当前价格追踪
        self.current_price: Optional[float] = None
        self.current_center_level: Optional[int] = None

        # 已激活标志
        self.is_initialized = False

        # 挂单管理 (用于回测引擎)
        self.pending_orders: Dict[int, Tuple[TradeDirection, float]] = {}  # level_index -> (direction, size)

    def _init_grids(self):
        """初始化所有网格"""
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        for i in range(self.MAX_GRID_LEVELS):
            price = i * spacing
            self.grids[i] = GridLevel(price=price, level_index=i)

    def get_default_params(self) -> Dict[str, Any]:
        """返回默认参数"""
        return {
            'grid_spacing': self.GRID_SPACING,
            'coverage_count': self.COVERAGE_COUNT,
            'initial_position': self.INITIAL_POSITION,
            'take_profit': self.TAKE_PROFIT_DISTANCE,
        }

    def get_param_bounds(self) -> Dict[str, tuple]:
        """返回参数优化范围"""
        return {
            'grid_spacing': (3.0, 10.0),
            'coverage_count': (3, 10),
            'initial_position': (0.01, 0.05),
            'take_profit': (3.0, 10.0),
        }

    def get_position_size(self) -> float:
        """获取当前仓位大小（用于回测引擎）"""
        return self.params.get('initial_position', self.INITIAL_POSITION)

    def generate_signal(
        self,
        df: pd.DataFrame,
        current_idx: int,
        **kwargs
    ) -> Optional[TradeSignal]:
        """
        生成交易信号 - 基于K线数据

        注意：实际策略主要工作在tick级别，此方法用于兼容K线回测引擎
        """
        # K线模式下，使用收盘价作为当前价格
        if current_idx < 0 or current_idx >= len(df):
            return None

        current_bar = df.iloc[current_idx]
        price = current_bar['Close']
        timestamp = df.index[current_idx]

        # 处理价格更新
        self._on_price_update(price, timestamp)

        # 检查是否有触发的挂单（模拟突破）
        return self._check_pending_orders_triggered(price, timestamp, current_idx)

    def on_tick(self, tick: TickData, timestamp: datetime) -> Optional[TradeSignal]:
        """
        处理tick数据 - 策略核心逻辑

        Args:
            tick: Tick数据
            timestamp: 时间戳

        Returns:
            触发的交易信号或None
        """
        price = tick.mid

        # 更新价格并管理挂单
        self._on_price_update(price, timestamp)

        # 检查挂单触发
        return self._check_pending_orders_triggered(price, timestamp, 0)

    def _on_price_update(self, price: float, timestamp: datetime):
        """
        价格更新时的处理

        1. 确定当前中心网格
        2. 初始化（首次运行）
        3. 检查挂单触发
        4. 更新挂单布局
        """
        self.current_price = price

        # 计算当前价格所在的网格索引
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        center_level = int(price / spacing)
        center_level = max(0, min(center_level, self.MAX_GRID_LEVELS - 1))

        # 首次运行或网格中心变化时，更新挂单
        if not self.is_initialized:
            self._initialize_strategy(price, timestamp, center_level)
            self.is_initialized = True
        elif center_level != self.current_center_level:
            self._update_grid_layout(center_level)

        self.current_center_level = center_level

    def _initialize_strategy(self, price: float, timestamp: datetime, center_level: int):
        """
        初始化策略

        1. 建立初始仓位0.01手
        2. 在上方5个网格挂多单
        3. 在下方5个网格挂空单
        """
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        initial_size = self.params.get('initial_position', self.INITIAL_POSITION)
        coverage = self.params.get('coverage_count', self.COVERAGE_COUNT)

        # 确定初始方向（价格在网格上方则持有多单，下方则持有空单）
        grid_price = center_level * spacing

        if price >= grid_price:
            # 价格高于网格中心，建立多单
            self.total_long_position = initial_size
            self.grids[center_level].long_position = initial_size
        else:
            # 价格低于网格中心，建立空单
            self.total_short_position = initial_size
            self.grids[center_level].short_position = initial_size

        # 建立挂单布局
        self._update_grid_layout(center_level)

    def _update_grid_layout(self, center_level: int):
        """
        更新网格挂单布局

        根据当前中心网格，在上下coverage_count个网格内布置挂单
        """
        coverage = self.params.get('coverage_count', self.COVERAGE_COUNT)
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        initial_size = self.params.get('initial_position', self.INITIAL_POSITION)

        # 计算目标挂单范围
        min_level = max(0, center_level - coverage)
        max_level = min(self.MAX_GRID_LEVELS - 1, center_level + coverage)

        # 计算不平衡仓位
        imbalance = self.total_long_position - self.total_short_position

        # 确定多空挂单手数
        if self.total_short_position > self.total_long_position:
            # 空单多于多单：多单挂单数量 = 差额 + 0.01，空单挂单数量 = 0.01
            long_lot_size = self.total_short_position - self.total_long_position + initial_size
            short_lot_size = initial_size
        elif self.total_long_position > self.total_short_position:
            # 多单多于空单：多单挂单数量 = 0.01，空单挂单数量 = 差额 + 0.01
            long_lot_size = initial_size
            short_lot_size = self.total_long_position - self.total_short_position + initial_size
        else:
            # 平衡状态
            long_lot_size = initial_size
            short_lot_size = initial_size

        # 清除所有现有挂单
        for grid in self.grids.values():
            grid.long_pending = 0.0
            grid.short_pending = 0.0
        self.pending_orders.clear()

        # 在范围内布置新挂单
        for level in range(min_level, max_level + 1):
            if level == center_level:
                continue  # 跳过当前网格（已有仓位）

            grid = self.grids[level]

            if level > center_level:
                # 上方网格：挂多单（突破做多）
                # 条件：该网格没有多单持仓
                if grid.long_position == 0:
                    grid.long_pending = long_lot_size
                    self.pending_orders[level] = (TradeDirection.LONG, long_lot_size)

            else:
                # 下方网格：挂空单（突破做空）
                # 条件：该网格没有空单持仓
                if grid.short_position == 0:
                    grid.short_pending = short_lot_size
                    self.pending_orders[level] = (TradeDirection.SHORT, short_lot_size)

    def _check_pending_orders_triggered(
        self,
        price: float,
        timestamp: datetime,
        bar_idx: int
    ) -> Optional[TradeSignal]:
        """
        检查是否有挂单被触发

        突破逻辑：价格向上/向下穿越网格线时触发
        """
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        current_level = int(price / spacing)

        # 检查是否有挂单在当前价格范围内被触发
        for level, (direction, size) in list(self.pending_orders.items()):
            grid_price = level * spacing

            if direction == TradeDirection.LONG:
                # 多单挂单：价格向上突破网格线时触发
                if price >= grid_price:
                    return self._execute_order(
                        level, direction, size, price, timestamp, bar_idx
                    )
            else:
                # 空单挂单：价格向下突破网格线时触发
                if price <= grid_price:
                    return self._execute_order(
                        level, direction, size, price, timestamp, bar_idx
                    )

        return None

    def _execute_order(
        self,
        level: int,
        direction: TradeDirection,
        size: float,
        price: float,
        timestamp: datetime,
        bar_idx: int
    ) -> TradeSignal:
        """执行订单"""
        grid = self.grids[level]
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        tp_distance = self.params.get('take_profit', self.TAKE_PROFIT_DISTANCE)

        # 更新网格状态
        if direction == TradeDirection.LONG:
            grid.long_position += size
            self.total_long_position += size
            grid.long_pending = 0.0

            # 计算止盈价格（上方5美元）
            take_profit = price + tp_distance

            reason = f"Grid Long Entry: Level {level} ({grid.price:.2f}), Size {size:.2f}"
        else:
            grid.short_position += size
            self.total_short_position += size
            grid.short_pending = 0.0

            # 计算止盈价格（下方5美元）
            take_profit = price - tp_distance

            reason = f"Grid Short Entry: Level {level} ({grid.price:.2f}), Size {size:.2f}"

        # 从挂单列表移除
        if level in self.pending_orders:
            del self.pending_orders[level]

        # 触发后重新布局挂单
        if self.current_center_level is not None:
            self._update_grid_layout(self.current_center_level)

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
        交易完成回调

        用于更新网格持仓状态（止盈平仓时）
        """
        # 从交易记录中提取网格信息
        metadata = trade_record.get('metadata', {})
        grid_level = metadata.get('grid_level')
        direction = trade_record.get('direction')
        size = trade_record.get('size', 0)
        exit_reason = trade_record.get('exit_reason')

        if grid_level is not None and grid_level in self.grids:
            grid = self.grids[grid_level]

            if direction == TradeDirection.LONG:
                grid.long_position = max(0, grid.long_position - size)
                self.total_long_position = max(0, self.total_long_position - size)
            else:
                grid.short_position = max(0, grid.short_position - size)
                self.total_short_position = max(0, self.total_short_position - size)

        # 止盈平仓后重新布局挂单
        if self.current_center_level is not None:
            self._update_grid_layout(self.current_center_level)

    def check_take_profit(self, price: float, timestamp: datetime) -> List[TradeSignal]:
        """
        检查止盈条件

        返回需要平仓的信号列表
        """
        signals = []
        spacing = self.params.get('grid_spacing', self.GRID_SPACING)
        tp_distance = self.params.get('take_profit', self.TAKE_PROFIT_DISTANCE)

        for level, grid in self.grids.items():
            # 检查多单止盈
            if grid.long_position > 0:
                # 多单止盈价格 = 入场价格 + 5美元
                # 简化处理：使用网格线价格作为入场参考
                entry_price = level * spacing
                take_profit_price = entry_price + tp_distance

                if price >= take_profit_price:
                    # 触发多单止盈
                    signal = self._create_exit_signal(
                        level, TradeDirection.LONG, grid.long_position,
                        price, timestamp, "Long Take Profit"
                    )
                    signals.append(signal)

            # 检查空单止盈
            if grid.short_position > 0:
                entry_price = level * spacing
                take_profit_price = entry_price - tp_distance

                if price <= take_profit_price:
                    # 触发空单止盈
                    signal = self._create_exit_signal(
                        level, TradeDirection.SHORT, grid.short_position,
                        price, timestamp, "Short Take Profit"
                    )
                    signals.append(signal)

        return signals

    def _create_exit_signal(
        self,
        level: int,
        direction: TradeDirection,
        size: float,
        price: float,
        timestamp: datetime,
        reason: str
    ) -> TradeSignal:
        """创建平仓信号"""
        grid = self.grids[level]

        # 反向信号用于平仓
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
        self.current_center_level = None
        self.is_initialized = False
        self.pending_orders.clear()

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
