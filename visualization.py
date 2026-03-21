"""
可视化模块
绘制回测结果和优化过程图表
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
from typing import Dict, Optional
import warnings
warnings.filterwarnings('ignore')

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


def plot_equity_curve(
    equity_curve: pd.DataFrame,
    stats: Dict,
    save_path: Optional[str] = None
):
    """
    绘制权益曲线

    Args:
        equity_curve: 权益曲线DataFrame
        stats: 统计数据
        save_path: 保存路径
    """
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    fig.suptitle('XAUUSD 回测结果', fontsize=14, fontweight='bold')

    # 权益曲线
    ax1 = axes[0]
    ax1.plot(equity_curve.index, equity_curve['equity'], 'b-', linewidth=1.5, label='账户权益')
    ax1.axhline(y=stats['final_capital'], color='gray', linestyle='--', alpha=0.5)
    ax1.fill_between(equity_curve.index, stats['final_capital'], equity_curve['equity'],
                     where=equity_curve['equity'] >= stats['final_capital'],
                     color='green', alpha=0.3, label='盈利区域')
    ax1.fill_between(equity_curve.index, stats['final_capital'], equity_curve['equity'],
                     where=equity_curve['equity'] < stats['final_capital'],
                     color='red', alpha=0.3, label='亏损区域')
    ax1.set_ylabel('账户权益 ($)')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    ax1.set_title(f'总收益率: {stats["total_return"]:.2f}% | 最大回撤: {stats["max_drawdown"]:.2f}%')

    # 回撤曲线
    ax2 = axes[1]
    rolling_max = equity_curve['equity'].expanding().max()
    drawdown = (equity_curve['equity'] - rolling_max) / rolling_max * 100
    ax2.fill_between(equity_curve.index, 0, drawdown, color='red', alpha=0.5)
    ax2.set_ylabel('回撤 (%)')
    ax2.grid(True, alpha=0.3)
    ax2.set_title(f'最大回撤: {abs(drawdown.min()):.2f}%')

    # 盈亏分布
    ax3 = axes[2]
    if 'trades_df' in stats and not stats['trades_df'].empty:
        trades = stats['trades_df']
        colors = ['green' if p > 0 else 'red' for p in trades['pnl']]
        ax3.bar(range(len(trades)), trades['pnl'], color=colors, alpha=0.7)
        ax3.axhline(y=0, color='black', linewidth=0.5)
        ax3.set_ylabel('单笔盈亏 ($)')
        ax3.set_xlabel('交易序号')
        ax3.grid(True, alpha=0.3)
        ax3.set_title(f'总交易: {stats["total_trades"]} | 胜率: {stats["win_rate"]:.1f}%')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"图表已保存: {save_path}")

    plt.show()


def plot_optimization_history(
    history_df: pd.DataFrame,
    save_path: Optional[str] = None
):
    """
    绘制优化历史

    Args:
        history_df: 优化历史DataFrame
        save_path: 保存路径
    """
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    fig.suptitle('遗传算法优化过程', fontsize=14, fontweight='bold')

    # 适应度曲线
    ax1 = axes[0]
    ax1.plot(history_df['generation'], history_df['best'], 'g-', linewidth=2, label='代最佳')
    ax1.plot(history_df['generation'], history_df['avg'], 'b--', linewidth=1, label='代平均')
    ax1.plot(history_df['generation'], history_df['global_best'], 'r-', linewidth=2.5, label='全局最佳')
    ax1.set_ylabel('适应度')
    ax1.legend(loc='lower right')
    ax1.grid(True, alpha=0.3)
    ax1.set_title('适应度变化')

    # 改善率
    ax2 = axes[1]
    improvement = history_df['global_best'].diff().fillna(0)
    colors = ['green' if i > 0 else 'red' for i in improvement]
    ax2.bar(history_df['generation'], improvement, color=colors, alpha=0.7)
    ax2.set_ylabel('适应度改善')
    ax2.set_xlabel('迭代次数')
    ax2.grid(True, alpha=0.3)
    ax2.set_title('每代改善量')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"图表已保存: {save_path}")

    plt.show()


def plot_trades_on_price(
    df: pd.DataFrame,
    trades_df: pd.DataFrame,
    save_path: Optional[str] = None
):
    """
    在价格图上标注交易

    Args:
        df: 价格数据
        trades_df: 交易记录
        save_path: 保存路径
    """
    fig, ax = plt.subplots(figsize=(16, 8))

    # 价格曲线
    ax.plot(df.index, df['Close'], 'b-', linewidth=1, alpha=0.7, label='收盘价')

    # 标注交易
    if not trades_df.empty:
        for _, trade in trades_df.iterrows():
            entry_time = trade['entry_time']
            exit_time = trade['exit_time']
            entry_price = trade['entry_price']
            exit_price = trade['exit_price']

            # 入场点
            color = 'green' if trade['direction'] == 'LONG' else 'red'
            marker = '^' if trade['direction'] == 'LONG' else 'v'
            ax.scatter(entry_time, entry_price, color=color, marker=marker, s=100, zorder=5)

            # 出场点
            exit_color = 'green' if trade['pnl'] > 0 else 'red'
            ax.scatter(exit_time, exit_price, color=exit_color, marker='x', s=100, zorder=5)

            # 连线
            ax.plot([entry_time, exit_time], [entry_price, exit_price],
                   color=color, linestyle='--', alpha=0.5, linewidth=1)

    ax.set_ylabel('价格 ($)')
    ax.set_xlabel('时间')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_title('交易信号标注')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')

    plt.show()


def plot_parameter_comparison(
    results: Dict[str, Dict],
    save_path: Optional[str] = None
):
    """
    绘制参数对比图

    Args:
        results: 不同参数组合的结果
        save_path: 保存路径
    """
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    fig.suptitle('参数优化结果对比', fontsize=14, fontweight='bold')

    metrics = ['total_return', 'win_rate', 'max_drawdown', 'sharpe_ratio']
    titles = ['总收益率 (%)', '胜率 (%)', '最大回撤 (%)', '夏普比率']

    for ax, metric, title in zip(axes.flat, metrics, titles):
        names = list(results.keys())
        values = [results[n].get(metric, 0) for n in names]

        colors = ['green' if v > 0 else 'red' for v in values]
        ax.bar(names, values, color=colors, alpha=0.7)
        ax.set_ylabel(title)
        ax.set_title(title)
        ax.axhline(y=0, color='black', linewidth=0.5)
        ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')

    plt.show()


def print_trade_summary(trades_df: pd.DataFrame, n: int = 20):
    """打印交易摘要"""
    if trades_df.empty:
        print("无交易记录")
        return

    print(f"\n最近 {min(n, len(trades_df))} 笔交易:")
    print("-" * 100)
    print(f"{'入场时间':<20} {'出场时间':<20} {'方向':<6} {'入场价':<10} {'出场价':<10} {'盈亏':<10} {'策略':<6}")
    print("-" * 100)

    for _, trade in trades_df.tail(n).iterrows():
        print(f"{str(trade['entry_time']):<20} {str(trade['exit_time']):<20} "
              f"{trade['direction']:<6} {trade['entry_price']:<10.2f} "
              f"{trade['exit_price']:<10.2f} {trade['pnl']:<10.2f} {trade['strategy']:<6}")


if __name__ == "__main__":
    # 测试可视化
    from data_loader import generate_sample_data
    from indicators import add_all_indicators
    from strategy import TradingStrategy
    from backtest import BacktestEngine

    params = {
        'bb_period': 20,
        'bb_std': 2.5,
        'kc_period': 20,
        'kc_atr_mult': 1.5,
        'atr_period': 14,
        'rsi_period': 14,
        'rsi_oversold': 30,
        'rsi_overbought': 70,
        'ema_fast': 20,
        'ema_slow': 50,
        'stop_loss_atr_mult_a': 1.5,
        'stop_loss_atr_mult_b': 1.5,
        'trailing_stop_atr_mult': 2.0,
        'max_hold_bars_a': 12,
        'squeeze_threshold': 1.0
    }

    df = generate_sample_data(days=90)
    df = add_all_indicators(df, params)

    strategy = TradingStrategy(params)
    engine = BacktestEngine(initial_capital=100000)

    stats = engine.run_backtest(df, strategy)
    equity_curve = engine.get_equity_curve()

    plot_equity_curve(equity_curve, stats)
