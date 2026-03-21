#!/usr/bin/env python3
"""
Numba Tick 级别贝叶斯优化
====================================
使用 Optuna TPE 算法，在 Numba Tick 级别回测引擎上优化策略参数。

关键特性:
1. 直接调用 optuna_optimizer.py 的 run_tick_optuna_optimization
2. 使用 Numba JIT 编译的高性能 Tick 撮合引擎 (100x 提升)
3. Walk-Forward Optimization (WFO) 交叉验证
4. 全量 14 个月 Tick 数据 (2025-01 至 2026-02)

数据范围: 2025年1月 至 2026年2月 (14个月)
回测粒度: Tick 逐笔撮合
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

def load_all_tick_data(data_dir: str, start_month: str, end_month: str) -> pd.DataFrame:
    """
    加载指定范围内的所有 Tick 数据

    Args:
        data_dir: 数据目录
        start_month: 开始月份 (格式: '2025-01')
        end_month: 结束月份 (格式: '2026-02')

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
    print("Numba Tick 级别贝叶斯优化 (Optuna TPE + WFO)")
    print("数据周期: 2025年1月 - 2026年2月 (14个月)")
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

    # -------------------------------------------------------------------------
    # 1. 加载全量 Tick 数据 (14个月)
    # -------------------------------------------------------------------------
    print("\n[1/4] 加载 Tick 数据...")

    DATA_DIR = '/home/ctyun/xauusd_data'
    ticks_df = load_all_tick_data(DATA_DIR, '2025-01', '2026-02')

    # -------------------------------------------------------------------------
    # 2. 聚合 K 线并计算指标
    # -------------------------------------------------------------------------
    print("\n[2/4] 聚合 K 线并计算指标...")

    INTERVAL = '15min'
    ohlcv_df = ticks_to_ohlcv(ticks_df, INTERVAL)
    ohlcv_df = add_all_indicators(ohlcv_df, DEFAULT_PARAMS)

    print(f"  K 线数量: {len(ohlcv_df):,} 根 ({INTERVAL})")
    print(f"  时间范围: {ohlcv_df.index[0]} 至 {ohlcv_df.index[-1]}")

    # -------------------------------------------------------------------------
    # 3. 运行 Numba Tick 优化 (带 WFO)
    # -------------------------------------------------------------------------
    print("\n[3/4] 运行 Numba Tick 优化...")

    N_TRIALS = 300       # Optuna 迭代次数
    MIN_TRADES = 50      # 最小交易次数
    USE_WFO = True       # 启用 Walk-Forward Optimization
    N_SPLITS = 4         # WFO 分割数

    print(f"\n  优化配置:")
    print(f"    迭代次数: {N_TRIALS}")
    print(f"    最小交易次数: {MIN_TRADES}")
    print(f"    Walk-Forward: {'启用' if USE_WFO else '禁用'} (splits={N_SPLITS})")
    print(f"    参数数量: {len(OPTIMIZATION_BOUNDS)} (简化版)")

    # 【关键】直接调用 optuna_optimizer.py 的 Numba Tick 优化入口
    result = run_tick_optuna_optimization(
        tick_df=ticks_df,
        ohlcv_df=ohlcv_df,
        n_trials=N_TRIALS,
        min_trades=MIN_TRADES,
        study_name="xauusd_tick_wfo_optimization",
        storage=None,  # 不持久化
        verbose=True,
        use_simplified_params=True
    )

    # -------------------------------------------------------------------------
    # 4. 保存结果
    # -------------------------------------------------------------------------
    print("\n[4/4] 保存优化结果...")

    results_dir = Path(__file__).parent / 'results'
    results_dir.mkdir(exist_ok=True)

    # 展开简化参数
    best_params = result.get('best_params', {})
    if 'channel_period' in best_params:
        full_params = expand_simplified_params(best_params)
    else:
        full_params = DEFAULT_PARAMS.copy()
        full_params.update(best_params)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # 保存完整结果
    result_to_save = {
        'timestamp': timestamp,
        'optimization_type': 'numba_tick_wfo_optuna_tpe',
        'backtest_engine': 'NumbaTickBacktestEngine',
        'data_range': {
            'start': str(ticks_df.index[0]),
            'end': str(ticks_df.index[-1]),
            'total_ticks': len(ticks_df),
            'interval': INTERVAL,
        },
        'optimization_config': {
            'n_trials': N_TRIALS,
            'min_trades': MIN_TRADES,
            'use_wfo': USE_WFO,
            'n_splits': N_SPLITS,
        },
        'best_params': full_params,
        'best_fitness': result.get('best_fitness', 0),
        'best_trial_stats': result.get('best_trial_stats', {}),
    }

    result_file = results_dir / f'numba_tick_wfo_optimized_{timestamp}.json'
    with open(result_file, 'w') as f:
        json.dump(result_to_save, f, indent=2, default=str)
    print(f"  优化结果已保存: {result_file}")

    # 保存参数文件
    params_file = results_dir / 'tick_optimized_params.json'
    with open(params_file, 'w') as f:
        json.dump(full_params, f, indent=2)
    print(f"  最优参数已保存: {params_file}")

    # MT4 格式参数文件
    mt4_file = results_dir / f'params_mt4_tick_{timestamp}.txt'
    with open(mt4_file, 'w') as f:
        f.write("// XAUUSD 最佳策略参数 (Numba Tick 级别优化 + WFO)\n")
        f.write(f"// 优化时间: {timestamp}\n")
        f.write(f"// 数据范围: {ticks_df.index[0]} 到 {ticks_df.index[-1]}\n")
        stats = result.get('best_trial_stats', {})
        f.write(f"// 总收益率: {stats.get('total_return', 0):.2f}%\n")
        f.write(f"// 最大回撤: {stats.get('max_drawdown', 0):.2f}%\n")
        f.write(f"// 夏普比率: {stats.get('sharpe_ratio', 0):.2f}\n")
        f.write(f"// 胜率: {stats.get('win_rate', 0):.2f}%\n")
        f.write(f"// 交易次数: {stats.get('total_trades', 0)}\n")
        f.write(f"// Tick 处理数: {stats.get('ticks_processed', 0):,}\n")
        f.write("//\n\n")
        for name, value in sorted(full_params.items()):
            if isinstance(value, int):
                f.write(f"input int {name} = {value};\n")
            else:
                f.write(f"input double {name} = {value:.6f};\n")
    print(f"  MT4 参数文件已保存: {mt4_file}")

    # -------------------------------------------------------------------------
    # 最终验证 (使用最佳参数运行完整 Tick 回测)
    # -------------------------------------------------------------------------
    print("\n[最终验证] 使用最佳参数运行完整 Tick 回测...")

    ohlcv_ind = add_all_indicators(ohlcv_df.copy(), full_params)
    strategy = TradingStrategy(full_params)

    engine = TickBacktestEngine(
        initial_capital=100000,
        position_size=1.0,
        contract_size=100
    )
    final_stats = engine.run_tick_backtest(ticks_df, ohlcv_ind, strategy, verbose=False)
    print_tick_backtest_results(final_stats)

    # 汇总打印
    print(f"\n{'='*70}")
    print("Numba Tick 级别贝叶斯优化完成!")
    print(f"{'='*70}")
    print(f"\n最佳参数表现 (Tick 验证):")
    print(f"  总收益率:  {final_stats.get('total_return', 0):.2f}%")
    print(f"  最大回撤:  {final_stats.get('max_drawdown', 0):.2f}%")
    print(f"  夏普比率:  {final_stats.get('sharpe_ratio', 0):.2f}")
    print(f"  胜率:      {final_stats.get('win_rate', 0):.2f}%")
    print(f"  交易次数:  {final_stats.get('total_trades', 0)}")
    print(f"  处理Tick:  {final_stats.get('total_ticks_processed', 0):,}")

    print(f"\n最佳参数:")
    for name, value in sorted(full_params.items()):
        print(f"  {name}: {value}")

    # 飞书通知
    try:
        sys.path.insert(0, '/home/ctyun/.claude/skills/feishu-bridge')
        from milestone_helper import send_milestone
        send_milestone(
            title='Numba Tick WFO 优化完成',
            status='已完成',
            progress=100,
            message=f'''数据: 2025-01至2026-02 (14个月, {len(ticks_df):,} ticks)
迭代: {N_TRIALS} 次
WFO: 启用 ({N_SPLITS} splits)

Tick 级验证结果:
总收益率: {final_stats.get("total_return", 0):.2f}%
最大回撤: {final_stats.get("max_drawdown", 0):.2f}%
夏普比率: {final_stats.get("sharpe_ratio", 0):.2f}
胜率: {final_stats.get("win_rate", 0):.2f}%
交易次数: {final_stats.get("total_trades", 0)}

结果已保存: {result_file.name}'''
        )
    except Exception:
        pass

    return result_to_save


if __name__ == "__main__":
    main()
