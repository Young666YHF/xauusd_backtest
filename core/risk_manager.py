"""
风险管理模块
============
提供风险评估、仓位管理、止损计算等功能
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np
import pandas as pd


class RiskLevel(Enum):
    """风险等级枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskMetrics:
    """风险指标数据结构"""
    var_95: float = 0.0  # 95% VaR
    var_99: float = 0.0  # 99% VaR
    expected_shortfall: float = 0.0  # 预期亏损
    max_consecutive_losses: int = 0  # 最大连续亏损次数
    current_drawdown: float = 0.0  # 当前回撤
    max_drawdown: float = 0.0  # 最大回撤
    volatility: float = 0.0  # 波动率
    sharpe_ratio: float = 0.0  # 夏普比率
    sortino_ratio: float = 0.0  # 索提诺比率


class RiskManager:
    """风险管理器"""

    def __init__(
        self,
        max_position_size: float = 1.0,
        max_daily_loss_pct: float = 0.02,
        max_drawdown_pct: float = 0.15,
        max_leverage: float = 100.0,
        risk_per_trade_pct: float = 0.01
    ):
        self.max_position_size = max_position_size
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_leverage = max_leverage
        self.risk_per_trade_pct = risk_per_trade_pct

        # 状态追踪
        self.daily_pnl: float = 0.0
        self.daily_trades: int = 0
        self.current_drawdown: float = 0.0
        self.peak_equity: float = 0.0
        self.consecutive_losses: int = 0

        # 风险历史
        self.risk_history: List[RiskMetrics] = []

    def update_equity(self, equity: float):
        """更新权益并计算回撤"""
        if equity > self.peak_equity:
            self.peak_equity = equity
            self.consecutive_losses = 0

        self.current_drawdown = (self.peak_equity - equity) / self.peak_equity if self.peak_equity > 0 else 0

    def record_trade(self, pnl: float):
        """记录交易结果"""
        self.daily_pnl += pnl
        self.daily_trades += 1

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def can_trade(self, current_equity: float) -> Tuple[bool, str]:
        """检查是否可以开仓"""
        # 检查每日最大亏损
        daily_loss_pct = abs(self.daily_pnl) / current_equity if current_equity > 0 else 0
        if daily_loss_pct >= self.max_daily_loss_pct:
            return False, f"Daily loss limit reached: {daily_loss_pct:.2%}"

        # 检查最大回撤
        if self.current_drawdown >= self.max_drawdown_pct:
            return False, f"Max drawdown limit reached: {self.current_drawdown:.2%}"

        # 检查连续亏损
        if self.consecutive_losses >= 5:
            return False, f"Too many consecutive losses: {self.consecutive_losses}"

        return True, "OK"

    def calculate_position_size(
        self,
        capital: float,
        entry_price: float,
        stop_loss: float,
        atr: Optional[float] = None
    ) -> float:
        """
        基于风险计算仓位大小

        Args:
            capital: 可用资金
            entry_price: 入场价格
            stop_loss: 止损价格
            atr: ATR值（可选，用于动态调整）

        Returns:
            建议仓位大小（手数）
        """
        # 计算风险金额
        risk_amount = capital * self.risk_per_trade_pct

        # 计算每手风险
        price_risk = abs(entry_price - stop_loss)
        if price_risk <= 0:
            return 0.0

        # 基础仓位
        contract_size = 100  # XAUUSD合约大小
        risk_per_lot = price_risk * contract_size
        position_size = risk_amount / risk_per_lot

        # 考虑ATR进行动态调整
        if atr and atr > 0:
            volatility_factor = min(1.0, 0.02 / (atr / entry_price))
            position_size *= volatility_factor

        # 限制最大仓位
        position_size = min(position_size, self.max_position_size)

        return max(0.0, position_size)

    def calculate_stop_loss(
        self,
        entry_price: float,
        direction: int,
        atr: float,
        multiplier: float = 1.5
    ) -> float:
        """
        基于ATR计算止损价格

        Args:
            entry_price: 入场价格
            direction: 方向 (1=多, -1=空)
            atr: ATR值
            multiplier: ATR倍数

        Returns:
            止损价格
        """
        stop_distance = atr * multiplier

        if direction == 1:  # 多头
            return entry_price - stop_distance
        else:  # 空头
            return entry_price + stop_distance

    def calculate_take_profit(
        self,
        entry_price: float,
        stop_loss: float,
        direction: int,
        rr_ratio: float = 2.0
    ) -> float:
        """
        基于风险回报比计算止盈价格

        Args:
            entry_price: 入场价格
            stop_loss: 止损价格
            direction: 方向
            rr_ratio: 风险回报比

        Returns:
            止盈价格
        """
        risk = abs(entry_price - stop_loss)
        reward = risk * rr_ratio

        if direction == 1:  # 多头
            return entry_price + reward
        else:  # 空头
            return entry_price - reward

    def calculate_trailing_stop(
        self,
        current_price: float,
        highest_price: float,
        lowest_price: float,
        direction: int,
        atr: float,
        multiplier: float = 2.0
    ) -> Optional[float]:
        """
        计算追踪止损价格

        Args:
            current_price: 当前价格
            highest_price: 持仓期间最高价
            lowest_price: 持仓期间最低价
            direction: 方向
            atr: ATR值
            multiplier: ATR倍数

        Returns:
            新的止损价格或None（不调整）
        """
        trail_distance = atr * multiplier

        if direction == 1:  # 多头
            new_stop = highest_price - trail_distance
            if new_stop > current_price - trail_distance * 1.5:
                return new_stop
        else:  # 空头
            new_stop = lowest_price + trail_distance
            if new_stop < current_price + trail_distance * 1.5:
                return new_stop

        return None

    def assess_risk_level(self, equity_curve: pd.Series) -> RiskLevel:
        """评估当前风险等级"""
        if len(equity_curve) < 20:
            return RiskLevel.MEDIUM

        returns = equity_curve.pct_change().dropna()

        # 计算波动率
        volatility = returns.std() * np.sqrt(252)

        # 计算当前回撤
        peak = equity_curve.expanding().max()
        drawdown = (equity_curve - peak) / peak
        max_dd = drawdown.min()

        # 风险评分
        risk_score = 0

        if volatility > 0.3:
            risk_score += 2
        elif volatility > 0.2:
            risk_score += 1

        if max_dd < -0.15:
            risk_score += 2
        elif max_dd < -0.10:
            risk_score += 1

        if self.consecutive_losses >= 5:
            risk_score += 1

        # 确定风险等级
        if risk_score >= 4:
            return RiskLevel.CRITICAL
        elif risk_score >= 3:
            return RiskLevel.HIGH
        elif risk_score >= 1:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    def reset_daily(self):
        """重置每日统计"""
        self.daily_pnl = 0.0
        self.daily_trades = 0

    def get_status(self) -> Dict:
        """获取风险管理状态"""
        return {
            "daily_pnl": self.daily_pnl,
            "daily_trades": self.daily_trades,
            "current_drawdown": self.current_drawdown,
            "consecutive_losses": self.consecutive_losses,
            "can_trade": self.can_trade(100000)[0]  # 示例检查
        }
