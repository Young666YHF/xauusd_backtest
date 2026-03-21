"""
可视化模块
"""
import pandas as pd
import numpy as np
from typing import Dict, List


def plot_backtest_results(df: pd.DataFrame, trades: List[Dict], stats: Dict):
    """绘制回测结果"""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

        # 价格图
        ax1 = axes[0]
        ax1.plot(df.index, df['Close'], label='Close', alpha=0.7)
        if 'BB_Upper' in df.columns:
            ax1.plot(df.index, df['BB_Upper'], 'b--', alpha=0.5, label='BB Upper')
            ax1.plot(df.index, df['BB_Lower'], 'b--', alpha=0.5, label='BB Lower')
        ax1.set_ylabel('Price')
        ax1.legend()
        ax1.set_title('Price & Indicators')

        # 权益曲线
        ax2 = axes[1]
        equity = [stats.get('initial_capital', 100000)]
        for trade in trades:
            equity.append(equity[-1] + trade.get('pnl', 0))
        ax2.plot(range(len(equity)), equity, label='Equity')
        ax2.set_ylabel('Equity')
        ax2.legend()
        ax2.set_title('Equity Curve')

        # 交易标记
        ax3 = axes[2]
        trade_pnls = [t.get('pnl', 0) for t in trades]
        colors = ['green' if p > 0 else 'red' for p in trade_pnls]
        ax3.bar(range(len(trade_pnls)), trade_pnls, color=colors, alpha=0.7)
        ax3.set_ylabel('PnL')
        ax3.set_xlabel('Trade #')
        ax3.set_title('Trade PnL')

        plt.tight_layout()
        plt.savefig('backtest_results.png', dpi=150)
        plt.close()

        print("图表已保存: backtest_results.png")
    except ImportError:
        print("matplotlib未安装，跳过绘图")


def print_tick_backtest_results(stats: Dict):
    """打印Tick回测结果"""
    print(f"\n{'='*60}")
    print("Tick 级别回测结果")
    print(f"{'='*60}")
    print(f"总交易次数: {stats.get('total_trades', 0)}")
    print(f"胜率: {stats.get('win_rate', 0):.2f}%")
    print(f"总收益率: {stats.get('total_return', 0):.2f}%")
    print(f"最大回撤: {stats.get('max_drawdown', 0):.2f}%")
    print(f"夏普比率: {stats.get('sharpe_ratio', 0):.2f}")
    print(f"盈亏比: {stats.get('profit_factor', 0):.2f}")
    print(f"处理Tick数: {stats.get('total_ticks_processed', 0):,}")
    print(f"{'='*60}")
