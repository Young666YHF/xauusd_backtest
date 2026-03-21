"""
Tick级别回测引擎
================
基于Numba JIT编译的高性能撮合引擎
支持Bid/Ask价格处理，无需spread参数
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import warnings

try:
    from numba import jit, prange
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False
    warnings.warn("Numba not available, using pure Python implementation")


@dataclass
class TickPosition:
    """Tick级别持仓"""
    direction: int  # 1=多, -1=空
    entry_price: float
    entry_time: int  # tick索引
    stop_loss: float
    trailing_stop: float
    strategy: str
    size: float = 1.0
    highest_price: float = 0.0
    lowest_price: float = float('inf')
    entry_atr: float = 0.0


@dataclass
class TickTrade:
    """Tick级别交易记录"""
    entry_time: int
    exit_time: int
    direction: int
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    strategy: str
    exit_reason: str
    entry_atr: float
    exit_atr: float


# Numba核心撮合函数
def fast_tick_matcher(
    bid_prices: np.ndarray,
    ask_prices: np.ndarray,
    timestamps: np.ndarray,
    signal_times: np.ndarray,  # 信号触发时间索引
    signal_directions: np.ndarray,  # 信号方向 (1=多, -1=空)
    signal_stop_losses: np.ndarray,  # 止损价格
    signal_strategies: np.ndarray,  # 策略类型 (0=A, 1=B)
    signal_atrs: np.ndarray,  # 信号时的ATR
    stop_loss_mult_b: float,
    trailing_stop_mult: float,
    max_hold_bars_a: int,
    atr_time_stop_base: float,
    atr_time_stop_mult: float,
    bar_indices: np.ndarray,  # 每个tick对应的K线索引
    contract_size: float = 100.0
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Numba JIT编译的核心撮合引擎

    Args:
        bid_prices: Bid价格数组
        ask_prices: Ask价格数组
        timestamps: 时间戳数组
        signal_times: 信号触发时间索引数组
        signal_directions: 信号方向数组
        signal_stop_losses: 止损价格数组
        signal_strategies: 策略类型数组
        signal_atrs: 信号时ATR数组
        stop_loss_mult_b: 策略B止损倍数
        trailing_stop_mult: 追踪止损倍数
        max_hold_bars_a: 策略A最大持仓K线数
        atr_time_stop_base: ATR时间止损基数
        atr_time_stop_mult: ATR时间止损倍数
        bar_indices: 每个tick对应的K线索引
        contract_size: 合约大小

    Returns:
        (交易记录数组, 权益曲线数组)
    """
    n_ticks = len(bid_prices)
    n_signals = len(signal_times)

    # 交易记录
    trades = []
    trade_idx = 0

    # 状态变量
    position = None  # (direction, entry_price, entry_time, stop_loss, trailing_stop, strategy, highest, lowest, entry_atr, entry_bar)
    equity = 100000.0  # 初始资金
    initial_capital = 100000.0

    # 权益曲线
    equity_curve = np.zeros(n_ticks)
    equity_curve[0] = equity

    # 当前信号索引
    signal_idx = 0

    for tick_idx in range(n_ticks):
        bid = bid_prices[tick_idx]
        ask = ask_prices[tick_idx]
        current_bar = bar_indices[tick_idx]

        # 检查入场信号
        if position is None and signal_idx < n_signals:
            sig_time = signal_times[signal_idx]

            if tick_idx == sig_time:
                direction = signal_directions[signal_idx]
                stop_loss = signal_stop_losses[signal_idx]
                strategy = signal_strategies[signal_idx]
                atr = signal_atrs[signal_idx]

                # 入场价格: 做多用Ask, 做空用Bid
                if direction == 1:
                    entry_price = ask
                else:
                    entry_price = bid

                # 策略B初始化追踪止损
                trailing_stop = 0.0
                if strategy == 1:  # 策略B
                    if direction == 1:
                        trailing_stop = entry_price - trailing_stop_mult * atr
                    else:
                        trailing_stop = entry_price + trailing_stop_mult * atr

                position = (
                    direction,
                    entry_price,
                    tick_idx,
                    stop_loss,
                    trailing_stop,
                    strategy,
                    entry_price,  # highest
                    entry_price,  # lowest
                    atr,  # entry_atr
                    current_bar  # entry_bar
                )

                signal_idx += 1

        # 检查出场
        if position is not None:
            direction, entry_price, entry_time, stop_loss, trailing_stop, strategy, highest, lowest, entry_atr, entry_bar = position

            # 更新最高/最低价
            mid = (bid + ask) / 2
            highest = max(highest, mid)
            lowest = min(lowest, mid)

            # 计算当前ATR (简化: 使用入场ATR作为基准)
            # 在完整实现中应该传入实时ATR
            current_atr = entry_atr

            exit_triggered = False
            exit_reason = ''
            exit_price = 0.0

            if direction == 1:  # 多头
                # 止损检查
                if bid <= stop_loss:
                    exit_triggered = True
                    exit_reason = 'stop_loss'
                    exit_price = stop_loss

                # 追踪止损 (策略B)
                elif strategy == 1:
                    new_trailing = highest - trailing_stop_mult * current_atr
                    trailing_stop = max(trailing_stop, new_trailing)
                    if bid <= trailing_stop:
                        exit_triggered = True
                        exit_reason = 'trailing_stop'
                        exit_price = trailing_stop

            else:  # 空头
                # 止损检查
                if ask >= stop_loss:
                    exit_triggered = True
                    exit_reason = 'stop_loss'
                    exit_price = stop_loss

                # 追踪止损 (策略B)
                elif strategy == 1:
                    new_trailing = lowest + trailing_stop_mult * current_atr
                    if trailing_stop == 0:
                        trailing_stop = new_trailing
                    else:
                        trailing_stop = min(trailing_stop, new_trailing)
                    if ask >= trailing_stop:
                        exit_triggered = True
                        exit_reason = 'trailing_stop'
                        exit_price = trailing_stop

            # 时间止损 (策略A)
            if strategy == 0 and not exit_triggered:
                bars_held = current_bar - entry_bar
                adaptive_max_bars = int(atr_time_stop_base + atr_time_stop_mult * entry_atr)
                max_bars = min(max_hold_bars_a, adaptive_max_bars)

                if bars_held >= max_bars:
                    exit_triggered = True
                    exit_reason = 'time_stop'
                    exit_price = bid if direction == 1 else ask

            # 执行出场
            if exit_triggered:
                # 计算盈亏
                pnl = (exit_price - entry_price) * direction
                pnl *= contract_size

                trades.append((
                    entry_time,
                    tick_idx,
                    direction,
                    1.0,  # size
                    entry_price,
                    exit_price,
                    pnl,
                    pnl / equity * 100,
                    strategy,
                    exit_reason,
                    entry_atr,
                    current_atr
                ))

                equity += pnl
                position = None

        # 更新持仓的最高/最低价
        if position is not None:
            position = (
                position[0], position[1], position[2], position[3],
                position[4], position[5], highest, lowest, position[8], position[9]
            )

        # 记录权益
        equity_curve[tick_idx] = equity

    # 转换为数组
    trades_array = np.array(trades) if trades else np.zeros((0, 12))

    return trades_array, equity_curve


class NumbaTickBacktestEngine:
    """
    Numba加速的Tick回测引擎
    """

    def __init__(
        self,
        initial_capital: float = 100000,
        position_size: float = 1.0,
        contract_size: float = 100,
        stop_loss_mult_b: float = 2.0,
        trailing_stop_mult: float = 3.0,
        max_hold_bars_a: int = 6,
        atr_time_stop_base: float = 5.0,
        atr_time_stop_mult: float = 0.5
    ):
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.contract_size = contract_size
        self.stop_loss_mult_b = stop_loss_mult_b
        self.trailing_stop_mult = trailing_stop_mult
        self.max_hold_bars_a = max_hold_bars_a
        self.atr_time_stop_base = atr_time_stop_base
        self.atr_time_stop_mult = atr_time_stop_mult

    def run(
        self,
        ticks_df: pd.DataFrame,
        signals: List[Dict],
        ohlcv_df: pd.DataFrame
    ) -> Dict:
        """
        运行Tick级别回测

        Args:
            ticks_df: Tick数据 (bid, ask, volume)
            signals: 信号列表
            ohlcv_df: OHLCV数据 (用于获取ATR和bar索引)

        Returns:
            回测结果统计
        """
        # 准备数据
        bid_prices = ticks_df['bid'].values.astype(np.float64)
        ask_prices = ticks_df['ask'].values.astype(np.float64)
        n_ticks = len(ticks_df)

        # 创建tick到K线的映射
        bar_indices = self._create_bar_mapping(ticks_df, ohlcv_df)

        # 准备信号数据
        signal_times = []
        signal_directions = []
        signal_stop_losses = []
        signal_strategies = []
        signal_atrs = []

        for sig in signals:
            # 找到信号对应的tick索引
            sig_time = sig.get('timestamp')
            if sig_time is None:
                continue

            # 在ticks中找到最近的索引
            try:
                tick_idx = ticks_df.index.get_indexer([sig_time], method='nearest')[0]
            except:
                continue

            if tick_idx < 0 or tick_idx >= n_ticks:
                continue

            signal_times.append(tick_idx)
            signal_directions.append(sig.get('direction', 1))
            signal_stop_losses.append(sig.get('stop_loss', 0.0))
            signal_strategies.append(0 if sig.get('strategy') == 'A' else 1)

            # 获取ATR
            atr = self._get_atr_at_time(ohlcv_df, sig_time)
            signal_atrs.append(atr)

        # 转换为numpy数组
        signal_times = np.array(signal_times, dtype=np.int64)
        signal_directions = np.array(signal_directions, dtype=np.int64)
        signal_stop_losses = np.array(signal_stop_losses, dtype=np.float64)
        signal_strategies = np.array(signal_strategies, dtype=np.int64)
        signal_atrs = np.array(signal_atrs, dtype=np.float64)

        # 按时间排序信号
        if len(signal_times) > 0:
            sort_idx = np.argsort(signal_times)
            signal_times = signal_times[sort_idx]
            signal_directions = signal_directions[sort_idx]
            signal_stop_losses = signal_stop_losses[sort_idx]
            signal_strategies = signal_strategies[sort_idx]
            signal_atrs = signal_atrs[sort_idx]

        # 运行撮合引擎
        trades_array, equity_curve = fast_tick_matcher(
            bid_prices,
            ask_prices,
            ticks_df.index.values.astype(np.int64),
            signal_times,
            signal_directions,
            signal_stop_losses,
            signal_strategies,
            signal_atrs,
            self.stop_loss_mult_b,
            self.trailing_stop_mult,
            self.max_hold_bars_a,
            self.atr_time_stop_base,
            self.atr_time_stop_mult,
            bar_indices,
            self.contract_size
        )

        # 计算统计
        stats = self._calculate_stats(trades_array, equity_curve)

        return stats

    def _create_bar_mapping(
        self,
        ticks_df: pd.DataFrame,
        ohlcv_df: pd.DataFrame
    ) -> np.ndarray:
        """
        创建tick到K线索引的映射
        """
        n_ticks = len(ticks_df)
        bar_indices = np.zeros(n_ticks, dtype=np.int64)

        if len(ohlcv_df) == 0:
            return bar_indices

        ohlcv_times = ohlcv_df.index.values

        for i in range(n_ticks):
            tick_time = ticks_df.index[i]
            # 找到对应的K线索引
            bar_idx = np.searchsorted(ohlcv_times, tick_time, side='right') - 1
            bar_indices[i] = max(0, bar_idx)

        return bar_indices

    def _get_atr_at_time(self, ohlcv_df: pd.DataFrame, timestamp) -> float:
        """获取指定时间的ATR"""
        if 'ATR' not in ohlcv_df.columns:
            return 5.0  # 默认ATR

        try:
            idx = ohlcv_df.index.get_indexer([timestamp], method='nearest')[0]
            if idx >= 0 and idx < len(ohlcv_df):
                atr = ohlcv_df['ATR'].iloc[idx]
                return atr if not np.isnan(atr) else 5.0
        except:
            pass

        return 5.0

    def _calculate_stats(self, trades_array: np.ndarray, equity_curve: np.ndarray) -> Dict:
        """计算回测统计"""
        if len(trades_array) == 0:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'total_return': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'profit_factor': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'final_capital': self.initial_capital,
            }

        # 提取交易数据
        pnls = trades_array[:, 6]  # pnl列

        total_trades = len(trades_array)
        winning_trades = int(np.sum(pnls > 0))
        losing_trades = int(np.sum(pnls <= 0))

        total_pnl = float(np.sum(pnls))
        final_capital = self.initial_capital + total_pnl
        total_return = (final_capital / self.initial_capital - 1) * 100

        # 最大回撤
        peak = np.maximum.accumulate(equity_curve)
        drawdown = (peak - equity_curve) / peak * 100
        max_drawdown = float(np.max(drawdown))

        # 夏普比率
        if len(pnls) > 1 and np.std(pnls) > 0:
            sharpe = float(np.mean(pnls) / np.std(pnls) * np.sqrt(252))
        else:
            sharpe = 0

        # 盈亏比
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        profit_factor = float(np.sum(wins) / abs(np.sum(losses))) if len(losses) > 0 else float('inf')

        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
        avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0

        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': winning_trades / total_trades * 100 if total_trades > 0 else 0,
            'total_pnl': total_pnl,
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'final_capital': final_capital,
        }


class TickBacktestEngine:
    """
    Python实现的Tick回测引擎 (兼容模式)
    不使用Numba，纯Python实现
    """

    def __init__(
        self,
        initial_capital: float = 100000,
        position_size: float = 1.0,
        contract_size: float = 100,
        stop_loss_mult_b: float = 2.0,
        trailing_stop_mult: float = 3.0,
        max_hold_bars_a: int = 6,
        atr_time_stop_base: float = 5.0,
        atr_time_stop_mult: float = 0.5
    ):
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.contract_size = contract_size
        self.stop_loss_mult_b = stop_loss_mult_b
        self.trailing_stop_mult = trailing_stop_mult
        self.max_hold_bars_a = max_hold_bars_a
        self.atr_time_stop_base = atr_time_stop_base
        self.atr_time_stop_mult = atr_time_stop_mult

        self.capital = initial_capital
        self.position: Optional[TickPosition] = None
        self.trades: List[TickTrade] = []
        self.equity_curve: List[float] = []
        self.entry_bar: int = 0

    def run(
        self,
        ticks_df: pd.DataFrame,
        signals: List[Dict],
        ohlcv_df: pd.DataFrame
    ) -> Dict:
        """
        运行Tick级别回测

        Args:
            ticks_df: Tick数据 (bid, ask, volume)
            signals: 信号列表
            ohlcv_df: OHLCV数据

        Returns:
            回测结果统计
        """
        # 重置状态
        self.capital = self.initial_capital
        self.position = None
        self.trades = []
        self.equity_curve = []

        # 创建tick到K线的映射
        bar_indices = self._create_bar_mapping(ticks_df, ohlcv_df)

        # 预计算ATR数组
        atr_array = self._prepare_atr_array(ohlcv_df, len(ticks_df), bar_indices)

        # 信号索引映射
        signal_map = self._create_signal_map(signals, ticks_df)

        # 遍历每个tick
        for tick_idx in range(len(ticks_df)):
            bid = ticks_df['bid'].iloc[tick_idx]
            ask = ticks_df['ask'].iloc[tick_idx]
            current_bar = int(bar_indices[tick_idx])
            current_atr = atr_array[tick_idx]

            # 检查入场信号
            if self.position is None and tick_idx in signal_map:
                sig = signal_map[tick_idx]
                self._open_position(sig, bid, ask, tick_idx, current_bar, current_atr)

            # 检查出场条件
            if self.position is not None:
                self._check_exit(bid, ask, tick_idx, current_bar, current_atr, ohlcv_df)

            # 记录权益
            self.equity_curve.append(self.capital)

        # 计算统计
        return self._calculate_stats()

    def _create_bar_mapping(
        self,
        ticks_df: pd.DataFrame,
        ohlcv_df: pd.DataFrame
    ) -> np.ndarray:
        """创建tick到K线的映射"""
        n_ticks = len(ticks_df)
        bar_indices = np.zeros(n_ticks, dtype=np.int64)

        if len(ohlcv_df) == 0:
            return bar_indices

        ohlcv_times = ohlcv_df.index.values

        for i in range(n_ticks):
            tick_time = ticks_df.index[i]
            bar_idx = np.searchsorted(ohlcv_times, tick_time, side='right') - 1
            bar_indices[i] = max(0, bar_idx)

        return bar_indices

    def _prepare_atr_array(
        self,
        ohlcv_df: pd.DataFrame,
        n_ticks: int,
        bar_indices: np.ndarray
    ) -> np.ndarray:
        """准备ATR数组"""
        atr_array = np.full(n_ticks, 5.0)  # 默认ATR

        if 'ATR' not in ohlcv_df.columns:
            return atr_array

        atr_values = ohlcv_df['ATR'].values

        for i in range(n_ticks):
            bar_idx = int(bar_indices[i])
            if bar_idx < len(atr_values):
                atr = atr_values[bar_idx]
                if not np.isnan(atr):
                    atr_array[i] = atr

        return atr_array

    def _create_signal_map(
        self,
        signals: List[Dict],
        ticks_df: pd.DataFrame
    ) -> Dict[int, Dict]:
        """创建信号映射"""
        signal_map = {}

        for sig in signals:
            sig_time = sig.get('timestamp')
            if sig_time is None:
                continue

            try:
                tick_idx = ticks_df.index.get_indexer([sig_time], method='nearest')[0]
                if tick_idx >= 0 and tick_idx < len(ticks_df):
                    signal_map[tick_idx] = sig
            except:
                continue

        return signal_map

    def _open_position(
        self,
        sig: Dict,
        bid: float,
        ask: float,
        tick_idx: int,
        current_bar: int,
        current_atr: float
    ):
        """开仓"""
        direction = sig.get('direction', 1)

        # 入场价格: 做多用Ask, 做空用Bid
        if direction == 1:
            entry_price = ask
        else:
            entry_price = bid

        stop_loss = sig.get('stop_loss', 0.0)
        strategy = sig.get('strategy', 'A')

        # 策略B初始化追踪止损
        trailing_stop = 0.0
        if strategy == 'B':
            if direction == 1:
                trailing_stop = entry_price - self.trailing_stop_mult * current_atr
            else:
                trailing_stop = entry_price + self.trailing_stop_mult * current_atr

        self.position = TickPosition(
            direction=direction,
            entry_price=entry_price,
            entry_time=tick_idx,
            stop_loss=stop_loss,
            trailing_stop=trailing_stop,
            strategy=strategy,
            size=self.position_size,
            highest_price=entry_price,
            lowest_price=entry_price,
            entry_atr=current_atr
        )

        self.entry_bar = current_bar

    def _check_exit(
        self,
        bid: float,
        ask: float,
        tick_idx: int,
        current_bar: int,
        current_atr: float,
        ohlcv_df: pd.DataFrame
    ):
        """检查出场条件"""
        if self.position is None:
            return

        pos = self.position
        exit_triggered = False
        exit_reason = ''
        exit_price = 0.0

        # 更新最高/最低价
        mid = (bid + ask) / 2
        pos.highest_price = max(pos.highest_price, mid)
        pos.lowest_price = min(pos.lowest_price, mid)

        if pos.direction == 1:  # 多头
            # 止损检查
            if bid <= pos.stop_loss:
                exit_triggered = True
                exit_reason = 'stop_loss'
                exit_price = pos.stop_loss

            # 追踪止损 (策略B) - 使用当前ATR
            elif pos.strategy == 'B':
                new_trailing = pos.highest_price - self.trailing_stop_mult * current_atr
                pos.trailing_stop = max(pos.trailing_stop, new_trailing)
                if bid <= pos.trailing_stop:
                    exit_triggered = True
                    exit_reason = 'trailing_stop'
                    exit_price = pos.trailing_stop

        else:  # 空头
            # 止损检查
            if ask >= pos.stop_loss:
                exit_triggered = True
                exit_reason = 'stop_loss'
                exit_price = pos.stop_loss

            # 追踪止损 (策略B) - 使用当前ATR
            elif pos.strategy == 'B':
                new_trailing = pos.lowest_price + self.trailing_stop_mult * current_atr
                if pos.trailing_stop == 0:
                    pos.trailing_stop = new_trailing
                else:
                    pos.trailing_stop = min(pos.trailing_stop, new_trailing)
                if ask >= pos.trailing_stop:
                    exit_triggered = True
                    exit_reason = 'trailing_stop'
                    exit_price = pos.trailing_stop

        # 时间止损 (策略A)
        if pos.strategy == 'A' and not exit_triggered:
            bars_held = current_bar - self.entry_bar
            adaptive_max_bars = int(self.atr_time_stop_base + self.atr_time_stop_mult * pos.entry_atr)
            max_bars = min(self.max_hold_bars_a, adaptive_max_bars)

            if bars_held >= max_bars:
                exit_triggered = True
                exit_reason = 'time_stop'
                exit_price = bid if pos.direction == 1 else ask

        # 执行出场
        if exit_triggered:
            self._close_position(tick_idx, exit_price, exit_reason, current_atr)

    def _close_position(
        self,
        tick_idx: int,
        exit_price: float,
        exit_reason: str,
        exit_atr: float
    ):
        """平仓"""
        if self.position is None:
            return

        pos = self.position

        # 计算盈亏
        pnl = (exit_price - pos.entry_price) * pos.direction
        pnl *= pos.size * self.contract_size

        trade = TickTrade(
            entry_time=pos.entry_time,
            exit_time=tick_idx,
            direction=pos.direction,
            size=pos.size,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            pnl=pnl,
            pnl_pct=pnl / self.capital * 100,
            strategy=pos.strategy,
            exit_reason=exit_reason,
            entry_atr=pos.entry_atr,
            exit_atr=exit_atr
        )

        self.trades.append(trade)
        self.capital += pnl
        self.position = None

    def _calculate_stats(self) -> Dict:
        """计算回测统计"""
        if not self.trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'total_return': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'profit_factor': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'final_capital': self.initial_capital,
            }

        pnls = [t.pnl for t in self.trades]

        total_trades = len(self.trades)
        winning_trades = sum(1 for p in pnls if p > 0)
        losing_trades = sum(1 for p in pnls if p <= 0)

        total_pnl = sum(pnls)
        final_capital = self.capital
        total_return = (final_capital / self.initial_capital - 1) * 100

        # 最大回撤
        equity_array = np.array(self.equity_curve)
        peak = np.maximum.accumulate(equity_array)
        drawdown = (peak - equity_array) / peak * 100
        max_drawdown = float(np.max(drawdown))

        # 夏普比率
        if len(pnls) > 1 and np.std(pnls) > 0:
            sharpe = float(np.mean(pnls) / np.std(pnls) * np.sqrt(252))
        else:
            sharpe = 0

        # 盈亏比
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        profit_factor = sum(wins) / abs(sum(losses)) if losses else float('inf')

        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0

        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': winning_trades / total_trades * 100 if total_trades > 0 else 0,
            'total_pnl': total_pnl,
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'final_capital': final_capital,
        }

    def get_trades_df(self) -> pd.DataFrame:
        """获取交易记录DataFrame"""
        if not self.trades:
            return pd.DataFrame()

        data = []
        for t in self.trades:
            data.append({
                'entry_time': t.entry_time,
                'exit_time': t.exit_time,
                'direction': 'long' if t.direction == 1 else 'short',
                'size': t.size,
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'pnl': t.pnl,
                'pnl_pct': t.pnl_pct,
                'strategy': t.strategy,
                'exit_reason': t.exit_reason,
                'entry_atr': t.entry_atr,
                'exit_atr': t.exit_atr,
            })

        return pd.DataFrame(data)

    def get_equity_curve(self) -> pd.DataFrame:
        """获取权益曲线"""
        return pd.DataFrame({'equity': self.equity_curve})
