"""
趋势角度突破策略 - 灵活入场对比回测
======================================
对比两种模式的回测结果：
1. 严格模式: 入场价必须在K线范围内才成交（原逻辑）
2. 灵活模式: 入场价超出范围时，以开盘价/最近价成交

"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from strategies.trend_angle_breakout import (
    TrendAngleBreakoutStrategy,
    calculate_strategy_indicators
)
from engines.tick_engine import TickBacktestEngine
from engines.base import ExecutionModel
from core.config import TradingConfig
from core.types import BacktestResult, TradeDirection
from core.data_loader import DataLoader


# 成本配置
SPREAD_PER_OUNCE = 0.2
SLIPPAGE_POINTS = 0.1

# 数据路径
DATA_DIR = "/home/ctyun/xauusd_data"


def load_data(start_date: str, end_date: str) -> pd.DataFrame:
    """加载数据"""
    print(f"Loading data from {start_date} to {end_date}...")

    loader = DataLoader(DATA_DIR)

    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)

    months = []
    current = start_dt.replace(day=1)
    while current <= end_dt:
        months.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    df = loader.load_range(months, "15min")
    df = df[(df.index >= start_date) & (df.index <= end_date)]

    print(f"Loaded {len(df)} 15min bars")

    df = calculate_strategy_indicators(df, sma_period=20, atr_period=14, angle_lookback=5)

    return df


class FlexibleTickBacktestEngine(TickBacktestEngine):
    """
    支持灵活入场的Tick回测引擎

    当信号入场价超出K线范围时：
    - 做多: 使用 min(entry_price, High) 或 Open
    - 做空: 使用 max(entry_price, Low) 或 Open
    """

    def __init__(self, config: TradingConfig, execution_model=None, use_numba=True, flexible_entry=True):
        super().__init__(config, execution_model, use_numba)
        self.flexible_entry = flexible_entry
        self.skipped_signals = []  # 记录被调整的信号

    def _process_entry(self, signal, bar, tick_df=None):
        """处理入场 - 支持灵活价格调整"""
        atr = bar.get('ATR', 0)
        strategy_category = (
            self.execution.__class__.__dict__.get('StrategyCategory', None)
            or type('SC', (), {'MEAN_REVERSION': 1, 'MOMENTUM_BREAKOUT': 2})()
        )

        from engines.base import StrategyCategory
        strategy_category = (
            StrategyCategory.MEAN_REVERSION if 'MeanReversion' in signal.strategy_id
            else StrategyCategory.MOMENTUM_BREAKOUT
        )

        # 确定入场价格
        if tick_df is not None and self.bar_idx_to_ticks is not None:
            entry_price = self._find_entry_price_tick(signal)
        else:
            entry_price = signal.entry_price or bar['Open']

        if entry_price is None:
            entry_price = bar['Open']

        # 严格模式：如果入场价超出范围，跳过此信号
        if not self.flexible_entry:
            if entry_price < bar['Low'] or entry_price > bar['High']:
                self.skipped_signals.append({
                    'timestamp': signal.timestamp,
                    'direction': signal.direction.name,
                    'entry_price': entry_price,
                    'bar_ohlc': (bar['Open'], bar['High'], bar['Low'], bar['Close']),
                    'reason': f'Entry {entry_price:.2f} outside range [{bar["Low"]:.2f}, {bar["High"]:.2f}]'
                })
                return  # 跳过，不开仓

        # 灵活模式：调整超出范围的入场价
        original_price = entry_price
        if self.flexible_entry:
            if signal.direction == TradeDirection.LONG:
                # 做多：如果入场价高于High，使用Open；如果低于Low，使用Low
                if entry_price > bar['High']:
                    entry_price = bar['Open']  # 跳空高开，以开盘价追入
                    self.skipped_signals.append({
                        'timestamp': signal.timestamp,
                        'direction': signal.direction.name,
                        'original': original_price,
                        'adjusted': entry_price,
                        'bar_ohlc': (bar['Open'], bar['High'], bar['Low'], bar['Close']),
                        'reason': 'LONG entry above High, using Open'
                    })
                elif entry_price < bar['Low']:
                    entry_price = bar['Low']
            else:
                # 做空：如果入场价低于Low，使用Open；如果高于High，使用High
                if entry_price < bar['Low']:
                    entry_price = bar['Open']  # 跳空低开，以开盘价追入
                    self.skipped_signals.append({
                        'timestamp': signal.timestamp,
                        'direction': signal.direction.name,
                        'original': original_price,
                        'adjusted': entry_price,
                        'bar_ohlc': (bar['Open'], bar['High'], bar['Low'], bar['Close']),
                        'reason': 'SHORT entry below Low, using Open'
                    })
                elif entry_price > bar['High']:
                    entry_price = bar['High']

        # 计算滑点
        slippage = self.execution.calculate_entry_slippage(
            entry_price, atr, strategy_category
        )

        # 调整入场价格（加滑点）
        if signal.direction == TradeDirection.LONG:
            filled_price = entry_price + slippage
        else:
            filled_price = entry_price - slippage

        self._open_position(signal, filled_price, slippage)


def run_comparison_backtest(df: pd.DataFrame, strategy_params: dict, warmup_bars: int = 100):
    """运行对比回测"""

    # 创建策略
    strategy = TrendAngleBreakoutStrategy(
        params=strategy_params,
        strategy_id="TrendAngleBreakout"
    )

    # 生成信号（两种模式共用）
    signals = []
    for i in range(warmup_bars, len(df)):
        signal = strategy.generate_signal(df, i)
        if signal:
            signals.append(signal)

    print(f"\nTotal signals generated: {len(signals)}")

    # 创建配置和执行模型
    config = TradingConfig(
        symbol="XAUUSD",
        contract_size=100,
        tick_size=0.01,
        spread_per_ounce=SPREAD_PER_OUNCE,
        commission_per_lot=3.5,
        initial_capital=100000.0,
        leverage=100,
        base_slippage=SLIPPAGE_POINTS,
    )

    execution = ExecutionModel(
        spread_per_ounce=SPREAD_PER_OUNCE,
        contract_size=100,
        base_slippage=SLIPPAGE_POINTS,
        atr_slippage_ratio=0.03,
        stop_loss_slippage_mult=2.0,
        take_profit_slippage_mult=0.0,
        commission_per_lot=3.5,
    )

    results = {}

    # 模式1: 严格模式（原逻辑）
    print("\n" + "="*70)
    print("MODE 1: STRICT (Skip if entry outside bar range)")
    print("="*70)

    engine_strict = FlexibleTickBacktestEngine(
        config=config,
        execution_model=execution,
        use_numba=True,
        flexible_entry=False
    )
    result_strict = engine_strict.run(df, signals, tick_df=None)
    results['strict'] = result_strict
    results['strict_skipped'] = engine_strict.skipped_signals

    print_results(result_strict)

    # 模式2: 灵活模式
    print("\n" + "="*70)
    print("MODE 2: FLEXIBLE (Adjust entry to Open when outside range)")
    print("="*70)

    engine_flexible = FlexibleTickBacktestEngine(
        config=config,
        execution_model=execution,
        use_numba=True,
        flexible_entry=True
    )
    result_flexible = engine_flexible.run(df, signals, tick_df=None)
    results['flexible'] = result_flexible
    results['flexible_adjusted'] = engine_flexible.skipped_signals

    print_results(result_flexible)

    # 打印调整详情
    if engine_flexible.skipped_signals:
        print(f"\n{'='*70}")
        print("FLEXIBLE MODE - ADJUSTED ENTRIES")
        print(f"{'='*70}")
        for adj in engine_flexible.skipped_signals[:10]:  # 只显示前10个
            o, h, l, c = adj['bar_ohlc']
            print(f"\n{adj['timestamp']} | {adj['direction']}")
            print(f"  Original: ${adj['original']:.2f} -> Adjusted: ${adj['adjusted']:.2f}")
            print(f"  Bar OHLC: O={o:.2f} H={h:.2f} L={l:.2f} C={c:.2f}")
            print(f"  Reason: {adj['reason']}")
        if len(engine_flexible.skipped_signals) > 10:
            print(f"\n... and {len(engine_flexible.skipped_signals) - 10} more")

    return results


def print_results(result: BacktestResult, title: str = "Results"):
    """打印回测结果"""
    print(f"\n{title}")
    print("-" * 50)
    print(f"Total Trades:     {result.total_trades}")
    print(f"Winning Trades:   {result.winning_trades}")
    print(f"Losing Trades:    {result.losing_trades}")
    print(f"Win Rate:         {result.win_rate*100:.2f}%")
    print(f"Profit Factor:    {result.profit_factor:.2f}")
    print(f"Total P&L:        ${result.total_pnl:,.2f}")
    print(f"Total Return:     {result.total_return*100:.2f}%")
    print(f"Max Drawdown:     {result.max_drawdown_pct*100:.2f}%")
    print(f"Sharpe Ratio:     {result.sharpe_ratio:.2f}")


def print_comparison(results: dict):
    """打印对比结果"""
    strict = results['strict']
    flexible = results['flexible']

    print("\n" + "="*70)
    print("COMPARISON SUMMARY")
    print("="*70)

    print(f"\n{'Metric':<25} {'Strict':>15} {'Flexible':>15} {'Diff':>12}")
    print("-" * 70)

    metrics = [
        ('Total Trades', strict.total_trades, flexible.total_trades, 0),
        ('Win Rate (%)', strict.win_rate*100, flexible.win_rate*100, 2),
        ('Profit Factor', strict.profit_factor, flexible.profit_factor, 2),
        ('Total P&L ($)', strict.total_pnl, flexible.total_pnl, 2),
        ('Total Return (%)', strict.total_return*100, flexible.total_return*100, 2),
        ('Max Drawdown (%)', strict.max_drawdown_pct*100, flexible.max_drawdown_pct*100, 2),
        ('Sharpe Ratio', strict.sharpe_ratio, flexible.sharpe_ratio, 2),
    ]

    for name, s_val, f_val, decimals in metrics:
        diff = f_val - s_val
        if decimals == 0:
            print(f"{name:<25} {s_val:>15.0f} {f_val:>15.0f} {diff:>+12.0f}")
        else:
            print(f"{name:<25} {s_val:>15.{decimals}f} {f_val:>15.{decimals}f} {diff:>+12.{decimals}f}")

    # 判断哪个更优
    print("\n" + "="*70)
    print("CONCLUSION")
    print("="*70)

    s_score = strict.total_return / abs(strict.max_drawdown_pct) if strict.max_drawdown_pct != 0 else strict.total_return
    f_score = flexible.total_return / abs(flexible.max_drawdown_pct) if flexible.max_drawdown_pct != 0 else flexible.total_return

    if f_score > s_score:
        print(f"✓ FLEXIBLE mode is superior (Calmar: {f_score:.2f} vs {s_score:.2f})")
        print(f"  - Additional trades: {flexible.total_trades - strict.total_trades}")
        print(f"  - Additional P&L: ${flexible.total_pnl - strict.total_pnl:,.2f}")
    elif s_score > f_score:
        print(f"✓ STRICT mode is superior (Calmar: {s_score:.2f} vs {f_score:.2f})")
        print(f"  - Avoided {strict.total_trades - flexible.total_trades} potentially bad trades")
    else:
        print("≈ Both modes perform similarly")


def main():
    """主入口"""
    import argparse

    parser = argparse.ArgumentParser(description='Trend Angle Breakout - Entry Mode Comparison')
    parser.add_argument('--start', type=str, default="2025-01-01", help='Start date')
    parser.add_argument('--end', type=str, default="2025-10-31", help='End date')
    parser.add_argument('--angle-threshold', type=float, default=3.0, help='Angle threshold')
    parser.add_argument('--rr-ratio', type=float, default=2.0, help='Risk-reward ratio')

    args = parser.parse_args()

    # 加载数据
    df = load_data(args.start, args.end)

    # 策略参数
    strategy_params = {
        'sma_period': 20,
        'angle_threshold': args.angle_threshold,
        'risk_reward_ratio': args.rr_ratio,
        'use_fixed_exit': True,
    }

    print(f"\nRunning comparison backtest")
    print(f"Period: {args.start} ~ {args.end}")
    print(f"Params: {strategy_params}")

    # 运行对比回测
    results = run_comparison_backtest(df, strategy_params)

    # 打印对比
    print_comparison(results)

    # 保存结果
    output_dir = Path("results")
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for mode_name, result in [('strict', results['strict']), ('flexible', results['flexible'])]:
        if result.trades:
            trades_df = pd.DataFrame([
                {
                    'entry_time': t.entry_time,
                    'exit_time': t.exit_time,
                    'direction': t.direction.name,
                    'entry_price': t.entry_price,
                    'exit_price': t.exit_price,
                    'pnl': t.pnl,
                    'pnl_pct': t.pnl_pct,
                    'exit_reason': t.exit_reason.name,
                }
                for t in result.trades
            ])
            trades_df.to_csv(output_dir / f"comparison_{mode_name}_{timestamp}.csv", index=False)

    print(f"\nResults saved to: results/comparison_*_{timestamp}.csv")


if __name__ == "__main__":
    main()
