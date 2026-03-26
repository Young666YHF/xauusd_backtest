"""
Dollar Trader 策略回测脚本 - 简化版
基于Tick级别数据的高精度回测
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Any

sys.path.insert(0, '/home/ctyun/xauusd_backtest')

from strategies.dollar_trader import DollarTraderStrategy, calculate_dollar_trader_indicators
from core.types import TradeDirection
from core.config import TradingConfig
from core.data_loader import DataLoader
from engines.dollar_trader_engine import DollarTraderBacktestEngine


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='Dollar Trader Strategy Backtest')

    parser.add_argument('--mode', type=str, choices=['is', 'oos', 'full', 'custom'],
                       default='is', help='回测模式: is=样本内(2025-01~2025-10), oos=样本外(2025-11~2026-02), full=全量(2024-01~2026-02), custom=自定义日期')
    parser.add_argument('--start-date', type=str, help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--data-dir', type=str, default='/home/ctyun/xauusd_data',
                       help='数据目录路径')
    parser.add_argument('--output', type=str, help='输出结果文件路径(CSV格式)')
    parser.add_argument('--initial-capital', type=float, default=100000.0,
                       help='初始资金')
    parser.add_argument('--contract-size', type=int, default=100,
                       help='合约大小(盎司/手)')
    parser.add_argument('--spread-per-lot', type=float, default=60.0,
                       help='每手点差成本(美元)')
    parser.add_argument('--risk-per-trade', type=float, default=0.02,
                       help='每笔交易风险百分比 (默认2%)')

    parser.add_argument('--interval', type=str, default='15m', choices=['5m', '15m', '30m', '1h'],
                       help='K线周期 (默认15m)')

    # 策略参数
    parser.add_argument('--sma-short', type=int, default=20, help='短期SMA周期')
    parser.add_argument('--sma-medium', type=int, default=50, help='中期SMA周期')
    parser.add_argument('--sma-long', type=int, default=200, help='长期SMA周期')

    return parser.parse_args()


def get_date_range(mode: str) -> tuple[str, str]:
    """获取回测日期范围"""
    if mode == 'is':
        return '2025-01-01', '2025-10-31'
    elif mode == 'oos':
        return '2025-11-01', '2026-02-28'
    elif mode == 'full':
        return '2024-01-01', '2026-02-28'
    else:
        raise ValueError("Custom mode requires --start-date and --end-date")


def load_kline_data(data_dir: str, start_date: str, end_date: str, months: list[str], interval: str = "15m") -> tuple:
    """从本地K线数据加载OHLCV"""
    kline_dir = Path(data_dir) / "kline" / interval

    dfs = []
    for month_str in months:
        filepath = kline_dir / f"XAUUSD_{month_str}.csv"
        if filepath.exists():
            df = pd.read_csv(filepath, index_col=0, parse_dates=True)
            dfs.append(df)
        else:
            print(f"Warning: File not found: {filepath}")

    if not dfs:
        raise ValueError("没有成功加载任何数据")

    ohlc_df = pd.concat(dfs)
    ohlc_df = ohlc_df.sort_index()
    ohlc_df = ohlc_df[~ohlc_df.index.duplicated(keep='first')]

    # 过滤日期范围
    ohlc_df = ohlc_df.loc[start_date:end_date]

    return ohlc_df


def load_data(data_dir: str, start_date: str, end_date: str, months: list[str], interval: str = "15m") -> tuple:
    """加载数据（优先使用本地K线数据）"""
    kline_dir = Path(data_dir) / "kline" / interval

    # 如果存在K线数据，直接使用
    if kline_dir.exists():
        return load_kline_data(data_dir, start_date, end_date, months, interval)

    # 否则使用DataLoader从tick数据重采样
    loader = DataLoader(data_dir)
    ohlc_df = loader.load_range(months, interval=interval)
    ohlc_df = ohlc_df.loc[start_date:end_date]
    return ohlc_df


def print_performance_report(result, config: TradingConfig):
    """打印绩效报告"""
    print("\n" + "="*60)
    print("DOLLAR TRADER BACKTEST PERFORMANCE REPORT")
    print("="*60)

    print("\n【基本统计】")
    print(f"  总交易次数:     {result.total_trades}")
    print(f"  盈利次数:       {result.winning_trades}")
    print(f"  亏损次数:       {result.losing_trades}")
    print(f"  胜率:           {result.win_rate*100:.2f}%")

    print("\n【盈亏统计】")
    print(f"  总盈亏:         ${result.total_pnl:,.2f}")
    print(f"  总收益率:       {result.total_return*100:.2f}%")
    print(f"  平均盈亏:       ${result.avg_pnl:,.2f}")
    print(f"  平均盈利:       ${result.avg_win:,.2f}")
    print(f"  平均亏损:       ${result.avg_loss:,.2f}")
    print(f"  盈利因子:       {result.profit_factor:.2f}")

    print("\n【风险指标】")
    print(f"  最大回撤:       ${result.max_drawdown:,.2f}")
    print(f"  最大回撤率:     {result.max_drawdown_pct*100:.2f}%")
    print(f"  夏普比率:       {result.sharpe_ratio:.2f}")
    print(f"  索提诺比率:     {result.sortino_ratio:.2f}")
    print(f"  卡尔马比率:     {result.calmar_ratio:.2f}")

    print("\n【成本配置】")
    print(f"  初始资金:       ${config.initial_capital:,.2f}")
    print(f"  合约大小:       {config.contract_size} 盎司/手")
    print(f"  每手点差:       ${config.spread_per_ounce * config.contract_size:.2f}")

    print("\n" + "="*60)


def save_results(result, output_path: str):
    """保存结果到文件"""
    import pandas as pd

    trades_data = [
        {
            'entry_time': t.entry_time,
            'exit_time': t.exit_time,
            'direction': t.direction.name,
            'entry_price': t.entry_price,
            'exit_price': t.exit_price,
            'pnl': t.pnl,
            'bars_held': t.bars_held,
            'exit_reason': t.exit_reason.name,
        }
        for t in result.trades
    ]

    pd.DataFrame(trades_data).to_csv(output_path, index=False)
    print(f"\nResults saved to: {output_path}")


def main():
    """主函数"""
    args = parse_args()

    # 获取日期范围
    if args.mode == 'custom':
        start_date, end_date = args.start_date, args.end_date
        if not start_date or not end_date:
            raise ValueError("Custom mode requires --start-date and --end-date")
        months = sorted(set(pd.date_range(start_date, end_date, freq='MS').strftime('%Y-%m')))
    elif args.mode == 'is':
        start_date, end_date = get_date_range(args.mode)
        months = [f'2025-{m:02d}' for m in range(1, 11)]
    elif args.mode == 'oos':
        start_date, end_date = get_date_range(args.mode)
        months = ['2025-11', '2025-12', '2026-01', '2026-02']
    elif args.mode == 'full':
        start_date, end_date = get_date_range(args.mode)
        # 2024年1月到2026年2月
        months = [f'2024-{m:02d}' for m in range(1, 13)] + \
                 [f'2025-{m:02d}' for m in range(1, 13)] + \
                 ['2026-01', '2026-02']
    else:
        raise ValueError(f"Unknown mode: {args.mode}")

    print(f"\nBacktest Period: {start_date} to {end_date}")
    print(f"Interval: {args.interval}")

    # 加载数据
    print("\n" + "="*60)
    ohlc_df = load_data(args.data_dir, start_date, end_date, months, args.interval)
    print(f"Loaded {len(ohlc_df):,} bars from {ohlc_df.index[0]} to {ohlc_df.index[-1]}")

    # 计算指标
    print("\nCalculating indicators...")
    ohlc_df = calculate_dollar_trader_indicators(
        ohlc_df,
        sma_short=args.sma_short,
        sma_medium=args.sma_medium,
        sma_long=args.sma_long
    )

    # 创建策略
    strategy_params = {
        'sma_short': args.sma_short,
        'sma_medium': args.sma_medium,
        'sma_long': args.sma_long,
        'position_size': 1.0,  # 固定手数
    }
    strategy = DollarTraderStrategy(params=strategy_params, strategy_id="DollarTrader")

    print(f"\nStrategy Parameters:")
    print(f"  SMA Short:   {args.sma_short}")
    print(f"  SMA Medium:  {args.sma_medium}")
    print(f"  SMA Long:    {args.sma_long}")

    # 配置
    config = TradingConfig(
        initial_capital=args.initial_capital,
        contract_size=args.contract_size,
        spread_per_ounce=args.spread_per_lot / args.contract_size,
    )

    # 运行回测
    print("\n" + "="*60)
    print("RUNNING BACKTEST...")
    print("="*60)

    # 计算信号
    signals = []
    warmup_bars = strategy.params['sma_long'] + 5
    for i in range(warmup_bars, len(ohlc_df)):
        signal = strategy.generate_signal(ohlc_df, i)
        if signal:
            signals.append(signal)

    print(f"Generated {len(signals)} signals")

    # 执行回测
    engine = DollarTraderBacktestEngine(config)
    result = engine.run(ohlc_df, signals)

    # 打印报告
    print_performance_report(result, config)

    # 保存结果
    if args.output:
        save_results(result, args.output)
    else:
        output_path = f'/home/ctyun/xauusd_backtest/results_dollar_trader_{args.mode}_{args.interval}.csv'
        save_results(result, output_path)

    print("\nBacktest completed!")


if __name__ == '__main__':
    import pandas as pd
    main()
