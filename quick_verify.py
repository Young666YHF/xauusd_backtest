#!/usr/bin/env python3
"""
快速验证脚本 - 测试时区修复后的效果
"""
import warnings
warnings.filterwarnings('ignore')

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from datetime import datetime

from data_loader import load_dukascopy_tick_data, ticks_to_ohlcv
from indicators import add_all_indicators
from strategy import TradingStrategy
from tick_engine import (
    prepare_tick_data, prepare_bar_stats, prepare_signals,
    enhanced_tick_matcher, COMMISSION_PER_LOT, DEFAULT_LEVERAGE, MARGIN_CALL_RATIO
)
from config import DEFAULT_PARAMS, SPREAD_PER_OUNCE

DATA_DIR = '/home/ctyun/xauusd_data'
INTERVAL = '15min'

# 加载测试数据
print('='*60)
print('时区修复验证: 使用 Dukascopy 数据加载器')
print('='*60)

# 分别加载每个月的数据
tick_dfs = []
for m in ['2026-01', '2026-02']:
    year, month = map(int, m.split('-'))
    filepath = f'{DATA_DIR}/XAUUSD_{year}-{month:02d}.csv'
    print(f'加载 {m}...')
    # 使用新的 Dukascopy 加载器，保持 UTC 时区
    df = load_dukascopy_tick_data(filepath, keep_utc=True)
    tick_dfs.append(df)

# 合并
tick_df = pd.concat(tick_dfs)
print(f'\n合并后总 Tick 数: {len(tick_df):,}')
print(f'数据时区: {tick_df.index.tz}')

# 转换K线
print('\n转换K线...')
ohlcv_df = ticks_to_ohlcv(tick_df, INTERVAL)
print(f'K线数: {len(ohlcv_df)}')
print(f'K线时区: {ohlcv_df.index.tz}')

# 计算指标（包含时段判定）
print('\n计算指标...')
df = add_all_indicators(ohlcv_df, DEFAULT_PARAMS)

# 检查时段分布
print('\n时段分布统计:')
if 'Is_Asian' in df.columns and 'Is_European' in df.columns:
    asian_count = df['Is_Asian'].sum()
    european_count = df['Is_European'].sum()
    total = len(df)
    print(f'  亚盘 K 线: {asian_count} ({asian_count/total*100:.1f}%)')
    print(f'  欧美盘 K 线: {european_count} ({european_count/total*100:.1f}%)')

    # 检查时段时间示例
    sample_asian = df[df['Is_Asian']].head(3)
    sample_european = df[df['Is_European']].head(3)
    print(f'\n  亚盘样本时间 (UTC): {sample_asian.index.strftime("%Y-%m-%d %H:%M").tolist()}')
    print(f'  欧美盘样本时间 (UTC): {sample_european.index.strftime("%Y-%m-%d %H:%M").tolist()}')

# 生成信号
print('\n生成信号...')
strategy = TradingStrategy(DEFAULT_PARAMS)
signals = strategy.generate_signals(df)
print(f'信号数: {len(signals)}')

if len(signals) == 0:
    print('无信号生成，请检查参数设置')
    sys.exit(1)

# 统计信号策略分布
strategy_a = sum(1 for s in signals if s.strategy == 'A')
strategy_b = sum(1 for s in signals if s.strategy == 'B')
print(f'  策略A信号: {strategy_a}')
print(f'  策略B信号: {strategy_b}')

# 准备数据
print('\n准备Tick数据...')
ticks_array = prepare_tick_data(tick_df, df, INTERVAL, SPREAD_PER_OUNCE)
bar_stats = prepare_bar_stats(df)
signals_array = prepare_signals(signals, df)

# 运行回测
print('运行Tick级回测...')

max_hold_bars_a = DEFAULT_PARAMS.get('max_hold_bars_a', 5)
trailing_mult_b = DEFAULT_PARAMS.get('trailing_stop_atr_mult', 4.89)

trades_record, equity_curve, total_trades, winning_trades, total_ticks, margin_calls = enhanced_tick_matcher(
    ticks_array,
    signals_array,
    bar_stats,
    100000.0,  # initial_capital
    100.0,     # contract_size
    max_hold_bars_a,
    trailing_mult_b,
    1.0,       # position_size
    3.5,       # commission_per_lot
    DEFAULT_LEVERAGE,
    MARGIN_CALL_RATIO
)

# 计算统计
if total_trades == 0:
    print('无交易执行')
    sys.exit(1)

pnls = trades_record[:, 5]  # TRADE_PNL
total_pnl = np.sum(pnls)
total_return = (equity_curve[-1] - 100000) / 100000 * 100
win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0

wins = pnls[pnls > 0]
losses = pnls[pnls <= 0]
avg_win = np.mean(wins) if len(wins) > 0 else 0
avg_loss = abs(np.mean(losses)) if len(losses) > 0 else 0
profit_factor = np.sum(wins) / abs(np.sum(losses)) if np.sum(losses) != 0 else float('inf')

# 计算最大回撤
rolling_max = np.maximum.accumulate(equity_curve)
drawdowns = (rolling_max - equity_curve) / rolling_max * 100
max_drawdown = np.max(drawdowns)

# 计算夏普比率
equity_daily = equity_curve[::96]
if len(equity_daily) > 1:
    daily_returns = np.diff(equity_daily) / equity_daily[:-1]
    if len(daily_returns) > 1 and np.std(daily_returns) > 0:
        sharpe_ratio = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)
    else:
        sharpe_ratio = 0
else:
    sharpe_ratio = 0

print('')
print('='*60)
print('回测结果 (时区修复后)')
print('='*60)
print(f'  交易次数: {total_trades}')
print(f'  胜率: {win_rate:.1f}%')
print(f'  总收益: {total_return:.2f}%')
print(f'  最大回撤: {max_drawdown:.2f}%')
print(f'  夏普比率: {sharpe_ratio:.2f}')
print(f'  盈亏比: {profit_factor:.2f}')
print('='*60)
