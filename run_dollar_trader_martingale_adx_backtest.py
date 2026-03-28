#!/usr/bin/env python3
"""
Dollar Trader Martingale ADX Enhanced 策略回测脚本
====================================================
基于SMA_20/50/200趋势跟踪 + ADX过滤的马丁格尔仓位管理

ADX增强逻辑:
  - 首次亏损后检查ADX值
  - 当ADX > threshold时，启用马丁加倍
  - 一旦启用马丁，连续加倍直到盈利（不再检查ADX）
  - 盈利后重置，下次亏损重新判断ADX

用法:
    python run_dollar_trader_martingale_adx_backtest.py --mode is --multiplier 2.0
    python run_dollar_trader_martingale_adx_backtest.py --mode full --adx-threshold 25
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta

# 添加项目根目录到路径
sys.path.insert(0, '/home/ctyun/xauusd_backtest')

import pandas as pd
import numpy as np
from typing import Dict, Any, List

from strategies.dollar_trader_martingale_adx import (
    DollarTraderMartingaleADXStrategy,
    calculate_dollar_trader_martingale_adx_indicators
)
from engines.dollar_trader_engine import DollarTraderBacktestEngine
from core.config import TradingConfig
from core.data_loader import DataLoader


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Dollar Trader Martingale ADX Enhanced 策略回测',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # IS样本内回测 (默认)
  python run_dollar_trader_martingale_adx_backtest.py --mode is

  # OOS样本外回测
  python run_dollar_trader_martingale_adx_backtest.py --mode oos

  # 完整数据回测
  python run_dollar_trader_martingale_adx_backtest.py --mode full

  # 自定义ADX阈值
  python run_dollar_trader_martingale_adx_backtest.py --adx-threshold 25

  # 自定义时间范围和周期
  python run_dollar_trader_martingale_adx_backtest.py --mode custom \
    --start-date 2024-01-01 --end-date 2026-02-28 --timeframe 30m
        """
    )

    parser.add_argument('--mode', type=str, default='is',
                        choices=['is', 'oos', 'full', 'custom'],
                        help='回测模式: is=样本内, oos=样本外, full=完整数据, custom=自定义 (默认: is)')

    parser.add_argument('--data-path', type=str, default='./xauusd_data',
                        help='数据目录路径 (默认: ./xauusd_data)')

    parser.add_argument('--timeframe', type=str, default='30m',
                        help='K线周期 (默认: 30m, 可选: 5m, 15m, 30m, 1h, 4h, 1d)')

    parser.add_argument('--start-date', type=str, default=None,
                        help='开始日期 (格式: YYYY-MM-DD, 默认根据mode自动设置)')

    parser.add_argument('--end-date', type=str, default=None,
                        help='结束日期 (格式: YYYY-MM-DD, 默认根据mode自动设置)')

    parser.add_argument('--multiplier', type=float, default=2.0,
                        help='马丁格尔倍数 (默认: 2.0)')

    parser.add_argument('--max-steps', type=int, default=5,
                        help='最大连续翻倍次数 (默认: 5)')

    parser.add_argument('--position-size', type=float, default=1.0,
                        help='基础仓位大小 (默认: 1.0)')

    parser.add_argument('--sma-short', type=int, default=20,
                        help='短期SMA周期 (默认: 20)')

    parser.add_argument('--sma-medium', type=int, default=50,
                        help='中期SMA周期 (默认: 50)')

    parser.add_argument('--sma-long', type=int, default=200,
                        help='长期SMA周期 (默认: 200)')

    parser.add_argument('--adx-period', type=int, default=14,
                        help='ADX周期 (默认: 14)')

    parser.add_argument('--adx-threshold', type=float, default=20.0,
                        help='ADX阈值，大于此值才启用马丁 (默认: 20.0)')

    parser.add_argument('--spread', type=float, default=20.0,
                        help='点差 (points, 默认: 20)')

    parser.add_argument('--output', type=str, default=None,
                        help='输出CSV文件路径 (可选)')

    parser.add_argument('--verbose', '-v', action='store_true',
                        help='显示详细信息')

    return parser.parse_args()


def load_data(mode: str, data_path: str, timeframe: str = '30m',
              start_date: str = None, end_date: str = None,
              verbose: bool = False) -> pd.DataFrame:
    """加载K线数据"""

    # 根据模式确定日期范围
    if start_date and end_date:
        pass
    elif mode == 'is':
        start_date = '2025-01-01'
        end_date = '2025-11-01'
    elif mode == 'oos':
        start_date = '2025-11-01'
        end_date = '2026-03-01'
    elif mode == 'full':
        start_date = '2024-01-01'
        end_date = '2026-02-28'
    else:  # custom
        start_date = start_date or '2024-01-01'
        end_date = end_date or '2026-02-28'

    if verbose:
        print(f"加载数据: {start_date} ~ {end_date}")

    # 生成月份列表
    months = []
    current = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    while current <= end:
        months.append(current.strftime('%Y-%m'))
        current += relativedelta(months=1)

    # 加载K线数据
    kline_dir = Path(data_path) / "kline" / timeframe
    dfs = []
    for month_str in months:
        filepath = kline_dir / f"XAUUSD_{month_str}.csv"
        if filepath.exists():
            df = pd.read_csv(filepath, index_col=0, parse_dates=True)
            dfs.append(df)
        else:
            if verbose:
                print(f"Warning: 文件不存在: {filepath}")

    if not dfs:
        raise ValueError(f"没有成功加载任何数据: {kline_dir}")

    ohlc_df = pd.concat(dfs)
    ohlc_df = ohlc_df.sort_index()
    ohlc_df = ohlc_df[~ohlc_df.index.duplicated(keep='first')]

    # 过滤日期范围
    ohlc_df = ohlc_df.loc[start_date:end_date]

    if verbose:
        print(f"OHLC数据 ({timeframe}): {len(ohlc_df):,} 条")

    return ohlc_df


def run_backtest(args) -> Dict[str, Any]:
    """运行回测"""

    print("=" * 70)
    print("Dollar Trader Martingale ADX Enhanced 策略回测")
    print("=" * 70)

    # 加载数据
    print(f"\n[1/4] 加载数据 (模式: {args.mode.upper()}, 周期: {args.timeframe})...")
    df = load_data(args.mode, args.data_path, args.timeframe,
                   args.start_date, args.end_date, args.verbose)

    # 策略参数
    strategy_params = {
        'sma_short': args.sma_short,
        'sma_medium': args.sma_medium,
        'sma_long': args.sma_long,
        'position_size': args.position_size,
        'martingale_multiplier': args.multiplier,
        'max_martingale_steps': args.max_steps,
        'adx_period': args.adx_period,
        'adx_threshold': args.adx_threshold,
    }

    print(f"\n[2/4] 策略参数:")
    print(f"  时间周期: {args.timeframe}")
    print(f"  SMA周期: {args.sma_short}/{args.sma_medium}/{args.sma_long}")
    print(f"  基础仓位: {args.position_size}")
    print(f"  马丁格尔倍数: {args.multiplier}")
    print(f"  最大翻倍次数: {args.max_steps}")
    print(f"  ADX周期: {args.adx_period}")
    print(f"  ADX阈值: {args.adx_threshold}")

    # 计算指标
    print(f"\n[3/4] 计算技术指标 (SMA + ADX)...")
    df = calculate_dollar_trader_martingale_adx_indicators(
        df,
        sma_short=args.sma_short,
        sma_medium=args.sma_medium,
        sma_long=args.sma_long,
        adx_period=args.adx_period
    )

    # 创建配置
    config = TradingConfig(
        symbol='XAUUSD',
        spread_points=args.spread,
        slippage_points=10,
        initial_capital=100000,
    )

    # 创建策略
    strategy = DollarTraderMartingaleADXStrategy(
        params=strategy_params,
        strategy_id=f"DT_Martingale_ADX_{args.adx_threshold}"
    )

    # 生成信号
    print(f"\n[4/4] 生成交易信号...")
    signals = []
    warmup_bars = max(args.sma_long, args.adx_period * 2) + 5
    for i in range(warmup_bars, len(df)):
        signal = strategy.generate_signal(df, i)
        if signal:
            signals.append(signal)

    print(f"  生成信号: {len(signals)} 个")

    # 运行回测
    print(f"\n运行回测...")
    engine = DollarTraderBacktestEngine(config)
    result = engine.run(df, signals)

    return result, engine, strategy


def print_results(result, engine, strategy):
    """打印回测结果"""

    print("\n" + "=" * 70)
    print("回测结果")
    print("=" * 70)

    print(f"\n【交易统计】")
    print(f"  总交易次数: {result.total_trades}")
    print(f"  盈利次数: {result.winning_trades}")
    print(f"  亏损次数: {result.losing_trades}")
    print(f"  胜率: {result.win_rate*100:.2f}%")

    print(f"\n【盈亏统计】")
    print(f"  总盈亏: ${result.total_pnl:,.2f}")
    print(f"  总收益率: {result.total_return*100:.2f}%")
    print(f"  平均盈亏: ${result.avg_pnl:,.2f}")
    print(f"  平均盈利: ${result.avg_win:,.2f}")
    print(f"  平均亏损: ${result.avg_loss:,.2f}")
    print(f"  盈利因子: {result.profit_factor:.2f}")

    print(f"\n【风险指标】")
    print(f"  最大回撤: ${result.max_drawdown:,.2f}")
    print(f"  最大回撤率: {result.max_drawdown_pct*100:.2f}%")
    print(f"  夏普比率: {result.sharpe_ratio:.2f}")
    print(f"  索提诺比率: {result.sortino_ratio:.2f}")

    # ADX马丁统计
    if result.trades:
        print(f"\n【ADX马丁格尔统计】")

        # 获取策略状态信息
        status = strategy.get_status_info()
        print(f"  最终连续亏损次数: {status['consecutive_losses']}")
        print(f"  马丁启用状态: {'是' if status['martingale_enabled'] else '否'}")
        print(f"  最后ADX值: {status['last_adx_value']:.2f}" if status['last_adx_value'] else "  最后ADX值: N/A")

        # 连续亏损分析
        consecutive_losses = 0
        max_consecutive = 0
        for t in result.trades:
            if t.pnl < 0:
                consecutive_losses += 1
                max_consecutive = max(max_consecutive, consecutive_losses)
            else:
                consecutive_losses = 0

        print(f"  最大连续亏损次数: {max_consecutive}")

    # 权益曲线
    if result.equity_curve:
        print(f"\n【权益曲线】")
        print(f"  初始权益: ${result.equity_curve[0]:,.2f}")
        print(f"  最终权益: ${result.equity_curve[-1]:,.2f}")

    print("\n" + "=" * 70)


def main():
    """主函数"""
    args = parse_args()

    try:
        # 运行回测
        results, engine, strategy = run_backtest(args)

        # 打印结果
        print_results(results, engine, strategy)

        # 保存结果
        if args.output:
            if results.trades:
                trades_df = pd.DataFrame([
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
                    for t in results.trades
                ])
                trades_df.to_csv(args.output, index=False)
                print(f"\n交易记录已保存: {args.output}")

        return 0

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
