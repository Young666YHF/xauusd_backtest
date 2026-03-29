"""
Backtrader 简化版对比验证
=========================
使用简化的策略逻辑，重点验证信号生成是否一致
"""

import sys
sys.path.insert(0, '/home/ctyun/xauusd_backtest')

import backtrader as bt
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime


class SimpleBBWStrategy(bt.Strategy):
    """
    简化版 BBW 策略 - 只做多或做空，不使用马丁格尔
    用于验证信号生成逻辑
    """

    params = (
        ('sma_short', 20),
        ('sma_medium', 50),
        ('sma_long', 200),
        ('bb_period', 36),
        ('bb_std', 2.0),
        ('bbw_ma_period', 84),
        ('warmup_bars', 250),
    )

    def __init__(self):
        self.sma_short = bt.indicators.SMA(self.data.close, period=self.p.sma_short)
        self.sma_medium = bt.indicators.SMA(self.data.close, period=self.p.sma_medium)
        self.sma_long = bt.indicators.SMA(self.data.close, period=self.p.sma_long)

        self.bb_mid = bt.indicators.SMA(self.data.close, period=self.p.bb_period)
        self.bb_std = bt.indicators.StdDev(self.data.close, period=self.p.bb_period)
        self.bb_upper = self.bb_mid + self.p.bb_std * self.bb_std
        self.bb_lower = self.bb_mid - self.p.bb_std * self.bb_std

        self.bbw = (self.bb_upper - self.bb_lower) / self.bb_mid * 100
        self.bbw_ma = bt.indicators.SMA(self.bbw, period=self.p.bbw_ma_period)

        # 记录信号
        self.signals = []

    def next(self):
        if len(self.data) < self.p.warmup_bars:
            return

        # 获取上一根K线的值 (Backtrader 使用负索引)
        prev_close = self.data.close[-1]
        prev_sma_s = self.sma_short[-1]
        prev_sma_m = self.sma_medium[-1]
        prev_sma_l = self.sma_long[-1]
        prev_bbw = self.bbw[-1]
        prev_bbw_ma = self.bbw_ma[-1]

        if np.isnan(prev_sma_s) or np.isnan(prev_bbw):
            return

        # 趋势判断
        is_bullish = (prev_close > prev_sma_s and
                      prev_sma_s > prev_sma_m and
                      prev_sma_m > prev_sma_l)
        is_bearish = (prev_close < prev_sma_s and
                      prev_sma_s < prev_sma_m and
                      prev_sma_m < prev_sma_l)

        # BBW 过滤
        bbw_allow = prev_bbw > prev_bbw_ma

        # 记录信号
        current_time = self.data.datetime.datetime(0)
        if is_bullish and bbw_allow and not self.position:
            self.signals.append({
                'time': current_time,
                'type': 'LONG',
                'price': self.data.open[0],
                'close': prev_close,
                'sma20': prev_sma_s,
                'sma50': prev_sma_m,
                'sma200': prev_sma_l,
                'bbw': prev_bbw,
                'bbw_ma': prev_bbw_ma,
            })
            self.buy(size=0.01)

        elif is_bearish and bbw_allow and not self.position:
            self.signals.append({
                'time': current_time,
                'type': 'SHORT',
                'price': self.data.open[0],
                'close': prev_close,
                'sma20': prev_sma_s,
                'sma50': prev_sma_m,
                'sma200': prev_sma_l,
                'bbw': prev_bbw,
                'bbw_ma': prev_bbw_ma,
            })
            self.sell(size=0.01)

        # 简单出场逻辑
        if self.position:
            # 获取前两根K线的 SMA 用于交叉判断
            prev2_sma_s = self.sma_short[-2]
            prev2_sma_m = self.sma_medium[-2]

            sma_bearish_cross = (prev2_sma_s >= prev2_sma_m) and (prev_sma_s < prev_sma_m)
            sma_bullish_cross = (prev2_sma_s <= prev2_sma_m) and (prev_sma_s > prev_sma_m)

            if self.position.size > 0 and sma_bearish_cross:
                self.close()
            elif self.position.size < 0 and sma_bullish_cross:
                self.close()


def main():
    print("=" * 70)
    print("Backtrader 简化版信号验证")
    print("=" * 70)

    # 加载数据
    data_path = Path('/home/ctyun/xauusd_data/kline/30m')
    dfs = []
    for month in ['201710', '201711', '201712']:
        filepath = data_path / f'XAUUSD_BID_30m_{month}.csv'
        if filepath.exists():
            df = pd.read_csv(filepath, index_col=0)
            df.index = pd.to_datetime(df.index, unit='ms')
            df.columns = [col.capitalize() for col in df.columns]
            dfs.append(df)

    df = pd.concat(dfs).sort_index()
    df = df[~df.index.duplicated(keep='first')]

    print(f"\n数据范围: {df.index[0]} ~ {df.index[-1]}")

    # 运行 Backtrader
    cerebro = bt.Cerebro()
    data = bt.feeds.PandasData(
        dataname=df,
        datetime=None,
        open='Open',
        high='High',
        low='Low',
        close='Close',
        volume='Volume',
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SimpleBBWStrategy)
    cerebro.broker.setcash(100000)

    results = cerebro.run()
    strategy = results[0]

    print(f"\nBacktrader 信号 (前10个):")
    print("-" * 90)
    for i, s in enumerate(strategy.signals[:10]):
        print(f"{i+1}. {s['time'].strftime('%Y/%m/%d %H:%M')} | {s['type']} | "
              f"入场价: {s['price']:.2f} | BBW: {s['bbw']:.4f} > MA: {s['bbw_ma']:.4f}")

    # 对比自定义框架的信号
    print(f"\n" + "=" * 70)
    print("对比自定义框架的信号")
    print("=" * 70)

    from strategies.dollar_trader_martingale_adx import calculate_dollar_trader_martingale_bbw_indicators

    df_ind = calculate_dollar_trader_martingale_bbw_indicators(
        df.copy(), sma_short=20, sma_medium=50, sma_long=200,
        bb_period=36, bb_std=2.0, bbw_ma_period=84
    )

    warmup = 250
    py_signals = []

    for i in range(warmup, len(df_ind)):
        prev_bar = df_ind.iloc[i - 1]
        current_bar = df_ind.iloc[i]

        prev_close = prev_bar['Close']
        prev_sma_s = prev_bar['SMA_20']
        prev_sma_m = prev_bar['SMA_50']
        prev_sma_l = prev_bar['SMA_200']
        prev_bbw = prev_bar['BBW']
        prev_bbw_ma = prev_bar['BBW_MA_84']

        if pd.isna(prev_sma_s) or pd.isna(prev_bbw):
            continue

        is_bullish = (prev_close > prev_sma_s and
                      prev_sma_s > prev_sma_m and
                      prev_sma_m > prev_sma_l)
        is_bearish = (prev_close < prev_sma_s and
                      prev_sma_s < prev_sma_m and
                      prev_sma_m < prev_sma_l)
        bbw_allow = prev_bbw > prev_bbw_ma

        if is_bullish and bbw_allow:
            py_signals.append({
                'time': df_ind.index[i],
                'type': 'LONG',
                'price': current_bar['Open'],
            })
        elif is_bearish and bbw_allow:
            py_signals.append({
                'time': df_ind.index[i],
                'type': 'SHORT',
                'price': current_bar['Open'],
            })

    print(f"\n自定义框架信号 (前10个):")
    print("-" * 90)
    for i, s in enumerate(py_signals[:10]):
        print(f"{i+1}. {s['time'].strftime('%Y/%m/%d %H:%M')} | {s['type']} | 入场价: {s['price']:.2f}")

    # 对比分析
    print(f"\n" + "=" * 70)
    print("信号对比分析")
    print("=" * 70)
    print(f"Backtrader 信号数: {len(strategy.signals)}")
    print(f"自定义框架信号数: {len(py_signals)}")

    # 对比前5个信号
    print(f"\n前5个信号对比:")
    print(f"{'#':<3} {'Backtrader':<30} {'自定义框架':<30} {'一致?':<10}")
    print("-" * 75)

    for i in range(min(5, len(strategy.signals), len(py_signals))):
        bt_sig = strategy.signals[i]
        py_sig = py_signals[i]

        bt_str = f"{bt_sig['time'].strftime('%m/%d %H:%M')} {bt_sig['type']}"
        py_str = f"{py_sig['time'].strftime('%m/%d %H:%M')} {py_sig['type']}"

        match = (bt_sig['time'] == py_sig['time'] and bt_sig['type'] == py_sig['type'])
        print(f"{i+1:<3} {bt_str:<30} {py_str:<30} {'✓' if match else '✗':<10}")


if __name__ == '__main__':
    main()
