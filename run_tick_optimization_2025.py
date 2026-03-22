#!/usr/bin/env python3
"""
Tick级别贝叶斯优化 + 样本外回测
========================================
- 优化数据: 2025年1月-12月 (全年)
- 回测数据: 2026年1月-2月 (样本外)

使用 Numba JIT 加速的 Tick 级回测引擎
"""

import os
import sys
import warnings
import time
from datetime import datetime

warnings.filterwarnings('ignore')

# 强制刷新输出
import functools
print = functools.partial(print, flush=True)

# 确保当前目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np

# 导入自定义模块
from data_loader import load_tick_data_from_csv, ticks_to_ohlcv
from indicators import add_all_indicators
from strategy import TradingStrategy
from tick_engine import EnhancedTickBacktestEngine, prepare_tick_data, prepare_bar_stats
from optuna_optimizer import (
    OPTIMIZATION_BOUNDS,
    expand_simplified_params,
    calculate_custom_fitness,
    DEFAULT_PARAMS
)
from config import SPREAD_PER_OUNCE

# =============================================================================
# 配置
# =============================================================================
DATA_DIR = '/home/ctyun/xauusd_data'
INTERVAL = '15min'
N_TRIALS = 200  # Optuna 优化次数（增加到200次以更好探索参数空间）
MIN_TRADES = 100  # 最小交易次数阈值

# 数据范围
TRAIN_MONTHS = [  # 优化数据 (2025全年)
    '2025-01', '2025-02', '2025-03', '2025-04', '2025-05', '2025-06',
    '2025-07', '2025-08', '2025-09', '2025-10', '2025-11', '2025-12'
]

TEST_MONTHS = [  # 回测数据 (2026年)
    '2026-01', '2026-02'
]


def load_tick_data_for_months(months: list) -> pd.DataFrame:
    """加载多个月的 tick 数据"""
    dfs = []
    for month_str in months:
        year, month = map(int, month_str.split('-'))
        filename = f"XAUUSD_{year}-{month:02d}.csv"
        filepath = os.path.join(DATA_DIR, filename)

        if not os.path.exists(filepath):
            print(f"⚠️ 文件不存在: {filepath}")
            continue

        print(f"加载 {month_str}...")
        tick_df = load_tick_data_from_csv(filepath)
        dfs.append(tick_df)
        print(f"  Tick数: {len(tick_df):,}")

    if not dfs:
        raise ValueError("未找到任何数据文件")

    combined = pd.concat(dfs)
    combined = combined.sort_index()
    combined = combined[~combined.index.duplicated(keep='first')]

    return combined


def load_ohlcv_for_months(months: list, interval: str = '15min') -> pd.DataFrame:
    """加载多个月的 OHLCV 数据"""
    dfs = []
    for month_str in months:
        year, month = map(int, month_str.split('-'))
        filename = f"XAUUSD_{year}-{month:02d}.csv"
        filepath = os.path.join(DATA_DIR, filename)

        if not os.path.exists(filepath):
            print(f"⚠️ 文件不存在: {filepath}")
            continue

        print(f"加载 {month_str}...")
        tick_df = load_tick_data_from_csv(filepath)
        ohlcv = ticks_to_ohlcv(tick_df, interval)
        dfs.append(ohlcv)
        print(f"  K线数: {len(ohlcv):,}")

    if not dfs:
        raise ValueError("未找到任何数据文件")

    combined = pd.concat(dfs)
    combined = combined.sort_index()
    combined = combined[~combined.index.duplicated(keep='first')]

    return combined


def create_tick_optuna_objective(
    tick_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    min_trades: int = 100
):
    """创建 Tick 级别的 Optuna 目标函数"""
    from tick_engine import NUMBA_AVAILABLE

    print(f"\n{'='*60}")
    print("预序列化 Tick 数据...")
    print(f"{'='*60}")

    # 计算 OHLCV 的指标
    ohlcv_with_indicators = add_all_indicators(ohlcv_df.copy(), DEFAULT_PARAMS)

    # 预序列化数据
    ticks_array = prepare_tick_data(tick_df, ohlcv_with_indicators, INTERVAL, SPREAD_PER_OUNCE)
    bar_stats = prepare_bar_stats(ohlcv_with_indicators)

    print(f"Tick 数据序列化完成: {len(ticks_array):,} ticks")
    print(f"K 线统计序列化完成: {len(bar_stats):,} bars")
    if NUMBA_AVAILABLE:
        print("✅ Numba JIT 已启用")
    else:
        print("⚠️ Numba 未安装，使用纯 Python 模式")

    def objective(trial) -> float:
        """Optuna 目标函数"""
        # 1. 参数采样（简化版）
        simplified_params = {}
        for param_name, (low, high) in OPTIMIZATION_BOUNDS.items():
            if isinstance(low, int) and isinstance(high, int):
                simplified_params[param_name] = trial.suggest_int(param_name, low, high)
            else:
                simplified_params[param_name] = trial.suggest_float(param_name, low, high)

        params = expand_simplified_params(simplified_params)

        # 2. 参数约束检查
        if params['ema_fast'] >= params['ema_slow']:
            return -1e6
        if params['rsi_oversold'] >= params['rsi_overbought']:
            return -1e6

        # 3. 计算指标
        df_ind = add_all_indicators(ohlcv_df.copy(), params)

        # 4. 生成信号
        strategy = TradingStrategy(params)
        signals = strategy.generate_signals(df_ind)

        if len(signals) == 0:
            return -1e6

        # 5. 运行 Tick 回测
        from tick_engine import prepare_signals

        signals_array = prepare_signals(signals, df_ind)

        # 创建临时引擎
        engine = EnhancedTickBacktestEngine(
            initial_capital=100000,
            position_size=1.0,
            contract_size=100,
            enable_news_filter=True
        )
        engine._cached_ticks_array = ticks_array
        engine._cached_bar_stats = bar_stats
        engine._cache_key = "pre_serialized"

        max_hold_bars_a = params.get('max_hold_bars_a', 5)
        trailing_mult_b = params.get('trailing_stop_atr_mult', 4.89)

        from tick_engine import enhanced_tick_matcher, COMMISSION_PER_LOT, DEFAULT_LEVERAGE, MARGIN_CALL_RATIO

        # 【零摩擦基准测试】使用零佣金
        trades_record, equity_curve, total_trades, winning_trades, total_ticks, margin_calls = enhanced_tick_matcher(
            ticks_array,
            signals_array,
            bar_stats,
            100000.0,  # initial_capital
            100.0,     # contract_size
            max_hold_bars_a,
            trailing_mult_b,
            1.0,       # position_size
            0.0,       # 【零摩擦】commission_per_lot: 3.5 -> 0
            DEFAULT_LEVERAGE,
            MARGIN_CALL_RATIO
        )

        # 6. 计算统计
        if total_trades == 0:
            return -1e6

        pnls = trades_record[:, 5]  # TRADE_PNL
        total_pnl = np.sum(pnls)
        total_return = (equity_curve[-1] - 100000) / 100000 * 100
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0

        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        avg_win = np.mean(wins) if len(wins) > 0 else 0
        avg_loss = abs(np.mean(losses)) if len(losses) > 0 else 0
        profit_factor = np.sum(wins) / abs(np.sum(losses)) if np.sum(losses) != 0 else float('inf')

        rolling_max = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - rolling_max) / rolling_max * 100
        max_drawdown = abs(np.min(drawdown)) if len(drawdown) > 0 else 0

        if len(equity_curve) > 1:
            returns = np.diff(equity_curve) / equity_curve[:-1]
            if np.std(returns) > 0:
                sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252 * 24 * 4)
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0

        stats = {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': total_trades - winning_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
        }

        # 7. 计算适应度
        fitness = calculate_custom_fitness(stats, min_trades, verbose=False, spread_per_ounce=SPREAD_PER_OUNCE)

        # 记录属性
        trial.set_user_attr('total_trades', total_trades)
        trial.set_user_attr('total_return', total_return)
        trial.set_user_attr('max_drawdown', max_drawdown)
        trial.set_user_attr('win_rate', win_rate)
        trial.set_user_attr('sharpe_ratio', sharpe_ratio)
        trial.set_user_attr('profit_factor', profit_factor)

        return fitness

    return objective


def run_optimization():
    """运行优化流程"""
    try:
        import optuna
    except ImportError:
        raise ImportError("请先安装 optuna: pip install optuna")

    print("\n" + "="*70)
    print("Tick 级别贝叶斯优化")
    print("="*70)
    print(f"优化数据: 2025年1月-12月")
    print(f"回测数据: 2026年1月-2月")
    print(f"优化次数: {N_TRIALS}")
    print(f"最小交易数: {MIN_TRADES}")
    print(f"点差: ${SPREAD_PER_OUNCE}/盎司")
    print("="*70 + "\n")

    # ========================
    # 1. 加载训练数据
    # ========================
    print("【步骤1】加载训练数据 (2025年)")
    print("-"*40)

    train_tick_df = load_tick_data_for_months(TRAIN_MONTHS)
    train_ohlcv_df = load_ohlcv_for_months(TRAIN_MONTHS, INTERVAL)

    print(f"\n训练数据统计:")
    print(f"  Tick数: {len(train_tick_df):,}")
    print(f"  K线数: {len(train_ohlcv_df):,}")
    print(f"  时间范围: {train_ohlcv_df.index[0]} 到 {train_ohlcv_df.index[-1]}")

    # ========================
    # 2. 运行 Optuna 优化
    # ========================
    print(f"\n【步骤2】运行 Optuna TPE 优化 ({N_TRIALS} trials)")
    print("-"*40)

    start_time = time.time()

    # 创建目标函数
    objective = create_tick_optuna_objective(train_tick_df, train_ohlcv_df, MIN_TRADES)

    # 创建研究
    study = optuna.create_study(
        direction='maximize',
        sampler=optuna.samplers.TPESampler(seed=42, n_startup_trials=max(30, N_TRIALS // 10)),
        pruner=optuna.pruners.MedianPruner()
    )

    # 运行优化
    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=True)

    elapsed = time.time() - start_time

    # 输出优化结果
    print(f"\n{'='*70}")
    print("优化完成!")
    print(f"耗时: {elapsed:.1f} 秒 ({elapsed/60:.1f} 分钟)")
    print(f"最佳适应度: {study.best_value:.4f}")
    print(f"{'='*70}")

    print(f"\n最佳参数:")
    best_params = expand_simplified_params(study.best_params)
    for name, value in best_params.items():
        if isinstance(value, float):
            print(f"  {name}: {value:.4f}")
        else:
            print(f"  {name}: {value}")

    best_trial = study.best_trial
    print(f"\n最佳试验统计:")
    print(f"  交易次数: {best_trial.user_attrs.get('total_trades', 'N/A')}")
    print(f"  总收益: {best_trial.user_attrs.get('total_return', 0):.2f}%")
    print(f"  最大回撤: {best_trial.user_attrs.get('max_drawdown', 0):.2f}%")
    print(f"  胜率: {best_trial.user_attrs.get('win_rate', 0):.2f}%")
    print(f"  夏普比率: {best_trial.user_attrs.get('sharpe_ratio', 0):.4f}")
    print(f"  盈亏比: {best_trial.user_attrs.get('profit_factor', 0):.4f}")

    return best_params, study


def run_backtest(best_params: dict):
    """运行样本外回测"""
    print(f"\n{'='*70}")
    print("【步骤3】样本外回测 (2026年)")
    print("="*70)

    # 加载测试数据
    print("\n加载测试数据...")
    test_tick_df = load_tick_data_for_months(TEST_MONTHS)
    test_ohlcv_df = load_ohlcv_for_months(TEST_MONTHS, INTERVAL)

    print(f"\n测试数据统计:")
    print(f"  Tick数: {len(test_tick_df):,}")
    print(f"  K线数: {len(test_ohlcv_df):,}")
    print(f"  时间范围: {test_ohlcv_df.index[0]} 到 {test_ohlcv_df.index[-1]}")

    # 计算指标
    print("\n计算指标...")
    df_ind = add_all_indicators(test_ohlcv_df.copy(), best_params)

    # 生成信号
    print("生成交易信号...")
    strategy = TradingStrategy(best_params)
    signals = strategy.generate_signals(df_ind)

    print(f"生成信号数: {len(signals)}")

    if len(signals) == 0:
        print("⚠️ 未生成任何交易信号!")
        return None

    # 准备数据
    print("\n准备 Tick 数据...")
    ticks_array = prepare_tick_data(test_tick_df, df_ind, INTERVAL, SPREAD_PER_OUNCE)
    bar_stats = prepare_bar_stats(df_ind)

    from tick_engine import prepare_signals, enhanced_tick_matcher, COMMISSION_PER_LOT, DEFAULT_LEVERAGE, MARGIN_CALL_RATIO

    signals_array = prepare_signals(signals, df_ind)

    # 运行回测
    print("运行 Tick 级回测...")
    start_time = time.time()

    max_hold_bars_a = best_params.get('max_hold_bars_a', 5)
    trailing_mult_b = best_params.get('trailing_stop_atr_mult', 4.89)

    trades_record, equity_curve, total_trades, winning_trades, total_ticks, margin_calls = enhanced_tick_matcher(
        ticks_array,
        signals_array,
        bar_stats,
        100000.0,
        100.0,
        max_hold_bars_a,
        trailing_mult_b,
        1.0,
        0.0,       # 【零摩擦】commission_per_lot: 3.5 -> 0
        DEFAULT_LEVERAGE,
        MARGIN_CALL_RATIO
    )

    elapsed = time.time() - start_time

    # 计算统计
    if total_trades == 0:
        print("⚠️ 回测期间无交易!")
        return None

    pnls = trades_record[:, 5]
    total_pnl = np.sum(pnls)
    total_return = (equity_curve[-1] - 100000) / 100000 * 100
    win_rate = winning_trades / total_trades * 100

    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    avg_win = np.mean(wins) if len(wins) > 0 else 0
    avg_loss = abs(np.mean(losses)) if len(losses) > 0 else 0
    profit_factor = np.sum(wins) / abs(np.sum(losses)) if np.sum(losses) != 0 else float('inf')

    rolling_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - rolling_max) / rolling_max * 100
    max_drawdown = abs(np.min(drawdown))

    if len(equity_curve) > 1:
        returns = np.diff(equity_curve) / equity_curve[:-1]
        if np.std(returns) > 0:
            sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252 * 24 * 4)
        else:
            sharpe_ratio = 0
    else:
        sharpe_ratio = 0

    # Calmar 比率
    if max_drawdown > 0:
        # 计算年化收益
        days = (test_ohlcv_df.index[-1] - test_ohlcv_df.index[0]).days
        annual_return = total_return * (260 / max(days, 1)) if days > 0 else total_return
        calmar_ratio = annual_return / max_drawdown
    else:
        calmar_ratio = float('inf')

    # 输出结果
    print(f"\n{'='*70}")
    print("样本外回测结果 (2026年)")
    print(f"{'='*70}")
    print(f"处理 Tick 数: {total_ticks:,}")
    print(f"执行时间: {elapsed:.2f} 秒")
    print(f"{'='*70}")
    print(f"{'总交易次数':^20}: {total_trades}")
    print(f"{'盈利交易':^20}: {winning_trades}")
    print(f"{'亏损交易':^20}: {total_trades - winning_trades}")
    print(f"{'胜率':^20}: {win_rate:.2f}%")
    print(f"{'-'*70}")
    print(f"{'总收益':^20}: {total_return:.2f}%")
    print(f"{'总盈亏':^20}: ${total_pnl:.2f}")
    print(f"{'最大回撤':^20}: {max_drawdown:.2f}%")
    print(f"{'-'*70}")
    print(f"{'夏普比率':^20}: {sharpe_ratio:.4f}")
    print(f"{'Calmar比率':^20}: {calmar_ratio:.4f}")
    print(f"{'盈亏比':^20}: {profit_factor:.4f}")
    print(f"{'平均盈利':^20}: ${avg_win:.2f}")
    print(f"{'平均亏损':^20}: ${avg_loss:.2f}")
    print(f"{'爆仓次数':^20}: {margin_calls}")
    print(f"{'='*70}")

    return {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'win_rate': win_rate,
        'total_return': total_return,
        'total_pnl': total_pnl,
        'max_drawdown': max_drawdown,
        'sharpe_ratio': sharpe_ratio,
        'calmar_ratio': calmar_ratio,
        'profit_factor': profit_factor,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'margin_calls': margin_calls,
    }


def main():
    """主函数"""
    print("\n" + "#"*70)
    print("#" + " "*68 + "#")
    print("#" + "  XAUUSD Tick 级别贝叶斯优化 + 样本外回测  ".center(68) + "#")
    print("#" + " "*68 + "#")
    print("#"*70)

    # 运行优化
    best_params, study = run_optimization()

    # 运行样本外回测
    backtest_results = run_backtest(best_params)

    # 保存结果
    if backtest_results:
        import json
        from datetime import datetime

        results = {
            'timestamp': datetime.now().isoformat(),
            'optimization': {
                'n_trials': N_TRIALS,
                'best_fitness': study.best_value,
                'best_params': best_params,
            },
            'backtest': backtest_results,
        }

        # 保存到文件
        output_file = f"optimization_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        print(f"\n结果已保存到: {output_file}")

        # 发送飞书通知
        try:
            import sys
            sys.path.insert(0, '/home/ctyun/.claude/skills/feishu-bridge')
            from milestone_helper import send_milestone

            send_milestone(
                title='Tick级贝叶斯优化完成',
                status='已完成',
                progress=100,
                message=f'''
【优化数据】2025年1-12月 ({N_TRIALS} trials)
【回测数据】2026年1-2月

【最佳参数】
- BB周期: {best_params.get('bb_period')}
- EMA快/慢: {best_params.get('ema_fast')}/{best_params.get('ema_slow')}
- 止损ATR倍数: A={best_params.get('stop_loss_atr_mult_a'):.2f}, B={best_params.get('stop_loss_atr_mult_b'):.2f}

【样本外表现】
- 总收益: {backtest_results['total_return']:.2f}%
- 最大回撤: {backtest_results['max_drawdown']:.2f}%
- 夏普比率: {backtest_results['sharpe_ratio']:.4f}
- 交易次数: {backtest_results['total_trades']}
- 胜率: {backtest_results['win_rate']:.2f}%
'''
            )
        except Exception as e:
            print(f"飞书通知失败: {e}")


if __name__ == "__main__":
    main()
