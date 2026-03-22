#!/usr/bin/env python3
"""
信号生成诊断脚本
========================================
分析为什么交易信号太少
"""

import os
import sys
import warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from data_loader import load_tick_data_from_csv, ticks_to_ohlcv
from indicators import add_all_indicators
from strategy import TradingStrategy
from config import DEFAULT_PARAMS

DATA_DIR = '/home/ctyun/xauusd_data'

def diagnose():
    """诊断信号生成过程"""
    print("="*70)
    print("信号生成诊断")
    print("="*70)

    # 加载一个月的数据进行诊断
    print("\n加载数据 (2025-08)...")
    filepath = os.path.join(DATA_DIR, "XAUUSD_2025-08.csv")
    tick_df = load_tick_data_from_csv(filepath)
    ohlcv = ticks_to_ohlcv(tick_df, '15min')

    print(f"K线数: {len(ohlcv)}")
    print(f"时间范围: {ohlcv.index[0]} 到 {ohlcv.index[-1]}")

    # 使用优化得到的最佳参数
    best_params = {
      'bb_period': 22,
      'bb_std': 2.918,
      'kc_period': 22,
      'kc_atr_mult': 2.377,
      'atr_period': 16,
      'rsi_period': 14,
      'rsi_oversold': 24,
      'rsi_overbought': 76,
      'stop_loss_atr_mult_a': 1.085,
      'max_hold_bars_a': 7,
      'ema_fast': 17,
      'ema_slow': 47,
      'stop_loss_atr_mult_b': 2.249,
      'trailing_stop_atr_mult': 3.646,
      'squeeze_threshold': 0.74,
      'ema_momentum_threshold': 0.00067,
      'volatility_filter_period': 17,
      'volatility_filter_mult': 1.47,
      'pullback_confirmation_bars': 3,
    }

    print("\n计算指标...")
    df = add_all_indicators(ohlcv, best_params)

    # 诊断各条件
    print("\n" + "="*70)
    print("【策略A诊断】亚盘均值回归")
    print("="*70)

    # 时段过滤
    is_asian = df['Is_Asian']
    print(f"亚盘 K 线数: {is_asian.sum()} / {len(df)} ({is_asian.sum()/len(df)*100:.1f}%)")

    # RSI 条件
    rsi_oversold = best_params['rsi_oversold']
    rsi_overbought = best_params['rsi_overbought']
    rsi_low = df['RSI'] < rsi_oversold
    rsi_high = df['RSI'] > rsi_overbought
    print(f"\nRSI 条件:")
    print(f"  RSI < {rsi_oversold} (超卖): {rsi_low.sum()} 根 K 线")
    print(f"  RSI > {rsi_overbought} (超买): {rsi_high.sum()} 根 K 线")

    # 布林带触及
    touch_lower = df['Close'] <= df['BB_Lower']
    touch_upper = df['Close'] >= df['BB_Upper']
    print(f"\n布林带触及:")
    print(f"  价格触及下轨: {touch_lower.sum()} 根 K 线")
    print(f"  价格触及上轨: {touch_upper.sum()} 根 K 线")

    # 策略A组合条件
    long_condition_a = is_asian & touch_lower & rsi_low
    short_condition_a = is_asian & touch_upper & rsi_high
    print(f"\n策略A组合条件:")
    print(f"  做多信号 (亚盘 + 触下轨 + RSI超卖): {long_condition_a.sum()}")
    print(f"  做空信号 (亚盘 + 触上轨 + RSI超买): {short_condition_a.sum()}")

    print("\n" + "="*70)
    print("【策略B诊断】动量突破")
    print("="*70)

    is_european = df['Is_European']
    print(f"欧美盘 K 线数: {is_european.sum()} / {len(df)} ({is_european.sum()/len(df)*100:.1f}%)")

    # Squeeze 条件
    squeeze_threshold = best_params['squeeze_threshold']
    squeeze_release = df['Squeeze_Release']
    squeeze_ratio = df['Squeeze_Ratio']

    print(f"\nSqueeze 条件:")
    print(f"  Squeeze Release 信号: {squeeze_release.sum()} 根 K 线")
    print(f"  Squeeze Ratio >= {squeeze_threshold}: {(squeeze_ratio >= squeeze_threshold).sum()} 根 K 线")

    # 布林带突破
    break_upper = df['Close'] > df['BB_Upper']
    break_lower = df['Close'] < df['BB_Lower']
    print(f"\n布林带突破:")
    print(f"  突破上轨: {break_upper.sum()} 根 K 线")
    print(f"  突破下轨: {break_lower.sum()} 根 K 线")

    # KC 突破
    bb_above_kc = df['BB_Upper'] > df['KC_Upper']
    bb_below_kc = df['BB_Lower'] < df['KC_Lower']
    print(f"\nBB/KC 关系:")
    print(f"  BB上轨 > KC上轨: {bb_above_kc.sum()} 根 K 线")
    print(f"  BB下轨 < KC下轨: {bb_below_kc.sum()} 根 K 线")

    # EMA 条件
    ema_fast = df['EMA_Fast']
    ema_slow = df['EMA_Slow']
    ema_golden = ema_fast > ema_slow
    ema_death = ema_fast < ema_slow
    print(f"\nEMA 条件:")
    print(f"  EMA 金叉 (快 > 慢): {ema_golden.sum()} 根 K 线")
    print(f"  EMA 死叉 (快 < 慢): {ema_death.sum()} 根 K 线")

    # EMA 动能过滤
    ema_momentum_threshold = best_params['ema_momentum_threshold']
    ema_momentum = abs(ema_fast - ema_slow) / ema_slow
    ema_momentum_ok = ema_momentum > ema_momentum_threshold
    print(f"\nEMA 动能过滤 (threshold={ema_momentum_threshold:.5f}):")
    print(f"  动能充足: {ema_momentum_ok.sum()} 根 K 线")
    print(f"  动能范围: {ema_momentum.min():.5f} - {ema_momentum.max():.5f}")

    # 策略B组合条件
    long_condition_b = is_european & break_upper & bb_above_kc & ema_golden & ema_momentum_ok
    short_condition_b = is_european & break_lower & bb_below_kc & ema_death & ema_momentum_ok
    print(f"\n策略B组合条件 (不含 Squeeze):")
    print(f"  做多信号: {long_condition_b.sum()}")
    print(f"  做空信号: {short_condition_b.sum()}")

    # 市场状态检测
    print("\n" + "="*70)
    print("【市场状态检测】")
    print("="*70)

    regime_range = ((squeeze_ratio < squeeze_threshold) & is_asian).sum()
    regime_trend = ((squeeze_ratio >= squeeze_threshold) & is_european).sum()
    print(f"震荡市场 (Squeeze < {squeeze_threshold} + 亚盘): {regime_range}")
    print(f"趋势市场 (Squeeze >= {squeeze_threshold} + 欧美盘): {regime_trend}")

    # 生成信号
    print("\n" + "="*70)
    print("【实际信号生成】")
    print("="*70)

    strategy = TradingStrategy(best_params)
    signals = strategy.generate_signals(df)

    print(f"生成的信号总数: {len(signals)}")

    if len(signals) > 0:
        strategy_a_signals = [s for s in signals if s.strategy == 'A']
        strategy_b_signals = [s for s in signals if s.strategy == 'B']
        print(f"  策略A信号: {len(strategy_a_signals)}")
        print(f"  策略B信号: {len(strategy_b_signals)}")

        for i, sig in enumerate(signals[:5]):
            print(f"\n  信号 {i+1}:")
            print(f"    时间: {sig.timestamp}")
            print(f"    策略: {sig.strategy}")
            print(f"    方向: {'做多' if sig.signal_type.value == 1 else '做空'}")
            print(f"    原因: {sig.reason}")

    # 检查待确认信号
    print(f"\n待确认信号统计:")
    print(f"  总待确认信号: {strategy.state.total_pending_signals}")
    print(f"  超时失效信号: {strategy.state.expired_signals_count}")

if __name__ == "__main__":
    diagnose()
