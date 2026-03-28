#!/usr/bin/env python3
"""
Dollar Trader Martingale BBW Step 策略回测脚本
===============================================
基于SMA_20/50/200趋势跟踪 + BBW波动率过滤 + 阶梯式马丁格尔

阶梯式马丁逻辑:
  - 仓位 = 基础仓位 × multiplier^martingale_step
  - 亏损2次 → 阶梯+1
  - 盈利1次 → 阶梯-1
  - 最大层数继续亏损 → 超调计数
  - 超调计数>0时盈利 → 消耗计数保持仓位

BBW逻辑:
  - BBW = (Upper - Lower) / Middle × 100
  - 当前BBW > MA(BBW, 50) 时允许开仓

用法:
    python run_dollar_trader_martingale_bbw_backtest.py --mode is
    python run_dollar_trader_martingale_bbw_backtest.py --mode full --multiplier 1.5
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
    DollarTraderMartingaleBBWStepStrategy,
    calculate_dollar_trader_martingale_bbw_indicators
)
from engines.dollar_trader_engine import DollarTraderBacktestEngine
from core.config import TradingConfig


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Dollar Trader Martingale BBW Step 策略回测',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # IS样本内回测 (默认)
  python run_dollar_trader_martingale_bbw_backtest.py --mode is

  # OOS样本外回测
  python run_dollar_trader_martingale_bbw_backtest.py --mode oos

  # 完整数据回测
  python run_dollar_trader_martingale_bbw_backtest.py --mode full

  # 自定义参数
  python run_dollar_trader_martingale_bbw_backtest.py --multiplier 1.5 --max-steps 5
        """
    )

    parser.add_argument('--mode', type=str, default='is',
                        choices=['is', 'oos', 'full', 'custom'],
                        help='回测模式 (默认: is)')

    parser.add_argument('--data-path', type=str, default='./xauusd_data',
                        help='数据目录路径 (默认: ./xauusd_data)')

    parser.add_argument('--timeframe', type=str, default='30m',
                        help='K线周期 (默认: 30m)')

    parser.add_argument('--start-date', type=str, default=None,
                        help='开始日期 (YYYY-MM-DD)')

    parser.add_argument('--end-date', type=str, default=None,
                        help='结束日期 (YYYY-MM-DD)')

    parser.add_argument('--multiplier', type=float, default=2.0,
                        help='马丁格尔倍数 (默认: 2.0)')

    parser.add_argument('--max-steps', type=int, default=5,
                        help='最大阶梯层级 (默认: 5)')

    parser.add_argument('--position-size', type=float, default=0.01,
                        help='基础仓位大小 (默认: 0.01手)')

    parser.add_argument('--sma-short', type=int, default=20,
                        help='短期SMA周期 (默认: 20)')

    parser.add_argument('--sma-medium', type=int, default=50,
                        help='中期SMA周期 (默认: 50)')

    parser.add_argument('--sma-long', type=int, default=200,
                        help='长期SMA周期 (默认: 200)')

    parser.add_argument('--bb-period', type=int, default=20,
                        help='布林带周期 (默认: 20)')

    parser.add_argument('--bb-std', type=float, default=2.0,
                        help='布林带标准差 (默认: 2.0)')

    parser.add_argument('--bbw-ma-period', type=int, default=50,
                        help='BBW均线周期 (默认: 50)')

    parser.add_argument('--enable-overshoot', type=lambda x: x.lower() == 'true', default=True,
                        help='启用超调计数 (默认: true)')

    parser.add_argument('--enable-undershoot', type=lambda x: x.lower() == 'true', default=True,
                        help='启用欠调计数 (默认: true)')

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
        # 支持两种文件名格式: XAUUSD_YYYY-MM.csv 或 XAUUSD_BID_时间周期_YYYYMM.csv
        filepath = kline_dir / f"XAUUSD_{month_str}.csv"
        if not filepath.exists():
            # 尝试BID格式
            month_str_compact = month_str.replace('-', '')
            filepath = kline_dir / f"XAUUSD_BID_{timeframe}_{month_str_compact}.csv"

        if filepath.exists():
            df = pd.read_csv(filepath, index_col=0)
            # 转换毫秒时间戳为datetime
            df.index = pd.to_datetime(df.index, unit='ms')
            # 统一列名为大写（兼容不同数据源）
            df.columns = [col.capitalize() for col in df.columns]
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
    print("Dollar Trader Martingale BBW Step 策略回测")
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
        'bb_period': args.bb_period,
        'bb_std': args.bb_std,
        'bbw_ma_period': args.bbw_ma_period,
        'enable_overshoot': args.enable_overshoot,
        'enable_undershoot': args.enable_undershoot,
    }

    print(f"\n[2/4] 策略参数:")
    print(f"  时间周期: {args.timeframe}")
    print(f"  SMA周期: {args.sma_short}/{args.sma_medium}/{args.sma_long}")
    print(f"  布林带: 周期={args.bb_period}, 标准差={args.bb_std}")
    print(f"  BBW均线周期: {args.bbw_ma_period}")
    print(f"  基础仓位: {args.position_size}")
    print(f"  马丁倍数: {args.multiplier}")
    print(f"  最大阶梯层级: {args.max_steps}")
    print(f"  启用超调计数: {args.enable_overshoot}")
    print(f"  启用欠调计数: {args.enable_undershoot}")

    # 计算指标
    print(f"\n[3/4] 计算技术指标 (SMA + BBW)...")
    df = calculate_dollar_trader_martingale_bbw_indicators(
        df,
        sma_short=args.sma_short,
        sma_medium=args.sma_medium,
        sma_long=args.sma_long,
        bb_period=args.bb_period,
        bb_std=args.bb_std,
        bbw_ma_period=args.bbw_ma_period
    )

    # 创建配置
    config = TradingConfig(
        symbol='XAUUSD',
        spread_points=args.spread,
        slippage_points=10,
        initial_capital=100000,
    )

    # 创建策略
    strategy = DollarTraderMartingaleBBWStepStrategy(
        params=strategy_params,
        strategy_id=f"DT_Martingale_BBW_{args.multiplier}x"
    )

    # 运行回测（实时信号生成模式）
    print(f"\n[4/4] 运行回测（实时信号生成模式）...")
    engine = DollarTraderBacktestEngine(config)
    result = engine.run(df, signals=None, strategy=strategy)  # 传递策略实例，引擎会实时生成信号

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

    # 阶梯式马丁统计
    if result.trades:
        print(f"\n【阶梯式马丁统计】")

        # 获取策略状态信息
        status = strategy.get_status_info()
        print(f"  最终马丁阶梯: {status['martingale_step']}")
        print(f"  当前阶梯内亏损次数: {status['loss_count_in_step']}")
        print(f"  超调计数: {status['overshoot_count']} (启用: {status['enable_overshoot']})")
        print(f"  欠调计数: {status['undershoot_count']} (启用: {status['enable_undershoot']})")
        print(f"  最后BBW值: {status['last_bbw_value']:.2f}" if status['last_bbw_value'] else "  最后BBW值: N/A")
        print(f"  最后BBW均线: {status['last_bbw_ma']:.2f}" if status['last_bbw_ma'] else "  最后BBW均线: N/A")

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
