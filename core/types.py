"""
核心数据类型定义
================
定义系统中使用的所有基础数据结构和枚举
"""

from enum import Enum, IntEnum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime
import pandas as pd
import numpy as np


class SignalType(Enum):
    """信号类型枚举"""
    NONE = 0
    LONG = 1
    SHORT = -1
    CLOSE_LONG = 2
    CLOSE_SHORT = -2
    FLAT = 3


class TradeDirection(IntEnum):
    """交易方向枚举"""
    LONG = 1
    SHORT = -1
    FLAT = 0


class OrderType(Enum):
    """订单类型枚举"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class ExitReason(IntEnum):
    """出场原因枚举"""
    NONE = 0
    STOP_LOSS = 1
    TAKE_PROFIT = 2
    TRAILING_STOP = 3
    TIME_STOP = 4
    FORCE_CLOSE = 5
    STOP_LOSS_GAP = 6
    MARGIN_CALL = 7
    SIGNAL_REVERSE = 8
    END_OF_DATA = 9


class StrategyType(Enum):
    """策略类型枚举"""
    MEAN_REVERSION = "mean_reversion"  # 均值回归
    MOMENTUM_BREAKOUT = "momentum_breakout"  # 动量突破
    TREND_FOLLOWING = "trend_following"  # 趋势跟踪
    MULTI_FACTOR = "multi_factor"  # 多因子
    CUSTOM = "custom"  # 自定义


@dataclass
class TradeSignal:
    """交易信号数据结构"""
    timestamp: datetime
    signal_type: SignalType
    strategy_id: str  # 策略标识
    direction: TradeDirection
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    size: Optional[float] = None  # 固定手数（优先使用）
    risk_per_trade: float = 0.01  # 每笔交易风险百分比（默认1%）
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 信号生成和执行索引（用于避免前视偏差）
    signal_bar_index: int = 0
    execution_bar_index: int = 0

    def __post_init__(self):
        """验证信号一致性"""
        if self.signal_type == SignalType.LONG and self.direction != TradeDirection.LONG:
            raise ValueError("LONG signal must have LONG direction")
        if self.signal_type == SignalType.SHORT and self.direction != TradeDirection.SHORT:
            raise ValueError("SHORT signal must have SHORT direction")


@dataclass
class MarketData:
    """市场数据结构"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    # 额外数据
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def typical_price(self) -> float:
        """典型价格"""
        return (self.high + self.low + self.close) / 3.0

    @property
    def range(self) -> float:
        """价格范围"""
        return self.high - self.low


@dataclass
class TickData:
    """Tick数据结构的"""
    timestamp: datetime
    bid: float
    ask: float
    bid_volume: float = 0.0
    ask_volume: float = 0.0

    @property
    def mid(self) -> float:
        """中间价"""
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        """点差"""
        return self.ask - self.bid


@dataclass
class Position:
    """持仓数据结构"""
    entry_time: datetime
    entry_price: float
    direction: TradeDirection
    size: float
    strategy_id: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    # 动态追踪
    highest_price: float = field(default=0.0)
    lowest_price: float = field(default=float('inf'))
    current_price: float = field(default=0.0)
    bars_held: int = field(default=0)

    # 入场索引
    entry_bar_index: int = field(default=0)

    def __post_init__(self):
        """初始化追踪价格"""
        if self.highest_price == 0.0:
            self.highest_price = self.entry_price
        if self.lowest_price == float('inf'):
            self.lowest_price = self.entry_price
        if self.current_price == 0.0:
            self.current_price = self.entry_price

    def update_price(self, price: float):
        """更新当前价格并追踪最高/最低价"""
        self.current_price = price
        self.highest_price = max(self.highest_price, price)
        self.lowest_price = min(self.lowest_price, price)

    @property
    def unrealized_pnl(self) -> float:
        """未实现盈亏（按点数）"""
        if self.direction == TradeDirection.LONG:
            return (self.current_price - self.entry_price) * self.size
        elif self.direction == TradeDirection.SHORT:
            return (self.entry_price - self.current_price) * self.size
        return 0.0

    @property
    def is_long(self) -> bool:
        return self.direction == TradeDirection.LONG

    @property
    def is_short(self) -> bool:
        return self.direction == TradeDirection.SHORT


@dataclass
class TradeRecord:
    """交易记录数据结构"""
    entry_time: datetime
    exit_time: datetime
    direction: TradeDirection
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    strategy_id: str
    exit_reason: ExitReason
    bars_held: int

    # 额外数据
    entry_slippage: float = 0.0
    exit_slippage: float = 0.0
    commission: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_win(self) -> bool:
        """是否盈利"""
        return self.pnl > 0

    @property
    def is_loss(self) -> bool:
        """是否亏损"""
        return self.pnl < 0


@dataclass
class BacktestResult:
    """回测结果数据结构"""
    # 基本统计
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    # 盈亏统计
    total_pnl: float = 0.0
    total_return: float = 0.0
    avg_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0

    # 风险指标
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # 权益曲线
    equity_curve: List[float] = field(default_factory=list)
    equity_timestamps: List[datetime] = field(default_factory=list)

    # 交易记录
    trades: List[TradeRecord] = field(default_factory=list)

    # 策略统计
    strategy_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # 元数据
    params: Dict[str, Any] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    def calculate_metrics(self):
        """计算衍生指标"""
        if self.total_trades > 0:
            self.win_rate = self.winning_trades / self.total_trades
            self.avg_pnl = self.total_pnl / self.total_trades

        if self.winning_trades > 0:
            self.avg_win = sum(t.pnl for t in self.trades if t.is_win) / self.winning_trades

        if self.losing_trades > 0:
            self.avg_loss = sum(t.pnl for t in self.trades if t.is_loss) / self.losing_trades

        # 盈利因子
        total_gains = sum(t.pnl for t in self.trades if t.is_win)
        total_losses = abs(sum(t.pnl for t in self.trades if t.is_loss))
        if total_losses > 0:
            self.profit_factor = total_gains / total_losses
        elif total_gains > 0:
            self.profit_factor = float('inf')

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'total_pnl': self.total_pnl,
            'total_return': self.total_return,
            'avg_pnl': self.avg_pnl,
            'avg_win': self.avg_win,
            'avg_loss': self.avg_loss,
            'profit_factor': self.profit_factor,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'sharpe_ratio': self.sharpe_ratio,
            'sortino_ratio': self.sortino_ratio,
            'calmar_ratio': self.calmar_ratio,
        }


@dataclass
class OptimizationResult:
    """优化结果数据结构"""
    # 最优参数
    best_params: Dict[str, Any] = field(default_factory=dict)
    best_fitness: float = 0.0

    # 优化统计
    total_trials: int = 0
    completed_trials: int = 0
    pruned_trials: int = 0
    failed_trials: int = 0

    # 优化历史
    trials_history: List[Dict[str, Any]] = field(default_factory=list)

    # 优化时间
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0

    # Walk-Forward 结果
    train_results: Optional[BacktestResult] = None
    test_results: Optional[BacktestResult] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'best_params': self.best_params,
            'best_fitness': self.best_fitness,
            'total_trials': self.total_trials,
            'completed_trials': self.completed_trials,
            'pruned_trials': self.pruned_trials,
            'failed_trials': self.failed_trials,
            'duration_seconds': self.duration_seconds,
            'train_results': self.train_results.to_dict() if self.train_results else None,
            'test_results': self.test_results.to_dict() if self.test_results else None,
        }


# 类型别名
SignalGenerator = Callable[[pd.DataFrame, int, Dict[str, Any]], Optional[TradeSignal]]
PriceData = pd.DataFrame
