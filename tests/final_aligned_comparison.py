"""
最终对比：统一滑点和成本模型
============================
"""

import sys
sys.path.insert(0, '/home/ctyun/xauusd_backtest')

import backtrader as bt
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================
# 数据加载
# ============================================
data_path = Path('/home/ctyun/xauusd_data/kline/30m')
dfs = []
for month in ['201710', '201711', '201712', '201801']:
    filepath = data_path / f'XAUUSD_BID_30m_{month}.csv'
    if filepath.exists():
        df = pd.read_csv(filepath, index_col=0)
        df.index = pd.to_datetime(df.index, unit='ms')
        df.columns = [col.capitalize() for col in df.columns]
        dfs.append(df)

df = pd.concat(dfs).sort_index()
df = df[~df.index.duplicated(keep='first')]

print("=" * 80)
print("最终对比：统一滑点和成本模型")
print("=" * 80)
print(f"数据范围: {df.index[0]} ~ {df.index[-1]}")

# ============================================
# 参数
# ============================================
params = {
    'sma_short': 20,
    'sma_medium': 50,
    'sma_long': 200,
    'bb_period': 36,
    'bb_std': 2.0,
    'bbw_ma_period': 84,
    'position_size': 0.01,
    'martingale_multiplier': 2.0,
    'max_martingale_steps': 5,
    'spread_per_ounce': 0.6,
    'contract_size': 100,
    'slippage': 0.1,  # 滑点
}

warmup = max(params['sma_long'], params['bb_period'] + params['bbw_ma_period']) + 5

# ============================================
# 统一的策略逻辑（固定仓位，无马丁格尔）
# ============================================
print("\n" + "=" * 80)
print("固定仓位策略对比（无马丁格尔）")
print("=" * 80)

# 手动计算指标
df['SMA_20'] = df['Close'].rolling(window=params['sma_short']).mean()
df['SMA_50'] = df['Close'].rolling(window=params['sma_medium']).mean()
df['SMA_200'] = df['Close'].rolling(window=params['sma_long']).mean()

bb_middle = df['Close'].rolling(window=params['bb_period']).mean()
bb_std = df['Close'].rolling(window=params['bb_period']).std(ddof=0)
df['BBW'] = (bb_middle + params['bb_std'] * bb_std - (bb_middle - params['bb_std'] * bb_std)) / bb_middle * 100
df['BBW_MA'] = df['BBW'].rolling(window=params['bbw_ma_period']).mean()

# ============================================
# Python 模拟
# ============================================
position = None
entry_price = None
entry_idx = None
py_trades = []

for i in range(warmup, len(df)):
    bar = df.iloc[i]
    prev_bar = df.iloc[i-1]
    prev2_bar = df.iloc[i-2] if i >= 2 else None

    prev_close = prev_bar['Close']
    prev_sma_s = prev_bar['SMA_20']
    prev_sma_m = prev_bar['SMA_50']
    prev_sma_l = prev_bar['SMA_200']
    prev_bbw = prev_bar['BBW']
    prev_bbw_ma = prev_bar['BBW_MA']

    if pd.isna(prev_sma_s) or pd.isna(prev_bbw):
        continue

    is_bullish = (prev_close > prev_sma_s and prev_sma_s > prev_sma_m and prev_sma_m > prev_sma_l)
    is_bearish = (prev_close < prev_sma_s and prev_sma_s < prev_sma_m and prev_sma_m < prev_sma_l)
    bbw_allow = prev_bbw > prev_bbw_ma

    if prev2_bar is not None:
        prev2_sma_s = prev2_bar['SMA_20']
        prev2_sma_m = prev2_bar['SMA_50']
        sma_bearish_cross = (prev2_sma_s >= prev2_sma_m) and (prev_sma_s < prev_sma_m)
        sma_bullish_cross = (prev2_sma_s <= prev2_sma_m) and (prev_sma_s > prev_sma_m)
    else:
        sma_bearish_cross = False
        sma_bullish_cross = False

    open_price = bar['Open']
    slippage = params['slippage']

    # 出场
    if position == 'long' and sma_bearish_cross:
        exit_price = open_price - slippage
        pnl = (exit_price - entry_price) * params['contract_size'] * params['position_size'] - params['spread_per_ounce'] * params['contract_size'] * params['position_size']
        py_trades.append({
            'entry_time': df.index[entry_idx],
            'exit_time': df.index[i],
            'direction': 'long',
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl': pnl,
        })
        if is_bearish and bbw_allow:
            position = 'short'
            entry_price = open_price - slippage
            entry_idx = i
        else:
            position = None

    elif position == 'short' and sma_bullish_cross:
        exit_price = open_price + slippage
        pnl = (entry_price - exit_price) * params['contract_size'] * params['position_size'] - params['spread_per_ounce'] * params['contract_size'] * params['position_size']
        py_trades.append({
            'entry_time': df.index[entry_idx],
            'exit_time': df.index[i],
            'direction': 'short',
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl': pnl,
        })
        if is_bullish and bbw_allow:
            position = 'long'
            entry_price = open_price + slippage
            entry_idx = i
        else:
            position = None

    # 入场
    elif position is None:
        if is_bullish and bbw_allow:
            position = 'long'
            entry_price = open_price + slippage
            entry_idx = i
        elif is_bearish and bbw_allow:
            position = 'short'
            entry_price = open_price - slippage
            entry_idx = i

# 强制平仓
if position:
    last_price = df.iloc[-1]['Close']
    if position == 'long':
        exit_price = last_price - slippage
        pnl = (exit_price - entry_price) * params['contract_size'] * params['position_size'] - params['spread_per_ounce'] * params['contract_size'] * params['position_size']
    else:
        exit_price = last_price + slippage
        pnl = (entry_price - exit_price) * params['contract_size'] * params['position_size'] - params['spread_per_ounce'] * params['contract_size'] * params['position_size']
    py_trades.append({
        'entry_time': df.index[entry_idx],
        'exit_time': df.index[-1],
        'direction': position,
        'entry_price': entry_price,
        'exit_price': exit_price,
        'pnl': pnl,
    })

print(f"\n【Python 模拟】")
print(f"总交易数: {len(py_trades)}")
print(f"总收益: ${sum(t['pnl'] for t in py_trades):.2f}")

print("\n前5笔交易:")
for t in py_trades[:5]:
    print(f"  {t['entry_time'].strftime('%Y/%m/%d %H:%M')} | {t['direction']:5} | 入场: {t['entry_price']:.2f} | PnL: ${t['pnl']:.2f}")

# ============================================
# 自定义框架
# ============================================
print(f"\n【自定义框架】")

from strategies.dollar_trader_martingale_adx import (
    DollarTraderMartingaleBBWStepStrategy,
    calculate_dollar_trader_martingale_bbw_indicators
)
from engines.dollar_trader_engine import DollarTraderBacktestEngine
from core.config import TradingConfig

df_ind = calculate_dollar_trader_martingale_bbw_indicators(
    df.copy(),
    sma_short=params['sma_short'],
    sma_medium=params['sma_medium'],
    sma_long=params['sma_long'],
    bb_period=params['bb_period'],
    bb_std=params['bb_std'],
    bbw_ma_period=params['bbw_ma_period']
)

config = TradingConfig(
    symbol='XAUUSD',
    spread_per_ounce=params['spread_per_ounce'],
    initial_capital=100000
)

strategy = DollarTraderMartingaleBBWStepStrategy(
    params={
        'sma_short': params['sma_short'],
        'sma_medium': params['sma_medium'],
        'sma_long': params['sma_long'],
        'position_size': params['position_size'],
        'bb_period': params['bb_period'],
        'bb_std': params['bb_std'],
        'bbw_ma_period': params['bbw_ma_period'],
    },
    strategy_id="compare"
)

engine = DollarTraderBacktestEngine(config)
result = engine.run(df_ind, signals=None, strategy=strategy)

print(f"总交易数: {result.total_trades}")
print(f"总收益: ${result.total_pnl:.2f}")

print("\n前5笔交易:")
for t in result.trades[:5]:
    print(f"  {t.entry_time.strftime('%Y/%m/%d %H:%M')} | {t.direction.name:5} | 入场: {t.entry_price:.2f} | PnL: ${t.pnl:.2f}")

# ============================================
# 逐笔对比
# ============================================
print("\n" + "=" * 80)
print("逐笔对比")
print("=" * 80)

print(f"\n{'#':<3} {'Python时间':<18} {'框架时间':<18} {'方向':<8} {'入场价Py':>10} {'入场价框架':>12} {'PnL_Py':>10} {'PnL_框架':>10}")
print("-" * 100)

matches = 0
for i in range(min(len(py_trades), len(result.trades))):
    py_t = py_trades[i]
    fw_t = result.trades[i]

    py_time = py_t['entry_time'].strftime('%m/%d %H:%M')
    fw_time = fw_t.entry_time.strftime('%m/%d %H:%M')

    dir_match = py_t['direction'] == fw_t.direction.name.lower()
    time_match = py_time == fw_time

    if dir_match and time_match:
        matches += 1

    print(f"{i+1:<3} {py_time:<18} {fw_time:<18} "
          f"{'✓' if dir_match and time_match else '✗':<8} "
          f"{py_t['entry_price']:>10.2f} {fw_t.entry_price:>12.2f} "
          f"${py_t['pnl']:>9.2f} ${fw_t.pnl:>9.2f}")

print(f"\n匹配率: {matches}/{min(len(py_trades), len(result.trades))} = {matches/min(len(py_trades), len(result.trades))*100:.1f}%")

# ============================================
# 总结
# ============================================
print("\n" + "=" * 80)
print("验证总结")
print("=" * 80)

py_total = sum(t['pnl'] for t in py_trades)
fw_total = result.total_pnl

print(f"""
1. 信号对比:
   - Python 模拟: {len(py_trades)} 笔交易
   - 自定义框架: {result.total_trades} 笔交易
   - 匹配率: {matches/min(len(py_trades), len(result.trades))*100:.1f}%

2. 收益对比:
   - Python 模拟总收益: ${py_total:.2f}
   - 自定义框架总收益: ${fw_total:.2f}
   - 差异: ${abs(py_total - fw_total):.2f}

3. 差异原因:
   - 自定义框架使用马丁格尔仓位管理
   - 随着亏损累积，仓位增大
   - 放大了盈亏幅度
""")

if matches == min(len(py_trades), len(result.trades)):
    print("✓ 框架核心逻辑验证通过！")
else:
    print("⚠ 存在信号不匹配，需要进一步检查")
