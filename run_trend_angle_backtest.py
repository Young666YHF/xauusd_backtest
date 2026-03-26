"""
趋势角度突破策略回测运行脚本
=============================
针对XAUUSD的极简趋势突破策略

数据要求:
- Dukascopy Tick级别原始数据
- 路径: /home/ctyun/xauusd_data/

回测周期:
- IS (样本内): 2025-01-01 ~ 2025-10-31
- OOS (样本外): 2025-11-01 ~ 2026-02-28

成本设定:
- Spread: 20 points (0.2美元/盎司)
- Slippage: 10 points (0.1美元/盎司)
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from strategies.trend_angle_breakout import (
    TrendAngleBreakoutStrategy,
    calculate_strategy_indicators
)
from engines.tick_engine import TickBacktestEngine
from engines.base import ExecutionModel
from core.config import TradingConfig
from core.types import BacktestResult
from core.data_loader import DataLoader


# ============================================================================
# 配置常量
# ============================================================================

# 成本配置 (根据用户要求)
SPREAD_PER_OUNCE = 0.2  # 20 points = 0.2美元
SLIPPAGE_POINTS = 0.1   # 10 points = 0.1美元

# 回测周期
IS_START = "2025-01-01"
IS_END = "2025-10-31"
OOS_START = "2025-11-01"
OOS_END = "2026-02-28"

# 数据路径
DATA_DIR = "/home/ctyun/xauusd_data"


# ============================================================================
# 数据加载与预处理
# ============================================================================

def load_tick_data_range(
    loader: DataLoader,
    months: List[str]
) -> pd.DataFrame:
    """
    加载多个月的tick数据

    Args:
        loader: 数据加载器
        months: 月份列表

    Returns:
        合并后的Tick DataFrame
    """
    tick_dfs = []

    for month_str in months:
        try:
            year, month = map(int, month_str.split('-'))
            filename = f"XAUUSD_{year}-{month:02d}.csv"
            filepath = loader.data_dir / filename

            if not filepath.exists():
                print(f"  Warning: Tick file not found: {filename}")
                continue

            tick_df = loader.load_tick_data(filepath)

            # 添加Mid价格
            tick_df['Mid'] = (tick_df['Bid'] + tick_df['Ask']) / 2

            tick_dfs.append(tick_df)
            print(f"  Loaded {len(tick_df):,} ticks from {month_str}")

        except Exception as e:
            print(f"  Warning: Failed to load tick data for {month_str}: {e}")
            continue

    if not tick_dfs:
        return None

    combined = pd.concat(tick_dfs)
    combined = combined.sort_index()
    combined = combined[~combined.index.duplicated(keep='first')]

    return combined

def load_and_prepare_data(
    start_date: str,
    end_date: str,
    data_dir: str = DATA_DIR,
    interval: str = "15min",
    load_ticks: bool = True  # 默认加载tick数据
) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    """
    加载并准备数据

    Args:
        start_date: 开始日期
        end_date: 结束日期
        data_dir: 数据目录
        interval: K线周期
        load_ticks: 是否加载tick数据用于回测执行

    Returns:
        (ohlcv_df, tick_df) - K线数据和Tick数据
    """
    print(f"Loading data from {start_date} to {end_date}...")

    from core.data_loader import DataLoader

    # 创建数据加载器
    loader = DataLoader(data_dir)

    # 计算需要加载的月份
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)

    months = []
    current = start_dt.replace(day=1)
    while current <= end_dt:
        months.append(current.strftime("%Y-%m"))
        # 移动到下个月
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    print(f"Loading months: {months}")

    # 加载K线数据（用于指标计算）
    df = loader.load_range(months, interval)

    # 过滤日期范围
    df = df[(df.index >= start_date) & (df.index <= end_date)]

    print(f"Loaded {len(df)} {interval} bars")

    # 计算策略指标
    df = calculate_strategy_indicators(
        df,
        sma_period=20,
        atr_period=14,
        angle_lookback=5
    )

    # 加载tick数据（用于回测执行）
    tick_df = None
    if load_ticks:
        print(f"\nLoading tick data for execution...")
        tick_df = load_tick_data_range(loader, months)
        if tick_df is not None:
            # 过滤tick数据日期范围
            tick_df = tick_df[(tick_df.index >= start_date) & (tick_df.index <= end_date)]
            print(f"Total tick data loaded: {len(tick_df):,} ticks")
            print(f"Date range: {tick_df.index[0]} to {tick_df.index[-1]}")

    return df, tick_df


# ============================================================================
# 回测执行
# ============================================================================

def create_trading_config() -> TradingConfig:
    """创建交易配置（含成本设定）"""
    return TradingConfig(
        symbol="XAUUSD",
        contract_size=100,
        tick_size=0.01,
        spread_per_ounce=SPREAD_PER_OUNCE,
        commission_per_lot=3.5,
        initial_capital=100000.0,
        leverage=100,
        base_slippage=SLIPPAGE_POINTS,
        atr_slippage_ratio=0.03,
        stop_loss_slippage_mult=2.0,
        take_profit_slippage_mult=0.0,
    )


def run_backtest(
    df: pd.DataFrame,
    tick_df: Optional[pd.DataFrame],
    strategy_params: Optional[dict] = None,
    warmup_bars: int = 100
) -> BacktestResult:
    """
    执行回测

    Args:
        df: OHLCV数据（已添加指标）
        tick_df: Tick数据（可选）
        strategy_params: 策略参数
        warmup_bars: 预热K线数

    Returns:
        BacktestResult
    """
    # 创建配置
    config = create_trading_config()

    # 创建执行模型
    execution = ExecutionModel(
        spread_per_ounce=SPREAD_PER_OUNCE,
        contract_size=100,
        base_slippage=SLIPPAGE_POINTS,
        atr_slippage_ratio=0.03,
        stop_loss_slippage_mult=2.0,
        take_profit_slippage_mult=0.0,
        commission_per_lot=3.5,
    )

    # 创建回测引擎
    engine = TickBacktestEngine(
        config=config,
        execution_model=execution
    )

    # 创建策略
    strategy = TrendAngleBreakoutStrategy(
        params=strategy_params,
        strategy_id="TrendAngleBreakout"
    )

    # 生成信号
    signals = []
    for i in range(warmup_bars, len(df)):
        signal = strategy.generate_signal(df, i)
        if signal:
            signals.append(signal)

    print(f"Generated {len(signals)} signals")

    # 执行回测
    result = engine.run(df, signals, tick_df)

    return result


def print_results(result: BacktestResult, period_name: str = "Backtest"):
    """打印回测结果"""
    print(f"\n{'='*60}")
    print(f"{period_name} Results")
    print(f"{'='*60}")
    print(f"Total Trades:     {result.total_trades}")
    print(f"Winning Trades:   {result.winning_trades}")
    print(f"Losing Trades:    {result.losing_trades}")
    print(f"Win Rate:         {result.win_rate*100:.2f}%")
    print(f"Profit Factor:    {result.profit_factor:.2f}")
    print(f"Total P&L:        ${result.total_pnl:,.2f}")
    print(f"Total Return:     {result.total_return*100:.2f}%")
    print(f"Max Drawdown:     {result.max_drawdown_pct*100:.2f}%")
    print(f"Sharpe Ratio:     {result.sharpe_ratio:.2f}")
    print(f"{'='*60}\n")


# ============================================================================
# 主函数
# ============================================================================

def main():
    """主入口"""
    import argparse

    parser = argparse.ArgumentParser(description='Trend Angle Breakout Backtest')
    parser.add_argument('--mode', choices=['is', 'oos', 'full'], default='is',
                        help='Backtest mode: is=in-sample, oos=out-of-sample, full=all')
    parser.add_argument('--data-dir', type=str, default=DATA_DIR,
                        help='Data directory path')
    parser.add_argument('--sma-period', type=int, default=20,
                        help='SMA period')
    parser.add_argument('--angle-threshold', type=float, default=3.0,
                        help='Angle threshold in degrees')
    parser.add_argument('--rr-ratio', type=float, default=2.0,
                        help='Risk-reward ratio')

    args = parser.parse_args()

    # 确定日期范围
    if args.mode == 'is':
        start_date, end_date = IS_START, IS_END
        period_name = "In-Sample (Jan-Oct 2025)"
    elif args.mode == 'oos':
        start_date, end_date = OOS_START, OOS_END
        period_name = "Out-of-Sample (Nov 2025-Feb 2026)"
    else:
        start_date, end_date = IS_START, OOS_END
        period_name = "Full Period (Jan 2025-Feb 2026)"

    # 策略参数
    strategy_params = {
        'sma_period': args.sma_period,
        'angle_threshold': args.angle_threshold,
        'risk_reward_ratio': args.rr_ratio,
        'use_fixed_exit': True,
    }

    print(f"\nRunning Trend Angle Breakout Strategy")
    print(f"Period: {period_name}")
    print(f"Cost: Spread={SPREAD_PER_OUNCE} ($/oz), Slippage={SLIPPAGE_POINTS} ($)")
    print(f"Params: {strategy_params}\n")

    try:
        # 加载数据
        df, tick_df = load_and_prepare_data(start_date, end_date, args.data_dir)

        # 执行回测
        result = run_backtest(df, tick_df, strategy_params)

        # 打印结果
        print_results(result, period_name)

        # 保存结果
        output_dir = Path("results")
        output_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_file = output_dir / f"trend_angle_{args.mode}_{timestamp}.csv"

        if result.trades:
            trades_df = pd.DataFrame([
                {
                    'entry_time': t.entry_time,
                    'exit_time': t.exit_time,
                    'direction': t.direction.name,
                    'size': t.size,
                    'entry_price': t.entry_price,
                    'exit_price': t.exit_price,
                    'pnl': t.pnl,
                    'pnl_pct': t.pnl_pct,
                    'exit_reason': t.exit_reason.name,
                    'bars_held': t.bars_held,
                }
                for t in result.trades
            ])
            trades_df.to_csv(result_file, index=False)
            print(f"Trade records saved to: {result_file}")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("\nPlease ensure data files are available in the specified directory.")
        print("Expected format: CSV with columns [Open, High, Low, Close, Volume]")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
