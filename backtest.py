"""
回测引擎模块 - 重构版本
========================================
修复前视偏差，支持动态止盈检查

主要改进:
1. Module 1: 使用信号中的execution_bar_index进行入场
2. Module 1: 在check_exit_conditions中传入df和idx以支持动态VWAP止盈
3. 保持tick级别的精确执行模拟
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json
import sys
import os

# 导入策略模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy import TradingStrategy, TradeSignal, SignalType


@dataclass
class Position:
    """持仓信息"""
    entry_time: pd.Timestamp
    entry_price: float
    direction: int  # 1=多头, -1=空头
    size: float
    strategy: str
    stop_loss: float
    take_profit: Optional[float] = None
    highest_price: float = 0.0
    lowest_price: float = float('inf')
    bars_held: int = 0
    entry_bar_idx: int = 0  # Module 1: 记录入场K线索引


@dataclass
class Trade:
    """交易记录"""
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    strategy: str
    exit_reason: str
    bars_held: int


class BacktestEngine:
    """
    回测引擎（重构版）

    关键修复:
    1. 入场时使用signal的execution_bar_index确保使用下一根K线开盘价
    2. 出场检查时传入完整的df和当前索引以支持动态止盈
    3. 滑点模拟更加精确
    """

    def __init__(
        self,
        initial_capital: float = 100000,
        position_size: float = 1.0,
        spread_per_ounce: float = 0.6,
        contract_size: int = 100
    ):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.position_size = position_size
        self.spread_per_ounce = spread_per_ounce
        self.contract_size = contract_size

        # 持仓和交易记录
        self.position: Optional[Position] = None
        self.trades: List[Trade] = []
        self.equity_curve: List[float] = []
        self.equity_timestamps: List[pd.Timestamp] = []

        # 统计信息
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0

    def calculate_spread_cost(self, price: float, size: float) -> float:
        """计算点差成本"""
        return self.spread_per_ounce * self.contract_size * size

    def execute_entry(
        self,
        signal: TradeSignal,
        df: pd.DataFrame
    ) -> bool:
        """
        执行入场（重构版 - 修复止损锚定点问题）

        核心改进:
        1. 策略A: 检查开盘价是否击穿止损，击穿则放弃交易
        2. 策略B: 价格行为确认信号，验证价格可达性
        3. 滑点计算统一使用固定值 + ATR比例

        Args:
            signal: 交易信号
            df: 完整DataFrame

        Returns:
            是否成功入场
        """
        if self.position is not None:
            return False

        direction = 1 if signal.signal_type == SignalType.LONG else -1

        # 使用信号中指定的execution_bar_index
        exec_idx = signal.execution_bar_index

        # 确保索引有效
        if exec_idx >= len(df):
            return False

        # 获取执行K线的数据
        exec_bar = df.iloc[exec_idx]
        high = exec_bar['High']
        low = exec_bar['Low']
        open_price = exec_bar['Open']
        atr = exec_bar['ATR']

        # ========== 滑点常量 ==========
        BASE_SLIPPAGE = 0.15  # 基础滑点 $0.15 (15 pips)
        ATR_SLIPPAGE_RATIO = 0.03  # ATR的3%作为波动滑点
        # 【加固2】策略B滑点动态化：突破行情流动性真空，滑点加大
        # 策略A: 均值回归，左侧交易，滑点较小
        # 策略B: 动量突破，右侧交易，流动性真空，滑点较大
        STRATEGY_B_ATR_SLIPPAGE_RATIO = 0.1  # 策略B使用ATR的10%作为滑点
        slippage = BASE_SLIPPAGE + atr * ATR_SLIPPAGE_RATIO

        # ========== 策略B价格行为确认：K线内执行 ==========
        if signal.entry_price is not None and signal.strategy == 'B':
            target_price = signal.entry_price

            # 幽灵成交验证：检查价格可达性
            if direction == 1:  # 做多，需要High >= target_price
                if high < target_price:
                    return False
            else:  # 做空，需要Low <= target_price
                if low > target_price:
                    return False

            # 【加固2】策略B滑点动态化：突破行情流动性真空
            strategy_b_slippage = BASE_SLIPPAGE + atr * STRATEGY_B_ATR_SLIPPAGE_RATIO

            # 验证通过，使用触发价格 + 更大的滑点
            if direction == 1:
                entry_price = target_price + strategy_b_slippage
            else:
                entry_price = target_price - strategy_b_slippage
        else:
            # ========== 策略A均值回归：开盘价执行 ==========
            entry_price = open_price

            # ========== 关键修复：检查开盘价是否击穿止损 ==========
            # 止损是策略生成时锚定的技术位，不应该"滑坡"
            # 如果开盘价已经击穿止损，放弃该交易
            if signal.stop_loss is not None:
                if direction == 1:  # 多头
                    if open_price <= signal.stop_loss:
                        # 开盘价已击穿止损，放弃交易
                        return False
                else:  # 空头
                    if open_price >= signal.stop_loss:
                        return False

            # 添加滑点
            if direction == 1:
                entry_price = entry_price + slippage
            else:
                entry_price = entry_price - slippage

        # 添加点差成本
        if direction == 1:  # 买入
            entry_price = entry_price + self.spread_per_ounce / 2
        else:  # 卖出
            entry_price = entry_price - self.spread_per_ounce / 2

        self.position = Position(
            entry_time=df.index[exec_idx],
            entry_price=entry_price,
            direction=direction,
            size=self.position_size,
            strategy=signal.strategy,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            highest_price=entry_price if direction == 1 else 0,
            lowest_price=entry_price if direction == -1 else float('inf'),
            bars_held=0,
            entry_bar_idx=exec_idx
        )

        return True

    def execute_exit(
        self,
        exit_price: float,
        exit_reason: str,
        timestamp: pd.Timestamp
    ) -> Optional[Trade]:
        """
        执行出场

        Args:
            exit_price: 出场价格
            exit_reason: 出场原因
            timestamp: 时间戳

        Returns:
            交易记录
        """
        if self.position is None:
            return None

        direction = self.position.direction
        size = self.position.size

        # 出场价格（考虑点差）
        if direction == 1:  # 平多仓
            actual_exit_price = exit_price - self.spread_per_ounce / 2
        else:  # 平空仓
            actual_exit_price = exit_price + self.spread_per_ounce / 2

        # 计算盈亏
        price_diff = (actual_exit_price - self.position.entry_price) * direction
        pnl = price_diff * self.contract_size * size

        # 计算盈亏百分比
        pnl_pct = pnl / self.initial_capital * 100

        # 更新资金
        self.capital += pnl

        # 创建交易记录
        trade = Trade(
            entry_time=self.position.entry_time,
            exit_time=timestamp,
            direction=direction,
            size=size,
            entry_price=self.position.entry_price,
            exit_price=actual_exit_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            strategy=self.position.strategy,
            exit_reason=exit_reason,
            bars_held=self.position.bars_held
        )

        self.trades.append(trade)
        self.total_trades += 1

        if pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

        self.position = None

        return trade

    def run_backtest(
        self,
        df: pd.DataFrame,
        strategy: TradingStrategy,
        verbose: bool = False
    ) -> Dict:
        """
        运行回测（修复版）

        Module 1修复:
        - 入场时机严格遵循execution_bar_index
        - 出场检查时传入df和当前索引以支持动态VWAP止盈

        Args:
            df: 包含所有指标的DataFrame
            strategy: 交易策略
            verbose: 是否打印详细信息

        Returns:
            回测结果字典
        """
        # 重置状态
        self.position = None
        self.trades = []
        self.equity_curve = [self.initial_capital]
        self.equity_timestamps = [df.index[0]]
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.capital = self.initial_capital

        # 生成信号
        signals = strategy.generate_signals(df)

        # 按execution_bar_index排序信号
        signals = sorted(signals, key=lambda s: s.execution_bar_index)

        signal_idx = 0
        pending_signals = []  # 等待执行的信号

        if verbose:
            print(f"生成 {len(signals)} 个交易信号")

        # 遍历每根K线
        # 从有足够历史数据的位置开始
        start_idx = max(100, strategy.params.get('ema_slow', 64))

        for i in range(start_idx, len(df)):
            current_bar = df.iloc[i]
            timestamp = df.index[i]

            # 更新持仓状态
            if self.position:
                self.position.bars_held = i - self.position.entry_bar_idx

                # 更新最高/最低价
                if self.position.direction == 1:
                    self.position.highest_price = max(
                        self.position.highest_price,
                        current_bar['High']
                    )
                else:
                    self.position.lowest_price = min(
                        self.position.lowest_price,
                        current_bar['Low']
                    )

                # Module 1修复: 检查出场条件时传入df和当前索引
                position_dict = {
                    'direction': self.position.direction,
                    'entry_price': self.position.entry_price,
                    'stop_loss': self.position.stop_loss,
                    'take_profit': self.position.take_profit,
                    'strategy': self.position.strategy,
                    'highest_price': self.position.highest_price,
                    'lowest_price': self.position.lowest_price
                }

                # ========== 重构：使用check_exit_conditions返回的实际出场价格 ==========
                should_exit, exit_reason, exit_price = strategy.check_exit_conditions(
                    position_dict,
                    current_bar,
                    self.position.bars_held,
                    df=df,
                    current_idx=i
                )

                # 执行出场
                if should_exit:
                    # 使用策略返回的实际出场价格
                    # 如果策略没有返回价格（不应该发生），使用收盘价作为后备
                    if exit_price is None:
                        exit_price = current_bar['Close']
                    trade = self.execute_exit(exit_price, exit_reason, timestamp)

                    if verbose and trade:
                        print(f"[{timestamp}] 平仓: {exit_reason}, 价格={exit_price:.2f}, PnL: ${trade.pnl:.2f}")

            # 检查是否有新信号需要执行
            while signal_idx < len(signals):
                signal = signals[signal_idx]

                # 信号在当前K线执行
                if signal.execution_bar_index == i:
                    if self.position is None and signal.signal_type in [SignalType.LONG, SignalType.SHORT]:
                        success = self.execute_entry(signal, df)

                        if verbose and success:
                            print(f"[{timestamp}] 开仓: {signal.reason}")

                    signal_idx += 1
                elif signal.execution_bar_index > i:
                    # 信号在未来K线执行，先跳过
                    break
                else:
                    # 信号应该已经执行了（可能已经过期）
                    signal_idx += 1

            # 记录权益曲线
            self.equity_curve.append(self.capital)
            self.equity_timestamps.append(timestamp)

        # 强制平仓最后的持仓
        if self.position:
            last_bar = df.iloc[-1]
            self.execute_exit(
                last_bar['Close'],
                "回测结束强制平仓",
                df.index[-1]
            )

        # 计算统计指标
        stats = self.calculate_statistics()

        return stats

    def calculate_statistics(self) -> Dict:
        """计算回测统计指标"""
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'total_return': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'profit_factor': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'max_win': 0,
                'max_loss': 0,
                'daily_returns': pd.Series(),  # 新增：日度收益率序列
            }

        trades_df = pd.DataFrame([
            {
                'entry_time': t.entry_time,
                'exit_time': t.exit_time,
                'direction': t.direction,
                'pnl': t.pnl,
                'pnl_pct': t.pnl_pct,
                'strategy': t.strategy,
                'bars_held': t.bars_held,
                'exit_reason': t.exit_reason
            }
            for t in self.trades
        ])

        # 基本统计
        total_pnl = trades_df['pnl'].sum()
        total_return = (self.capital - self.initial_capital) / self.initial_capital * 100
        win_rate = self.winning_trades / self.total_trades * 100 if self.total_trades > 0 else 0

        # 盈亏比
        wins = trades_df[trades_df['pnl'] > 0]['pnl']
        losses = trades_df[trades_df['pnl'] <= 0]['pnl']

        avg_win = wins.mean() if len(wins) > 0 else 0
        avg_loss = abs(losses.mean()) if len(losses) > 0 else 0
        profit_factor = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float('inf')

        # 最大回撤
        equity_series = pd.Series(self.equity_curve)
        rolling_max = equity_series.expanding().max()
        drawdown = (equity_series - rolling_max) / rolling_max * 100
        max_drawdown = abs(drawdown.min())

        # 夏普比率
        returns = equity_series.pct_change().dropna()
        sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252 * 24 * 4) if returns.std() != 0 else 0

        # ========== 新增：计算日度收益率序列 ==========
        # 用于精确计算 Calmar 比率
        daily_returns = self._calculate_daily_returns()

        # 按策略分组统计
        strategy_stats = {}
        for strat in ['A', 'B']:
            strat_trades = trades_df[trades_df['strategy'] == strat]
            if len(strat_trades) > 0:
                strategy_stats[f'strategy_{strat}'] = {
                    'trades': len(strat_trades),
                    'win_rate': len(strat_trades[strat_trades['pnl'] > 0]) / len(strat_trades) * 100,
                    'total_pnl': strat_trades['pnl'].sum(),
                    'avg_pnl': strat_trades['pnl'].mean()
                }

        return {
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_win': wins.max() if len(wins) > 0 else 0,
            'max_loss': losses.min() if len(losses) > 0 else 0,
            'avg_bars_held': trades_df['bars_held'].mean(),
            'strategy_stats': strategy_stats,
            'final_capital': self.capital,
            'trades_df': trades_df,
            'daily_returns': daily_returns,  # 新增：日度收益率序列
        }

    def _calculate_daily_returns(self) -> pd.Series:
        """
        计算日度收益率序列（用于精确计算 Calmar 比率）

        将权益曲线重采样为日度频率，计算每日收益率

        Returns:
            日度收益率序列 (pd.Series)
        """
        if len(self.equity_curve) < 2:
            return pd.Series()

        # 创建日度权益 DataFrame
        equity_df = pd.DataFrame({
            'timestamp': self.equity_timestamps,
            'equity': self.equity_curve
        }).set_index('timestamp')

        # 重采样为日度（取每天最后一个值）
        daily_equity = equity_df['equity'].resample('D').last().dropna()

        if len(daily_equity) < 2:
            return pd.Series()

        # 计算日度收益率
        daily_returns = daily_equity.pct_change().dropna()

        return daily_returns

    def get_equity_curve(self) -> pd.DataFrame:
        """获取权益曲线"""
        return pd.DataFrame({
            'timestamp': self.equity_timestamps,
            'equity': self.equity_curve
        }).set_index('timestamp')

    def get_trades_df(self) -> pd.DataFrame:
        """获取交易记录DataFrame"""
        if not self.trades:
            return pd.DataFrame()

        return pd.DataFrame([
            {
                'entry_time': t.entry_time,
                'exit_time': t.exit_time,
                'direction': 'LONG' if t.direction == 1 else 'SHORT',
                'size': t.size,
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'pnl': t.pnl,
                'pnl_pct': t.pnl_pct,
                'strategy': t.strategy,
                'exit_reason': t.exit_reason,
                'bars_held': t.bars_held
            }
            for t in self.trades
        ])


def print_backtest_results(stats: Dict, verbose: bool = True):
    """打印回测结果"""
    print("\n" + "=" * 60)
    print("回测结果摘要")
    print("=" * 60)

    print(f"\n📊 交易统计:")
    print(f"  总交易次数: {stats['total_trades']}")
    print(f"  盈利交易: {stats['winning_trades']}")
    print(f"  亏损交易: {stats['losing_trades']}")
    print(f"  胜率: {stats['win_rate']:.2f}%")

    print(f"\n💰 收益统计:")
    print(f"  总盈亏: ${stats['total_pnl']:.2f}")
    print(f"  总收益率: {stats['total_return']:.2f}%")
    print(f"  最大盈利: ${stats['max_win']:.2f}")
    print(f"  最大亏损: ${stats['max_loss']:.2f}")
    print(f"  平均盈利: ${stats['avg_win']:.2f}")
    print(f"  平均亏损: ${stats['avg_loss']:.2f}")

    print(f"\n📈 风险指标:")
    print(f"  最大回撤: {stats['max_drawdown']:.2f}%")
    print(f"  夏普比率: {stats['sharpe_ratio']:.2f}")
    print(f"  盈亏比: {stats['profit_factor']:.2f}")

    print(f"\n⏱️ 持仓统计:")
    print(f"  平均持仓K线数: {stats.get('avg_bars_held', 0):.1f}")

    if 'strategy_stats' in stats:
        print(f"\n📋 分策略统计:")
        for strat, strat_stats in stats['strategy_stats'].items():
            print(f"  {strat}:")
            print(f"    交易次数: {strat_stats['trades']}")
            print(f"    胜率: {strat_stats['win_rate']:.2f}%")
            print(f"    总盈亏: ${strat_stats['total_pnl']:.2f}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    # 测试回测引擎
    from data_loader import generate_sample_data
    from indicators import add_all_indicators

    # 参数
    params = {
        'bb_period': 12,
        'bb_std': 1.6,
        'kc_period': 15,
        'kc_atr_mult': 1.3,
        'atr_period': 8,
        'rsi_period': 13,
        'rsi_oversold': 21,
        'rsi_overbought': 75,
        'ema_fast': 28,
        'ema_slow': 64,
        'stop_loss_atr_mult_a': 1.2,  # Module 1: 收紧止损
        'stop_loss_atr_mult_b': 2.2,
        'trailing_stop_atr_mult': 3.5,
        'max_hold_bars_a': 5,
        'squeeze_threshold': 0.8,
        # Module 2新增参数
        'volatility_filter_period': 20,
        'volatility_filter_mult': 1.5,
        'pullback_confirmation_bars': 2,
        'ema_momentum_threshold': 0.001,
        'atr_time_stop_base': 3.0,
        'atr_time_stop_mult': 0.5,
    }

    # 获取数据
    df = generate_sample_data(days=90)
    df = add_all_indicators(df, params)

    # 创建策略和回测引擎
    strategy = TradingStrategy(params)
    engine = BacktestEngine(
        initial_capital=100000,
        position_size=1.0,
        spread_per_ounce=0.6
    )

    # 运行回测
    stats = engine.run_backtest(df, strategy, verbose=True)
    print_backtest_results(stats)
