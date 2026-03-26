#!/usr/bin/env python3
"""绘制黄金价格与资金曲线对比图"""
import sys
sys.path.insert(0, '/home/ctyun/xauusd_backtest')

import pandas as pd
import matplotlib
matplotlib.use('Agg')  # 非交互式后端
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial Unicode MS', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 加载交易记录
trades_df = pd.read_csv('/home/ctyun/xauusd_backtest/results_dollar_trader_full.csv')
trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])

# 重建资金曲线
initial_capital = 100000.0
equity_curve = [initial_capital]
timestamps = [pd.Timestamp('2024-01-01')]

for _, trade in trades_df.iterrows():
    equity_curve.append(equity_curve[-1] + trade['pnl'])
    timestamps.append(trade['exit_time'])

equity_df = pd.DataFrame({'timestamp': timestamps, 'equity': equity_curve})
equity_df.set_index('timestamp', inplace=True)

# 加载黄金价格数据
kline_dir = Path('/home/ctyun/xauusd_data/kline/15m')
months = [f'2024-{m:02d}' for m in range(1, 13)] + ['2025-01', '2025-02', '2025-03', '2025-04',
          '2025-05', '2025-06', '2025-07', '2025-08', '2025-09', '2025-10', '2025-11', '2025-12', '2026-01', '2026-02']

dfs = []
for m in months:
    fp = kline_dir / f'XAUUSD_{m}.csv'
    if fp.exists():
        dfs.append(pd.read_csv(fp, index_col=0, parse_dates=True))

price_df = pd.concat(dfs).sort_index()
price_df = price_df[~price_df.index.duplicated(keep='first')]
price_df = price_df.loc['2024-01-01':'2026-02-28']

# 对价格数据进行降采样以减少图表点数量
price_daily = price_df['Close'].resample('1H').last().dropna()

# 创建图表
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={'height_ratios': [1, 1]})

# 上图: 黄金价格
ax1.plot(price_daily.index, price_daily.values, color='#FFD700', linewidth=1.2, label='XAUUSD Price')
ax1.set_ylabel('Price (USD)', fontsize=12)
ax1.set_title('XAUUSD Price vs Dollar Trader Strategy Equity Curve (2024-2026)', fontsize=14, fontweight='bold')
ax1.legend(loc='upper left')
ax1.grid(True, alpha=0.3)
ax1.set_ylim(1800, 3000)

# 格式化Y轴为货币格式
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))

# 下图: 资金曲线
ax2.plot(equity_df.index, equity_df['equity'], color='#00AA00', linewidth=1.5, label='Strategy Equity')
ax2.axhline(y=initial_capital, color='gray', linestyle='--', linewidth=1, alpha=0.7, label='Initial Capital')
ax2.fill_between(equity_df.index, initial_capital, equity_df['equity'],
                  where=(equity_df['equity'] >= initial_capital), alpha=0.3, color='green')
ax2.fill_between(equity_df.index, initial_capital, equity_df['equity'],
                  where=(equity_df['equity'] < initial_capital), alpha=0.3, color='red')
ax2.set_ylabel('Equity (USD)', fontsize=12)
ax2.set_xlabel('Date', fontsize=12)
ax2.legend(loc='upper left')
ax2.grid(True, alpha=0.3)

# 格式化Y轴为货币格式
ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))

# 设置X轴日期格式
for ax in [ax1, ax2]:
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

# 添加统计信息文本框
stats_text = (
    f"Total Return: +87.59%\n"
    f"Total Trades: 1040\n"
    f"Win Rate: 32.12%\n"
    f"Max Drawdown: -76.71%"
)
props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
ax2.text(0.02, 0.98, stats_text, transform=ax2.transAxes, fontsize=10,
         verticalalignment='top', bbox=props)

plt.tight_layout()
plt.savefig('/home/ctyun/xauusd_backtest/equity_vs_price.png', dpi=150, bbox_inches='tight')
print("图表已保存: /home/ctyun/xauusd_backtest/equity_vs_price.png")
