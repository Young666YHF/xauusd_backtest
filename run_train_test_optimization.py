#!/usr/bin/env python3
"""
贝叶斯优化 - 样本外验证版本
====================================
训练数据: 2025年1月-2025年12月 (优化参数)
测试数据: 2026年1月-2026年2月 (样本外验证)

运行流程:
1. 加载2025年数据进行贝叶斯优化
2. 使用最优参数在2026年数据进行回测验证
3. 输出对比结果
"""

import sys
import json
import functools
from pathlib import Path
from datetime import datetime
import warnings

print = functools.partial(print, flush=True)
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from data_loader import load_tick_data_from_csv, ticks_to_ohlcv
from indicators import add_all_indicators
from strategy import TradingStrategy
from tick_engine import TickBacktestEngine, print_tick_backtest_results
from optuna_optimizer import (
    run_tick_optuna_optimization,
    OPTIMIZATION_BOUNDS,
    DEFAULT_PARAMS,
    expand_simplified_params,
    calculate_custom_fitness,
)


# =============================================================================
# 数据加载
# =============================================================================
def load_tick_data_by_range(data_dir: str, start_month: str, end_month: str) -> pd.DataFrame:
    """
    加载指定范围内的所有 Tick 数据

    Args:
        data_dir: 数据目录
        start_month: 开始月份 (格式: '2025-01')
        end_month: 结束月份 (格式: '2025-12')

    Returns:
        合并后的 Tick DataFrame
    """
    data_path = Path(data_dir)

    # 生成月份列表
    start = pd.to_datetime(start_month + '-01')
    end = pd.to_datetime(end_month + '-01')

    months = []
    current = start
    while current <= end:
        months.append(current.strftime('%Y-%m'))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    print(f"\n[数据加载] 计划加载 {len(months)} 个月份的 Tick 数据:")
    print(f"  范围: {months[0]} 至 {months[-1]}")

    all_ticks = []
    total_ticks = 0

    for m in months:
        filename = f'XAUUSD_{m}.csv'
        filepath = data_path / filename

        if not filepath.exists():
            print(f"  ⚠ {filename} 不存在，跳过")
            continue

        print(f"  加载: {filename}", end=' ')
        df_tick = load_tick_data_from_csv(str(filepath))

        if len(df_tick) > 0:
            all_ticks.append(df_tick)
            total_ticks += len(df_tick)
            print(f"✓ {len(df_tick):,} ticks")
        else:
            print("✗ 空数据")

    if not all_ticks:
        raise ValueError(f"未找到任何 Tick 数据! 请检查数据目录: {data_dir}")

    # 合并并去重
    ticks_df = pd.concat(all_ticks).sort_index()
    ticks_df = ticks_df[~ticks_df.index.duplicated(keep='first')]

    print(f"\n  总计: {len(ticks_df):,} ticks")
    print(f"  时间范围: {ticks_df.index[0]} 至 {ticks_df.index[-1]}")

    return ticks_df


# =============================================================================
# 主函数
# =============================================================================
def main():
    print("=" * 70)
    print("贝叶斯优化 - 样本外验证版本")
    print("训练数据: 2025年1月 - 2025年12月 (12个月)")
    print("测试数据: 2026年1月 - 2026年2月 (2个月)")
    print("回测粒度: Tick 逐笔撮合")
    print("=" * 70)

    # 检查 optuna 是否安装
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        print(f"Optuna 版本: {optuna.__version__}")
    except ImportError:
        print("请先安装 optuna: pip install optuna")
        sys.exit(1)

    DATA_DIR = '/home/ctyun/xauusd_data'
    INTERVAL = '15min'
    N_TRIALS = 300       # Optuna 迭代次数
    MIN_TRADES = 50      # 最小交易次数

    # -------------------------------------------------------------------------
    # 1. 加载训练数据 (2025年1月-12月)
    # -------------------------------------------------------------------------
    print("\n[1/5] 加载训练数据 (2025年1月-12月)...")

    train_ticks_df = load_tick_data_by_range(DATA_DIR, '2025-01', '2025-12')

    # 聚合 K 线并计算指标
    print("\n[2/5] 聚合 K 线并计算指标...")
    train_ohlcv_df = ticks_to_ohlcv(train_ticks_df, INTERVAL)
    train_ohlcv_df = add_all_indicators(train_ohlcv_df, DEFAULT_PARAMS)

    print(f"  K 线数量: {len(train_ohlcv_df):,} 根 ({INTERVAL})")
    print(f"  时间范围: {train_ohlcv_df.index[0]} 至 {train_ohlcv_df.index[-1]}")

    # -------------------------------------------------------------------------
    # 2. 运行贝叶斯优化 (在训练数据上)
    # -------------------------------------------------------------------------
    print("\n[3/5] 运行贝叶斯优化 (训练数据)...")

    print(f"\n  优化配置:")
    print(f"    迭代次数: {N_TRIALS}")
    print(f"    最小交易次数: {MIN_TRADES}")
    print(f"    参数数量: {len(OPTIMIZATION_BOUNDS)} (简化版)")

    result = run_tick_optuna_optimization(
        tick_df=train_ticks_df,
        ohlcv_df=train_ohlcv_df,
        n_trials=N_TRIALS,
        min_trades=MIN_TRADES,
        study_name="xauusd_train_2025",
        storage=None,  # 不持久化
        verbose=True,
        use_simplified_params=True
    )

    # -------------------------------------------------------------------------
    # 3. 加载测试数据 (2026年1月-2月)
    # -------------------------------------------------------------------------
    print("\n[4/5] 加载测试数据 (2026年1月-2月)...")

    test_ticks_df = load_tick_data_by_range(DATA_DIR, '2026-01', '2026-02')

    # 聚合 K 线并计算指标
    test_ohlcv_df = ticks_to_ohlcv(test_ticks_df, INTERVAL)

    print(f"  K 线数量: {len(test_ohlcv_df):,} 根 ({INTERVAL})")
    print(f"  时间范围: {test_ohlcv_df.index[0]} 至 {test_ohlcv_df.index[-1]}")

    # -------------------------------------------------------------------------
    # 4. 样本外验证 (使用最优参数在测试数据上回测)
    # -------------------------------------------------------------------------
    print("\n[5/5] 样本外验证...")

    # 展开简化参数
    best_params = result.get('best_params', {})
    if 'channel_period' in best_params:
        full_params = expand_simplified_params(best_params)
    else:
        full_params = DEFAULT_PARAMS.copy()
        full_params.update(best_params)

    # 在测试数据上计算指标
    test_ohlcv_ind = add_all_indicators(test_ohlcv_df.copy(), full_params)

    # 创建策略实例
    strategy = TradingStrategy(full_params)

    # 运行回测
    engine = TickBacktestEngine(
        initial_capital=100000,
        position_size=1.0,
        contract_size=100
    )

    print("\n" + "=" * 70)
    print("样本外验证结果 (2026年1月-2月)")
    print("=" * 70)

    test_stats = engine.run_tick_backtest(test_ticks_df, test_ohlcv_ind, strategy, verbose=True)
    print_tick_backtest_results(test_stats)

    # -------------------------------------------------------------------------
    # 5. 保存结果
    # -------------------------------------------------------------------------
    print("\n[保存结果]")

    results_dir = Path(__file__).parent / 'results'
    results_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # 保存完整结果
    result_to_save = {
        'timestamp': timestamp,
        'optimization_type': 'train_test_split_optuna_tpe',
        'backtest_engine': 'NumbaTickBacktestEngine',
        'train_data': {
            'range': '2025-01 to 2025-12',
            'total_ticks': len(train_ticks_df),
            'total_bars': len(train_ohlcv_df),
            'interval': INTERVAL,
        },
        'test_data': {
            'range': '2026-01 to 2026-02',
            'total_ticks': len(test_ticks_df),
            'total_bars': len(test_ohlcv_df),
        },
        'optimization_config': {
            'n_trials': N_TRIALS,
            'min_trades': MIN_TRADES,
        },
        'best_params': full_params,
        'train_result': {
            'best_fitness': result.get('best_fitness', 0),
            'best_trial_stats': result.get('best_trial_stats', {}),
        },
        'test_result': {
            'total_return': test_stats.get('total_return', 0),
            'max_drawdown': test_stats.get('max_drawdown', 0),
            'sharpe_ratio': test_stats.get('sharpe_ratio', 0),
            'win_rate': test_stats.get('win_rate', 0),
            'total_trades': test_stats.get('total_trades', 0),
            'total_pnl': test_stats.get('total_pnl', 0),
        },
    }

    result_file = results_dir / f'train_test_optimized_{timestamp}.json'
    with open(result_file, 'w') as f:
        json.dump(result_to_save, f, indent=2, default=str)
    print(f"  优化结果已保存: {result_file}")

    # 保存参数文件
    params_file = results_dir / 'train_test_optimized_params.json'
    with open(params_file, 'w') as f:
        json.dump(full_params, f, indent=2)
    print(f"  最优参数已保存: {params_file}")

    # MT4 格式参数文件
    mt4_file = results_dir / f'params_mt4_train_test_{timestamp}.txt'
    with open(mt4_file, 'w') as f:
        f.write("// XAUUSD 最佳策略参数 (训练-测试分离优化)\n")
        f.write(f"// 优化时间: {timestamp}\n")
        f.write(f"// 训练数据: 2025-01 到 2025-12\n")
        f.write(f"// 测试数据: 2026-01 到 2026-02\n")
        train_stats = result.get('best_trial_stats', {})
        f.write(f"// === 训练期表现 ===\n")
        f.write(f"// 总收益率: {train_stats.get('total_return', 0):.2f}%\n")
        f.write(f"// 最大回撤: {train_stats.get('max_drawdown', 0):.2f}%\n")
        f.write(f"// 夏普比率: {train_stats.get('sharpe_ratio', 0):.2f}\n")
        f.write(f"// 胜率: {train_stats.get('win_rate', 0):.2f}%\n")
        f.write(f"// 交易次数: {train_stats.get('total_trades', 0)}\n")
        f.write(f"// === 测试期表现 (样本外) ===\n")
        f.write(f"// 总收益率: {test_stats.get('total_return', 0):.2f}%\n")
        f.write(f"// 最大回撤: {test_stats.get('max_drawdown', 0):.2f}%\n")
        f.write(f"// 夏普比率: {test_stats.get('sharpe_ratio', 0):.2f}\n")
        f.write(f"// 胜率: {test_stats.get('win_rate', 0):.2f}%\n")
        f.write(f"// 交易次数: {test_stats.get('total_trades', 0)}\n")
        f.write("//\n\n")
        for name, value in sorted(full_params.items()):
            if isinstance(value, int):
                f.write(f"input int {name} = {value};\n")
            else:
                f.write(f"input double {name} = {value:.6f};\n")
    print(f"  MT4 参数文件已保存: {mt4_file}")

    # -------------------------------------------------------------------------
    # 汇总打印
    # -------------------------------------------------------------------------
    print(f"\n{'='*70}")
    print("优化完成! 结果对比:")
    print(f"{'='*70}")

    print(f"\n{'指标':<20} {'训练期 (2025)':<20} {'测试期 (2026)':<20}")
    print("-" * 60)
    print(f"{'总收益率':<20} {train_stats.get('total_return', 0):>18.2f}% {test_stats.get('total_return', 0):>18.2f}%")
    print(f"{'最大回撤':<20} {train_stats.get('max_drawdown', 0):>18.2f}% {test_stats.get('max_drawdown', 0):>18.2f}%")
    print(f"{'夏普比率':<20} {train_stats.get('sharpe_ratio', 0):>18.2f} {test_stats.get('sharpe_ratio', 0):>18.2f}")
    print(f"{'胜率':<20} {train_stats.get('win_rate', 0):>18.2f}% {test_stats.get('win_rate', 0):>18.2f}%")
    print(f"{'交易次数':<20} {train_stats.get('total_trades', 0):>18} {test_stats.get('total_trades', 0):>18}")

    print(f"\n最佳参数:")
    for name, value in sorted(full_params.items()):
        print(f"  {name}: {value}")

    # 飞书通知
    try:
        sys.path.insert(0, '/home/ctyun/.claude/skills/feishu-bridge')
        from milestone_helper import send_milestone
        send_milestone(
            title='贝叶斯优化完成 (训练-测试分离)',
            status='已完成',
            progress=100,
            message=f'''训练数据: 2025-01至2025-12 ({len(train_ticks_df):,} ticks)
测试数据: 2026-01至2026-02 ({len(test_ticks_df):,} ticks)
迭代次数: {N_TRIALS}

训练期表现:
收益率: {train_stats.get("total_return", 0):.2f}%
回撤: {train_stats.get("max_drawdown", 0):.2f}%
夏普: {train_stats.get("sharpe_ratio", 0):.2f}

测试期表现 (样本外):
收益率: {test_stats.get("total_return", 0):.2f}%
回撤: {test_stats.get("max_drawdown", 0):.2f}%
夏普: {test_stats.get("sharpe_ratio", 0):.2f}

结果已保存: {result_file.name}'''
        )
    except Exception as e:
        print(f"  飞书通知发送失败: {e}")

    return result_to_save


if __name__ == "__main__":
    main()
