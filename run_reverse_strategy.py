"""
反向趋势角度策略 (Reverse Trend Angle)
==============================
验证"反向操作是否能盈利"的假设

原理：原策略稳定亏损时，反向操作应该稳定盈利
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime
import json

from strategies.trend_angle_breakout import calculate_strategy_indicators
from core.config import TradingConfig
from engines.tick_engine import TickBacktestEngine
from core.data_loader import DataLoader
from core.types import TradeSignal, TradeDirection, SignalType

# 配置参数
DATA_DIR = "/home/ctyun/xauusd_data"
IS_START = '2025-01-01'
IS_END = '2025-10-31'
OOS_START = '2025-11-01'
OOS_END = '2026-02-28'

# 原策略参数（导致亏损的参数）
ORIGINAL_PARAMS = {
    'sma_period': 36,
    'angle_threshold': 5.87,
    'risk_reward_ratio': 1.45,
    'breakout_lookback': 5,
    'trailing_stop_atr': 2.56,
    'use_fixed_exit': True,
}


def load_data_for_period(loader: DataLoader, start_date: str, end_date: str):
    """加载指定时间段的数据"""
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    tick_dfs = []
    current = start.replace(day=1)

    while current <= end:
        year, month = current.year, current.month
        filename = f"XAUUSD_{year}-{month:02d}.csv"
        filepath = Path(loader.data_dir) / "tick" / str(year) / filename

        if filepath.exists():
            try:
                tick_df = loader.load_tick_data(filepath)
                tick_df['Mid'] = (tick_df['Bid'] + tick_df['Ask']) / 2
                tick_dfs.append(tick_df)
                print(f"  加载: {filename} ({len(tick_df):,} 条)")
            except Exception as e:
                print(f"  错误加载 {filename}: {e}")

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    if not tick_dfs:
        return None, None

    combined = pd.concat(tick_dfs)
    combined = combined.sort_index()
    combined = combined[~combined.index.duplicated(keep='first')]

    # 转换为15分钟K线
    bar_df = loader.resample_to_ohlcv(combined, '15min')

    return combined, bar_df


def generate_reverse_signals(df: pd.DataFrame, params: dict) -> list:
    """
    生成反向交易信号

    原策略：
    - 做多：角度 > 阈值 且 突破前N根K线高点
    - 做空：角度 < -阈值 且 跌破前N根K线低点

    反向策略：
    - 做多：角度 < -阈值 且 突破前N根K线高点（原做空条件，反向操作）
    - 做空：角度 > 阈值 且 跌破前N根K线低点（原做多条件，反向操作）
    """
    signals = []
    sma_col = f"SMA_{params['sma_period']}"
    angle_threshold = params['angle_threshold']
    lookback = params['breakout_lookback']

    min_bars = max(params['sma_period'] + 5, lookback + 1, 14) + 5

    for i in range(min_bars, len(df)):
        current_bar = df.iloc[i]

        sma_angle = current_bar.get('SMA_Angle', None)
        if pd.isna(sma_angle):
            continue

        atr = current_bar['ATR']
        if pd.isna(atr) or atr <= 0:
            continue

        # 计算前N根K线的高低点
        start_idx = i - lookback
        end_idx = i
        recent_highs = df['High'].iloc[start_idx:end_idx]
        recent_lows = df['Low'].iloc[start_idx:end_idx]
        highest = recent_highs.max()
        lowest = recent_lows.min()

        current_close = current_bar['Close']
        current_high = current_bar['High']
        current_low = current_bar['Low']

        signal = None

        # 反向做多：角度 < -阈值 且 突破前N根K线高点（原做空的反向）
        if sma_angle < -angle_threshold and current_high > highest:
            stop_loss = current_close - atr * params['trailing_stop_atr']
            take_profit = current_close + atr * params['risk_reward_ratio'] * params['trailing_stop_atr']

            signal = TradeSignal(
                timestamp=df.index[i],
                signal_type=SignalType.LONG,
                direction=TradeDirection.LONG,
                entry_price=current_close,
                stop_loss=stop_loss,
                take_profit=take_profit,
                size=1.0,
                strategy_id="ReverseTrendAngle",
                reason=f"Reverse Long: Angle={sma_angle:.1f}°<-{angle_threshold}°, Breakout>{highest:.2f}",
                signal_bar_index=i,
                execution_bar_index=i + 1,
            )

        # 反向做空：角度 > 阈值 且 跌破前N根K线低点（原做多的反向）
        elif sma_angle > angle_threshold and current_low < lowest:
            stop_loss = current_close + atr * params['trailing_stop_atr']
            take_profit = current_close - atr * params['risk_reward_ratio'] * params['trailing_stop_atr']

            signal = TradeSignal(
                timestamp=df.index[i],
                signal_type=SignalType.SHORT,
                direction=TradeDirection.SHORT,
                entry_price=current_close,
                stop_loss=stop_loss,
                take_profit=take_profit,
                size=1.0,
                strategy_id="ReverseTrendAngle",
                reason=f"Reverse Short: Angle={sma_angle:.1f}°>{angle_threshold}°, Breakdown<{lowest:.2f}",
                signal_bar_index=i,
                execution_bar_index=i + 1,
            )

        if signal:
            signals.append(signal)

    return signals


def create_bar_idx_to_ticks(bar_df: pd.DataFrame, tick_df: pd.DataFrame) -> dict:
    """创建Bar索引到Tick的映射"""
    mapping = {}
    tick_idx = 0
    tick_times = tick_df.index

    for bar_idx, bar_time in enumerate(bar_df.index):
        bar_end_time = bar_time
        tick_indices = []

        while tick_idx < len(tick_times) and tick_times[tick_idx] <= bar_end_time:
            tick_indices.append(tick_idx)
            tick_idx += 1

        mapping[bar_idx] = tick_indices

    return mapping


def run_reverse_backtest(mode='oos'):
    """运行反向策略回测"""
    print(f"\n{'='*60}")
    print(f"反向趋势角度策略回测 - {mode.upper()}")
    print(f"{'='*60}\n")

    # 加载数据
    print("加载数据...")
    loader = DataLoader(DATA_DIR)

    if mode == 'is':
        tick_df, bar_df = load_data_for_period(loader, IS_START, IS_END)
    else:
        tick_df, bar_df = load_data_for_period(loader, OOS_START, OOS_END)

    if tick_df is None or bar_df is None:
        print("错误: 无法加载数据")
        return None

    print(f"\nTick数据: {len(tick_df):,} 条")
    print(f"Bar数据: {len(bar_df):,} 条")

    # 计算指标
    print("\n计算指标...")
    df_with_indicators = calculate_strategy_indicators(
        bar_df.copy(),
        sma_period=ORIGINAL_PARAMS['sma_period'],
        atr_period=14,
        angle_lookback=5
    )

    # 生成反向信号
    print("\n生成反向交易信号...")
    signals = generate_reverse_signals(df_with_indicators, ORIGINAL_PARAMS)
    print(f"生成信号数量: {len(signals)}")

    if len(signals) == 0:
        print("警告: 没有生成任何信号！")
        return None

    # 显示前5个信号
    print("\n前5个信号示例:")
    for i, sig in enumerate(signals[:5]):
        print(f"  {i+1}. {sig.timestamp} | {sig.direction.value} | 角度突破反向")

    # 配置
    config = TradingConfig(
        symbol="XAUUSD",
        contract_size=100,
        spread_per_ounce=0.2,
        commission_per_lot=3.5,
        initial_capital=100000.0,
        leverage=100,
        base_slippage=0.1,
    )

    # 执行回测
    print("\n执行Tick级回测...")
    engine = TickBacktestEngine(config)
    result = engine.run(df_with_indicators, signals, tick_df)

    # 打印结果
    print(f"\n{'='*50}")
    print("反向策略回测结果")
    print(f"{'='*50}")
    print(f"总交易次数: {result.total_trades}")
    print(f"胜率: {result.win_rate*100:.1f}%")
    print(f"盈亏因子: {result.profit_factor:.2f}")
    print(f"总收益率: {result.total_return*100:.2f}%")
    print(f"最大回撤: {result.max_drawdown_pct*100:.2f}%")
    print(f"夏普比率: {result.sharpe_ratio:.2f}")
    if result.max_drawdown_pct != 0:
        calmar = result.total_return / abs(result.max_drawdown_pct)
        print(f"Calmar比率: {calmar:.2f}")

    # 对比原策略
    print(f"\n{'='*50}")
    print("与原策略对比 (OOS期间)")
    print(f"{'='*50}")
    print(f"{'指标':<18} {'原策略':>12} {'反向策略':>12} {'差异':>12}")
    print("-" * 58)

    original_oos = {
        'total_trades': 42,
        'win_rate': 0.3095,
        'profit_factor': 0.6411,
        'total_return': -0.1652,
        'max_drawdown_pct': -0.2835,
        'sharpe_ratio': -1.413,
    }

    print(f"{'总交易次数':<18} {original_oos['total_trades']:>12} {result.total_trades:>12} {result.total_trades - original_oos['total_trades']:>+12}")
    print(f"{'胜率(%)':<18} {original_oos['win_rate']*100:>11.1f}% {result.win_rate*100:>11.1f}% {(result.win_rate - original_oos['win_rate'])*100:>+11.1f}%")
    print(f"{'盈亏因子':<18} {original_oos['profit_factor']:>12.2f} {result.profit_factor:>12.2f} {result.profit_factor - original_oos['profit_factor']:>+12.2f}")
    print(f"{'收益率(%)':<18} {original_oos['total_return']*100:>11.2f}% {result.total_return*100:>11.2f}% {(result.total_return - original_oos['total_return'])*100:>+11.2f}%")
    print(f"{'最大回撤(%)':<18} {original_oos['max_drawdown_pct']*100:>11.2f}% {result.max_drawdown_pct*100:>11.2f}% {(result.max_drawdown_pct - original_oos['max_drawdown_pct'])*100:>+11.2f}%")

    # 关键分析
    print(f"\n{'='*50}")
    print("反向操作可行性分析")
    print(f"{'='*50}")

    expected_profit = -original_oos['total_return']
    actual_profit = result.total_return
    cost_drag = expected_profit - actual_profit

    print(f"理论上反向应盈利: {expected_profit*100:.2f}%")
    print(f"实际反向盈利: {actual_profit*100:.2f}%")
    print(f"成本损耗: {cost_drag*100:.2f}%")

    if actual_profit > 0:
        print("\n结论: 反向策略可行！但需要注意滑点和交易成本")
    else:
        print("\n结论: 反向策略同样亏损，说明问题不在策略方向")
        print("可能原因:")
        print("  1. 该时间段市场处于特定regime，策略失效")
        print("  2. 交易成本侵蚀了所有潜在利润")
        print("  3. 策略信号与市场真实走势存在系统性偏差")

    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', type=str, default='oos', choices=['is', 'oos'])
    args = parser.parse_args()

    result = run_reverse_backtest(args.mode)
