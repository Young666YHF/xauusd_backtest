#!/usr/bin/env python3
"""
回测运行脚本
============
统一的回测入口，支持多种策略和引擎

用法：
    python run_backtest.py --strategy mean_reversion --start-date 2025-01-01 --end-date 2025-06-30
    python run_backtest.py --strategy momentum_breakout --engine tick --tick-data /path/to/ticks.csv
"""

import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from core.config import Config, get_config
from core.indicators import add_all_indicators
from core.data_loader import DataLoader
from core.risk_manager import RiskManager
from strategies import StrategyRegistry
from engines import CandleBacktestEngine, TickBacktestEngine


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='XAUUSD Backtest System')

    # 策略选择
    parser.add_argument('--strategy', type=str, required=True,
                        choices=StrategyRegistry.list_strategies(),
                        help='Strategy to use')

    # 时间范围
    parser.add_argument('--start-date', type=str, required=True,
                        help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True,
                        help='End date (YYYY-MM-DD)')

    # 引擎选择
    parser.add_argument('--engine', type=str, default='candle',
                        choices=['candle', 'tick'],
                        help='Backtest engine type')

    # Tick数据（如果使用tick引擎）
    parser.add_argument('--tick-data', type=str,
                        help='Tick data file path (required for tick engine)')

    # 配置文件
    parser.add_argument('--config', type=str,
                        help='Config file path')

    # 参数覆盖
    parser.add_argument('--params', type=str,
                        help='Strategy parameters as JSON string')

    # 输出
    parser.add_argument('--output', type=str,
                        help='Output file path for results')

    # 详细输出
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')

    return parser.parse_args()


def load_config(args) -> Config:
    """加载配置"""
    if args.config:
        return Config.from_file(args.config)
    return get_config()


def load_data(config: Config, args) -> pd.DataFrame:
    """加载数据"""
    loader = DataLoader(config.data.data_dir)

    # 计算需要的月份
    start = datetime.strptime(args.start_date, '%Y-%m-%d')
    end = datetime.strptime(args.end_date, '%Y-%m-%d')

    months = []
    current = start
    while current <= end:
        months.append(current.strftime('%Y-%m'))
        # 增加一个月
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    print(f"Loading data for {len(months)} months...")
    df = loader.load_range(months, config.data.interval)

    # 过滤日期范围
    df = df[(df.index >= args.start_date) & (df.index <= args.end_date)]

    print(f"Loaded {len(df)} bars")
    return df


def add_indicators(df: pd.DataFrame, config: Config, strategy) -> pd.DataFrame:
    """添加技术指标"""
    print("Calculating indicators...")

    # 先添加通用指标
    params = config.strategy.to_dict()
    df = add_all_indicators(
        df,
        bb_period=params.get('bb_period', 20),
        bb_std=params.get('bb_std', 2.0),
        kc_period=params.get('kc_period', 20),
        kc_atr_mult=params.get('kc_atr_mult', 1.5),
        atr_period=params.get('atr_period', 14),
        rsi_period=params.get('rsi_period', 14),
        ema_fast=params.get('ema_fast', 20),
        ema_slow=params.get('ema_slow', 50),
        vwap_reset_hour=config.data.vwap_reset_hour_et
    )

    # 再调用策略特有的指标准备
    df = strategy.prepare_indicators(df)

    return df


def create_engine(config: Config, args):
    """创建回测引擎"""
    from core.config import TradingConfig

    trading_config = config.trading

    # 创建风控管理器
    risk_manager = RiskManager(config=trading_config)

    if args.engine == 'tick':
        return TickBacktestEngine(trading_config, risk_manager=risk_manager)
    else:
        return CandleBacktestEngine(trading_config, risk_manager=risk_manager)


def run_backtest(args):
    """运行回测"""
    print(f"\n{'='*60}")
    print(f"XAUUSD Backtest - {args.strategy}")
    print(f"{'='*60}\n")

    # 加载配置
    config = load_config(args)

    # 加载数据
    df = load_data(config, args)

    # 创建策略（先创建策略实例，以便调用策略特有的指标准备方法）
    strategy_params = config.strategy.to_dict()
    if args.params:
        import json
        override_params = json.loads(args.params)
        strategy_params.update(override_params)

    strategy = StrategyRegistry.create(args.strategy, strategy_params)

    # 添加指标（使用策略的 prepare_indicators 方法）
    df = add_indicators(df, config, strategy)
    print(f"\nStrategy: {strategy.strategy_id}")
    print(f"Parameters: {strategy_params}\n")

    # 创建引擎
    engine = create_engine(config, args)
    print(f"Engine: {args.engine}\n")

    # 加载Tick数据（如果需要）
    tick_df = None
    if args.engine == 'tick' and args.tick_data:
        tick_df = DataLoader(config.data.data_dir).load_tick_data(args.tick_data)
        print(f"Loaded tick data: {len(tick_df)} ticks\n")

    # 运行回测
    print("Running backtest...")
    result = engine.run_with_strategy(df, strategy, tick_df=tick_df)

    # 输出结果
    print(f"\n{'='*60}")
    print("Backtest Results")
    print(f"{'='*60}\n")

    print(f"Total Trades:     {result.total_trades}")
    print(f"Winning Trades:   {result.winning_trades}")
    print(f"Losing Trades:    {result.losing_trades}")
    print(f"Win Rate:         {result.win_rate:.2%}")
    print(f"\nTotal P&L:        ${result.total_pnl:,.2f}")
    print(f"Total Return:     {result.total_return:.2%}")
    print(f"\nMax Drawdown:     {result.max_drawdown_pct:.2%}")
    print(f"Sharpe Ratio:     {result.sharpe_ratio:.2f}")
    print(f"Profit Factor:    {result.profit_factor:.2f}")

    # 保存结果
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        result_data = {
            'config': config.to_dict(),
            'results': result.to_dict(),
            'trades': [
                {
                    'entry_time': t.entry_time.isoformat(),
                    'exit_time': t.exit_time.isoformat(),
                    'direction': 'long' if t.direction.value > 0 else 'short',
                    'size': t.size,
                    'entry_price': t.entry_price,
                    'exit_price': t.exit_price,
                    'pnl': t.pnl,
                    'pnl_pct': t.pnl_pct,
                    'exit_reason': t.exit_reason.name,
                    'bars_held': t.bars_held
                }
                for t in result.trades
            ]
        }

        import json
        with open(output_path, 'w') as f:
            json.dump(result_data, f, indent=2)

        print(f"\nResults saved to: {output_path}")

    return result


def main():
    """主函数"""
    args = parse_args()

    try:
        result = run_backtest(args)
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
