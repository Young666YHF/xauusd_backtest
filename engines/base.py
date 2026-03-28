"""
回测引擎基类
============
定义回测引擎的抽象接口
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from datetime import datetime

from core.types import (
    TradeSignal, TradeRecord, Position, TradeDirection,
    ExitReason, BacktestResult
)
from core.config import TradingConfig
from core.events import EventBus, EventType


class StrategyCategory(Enum):
    """策略分类 - 用于差异化执行参数"""
    MEAN_REVERSION = 1  # 均值回归策略（策略A）
    MOMENTUM_BREAKOUT = 2  # 动量突破策略（策略B）


@dataclass
class ExecutionModel:
    """执行模型 - 定义滑点、佣金等执行参数

    注意：根据全局配置，点差成本已包含佣金，所以commission_per_lot=0
    每手往返成本 = spread_per_ounce × contract_size = 0.6 × 100 = 60美元/手
    每0.01手往返成本 = 60 × 0.01 = 0.6美元
    """
    spread_per_ounce: float = 0.6  # 与TradingConfig一致
    contract_size: int = 100

    # 滑点模型
    base_slippage: float = 0.15
    atr_slippage_ratio: float = 0.03
    strategy_b_atr_ratio: float = 0.10  # 策略B使用更大的ATR比例
    stop_loss_atr_ratio: float = 0.08  # 止损ATR比例

    # 非对称滑点
    stop_loss_slippage_mult: float = 2.0
    take_profit_slippage_mult: float = 0.0

    # 佣金（已包含在点差中，所以设为0）
    commission_per_lot: float = 0.0

    def calculate_entry_slippage(
        self,
        price: float,
        atr: float,
        strategy_category: StrategyCategory = StrategyCategory.MEAN_REVERSION
    ) -> float:
        """计算入场滑点"""
        if strategy_category == StrategyCategory.MOMENTUM_BREAKOUT:
            # 策略B突破入场，滑点更大
            return self.base_slippage + atr * self.strategy_b_atr_ratio
        return self.base_slippage + atr * self.atr_slippage_ratio

    def calculate_exit_slippage(
        self,
        price: float,
        atr: float,
        exit_reason: ExitReason,
        strategy_category: StrategyCategory = StrategyCategory.MEAN_REVERSION
    ) -> float:
        """计算出场滑点"""
        if exit_reason == ExitReason.STOP_LOSS:
            # 止损滑点更大（流动性枯竭）
            return self.base_slippage * self.stop_loss_slippage_mult + atr * self.stop_loss_atr_ratio
        elif exit_reason == ExitReason.TAKE_PROFIT:
            # 止盈滑点较小（限价单）
            return 0.0
        return self.base_slippage + atr * self.atr_slippage_ratio

    def calculate_commission(self, size: float) -> float:
        """计算佣金"""
        return self.commission_per_lot * size * 2


class BaseBacktestEngine(ABC):
    """
    回测引擎抽象基类

    子类必须实现:
    - run: 执行回测
    - _execute_signal: 执行信号
    """

    def __init__(
        self,
        config: TradingConfig,
        execution_model: Optional[ExecutionModel] = None
    ):
        self.config = config
        self.execution = execution_model or ExecutionModel()
        self.event_bus = EventBus()

        # 状态
        self.capital: float = config.initial_capital
        self.initial_capital: float = config.initial_capital
        self.position: Optional[Position] = None
        self.trades: List[TradeRecord] = []
        self.equity_curve: List[float] = []
        self.equity_timestamps: List[datetime] = []

        # 统计
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0

        # 中间状态
        self._current_bar_idx = 0
        self._df: Optional[pd.DataFrame] = None

    @abstractmethod
    def run(
        self,
        df: pd.DataFrame,
        signals: List[TradeSignal]
    ) -> BacktestResult:
        """
        执行回测

        Args:
            df: 价格数据
            signals: 交易信号列表

        Returns:
            BacktestResult
        """
        pass

    def reset(self):
        """重置引擎状态"""
        self.capital = self.initial_capital
        self.position = None
        self.trades.clear()
        self.equity_curve.clear()
        self.equity_timestamps.clear()
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self._current_bar_idx = 0

    def get_current_equity(self) -> float:
        """获取当前权益（包含未实现盈亏）"""
        equity = self.capital
        if self.position:
            equity += self.position.unrealized_pnl * self.config.contract_size
        return equity

    def _open_position(
        self,
        signal: TradeSignal,
        filled_price: float,
        slippage: float = 0.0
    ) -> Position:
        """开仓 - 支持资金百分比风险管理"""

        # 计算仓位大小
        if signal.size is not None:
            # 使用固定手数
            position_size = signal.size
        elif signal.stop_loss is not None and signal.stop_loss > 0:
            # 基于风险百分比计算手数
            current_equity = self.get_current_equity()
            risk_amount = current_equity * signal.risk_per_trade  # 风险金额

            # 计算止损点数
            stop_distance = abs(filled_price - signal.stop_loss)
            if stop_distance > 0:
                # 手数 = 风险金额 / (止损点数 × 点值)
                point_value = self.config.contract_size  # 每点价值
                position_size = risk_amount / (stop_distance * point_value)

                # 限制最大手数（防止极端情况）
                max_size = current_equity / (filled_price * self.config.contract_size / self.config.leverage)
                position_size = min(position_size, max_size * 0.9)  # 留10%余量
            else:
                position_size = 0.01  # 最小手数兜底
        else:
            # 资金百分比仓位：使用 risk_per_trade 比例的资金作为名义本金
            # 公式：手数 = (资金 × 风险比例) / (价格 × 合约大小 / 杠杆)
            current_equity = self.get_current_equity()
            position_value = current_equity * signal.risk_per_trade  # 名义仓位金额
            contract_value = filled_price * self.config.contract_size  # 每手合约价值
            position_size = position_value / contract_value * self.config.leverage

            # 限制最小手数
            position_size = max(position_size, 0.01)

        position = Position(
            entry_time=signal.timestamp,
            entry_price=filled_price,
            direction=signal.direction,
            size=position_size,
            strategy_id=signal.strategy_id,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            entry_bar_index=self._current_bar_idx
        )

        self.position = position

        # 入场时扣除佣金（如果有的话）
        # 注意：点差成本在出场时一次性扣除，这里只扣除额外佣金
        commission = self.execution.calculate_commission(position_size)
        self.capital -= commission

        # 发送事件
        self.event_bus.emit_new(
            EventType.POSITION_OPENED,
            source=self.__class__.__name__,
            position=position,
            signal=signal,
            slippage=slippage,
            commission=commission
        )

        return position

    def _close_position(
        self,
        exit_price: float,
        exit_reason: ExitReason,
        slippage: float = 0.0
    ) -> TradeRecord:
        """平仓"""
        if not self.position:
            raise ValueError("No position to close")

        pos = self.position

        # 计算调整后的出场价格（考虑滑点）
        if pos.direction == TradeDirection.LONG:
            exit_price_adjusted = exit_price - slippage
            pnl_points = exit_price_adjusted - pos.entry_price
        else:
            exit_price_adjusted = exit_price + slippage
            pnl_points = pos.entry_price - exit_price_adjusted

        # 计算金额盈亏
        pnl = pnl_points * self.config.contract_size * pos.size
        pnl_pct = pnl_points / pos.entry_price if pos.entry_price != 0 else 0

        # 【修复】扣除点差成本（已包含佣金）
        # 每手往返成本 = spread_per_ounce × contract_size
        # 每0.01手成本 = 0.6 × 100 × 0.01 = 0.6美元
        spread_cost = self.config.spread_per_ounce * self.config.contract_size * pos.size
        pnl -= spread_cost

        # 扣除额外佣金（如果有）
        commission = self.execution.calculate_commission(pos.size)
        pnl -= commission
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
            commission=spread_cost + commission  # 记录总成本
        )

        self.trades.append(trade)
        self.total_trades += 1

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

    def _check_exit_conditions(
        self,
        high: float,
        low: float,
        close: float
    ) -> Optional[ExitReason]:
        """检查出场条件"""
        if not self.position:
            return None

        pos = self.position

        # 更新追踪价格
        pos.update_price(close)

        # 检查止损
        if pos.stop_loss:
            if pos.is_long and low <= pos.stop_loss:
                return ExitReason.STOP_LOSS
            if pos.is_short and high >= pos.stop_loss:
                return ExitReason.STOP_LOSS

        # 检查止盈
        if pos.take_profit:
            if pos.is_long and high >= pos.take_profit:
                return ExitReason.TAKE_PROFIT
            if pos.is_short and low <= pos.take_profit:
                return ExitReason.TAKE_PROFIT

        return None

    def _build_result(self) -> BacktestResult:
        """构建回测结果"""
        result = BacktestResult()

        # 基本统计
        result.total_trades = self.total_trades
        result.winning_trades = self.winning_trades
        result.losing_trades = self.losing_trades
        result.win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0

        # 盈亏统计
        result.total_pnl = sum(t.pnl for t in self.trades)
        result.total_return = result.total_pnl / self.initial_capital

        if self.total_trades > 0:
            result.avg_pnl = result.total_pnl / self.total_trades
            wins = [t.pnl for t in self.trades if t.is_win]
            losses = [t.pnl for t in self.trades if t.is_loss]
            result.avg_win = sum(wins) / len(wins) if wins else 0
            result.avg_loss = sum(losses) / len(losses) if losses else 0

        # 盈利因子
        total_gains = sum(t.pnl for t in self.trades if t.is_win)
        total_losses = abs(sum(t.pnl for t in self.trades if t.is_loss))
        result.profit_factor = total_gains / total_losses if total_losses > 0 else float('inf')

        # 权益曲线
        result.equity_curve = self.equity_curve.copy()
        result.equity_timestamps = self.equity_timestamps.copy()

        # 计算回撤（正确处理负权益情况）
        if self.equity_curve:
            peak = self.equity_curve[0]
            max_dd = 0
            max_dd_value = 0
            for equity in self.equity_curve:
                if equity > peak:
                    peak = equity
                # 回撤金额
                dd_value = peak - equity
                # 回撤率：基于初始资金计算（更直观）
                dd_pct = dd_value / self.initial_capital if self.initial_capital > 0 else 0
                if dd_value > max_dd_value:
                    max_dd_value = dd_value
                    max_dd = dd_pct
            result.max_drawdown_pct = -max_dd  # 返回负值表示回撤
            result.max_drawdown = max_dd_value

        # 夏普比率
        if len(self.equity_curve) > 1:
            returns = pd.Series(self.equity_curve).pct_change().dropna()
            if len(returns) > 0 and returns.std() > 0:
                # 年化因子：30分钟数据，每天48根K线，每年252个交易日
                annual_factor = np.sqrt(252 * 48)
                result.sharpe_ratio = (returns.mean() / returns.std()) * annual_factor

                # 索提诺比率（只考虑下行波动）
                downside_returns = returns[returns < 0]
                if len(downside_returns) > 0 and downside_returns.std() > 0:
                    result.sortino_ratio = (returns.mean() / downside_returns.std()) * annual_factor

        # 卡玛比率（年化收益率 / 最大回撤）
        if result.max_drawdown_pct != 0 and len(self.equity_curve) > 1:
            # 计算年化收益率
            total_return = result.total_return
            years = len(self.equity_curve) / (252 * 48)  # 30分钟数据
            if years > 0:
                annual_return = (1 + total_return) ** (1 / years) - 1
                result.calmar_ratio = annual_return / abs(result.max_drawdown_pct)

        result.trades = self.trades.copy()

        return result
