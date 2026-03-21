"""
K线级别回测引擎
===============
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class Position:
    """持仓信息"""
    direction: int  # 1=多, -1=空
    entry_price: float
    entry_time: pd.Timestamp
    stop_loss: float
    strategy: str
    size: float = 1.0
    highest_price: float = 0.0
    lowest_price: float = float('inf')


class BacktestEngine:
    """K线级别回测引擎"""

    def __init__(
        self,
        initial_capital: float = 100000,
        position_size: float = 1.0,
        spread_per_ounce: float = 0.6,
        contract_size: float = 100
    ):
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.spread_per_ounce = spread_per_ounce
        self.contract_size = contract_size

        self.capital = initial_capital
        self.position: Optional[Position] = None
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []

    def run_backtest(
        self,
        df: pd.DataFrame,
        strategy,
        verbose: bool = False
    ) -> Dict:
        """
        运行回测
        """
        self.capital = self.initial_capital
        self.position = None
        self.trades = []
        self.equity_curve = []

        # 生成信号
        signals = strategy.generate_signals(df)

        # 将信号转换为字典以便快速查找
        signal_dict = {}
        for sig in signals:
            bar_idx = sig.execution_bar_index
            if bar_idx not in signal_dict:
                signal_dict[bar_idx] = []
            signal_dict[bar_idx].append(sig)

        # 遍历K线
        for idx in range(len(df)):
            current_bar = df.iloc[idx]
            timestamp = df.index[idx]

            # 更新持仓统计
            if self.position:
                self._update_position_stats(current_bar)

            # 检查出场
            if self.position:
                exit_check = strategy.check_exit_conditions(
                    self._position_to_dict(),
                    current_bar,
                    idx - self._get_entry_idx(df, self.position.entry_time),
                    df, idx
                )
                if exit_check[0]:
                    self._close_position(
                        current_bar,
                        exit_check[1],
                        exit_check[2] if len(exit_check) > 2 else None
                    )

            # 检查入场信号
            if not self.position and idx in signal_dict:
                for sig in signal_dict[idx]:
                    if sig.signal_type.name in ['LONG', 'SHORT']:
                        self._open_position(sig, current_bar, timestamp)
                        break

            # 记录权益
            equity = self.capital
            if self.position:
                unrealized = self._calculate_unrealized_pnl(current_bar)
                equity += unrealized
            self.equity_curve.append({
                'timestamp': timestamp,
                'equity': equity
            })

        # 计算统计
        stats = self._calculate_stats(df)

        if verbose:
            self._print_stats(stats)

        return stats

    def _position_to_dict(self) -> Dict:
        return {
            'direction': self.position.direction,
            'entry_price': self.position.entry_price,
            'stop_loss': self.position.stop_loss,
            'strategy': self.position.strategy,
            'highest_price': self.position.highest_price,
            'lowest_price': self.position.lowest_price,
        }

    def _update_position_stats(self, bar):
        if self.position:
            self.position.highest_price = max(self.position.highest_price, bar['High'])
            self.position.lowest_price = min(self.position.lowest_price, bar['Low'])

    def _get_entry_idx(self, df, entry_time):
        try:
            return df.index.get_loc(entry_time)
        except:
            return 0

    def _open_position(self, sig, bar, timestamp):
        direction = 1 if sig.signal_type.name == 'LONG' else -1
        entry_price = sig.entry_price if sig.entry_price else bar['Open']

        # 添加滑点
        if direction == 1:
            entry_price += self.spread_per_ounce / 2
        else:
            entry_price -= self.spread_per_ounce / 2

        self.position = Position(
            direction=direction,
            entry_price=entry_price,
            entry_time=timestamp,
            stop_loss=sig.stop_loss,
            strategy=sig.strategy,
            size=self.position_size,
            highest_price=entry_price,
            lowest_price=entry_price
        )

    def _close_position(self, bar, reason, exit_price=None):
        if exit_price is None:
            exit_price = bar['Close']

        # 添加滑点
        if self.position.direction == 1:
            exit_price -= self.spread_per_ounce / 2
        else:
            exit_price += self.spread_per_ounce / 2

        pnl = (exit_price - self.position.entry_price) * self.position.direction
        pnl *= self.position.size * self.contract_size

        self.trades.append({
            'entry_time': self.position.entry_time,
            'exit_time': bar.name if hasattr(bar, 'name') else pd.Timestamp.now(),
            'direction': 'long' if self.position.direction == 1 else 'short',
            'size': self.position.size,
            'entry_price': self.position.entry_price,
            'exit_price': exit_price,
            'pnl': pnl,
            'pnl_pct': pnl / self.capital * 100,
            'strategy': self.position.strategy,
            'exit_reason': reason,
        })

        self.capital += pnl
        self.position = None

    def _calculate_unrealized_pnl(self, bar):
        if not self.position:
            return 0
        unrealized = (bar['Close'] - self.position.entry_price) * self.position.direction
        return unrealized * self.position.size * self.contract_size

    def _calculate_stats(self, df) -> Dict:
        if not self.trades:
            return {
                'total_trades': 0,
                'total_return': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'win_rate': 0,
            }

        trades_df = pd.DataFrame(self.trades)
        equity_df = pd.DataFrame(self.equity_curve)

        total_trades = len(self.trades)
        winning_trades = len(trades_df[trades_df['pnl'] > 0])
        losing_trades = len(trades_df[trades_df['pnl'] <= 0])

        total_pnl = trades_df['pnl'].sum()
        total_return = (self.capital / self.initial_capital - 1) * 100

        # 最大回撤
        equity_df['peak'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['peak'] - equity_df['equity']) / equity_df['peak'] * 100
        max_drawdown = equity_df['drawdown'].max()

        # 夏普比率
        if len(trades_df) > 1:
            returns = trades_df['pnl_pct']
            sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        else:
            sharpe = 0

        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': winning_trades / total_trades * 100 if total_trades > 0 else 0,
            'total_pnl': total_pnl,
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe,
            'profit_factor': trades_df[trades_df['pnl'] > 0]['pnl'].sum() / abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum()) if losing_trades > 0 else float('inf'),
            'avg_win': trades_df[trades_df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0,
            'avg_loss': trades_df[trades_df['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0,
            'final_capital': self.capital,
        }

    def _print_stats(self, stats):
        print(f"\n{'='*50}")
        print(f"回测结果")
        print(f"{'='*50}")
        print(f"总交易次数: {stats['total_trades']}")
        print(f"胜率: {stats['win_rate']:.2f}%")
        print(f"总收益率: {stats['total_return']:.2f}%")
        print(f"最大回撤: {stats['max_drawdown']:.2f}%")
        print(f"夏普比率: {stats['sharpe_ratio']:.2f}")
        print(f"盈亏比: {stats['profit_factor']:.2f}")
        print(f"{'='*50}")

    def get_equity_curve(self) -> pd.DataFrame:
        return pd.DataFrame(self.equity_curve)

    def get_trades_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.trades) if self.trades else pd.DataFrame()
