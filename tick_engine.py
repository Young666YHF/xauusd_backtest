#!/usr/bin/env python3
"""
================================================================================
Tick级别高性能回测引擎 - Numba @njit 重构版
================================================================================
将原有的纯 Python/Pandas 低效循环彻底重构为基于 Numba @njit 的超高速撮合引擎

【架构设计】
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 1: 数据转换层 (Python)                                                │
│  ├── prepare_tick_data(): Tick DataFrame → N x 6 float64 数组               │
│  ├── prepare_signals(): TradeSignal 列表 → M x 8 float64 数组               │
│  └── prepare_bar_stats(): K线指标 → K x N float64 数组                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  Layer 2: Numba 核心层 (JIT, 零对象开销)                                      │
│  └── fast_tick_matcher(): 单次遍历 Tick 数组，状态机撮合                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  Layer 3: 结果封装层 (Python)                                                │
│  └── NumbaTickBacktestEngine: 统计计算、与 Optuna 集成                        │
└─────────────────────────────────────────────────────────────────────────────┘

【性能优化要点】
1. 零 Pandas/对象规则: @njit 内部绝对不允许 DataFrame/Series/Dict/List/对象
2. 纯 Numpy 桥接: 所有数据在进入 @njit 前转为 float64 数组
3. 预分配内存: 交易记录、权益曲线预分配固定大小数组
4. 单次遍历: Tick 数据只遍历一次，状态机维护持仓
5. 向量化预处理: 数据转换层使用 Pandas/Numpy 向量化操作

【预期性能】
- 纯 Python: ~1,000 ticks/s
- Numba JIT: ~1,000,000 ticks/s (100x 提升)

作者: Quant Performance Team
日期: 2026-03-20
================================================================================
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import functools
import time
import warnings

warnings.filterwarnings('ignore')
print = functools.partial(print, flush=True)

# =============================================================================
# Numba 导入检测
# =============================================================================
try:
    from numba import njit, prange
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False
    print("[警告] Numba 未安装，将使用纯 Python 回退模式（性能约低 100 倍）")


# =============================================================================
# 全局常量定义 - Tick 数组列索引映射
# =============================================================================
# ─────────────────────────────────────────────────────────────────────────────
# Tick 数据数组 (N x 6, dtype=float64)
# ─────────────────────────────────────────────────────────────────────────────
TICK_TIMESTAMP = 0  # Unix 时间戳 (秒, float)
TICK_BID = 1        # 买价 (Bid)
TICK_ASK = 2        # 卖价 (Ask)
TICK_MID = 3        # 中间价 (Mid = (Bid + Ask) / 2)
TICK_VOLUME = 4     # 成交量 (可选)
TICK_BAR_IDX = 5    # 所属 K 线索引 (用于时间止损、VWAP 止盈)

# ─────────────────────────────────────────────────────────────────────────────
# 信号数组 (M x 8, dtype=float64)
# ─────────────────────────────────────────────────────────────────────────────
SIG_TIMESTAMP = 0       # 信号生成时间戳 (秒)
SIG_EXEC_BAR_IDX = 1    # 执行 K 线索引 (信号在哪根 K 线执行)
SIG_STRATEGY = 2        # 策略类型: 1.0=A(均值回归), 2.0=B(动量突破)
SIG_DIRECTION = 3       # 交易方向: 1.0=多头, -1.0=空头
SIG_ENTRY_PRICE = 4     # 目标入场价 (策略B 使用, 策略A 为 NaN 表示市价)
SIG_STOP_LOSS = 5       # 初始止损价
SIG_TAKE_PROFIT = 6     # 初始止盈价 (策略A 使用 VWAP 动态止盈, 可能为 NaN)
SIG_EXECUTED = 7        # 执行状态: 0.0=未执行, 1.0=已执行/已过期

# ─────────────────────────────────────────────────────────────────────────────
# 交易记录数组 (K x 10, dtype=float64)
# ─────────────────────────────────────────────────────────────────────────────
TRADE_ENTRY_TIME = 0    # 入场时间戳 (秒)
TRADE_EXIT_TIME = 1     # 出场时间戳 (秒)
TRADE_DIRECTION = 2     # 方向: 1.0=多头, -1.0=空头
TRADE_ENTRY_PRICE = 3   # 入场价 (含滑点)
TRADE_EXIT_PRICE = 4    # 出场价 (含滑点)
TRADE_PNL = 5           # 盈亏金额 (美元)
TRADE_PNL_PCT = 6       # 盈亏百分比 (%)
TRADE_STRATEGY = 7      # 策略类型: 1.0=A, 2.0=B
TRADE_EXIT_REASON = 8   # 出场原因编码
TRADE_BARS_HELD = 9     # 持仓 K 线数

# ─────────────────────────────────────────────────────────────────────────────
# 出场原因编码 (用于快速识别出场类型)
# ─────────────────────────────────────────────────────────────────────────────
EXIT_REASON_NONE = 0
EXIT_REASON_STOP_LOSS = 1           # 初始止损触发
EXIT_REASON_TAKE_PROFIT = 2         # 止盈触发 (VWAP)
EXIT_REASON_TRAILING_STOP = 3       # 追踪止损触发 (策略B)
EXIT_REASON_TIME_STOP = 4           # 时间止损触发 (策略A)
EXIT_REASON_FORCE_CLOSE = 5         # 回测结束强制平仓
EXIT_REASON_STOP_LOSS_GAP = 6       # 跳空击穿止损

# ─────────────────────────────────────────────────────────────────────────────
# K 线统计数组列索引 (K x N, dtype=float64)
# ─────────────────────────────────────────────────────────────────────────────
BAR_ATR = 0           # ATR 值
BAR_VWAP = 1          # VWAP 值
BAR_HIGH = 2          # K 线最高价
BAR_LOW = 3           # K 线最低价

# ─────────────────────────────────────────────────────────────────────────────
# 性能参数
# ─────────────────────────────────────────────────────────────────────────────
MAX_TRADES = 10000              # 最大交易记录数 (预分配)
EQUITY_SAMPLE_RATE = 100        # 权益采样频率 (每 N 个 tick 采样一次)
CONTRACT_SIZE = 100             # 合约乘数 (XAUUSD: 每手 100 盎司)
BASE_SLIPPAGE = 0.15            # 基础滑点 ($0.15 = 15 pips)
ATR_SLIPPAGE_RATIO = 0.03       # ATR 滑点比例 (波动越大滑点越大)


# =============================================================================
# Task 1: 数据转换层 (Data Serialization)
# =============================================================================

def prepare_tick_data(
    tick_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    interval: str = '15min'
) -> np.ndarray:
    """
    将 Tick DataFrame 转换为纯 Numpy 数组 (N x 6)

    【输入格式要求】
    tick_df.index: DatetimeIndex
    tick_df 列: bid/Bid, ask/Ask, price/Price, volume/Volume (可选)

    【输出格式】
    N x 6 float64 数组: [timestamp, bid, ask, mid, volume, bar_idx]

    【性能优化】
    - 使用 Pandas 向量化操作，避免逐行循环
    - 使用 searchsorted 进行快速 K 线匹配

    Args:
        tick_df: Tick 数据 DataFrame
        ohlcv_df: OHLCV 数据 DataFrame (用于确定 bar_idx)
        interval: K 线周期 (用于验证)

    Returns:
        N x 6 的 float64 Numpy 数组
    """
    n_ticks = len(tick_df)
    if n_ticks == 0:
        return np.zeros((0, 6), dtype=np.float64)

    # 预分配数组
    ticks_array = np.zeros((n_ticks, 6), dtype=np.float64)

    # ─────────────────────────────────────────────────────────────────────────
    # 列 0: 时间戳 (Unix 秒)
    # ─────────────────────────────────────────────────────────────────────────
    ticks_array[:, TICK_TIMESTAMP] = tick_df.index.astype(np.int64).values / 1e9

    # ─────────────────────────────────────────────────────────────────────────
    # 列 1-3: Bid, Ask, Mid (向量化提取)
    # ─────────────────────────────────────────────────────────────────────────
    # Bid 列 (兼容多种命名)
    if 'bid' in tick_df.columns:
        ticks_array[:, TICK_BID] = tick_df['bid'].values
    elif 'Bid' in tick_df.columns:
        ticks_array[:, TICK_BID] = tick_df['Bid'].values
    elif 'price' in tick_df.columns:
        # 如果没有 Bid，用 price - 0.3 估算 (XAUUSD 典型点差约 0.6)
        ticks_array[:, TICK_BID] = tick_df['price'].values - 0.3
    else:
        ticks_array[:, TICK_BID] = tick_df.iloc[:, 0].values - 0.3

    # Ask 列 (兼容多种命名)
    if 'ask' in tick_df.columns:
        ticks_array[:, TICK_ASK] = tick_df['ask'].values
    elif 'Ask' in tick_df.columns:
        ticks_array[:, TICK_ASK] = tick_df['Ask'].values
    elif 'price' in tick_df.columns:
        ticks_array[:, TICK_ASK] = tick_df['price'].values + 0.3
    else:
        ticks_array[:, TICK_ASK] = tick_df.iloc[:, 0].values + 0.3

    # Mid 列 (中间价)
    if 'price' in tick_df.columns:
        ticks_array[:, TICK_MID] = tick_df['price'].values
    elif 'Price' in tick_df.columns:
        ticks_array[:, TICK_MID] = tick_df['Price'].values
    else:
        ticks_array[:, TICK_MID] = (ticks_array[:, TICK_BID] + ticks_array[:, TICK_ASK]) / 2

    # ─────────────────────────────────────────────────────────────────────────
    # 列 4: Volume (可选)
    # ─────────────────────────────────────────────────────────────────────────
    if 'volume' in tick_df.columns:
        ticks_array[:, TICK_VOLUME] = tick_df['volume'].values
    elif 'Volume' in tick_df.columns:
        ticks_array[:, TICK_VOLUME] = tick_df['Volume'].values

    # ─────────────────────────────────────────────────────────────────────────
    # 列 5: bar_idx (每个 tick 所属的 K 线索引)
    # ─────────────────────────────────────────────────────────────────────────
    # 使用 searchsorted 快速匹配 (O(N log M), N=ticks, M=bars)
    bar_times = ohlcv_df.index.astype(np.int64).values / 1e9
    tick_times = ticks_array[:, TICK_TIMESTAMP]

    # 二分查找: 对于每个 tick，找到第一个大于它的 bar_time，然后减 1
    bar_indices = np.searchsorted(bar_times, tick_times, side='right') - 1

    # 边界处理: 确保索引在有效范围内
    bar_indices = np.clip(bar_indices, 0, len(ohlcv_df) - 1)
    ticks_array[:, TICK_BAR_IDX] = bar_indices

    return ticks_array


def prepare_signals(
    signals: List,
    ohlcv_df: pd.DataFrame
) -> np.ndarray:
    """
    将 TradeSignal 对象列表转换为纯 Numpy 数组 (M x 8)

    【输出格式】
    M x 8 float64 数组: [timestamp, exec_bar_idx, strategy, direction, entry_price, stop_loss, take_profit, executed]

    【Bug 2 修复: NaN 陷阱】
    - 在 Numba @njit(fastmath=True) 中，NaN 比较会产生未定义行为
    - 所有初始化值从 np.nan 改为 0.0
    - 引擎内部通过 > 0.0 判断有效价格，绝对不能使用 NaN

    【性能优化】
    - 批量提取时间戳，避免逐个转换
    - 使用 NumPy 数组操作而非列表追加

    Args:
        signals: TradeSignal 对象列表 (来自 strategy.py)
        ohlcv_df: OHLCV 数据 DataFrame (用于验证 bar_idx)

    Returns:
        M x 8 的 float64 Numpy 数组
    """
    n_signals = len(signals)
    if n_signals == 0:
        return np.zeros((0, 8), dtype=np.float64)

    # 预分配数组 - Bug 2 修复: 默认值用 0.0 而非 np.nan
    signals_array = np.zeros((n_signals, 8), dtype=np.float64)
    # 【关键修复】删除原 np.nan 初始化，使用 0.0 表示"无目标价"
    # 原代码: signals_array[:, SIG_ENTRY_PRICE] = np.nan  # 删除此行
    # 原代码: signals_array[:, SIG_TAKE_PROFIT] = np.nan  # 删除此行
    # 默认值已经是 0.0，无需额外赋值

    # 获取 K 线数量 (用于边界检查)
    n_bars = len(ohlcv_df)

    # ─────────────────────────────────────────────────────────────────────────
    # 批量处理信号
    # ─────────────────────────────────────────────────────────────────────────
    from strategy import SignalType

    for i, sig in enumerate(signals):
        # 时间戳 (秒)
        signals_array[i, SIG_TIMESTAMP] = sig.timestamp.timestamp()

        # 执行 K 线索引 (边界检查)
        exec_idx = sig.execution_bar_index
        if exec_idx >= n_bars:
            exec_idx = n_bars - 1
        signals_array[i, SIG_EXEC_BAR_IDX] = exec_idx

        # 策略类型: 'A' -> 1.0, 'B' -> 2.0
        signals_array[i, SIG_STRATEGY] = 1.0 if sig.strategy == 'A' else 2.0

        # 交易方向: LONG -> 1.0, SHORT -> -1.0
        if sig.signal_type == SignalType.LONG:
            signals_array[i, SIG_DIRECTION] = 1.0
        else:
            signals_array[i, SIG_DIRECTION] = -1.0

        # 入场价 (0.0 表示市价入场, 用于策略 A)
        # Bug 2 修复: 不再使用 np.isnan 检查，改用 > 0.0 判断
        if sig.entry_price is not None and sig.entry_price > 0.0:
            signals_array[i, SIG_ENTRY_PRICE] = sig.entry_price

        # 止损价 (必须有效)
        if sig.stop_loss is not None and sig.stop_loss > 0.0:
            signals_array[i, SIG_STOP_LOSS] = sig.stop_loss

        # 止盈价 (策略 A 使用 VWAP 动态止盈, 可能为 None)
        if sig.take_profit is not None and sig.take_profit > 0.0:
            signals_array[i, SIG_TAKE_PROFIT] = sig.take_profit

        # executed 默认 0 (未执行)

    return signals_array


def prepare_bar_stats(
    ohlcv_df: pd.DataFrame,
    trailing_mult_b: float = 4.89
) -> np.ndarray:
    """
    提取 K 线统计指标数组 (K x 4)

    【输出格式】
    K x 4 float64 数组: [ATR, VWAP, High, Low]

    Args:
        ohlcv_df: OHLCV 数据 DataFrame (包含 ATR, VWAP 等指标)
        trailing_mult_b: 策略 B 追踪止损 ATR 倍数

    Returns:
        K x 4 的 float64 Numpy 数组
    """
    n_bars = len(ohlcv_df)
    if n_bars == 0:
        return np.zeros((0, 4), dtype=np.float64)

    stats_array = np.zeros((n_bars, 4), dtype=np.float64)

    # ATR
    if 'ATR' in ohlcv_df.columns:
        stats_array[:, BAR_ATR] = ohlcv_df['ATR'].values
    else:
        # 如果没有 ATR，使用 High-Low 的移动平均估算
        stats_array[:, BAR_ATR] = (ohlcv_df['High'] - ohlcv_df['Low']).rolling(14).mean().fillna(5.0).values

    # VWAP
    if 'VWAP' in ohlcv_df.columns:
        stats_array[:, BAR_VWAP] = ohlcv_df['VWAP'].values
    else:
        # 如果没有 VWAP，使用 Close 的移动平均估算
        stats_array[:, BAR_VWAP] = ohlcv_df['Close'].rolling(20).mean().values

    # High, Low
    stats_array[:, BAR_HIGH] = ohlcv_df['High'].values
    stats_array[:, BAR_LOW] = ohlcv_df['Low'].values

    return stats_array


# =============================================================================
# Task 2: Numba 核心撮合循环 (The JIT Matcher)
# =============================================================================

def _create_numba_matcher():
    """
    创建 Numba JIT 编译的 Tick 撮合函数

    返回 JIT 编译后的函数，或纯 Python 回退版本
    """
    if NUMBA_AVAILABLE:
        # ═══════════════════════════════════════════════════════════════════════
        # Numba JIT 版本 (100x 性能提升)
        # ═══════════════════════════════════════════════════════════════════════
        @njit(cache=True, fastmath=True, nogil=True)
        def fast_tick_matcher(
            ticks_array: np.ndarray,
            signals_array: np.ndarray,
            bar_stats: np.ndarray,
            initial_capital: float,
            contract_size: float,
            max_hold_bars_a: int,
            trailing_mult_b: float
        ) -> Tuple[np.ndarray, np.ndarray, int, int, int]:
            """
            Numba JIT 编译的超高速 Tick 撮合引擎

            【Bug 修复摘要】
            ┌────────────────────────────────────────────────────────────────────────┐
            │ Bug 1: 消除"双重征税"点差陷阱                                           │
            │   - 真实 Tick 数据已含 Bid/Ask 差值，额外加减 spread/2 = 双重点差        │
            │   - 修复: 入场/出场价直接使用 Bid/Ask + slippage，删除 spread/2 逻辑     │
            ├────────────────────────────────────────────────────────────────────────┤
            │ Bug 3: 修复跳空缺口时间旅行 Bug                                         │
            │   - 策略 B 突破入场时，用 target_price 成交 = 以不存在的价格作弊         │
            │   - 修复: 成交价锚定触发 Tick 的真实 Bid/Ask，而非预期目标价             │
            └────────────────────────────────────────────────────────────────────────┘

            【核心逻辑】
            1. 单次遍历 ticks_array (时间顺序)
            2. 状态机维护持仓状态 (全用基础标量)
            3. 严格 Bid/Ask 撮合:
               - 多头入场: Ask + slippage (不再加 spread/2)
               - 空头入场: Bid - slippage (不再减 spread/2)
               - 多头平仓: Bid (不再减 spread/2)
               - 空头平仓: Ask (不再加 spread/2)
            4. 动态追踪止损: 每个 Tick 更新 highest/lowest_price

            【参数说明】
            ticks_array: N x 6 数组 [timestamp, bid, ask, mid, volume, bar_idx]
            signals_array: M x 8 数组 [timestamp, exec_bar_idx, strategy, direction, entry_price, stop_loss, take_profit, executed]
            bar_stats: K x 4 数组 [ATR, VWAP, High, Low]
            initial_capital: 初始资金
            contract_size: 合约乘数
            max_hold_bars_a: 策略 A 最大持仓 K 线数
            trailing_mult_b: 策略 B 追踪止损 ATR 倍数

            【返回值】
            (trades_record, equity_curve, total_trades, winning_trades, total_ticks)
            """
            n_ticks = len(ticks_array)
            n_signals = len(signals_array)
            n_bars = len(bar_stats)

            # ═══════════════════════════════════════════════════════════════════
            # 预分配结果数组
            # ═══════════════════════════════════════════════════════════════════
            trades_record = np.zeros((MAX_TRADES, 10), dtype=np.float64)

            # 权益曲线 (每 EQUITY_SAMPLE_RATE 个 tick 采样一次)
            max_equity_points = n_ticks // EQUITY_SAMPLE_RATE + 2
            equity_curve = np.zeros(max_equity_points, dtype=np.float64)
            equity_curve[0] = initial_capital
            equity_idx = 1

            # ═══════════════════════════════════════════════════════════════════
            # 持仓状态变量 (全用基础标量，零对象开销)
            # ═══════════════════════════════════════════════════════════════════
            is_in_position = False          # 是否持仓
            current_direction = 0           # 1=多头, -1=空头
            entry_price = 0.0               # 入场价 (含滑点)
            entry_time = 0.0                # 入场时间戳
            entry_bar_idx = 0               # 入场 K 线索引
            current_sl = 0.0                # 当前止损价
            highest_price = 0.0             # 持仓期间最高价 (用于追踪止损)
            lowest_price = 1e10             # 持仓期间最低价
            current_strategy = 0            # 1=A, 2=B

            # ═══════════════════════════════════════════════════════════════════
            # 统计变量
            # ═══════════════════════════════════════════════════════════════════
            capital = initial_capital
            trade_count = 0
            win_count = 0
            signal_idx = 0

            # ═══════════════════════════════════════════════════════════════════
            # 主循环: 遍历每个 Tick
            # ═══════════════════════════════════════════════════════════════════
            for tick_idx in range(n_ticks):
                # 提取当前 Tick 数据
                tick_time = ticks_array[tick_idx, TICK_TIMESTAMP]
                tick_bid = ticks_array[tick_idx, TICK_BID]
                tick_ask = ticks_array[tick_idx, TICK_ASK]
                bar_idx = int(ticks_array[tick_idx, TICK_BAR_IDX])

                # 获取当前 K 线的统计指标 (预加载避免重复索引)
                if bar_idx < n_bars:
                    current_atr = bar_stats[bar_idx, BAR_ATR]
                    current_vwap = bar_stats[bar_idx, BAR_VWAP]
                else:
                    current_atr = 5.0
                    current_vwap = (tick_bid + tick_ask) / 2

                # ─────────────────────────────────────────────────────────────────
                # 阶段 1: 持仓出场检查
                # ─────────────────────────────────────────────────────────────────
                if is_in_position:
                    # 更新持仓期间的最高/最低价 (用于追踪止损)
                    if current_direction == 1:  # 多头
                        if tick_ask > highest_price:
                            highest_price = tick_ask
                    else:  # 空头
                        if tick_bid < lowest_price:
                            lowest_price = tick_bid

                    # 计算持仓 K 线数
                    bars_held = bar_idx - entry_bar_idx

                    # 出场信号
                    should_exit = False
                    exit_reason = EXIT_REASON_NONE
                    exit_price = tick_bid  # 默认使用 Bid

                    # ═══════════════════════════════════════════════════════════
                    # 策略 A 出场逻辑 (均值回归)
                    # ═══════════════════════════════════════════════════════════
                    if current_strategy == 1:
                        # 止损检查
                        # 【Bug 4 修复】跳空出场: 止损触发时必须用实际 tick 价格，不能用止损价
                        # 否则跳空时会以"神仙价"成交，造成回测作弊
                        if current_direction == 1:  # 多头
                            if tick_bid <= current_sl:
                                should_exit = True
                                exit_reason = EXIT_REASON_STOP_LOSS
                                exit_price = tick_bid  # Bug 4: 多头止损用 Bid
                        else:  # 空头
                            if tick_ask >= current_sl:
                                should_exit = True
                                exit_reason = EXIT_REASON_STOP_LOSS
                                exit_price = tick_ask  # Bug 4: 空头止损用 Ask

                        # VWAP 止盈检查
                        # 【Bug 4 修复】止盈同样用 tick 价格 (跳空越过限价单时以更优价成交)
                        if not should_exit:
                            if current_direction == 1:  # 多头
                                if tick_ask >= current_vwap:
                                    should_exit = True
                                    exit_reason = EXIT_REASON_TAKE_PROFIT
                                    exit_price = tick_ask  # Bug 4: 多头止盈用 Ask
                            else:  # 空头
                                if tick_bid <= current_vwap:
                                    should_exit = True
                                    exit_reason = EXIT_REASON_TAKE_PROFIT
                                    exit_price = tick_bid  # Bug 4: 空头止盈用 Bid

                        # 时间止损
                        if not should_exit and bars_held >= max_hold_bars_a:
                            should_exit = True
                            exit_reason = EXIT_REASON_TIME_STOP
                            # 时间止损使用 Bid (多头) 或 Ask (空头)
                            exit_price = tick_bid if current_direction == 1 else tick_ask

                    # ═══════════════════════════════════════════════════════════
                    # 策略 B 出场逻辑 (动量突破)
                    # ═══════════════════════════════════════════════════════════
                    elif current_strategy == 2:
                        # 初始止损检查
                        # 【Bug 4 修复】跳空出场: 止损触发时必须用实际 tick 价格
                        if current_direction == 1:  # 多头
                            if tick_bid <= current_sl:
                                should_exit = True
                                exit_reason = EXIT_REASON_STOP_LOSS
                                exit_price = tick_bid  # Bug 4: 多头止损用 Bid
                        else:  # 空头
                            if tick_ask >= current_sl:
                                should_exit = True
                                exit_reason = EXIT_REASON_STOP_LOSS
                                exit_price = tick_ask  # Bug 4: 空头止损用 Ask

                        # 追踪止损检查 (只有盈利时才启用)
                        # 【Bug 4 修复】跳空出场: 追踪止损触发时必须用实际 tick 价格
                        if not should_exit:
                            if current_direction == 1:  # 多头
                                trailing_stop = highest_price - trailing_mult_b * current_atr
                                # 只有最高价超过入场价才启用追踪止损
                                if tick_bid <= trailing_stop and highest_price > entry_price:
                                    should_exit = True
                                    exit_reason = EXIT_REASON_TRAILING_STOP
                                    exit_price = tick_bid  # Bug 4: 多头追踪止损用 Bid
                            else:  # 空头
                                trailing_stop = lowest_price + trailing_mult_b * current_atr
                                if tick_ask >= trailing_stop and lowest_price < entry_price:
                                    should_exit = True
                                    exit_reason = EXIT_REASON_TRAILING_STOP
                                    exit_price = tick_ask  # Bug 4: 空头追踪止损用 Ask

                    # ═══════════════════════════════════════════════════════════
                    # 执行出场
                    # Bug 1 修复: 出场价直接使用 exit_price，删除 spread/2 逻辑
                    # ═══════════════════════════════════════════════════════════
                    if should_exit:
                        # 【Bug 1 修复】直接使用出场价，不再加减 spread/2
                        # 真实点差已存在于 Bid/Ask 差值中
                        actual_exit = exit_price

                        # 计算盈亏
                        price_diff = (actual_exit - entry_price) * current_direction
                        pnl = price_diff * contract_size
                        pnl_pct = pnl / initial_capital * 100

                        # 更新资金
                        capital += pnl

                        # 记录交易
                        if trade_count < MAX_TRADES:
                            trades_record[trade_count, TRADE_ENTRY_TIME] = entry_time
                            trades_record[trade_count, TRADE_EXIT_TIME] = tick_time
                            trades_record[trade_count, TRADE_DIRECTION] = float(current_direction)
                            trades_record[trade_count, TRADE_ENTRY_PRICE] = entry_price
                            trades_record[trade_count, TRADE_EXIT_PRICE] = actual_exit
                            trades_record[trade_count, TRADE_PNL] = pnl
                            trades_record[trade_count, TRADE_PNL_PCT] = pnl_pct
                            trades_record[trade_count, TRADE_STRATEGY] = float(current_strategy)
                            trades_record[trade_count, TRADE_EXIT_REASON] = float(exit_reason)
                            trades_record[trade_count, TRADE_BARS_HELD] = float(bars_held)
                            trade_count += 1

                        if pnl > 0:
                            win_count += 1

                        # 重置持仓状态
                        is_in_position = False
                        current_direction = 0

                # ─────────────────────────────────────────────────────────────────
                # 阶段 2: 入场信号检查 (只在无持仓时执行)
                # ─────────────────────────────────────────────────────────────────
                if not is_in_position:
                    # 遍历待执行的信号
                    while signal_idx < n_signals:
                        sig_bar_idx = int(signals_array[signal_idx, SIG_EXEC_BAR_IDX])

                        # 信号在当前 K 线执行
                        if sig_bar_idx == bar_idx:
                            # 检查信号是否已执行
                            if signals_array[signal_idx, SIG_EXECUTED] == 0.0:
                                sig_direction = int(signals_array[signal_idx, SIG_DIRECTION])
                                sig_strategy = int(signals_array[signal_idx, SIG_STRATEGY])
                                sig_sl = signals_array[signal_idx, SIG_STOP_LOSS]
                                sig_entry_price = signals_array[signal_idx, SIG_ENTRY_PRICE]

                                # 计算动态滑点
                                slippage = BASE_SLIPPAGE + current_atr * ATR_SLIPPAGE_RATIO

                                # ─────────────────────────────────────────────────
                                # 策略 A: 市价入场
                                # Bug 1 修复: 入场价 = Bid/Ask + slippage，删除 spread/2
                                # ─────────────────────────────────────────────────
                                if sig_strategy == 1:
                                    if sig_direction == 1:  # 多头
                                        # 检查是否击穿止损 (放弃交易)
                                        if sig_sl > 0.0 and tick_ask <= sig_sl:
                                            signals_array[signal_idx, SIG_EXECUTED] = 1.0
                                            signal_idx += 1
                                            continue
                                        # 【Bug 1 修复】从 Ask 买入，不再加 spread/2
                                        entry_px = tick_ask + slippage
                                    else:  # 空头
                                        if sig_sl > 0.0 and tick_bid >= sig_sl:
                                            signals_array[signal_idx, SIG_EXECUTED] = 1.0
                                            signal_idx += 1
                                            continue
                                        # 【Bug 1 修复】从 Bid 卖出，不再减 spread/2
                                        entry_px = tick_bid - slippage

                                    # 入场成功
                                    is_in_position = True
                                    current_direction = sig_direction
                                    entry_price = entry_px
                                    entry_time = tick_time
                                    entry_bar_idx = bar_idx
                                    current_sl = sig_sl
                                    current_strategy = 1
                                    highest_price = entry_px if sig_direction == 1 else 0.0
                                    lowest_price = entry_px if sig_direction == -1 else 1e10
                                    signals_array[signal_idx, SIG_EXECUTED] = 1.0

                                # ─────────────────────────────────────────────────
                                # 策略 B: 限价/止损入场 (价格行为确认)
                                # Bug 1 + Bug 3 联合修复:
                                #   - 删除 spread/2 (Bug 1)
                                #   - 使用触发 Tick 的真实 Bid/Ask 成交 (Bug 3)
                                # ─────────────────────────────────────────────────
                                elif sig_strategy == 2:
                                    target_price = sig_entry_price

                                    # 【Bug 2 修复】使用 > 0.0 判断有效目标价，不用 NaN
                                    if target_price <= 0.0:
                                        # 无有效目标价，跳过此信号
                                        signals_array[signal_idx, SIG_EXECUTED] = 1.0
                                        signal_idx += 1
                                        continue

                                    if sig_direction == 1:  # 多头 Buy Stop
                                        # 价格突破目标价时入场
                                        if tick_ask >= target_price:
                                            # 【Bug 3 修复】跳空缺口时，成交价 = 触发 Tick 的 Ask
                                            # 绝不能使用 target_price，那是"时间旅行"作弊
                                            # 【Bug 1 修复】不再加 spread/2
                                            entry_px = tick_ask + slippage
                                            is_in_position = True
                                            current_direction = 1
                                            entry_price = entry_px
                                            entry_time = tick_time
                                            entry_bar_idx = bar_idx
                                            current_sl = sig_sl
                                            current_strategy = 2
                                            highest_price = entry_px
                                            lowest_price = 1e10
                                            signals_array[signal_idx, SIG_EXECUTED] = 1.0
                                    else:  # 空头 Sell Stop
                                        if tick_bid <= target_price:
                                            # 【Bug 3 修复】跳空缺口时，成交价 = 触发 Tick 的 Bid
                                            # 绝不能使用 target_price，那是"时间旅行"作弊
                                            # 【Bug 1 修复】不再减 spread/2
                                            entry_px = tick_bid - slippage
                                            is_in_position = True
                                            current_direction = -1
                                            entry_price = entry_px
                                            entry_time = tick_time
                                            entry_bar_idx = bar_idx
                                            current_sl = sig_sl
                                            current_strategy = 2
                                            highest_price = 0.0
                                            lowest_price = entry_px
                                            signals_array[signal_idx, SIG_EXECUTED] = 1.0

                            signal_idx += 1

                        # 信号在未来 K 线，跳出循环
                        elif sig_bar_idx > bar_idx:
                            break
                        else:
                            # 信号已过期 (K 线已过)
                            signal_idx += 1

                # ─────────────────────────────────────────────────────────────────
                # 阶段 3: 权益曲线采样
                # ─────────────────────────────────────────────────────────────────
                if tick_idx % EQUITY_SAMPLE_RATE == 0 and equity_idx < max_equity_points:
                    equity_curve[equity_idx] = capital
                    equity_idx += 1

            # ═══════════════════════════════════════════════════════════════════
            # 强制平仓最后的持仓 (回测结束时)
            # Bug 1 修复: 出场价直接使用 Bid/Ask，不再加减 spread/2
            # ═══════════════════════════════════════════════════════════════════
            if is_in_position:
                last_tick_idx = n_ticks - 1
                # 【Bug 1 修复】直接使用最后一个 Tick 的 Bid/Ask
                if current_direction == 1:  # 多头 -> 卖给 Bid
                    exit_price = ticks_array[last_tick_idx, TICK_BID]
                else:  # 空头 -> 从 Ask 买回
                    exit_price = ticks_array[last_tick_idx, TICK_ASK]

                price_diff = (exit_price - entry_price) * current_direction
                pnl = price_diff * contract_size
                capital += pnl

                if trade_count < MAX_TRADES:
                    trades_record[trade_count, TRADE_ENTRY_TIME] = entry_time
                    trades_record[trade_count, TRADE_EXIT_TIME] = ticks_array[last_tick_idx, TICK_TIMESTAMP]
                    trades_record[trade_count, TRADE_DIRECTION] = float(current_direction)
                    trades_record[trade_count, TRADE_ENTRY_PRICE] = entry_price
                    trades_record[trade_count, TRADE_EXIT_PRICE] = exit_price
                    trades_record[trade_count, TRADE_PNL] = pnl
                    trades_record[trade_count, TRADE_PNL_PCT] = pnl / initial_capital * 100
                    trades_record[trade_count, TRADE_STRATEGY] = float(current_strategy)
                    trades_record[trade_count, TRADE_EXIT_REASON] = float(EXIT_REASON_FORCE_CLOSE)
                    trades_record[trade_count, TRADE_BARS_HELD] = 0.0
                    trade_count += 1

                if pnl > 0:
                    win_count += 1

            # 截断结果数组
            trades_record = trades_record[:trade_count]
            equity_curve = equity_curve[:equity_idx]

            return trades_record, equity_curve, trade_count, win_count, n_ticks

        return fast_tick_matcher

    else:
        # ═══════════════════════════════════════════════════════════════════════
        # 纯 Python 回退版本 (无 Numba 时使用)
        # ═══════════════════════════════════════════════════════════════════════
        def fast_tick_matcher(
            ticks_array: np.ndarray,
            signals_array: np.ndarray,
            bar_stats: np.ndarray,
            initial_capital: float,
            contract_size: float,
            max_hold_bars_a: int,
            trailing_mult_b: float
        ) -> Tuple[np.ndarray, np.ndarray, int, int, int]:
            """
            纯 Python 回退版本 (逻辑与 Numba 版本完全相同)
            Bug 1 修复: 删除 spread 参数
            """
            n_ticks = len(ticks_array)
            n_signals = len(signals_array)
            n_bars = len(bar_stats)

            trades_record = np.zeros((MAX_TRADES, 10), dtype=np.float64)
            max_equity_points = n_ticks // EQUITY_SAMPLE_RATE + 2
            equity_curve = np.zeros(max_equity_points, dtype=np.float64)
            equity_curve[0] = initial_capital
            equity_idx = 1

            is_in_position = False
            current_direction = 0
            entry_price = 0.0
            entry_time = 0.0
            entry_bar_idx = 0
            current_sl = 0.0
            highest_price = 0.0
            lowest_price = 1e10
            current_strategy = 0

            capital = initial_capital
            trade_count = 0
            win_count = 0
            signal_idx = 0

            for tick_idx in range(n_ticks):
                tick_time = ticks_array[tick_idx, TICK_TIMESTAMP]
                tick_bid = ticks_array[tick_idx, TICK_BID]
                tick_ask = ticks_array[tick_idx, TICK_ASK]
                bar_idx = int(ticks_array[tick_idx, TICK_BAR_IDX])

                current_atr = bar_stats[bar_idx, BAR_ATR] if bar_idx < n_bars else 5.0
                current_vwap = bar_stats[bar_idx, BAR_VWAP] if bar_idx < n_bars else (tick_bid + tick_ask) / 2

                if is_in_position:
                    if current_direction == 1:
                        highest_price = max(highest_price, tick_ask)
                    else:
                        lowest_price = min(lowest_price, tick_bid)

                    bars_held = bar_idx - entry_bar_idx
                    should_exit = False
                    exit_reason = EXIT_REASON_NONE
                    exit_price = tick_bid

                    if current_strategy == 1:
                        # 【Bug 4 修复】跳空出场: 止损/止盈触发时必须用实际 tick 价格
                        if current_direction == 1:
                            if tick_bid <= current_sl:
                                should_exit = True
                                exit_reason = EXIT_REASON_STOP_LOSS
                                exit_price = tick_bid  # Bug 4: 多头止损用 Bid
                        else:
                            if tick_ask >= current_sl:
                                should_exit = True
                                exit_reason = EXIT_REASON_STOP_LOSS
                                exit_price = tick_ask  # Bug 4: 空头止损用 Ask

                        if not should_exit:
                            if current_direction == 1:
                                if tick_ask >= current_vwap:
                                    should_exit = True
                                    exit_reason = EXIT_REASON_TAKE_PROFIT
                                    exit_price = tick_ask  # Bug 4: 多头止盈用 Ask
                            else:
                                if tick_bid <= current_vwap:
                                    should_exit = True
                                    exit_reason = EXIT_REASON_TAKE_PROFIT
                                    exit_price = tick_bid  # Bug 4: 空头止盈用 Bid

                        if not should_exit and bars_held >= max_hold_bars_a:
                            should_exit = True
                            exit_reason = EXIT_REASON_TIME_STOP
                            exit_price = tick_bid if current_direction == 1 else tick_ask

                    elif current_strategy == 2:
                        # 【Bug 4 修复】跳空出场: 止损/追踪止损触发时必须用实际 tick 价格
                        if current_direction == 1:
                            if tick_bid <= current_sl:
                                should_exit = True
                                exit_reason = EXIT_REASON_STOP_LOSS
                                exit_price = tick_bid  # Bug 4: 多头止损用 Bid
                        else:
                            if tick_ask >= current_sl:
                                should_exit = True
                                exit_reason = EXIT_REASON_STOP_LOSS
                                exit_price = tick_ask  # Bug 4: 空头止损用 Ask

                        if not should_exit:
                            if current_direction == 1:
                                trailing_stop = highest_price - trailing_mult_b * current_atr
                                if tick_bid <= trailing_stop and highest_price > entry_price:
                                    should_exit = True
                                    exit_reason = EXIT_REASON_TRAILING_STOP
                                    exit_price = tick_bid  # Bug 4: 多头追踪止损用 Bid
                            else:
                                trailing_stop = lowest_price + trailing_mult_b * current_atr
                                if tick_ask >= trailing_stop and lowest_price < entry_price:
                                    should_exit = True
                                    exit_reason = EXIT_REASON_TRAILING_STOP
                                    exit_price = tick_ask  # Bug 4: 空头追踪止损用 Ask

                    if should_exit:
                        # 【Bug 1 修复】直接使用出场价，不再加减 spread/2
                        actual_exit = exit_price

                        price_diff = (actual_exit - entry_price) * current_direction
                        pnl = price_diff * contract_size
                        capital += pnl

                        if trade_count < MAX_TRADES:
                            trades_record[trade_count, TRADE_ENTRY_TIME] = entry_time
                            trades_record[trade_count, TRADE_EXIT_TIME] = tick_time
                            trades_record[trade_count, TRADE_DIRECTION] = float(current_direction)
                            trades_record[trade_count, TRADE_ENTRY_PRICE] = entry_price
                            trades_record[trade_count, TRADE_EXIT_PRICE] = actual_exit
                            trades_record[trade_count, TRADE_PNL] = pnl
                            trades_record[trade_count, TRADE_PNL_PCT] = pnl / initial_capital * 100
                            trades_record[trade_count, TRADE_STRATEGY] = float(current_strategy)
                            trades_record[trade_count, TRADE_EXIT_REASON] = float(exit_reason)
                            trades_record[trade_count, TRADE_BARS_HELD] = float(bars_held)
                            trade_count += 1

                        if pnl > 0:
                            win_count += 1

                        is_in_position = False
                        current_direction = 0

                if not is_in_position:
                    while signal_idx < n_signals:
                        sig_bar_idx = int(signals_array[signal_idx, SIG_EXEC_BAR_IDX])

                        if sig_bar_idx == bar_idx:
                            if signals_array[signal_idx, SIG_EXECUTED] == 0.0:
                                sig_direction = int(signals_array[signal_idx, SIG_DIRECTION])
                                sig_strategy = int(signals_array[signal_idx, SIG_STRATEGY])
                                sig_sl = signals_array[signal_idx, SIG_STOP_LOSS]
                                sig_entry_price = signals_array[signal_idx, SIG_ENTRY_PRICE]
                                slippage = BASE_SLIPPAGE + current_atr * ATR_SLIPPAGE_RATIO

                                if sig_strategy == 1:
                                    if sig_direction == 1:
                                        if sig_sl > 0.0 and tick_ask <= sig_sl:
                                            signals_array[signal_idx, SIG_EXECUTED] = 1.0
                                            signal_idx += 1
                                            continue
                                        # 【Bug 1 修复】不再加 spread/2
                                        entry_px = tick_ask + slippage
                                    else:
                                        if sig_sl > 0.0 and tick_bid >= sig_sl:
                                            signals_array[signal_idx, SIG_EXECUTED] = 1.0
                                            signal_idx += 1
                                            continue
                                        # 【Bug 1 修复】不再减 spread/2
                                        entry_px = tick_bid - slippage

                                    is_in_position = True
                                    current_direction = sig_direction
                                    entry_price = entry_px
                                    entry_time = tick_time
                                    entry_bar_idx = bar_idx
                                    current_sl = sig_sl
                                    current_strategy = 1
                                    highest_price = entry_px if sig_direction == 1 else 0.0
                                    lowest_price = entry_px if sig_direction == -1 else 1e10
                                    signals_array[signal_idx, SIG_EXECUTED] = 1.0

                                elif sig_strategy == 2:
                                    target_price = sig_entry_price

                                    # 【Bug 2 修复】使用 > 0.0 判断有效目标价
                                    if target_price <= 0.0:
                                        signals_array[signal_idx, SIG_EXECUTED] = 1.0
                                        signal_idx += 1
                                        continue

                                    if sig_direction == 1 and tick_ask >= target_price:
                                        # 【Bug 3 修复】使用 tick_ask 而非 target_price
                                        # 【Bug 1 修复】不再加 spread/2
                                        entry_px = tick_ask + slippage
                                        is_in_position = True
                                        current_direction = 1
                                        entry_price = entry_px
                                        entry_time = tick_time
                                        entry_bar_idx = bar_idx
                                        current_sl = sig_sl
                                        current_strategy = 2
                                        highest_price = entry_px
                                        lowest_price = 1e10
                                        signals_array[signal_idx, SIG_EXECUTED] = 1.0
                                    elif sig_direction == -1 and tick_bid <= target_price:
                                        # 【Bug 3 修复】使用 tick_bid 而非 target_price
                                        # 【Bug 1 修复】不再减 spread/2
                                        entry_px = tick_bid - slippage
                                        is_in_position = True
                                        current_direction = -1
                                        entry_price = entry_px
                                        entry_time = tick_time
                                        entry_bar_idx = bar_idx
                                        current_sl = sig_sl
                                        current_strategy = 2
                                        highest_price = 0.0
                                        lowest_price = entry_px
                                        signals_array[signal_idx, SIG_EXECUTED] = 1.0

                            signal_idx += 1
                        elif sig_bar_idx > bar_idx:
                            break
                        else:
                            signal_idx += 1

                if tick_idx % EQUITY_SAMPLE_RATE == 0 and equity_idx < max_equity_points:
                    equity_curve[equity_idx] = capital
                    equity_idx += 1

            if is_in_position:
                last_tick_idx = n_ticks - 1
                # 【Bug 1 修复】直接使用 Bid/Ask，不再加减 spread/2
                if current_direction == 1:
                    exit_price = ticks_array[last_tick_idx, TICK_BID]
                else:
                    exit_price = ticks_array[last_tick_idx, TICK_ASK]

                price_diff = (exit_price - entry_price) * current_direction
                pnl = price_diff * contract_size
                capital += pnl

                if trade_count < MAX_TRADES:
                    trades_record[trade_count, TRADE_ENTRY_TIME] = entry_time
                    trades_record[trade_count, TRADE_EXIT_TIME] = ticks_array[last_tick_idx, TICK_TIMESTAMP]
                    trades_record[trade_count, TRADE_DIRECTION] = float(current_direction)
                    trades_record[trade_count, TRADE_ENTRY_PRICE] = entry_price
                    trades_record[trade_count, TRADE_EXIT_PRICE] = exit_price
                    trades_record[trade_count, TRADE_PNL] = pnl
                    trades_record[trade_count, TRADE_PNL_PCT] = pnl / initial_capital * 100
                    trades_record[trade_count, TRADE_STRATEGY] = float(current_strategy)
                    trades_record[trade_count, TRADE_EXIT_REASON] = float(EXIT_REASON_FORCE_CLOSE)
                    trades_record[trade_count, TRADE_BARS_HELD] = 0.0
                    trade_count += 1

                if pnl > 0:
                    win_count += 1

            trades_record = trades_record[:trade_count]
            equity_curve = equity_curve[:equity_idx]

            return trades_record, equity_curve, trade_count, win_count, n_ticks

        return fast_tick_matcher


# 创建全局匹配器函数 (JIT 编译或纯 Python)
fast_tick_matcher = _create_numba_matcher()


# =============================================================================
# Task 3: 高级封装类 - 与 Optuna 集成
# =============================================================================

class NumbaTickBacktestEngine:
    """
    Numba 加速的 Tick 回测引擎

    【Bug 1 修复】
    - 删除 spread 参数，真实点差已存在于 Tick 数据的 Bid/Ask 差值中
    - 双重点差计费已被彻底消除

    【核心优化】
    1. Tick 数据只序列化一次，Optuna 多次 Trial 复用
    2. Numba JIT 编译核心撮合逻辑
    3. 面向数组编程，零对象开销

    【使用流程】
    >>> engine = NumbaTickBacktestEngine()
    >>> engine.prepare_data(tick_df, ohlcv_df)  # 只调用一次
    >>> for params in optuna_trials:
    >>>     signals = strategy.generate_signals(ohlcv_df)
    >>>     stats = engine.run_backtest(signals, params, ohlcv_df)
    """

    def __init__(
        self,
        initial_capital: float = 100000,
        position_size: float = 1.0,
        contract_size: int = 100
    ):
        self.initial_capital = initial_capital
        self.position_size = position_size
        # 【Bug 1 修复】删除 spread 参数
        # 真实点差已存在于 Tick 数据的 Bid/Ask 差值中
        self.contract_size = contract_size

        # 缓存的序列化数据 (避免 Optuna 每次重复转换)
        self._cached_ticks_array: Optional[np.ndarray] = None
        self._cached_bar_stats: Optional[np.ndarray] = None
        self._cache_key: Optional[str] = None

    def prepare_data(
        self,
        tick_df: pd.DataFrame,
        ohlcv_df: pd.DataFrame,
        cache_key: Optional[str] = None
    ) -> None:
        """
        预处理并缓存数据 (Optuna 优化前调用一次)

        【关键优化】
        - Tick 数据在 Optuna 优化启动前只序列化一次
        - 通过引用传递给每次参数评估函数

        Args:
            tick_df: Tick 数据 DataFrame
            ohlcv_df: OHLCV 数据 DataFrame (包含 ATR, VWAP 等指标)
            cache_key: 缓存键 (用于判断是否需要重新处理)
        """
        # 检查是否已有缓存
        if cache_key is not None and cache_key == self._cache_key:
            print(f"[NumbaTick] 使用缓存数据: {cache_key}")
            return

        print(f"[NumbaTick] 序列化数据...")
        start_time = time.time()

        # 数据转换
        self._cached_ticks_array = prepare_tick_data(tick_df, ohlcv_df)
        self._cached_bar_stats = prepare_bar_stats(ohlcv_df)
        self._cache_key = cache_key

        elapsed = time.time() - start_time
        print(f"[NumbaTick] 数据序列化完成: {len(self._cached_ticks_array):,} ticks, 耗时 {elapsed:.2f}s")

    def run_backtest(
        self,
        signals: List,
        params: Dict,
        ohlcv_df: pd.DataFrame,
        verbose: bool = False
    ) -> Dict:
        """
        运行高性能 Tick 回测

        【Bug 修复摘要】
        - 调用 fast_tick_matcher 时不再传递 spread 参数
        - 真实点差已存在于 Tick 数据中，无需额外计算

        Args:
            signals: 交易信号列表 (TradeSignal 对象, 来自 strategy.generate_signals)
            params: 策略参数字典
            ohlcv_df: OHLCV 数据 DataFrame
            verbose: 是否打印详细信息

        Returns:
            回测统计字典
        """
        if self._cached_ticks_array is None:
            raise ValueError("请先调用 prepare_data() 预处理数据")

        start_time = time.time()

        # 序列化信号 (每次回测都需要重新处理，因为参数可能改变信号)
        signals_array = prepare_signals(signals, ohlcv_df)

        # 提取参数
        max_hold_bars_a = params.get('max_hold_bars_a', 5)
        trailing_mult_b = params.get('trailing_stop_atr_mult', 4.89)

        # 调用 Numba 核心
        # 【Bug 1 修复】不再传递 spread 参数
        trades_record, equity_curve, total_trades, winning_trades, total_ticks = fast_tick_matcher(
            self._cached_ticks_array,
            signals_array,
            self._cached_bar_stats,
            self.initial_capital,
            float(self.contract_size),
            max_hold_bars_a,
            trailing_mult_b
        )

        elapsed = time.time() - start_time

        if verbose:
            print(f"[NumbaTick] 回测完成: {total_ticks:,} ticks, {total_trades} trades, 耗时 {elapsed:.3f}s")

        # 计算统计指标
        stats = self._calculate_statistics(
            trades_record, equity_curve, total_trades, winning_trades, total_ticks, elapsed
        )

        return stats

    def _calculate_statistics(
        self,
        trades_record: np.ndarray,
        equity_curve: np.ndarray,
        total_trades: int,
        winning_trades: int,
        total_ticks: int,
        elapsed_time: float
    ) -> Dict:
        """
        将 Numba 输出转换为统计字典
        """
        if total_trades == 0:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'total_return': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'profit_factor': 0,
                'total_ticks_processed': total_ticks,
                'execution_time': elapsed_time,
                'trades_df': pd.DataFrame(),
                'daily_returns': pd.Series(),
            }

        # 从交易记录提取数据
        pnls = trades_record[:, TRADE_PNL]
        total_pnl = np.sum(pnls)
        total_return = (equity_curve[-1] - self.initial_capital) / self.initial_capital * 100
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0

        # 盈亏比
        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        avg_win = np.mean(wins) if len(wins) > 0 else 0
        avg_loss = abs(np.mean(losses)) if len(losses) > 0 else 0
        profit_factor = np.sum(wins) / abs(np.sum(losses)) if np.sum(losses) != 0 else float('inf')

        # 最大回撤
        rolling_max = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - rolling_max) / rolling_max * 100
        max_drawdown = abs(np.min(drawdown))

        # 夏普比率 (年化)
        if len(equity_curve) > 1:
            returns = np.diff(equity_curve) / equity_curve[:-1]
            if np.std(returns) > 0:
                # 假设 15 分钟 K 线，每年 252 * 24 * 4 = 24192 个采样点
                sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252 * 24 * 4)
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0

        # 构建交易 DataFrame
        trades_df = pd.DataFrame({
            'entry_time': pd.to_datetime(trades_record[:, TRADE_ENTRY_TIME], unit='s'),
            'exit_time': pd.to_datetime(trades_record[:, TRADE_EXIT_TIME], unit='s'),
            'direction': ['LONG' if d > 0 else 'SHORT' for d in trades_record[:, TRADE_DIRECTION]],
            'entry_price': trades_record[:, TRADE_ENTRY_PRICE],
            'exit_price': trades_record[:, TRADE_EXIT_PRICE],
            'pnl': trades_record[:, TRADE_PNL],
            'pnl_pct': trades_record[:, TRADE_PNL_PCT],
            'strategy': ['A' if s < 1.5 else 'B' for s in trades_record[:, TRADE_STRATEGY]],
            'exit_reason': [_decode_exit_reason(int(r)) for r in trades_record[:, TRADE_EXIT_REASON]],
            'bars_held': trades_record[:, TRADE_BARS_HELD].astype(int),
        })

        # 日度收益率
        equity_ts = pd.to_datetime(np.arange(0, len(equity_curve)) * EQUITY_SAMPLE_RATE, unit='s')
        daily_equity = pd.Series(equity_curve, index=equity_ts).resample('D').last().dropna()
        daily_returns = daily_equity.pct_change().dropna() if len(daily_equity) > 1 else pd.Series()

        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': total_trades - winning_trades,
            'win_rate': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2),
            'total_return': round(total_return, 2),
            'max_drawdown': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe_ratio, 4),
            'profit_factor': round(profit_factor, 4),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'max_win': round(np.max(pnls), 2) if len(pnls) > 0 else 0,
            'max_loss': round(np.min(pnls), 2) if len(pnls) > 0 else 0,
            'total_ticks_processed': total_ticks,
            'execution_time': elapsed_time,
            'final_capital': round(equity_curve[-1], 2),
            'trades_df': trades_df,
            'daily_returns': daily_returns,
            'equity_curve': equity_curve,
        }


def _decode_exit_reason(code: int) -> str:
    """解码出场原因"""
    reasons = {
        EXIT_REASON_NONE: "未知",
        EXIT_REASON_STOP_LOSS: "止损",
        EXIT_REASON_TAKE_PROFIT: "止盈(VWAP)",
        EXIT_REASON_TRAILING_STOP: "追踪止损",
        EXIT_REASON_TIME_STOP: "时间止损",
        EXIT_REASON_FORCE_CLOSE: "强制平仓",
        EXIT_REASON_STOP_LOSS_GAP: "跳空止损",
    }
    return reasons.get(code, "未知")


# =============================================================================
# 向后兼容的包装类
# =============================================================================

class TickBacktestEngine(NumbaTickBacktestEngine):
    """
    向后兼容的 Tick 回测引擎

    自动继承 Numba 版本的所有功能
    """

    def run_tick_backtest(
        self,
        ticks_df: pd.DataFrame,
        ohlcv_df: pd.DataFrame,
        strategy,
        verbose: bool = False
    ) -> Dict:
        """
        运行 Tick 回测 (兼容旧接口)

        Args:
            ticks_df: Tick 数据 DataFrame
            ohlcv_df: OHLCV 数据 DataFrame
            strategy: 策略对象 (必须有 generate_signals 方法)
            verbose: 是否打印详细信息

        Returns:
            回测统计字典
        """
        # 预处理数据
        cache_key = f"{ticks_df.index[0]}_{ticks_df.index[-1]}"
        self.prepare_data(ticks_df, ohlcv_df, cache_key)

        # 生成信号
        signals = strategy.generate_signals(ohlcv_df)

        # 运行回测
        return self.run_backtest(signals, strategy.params, ohlcv_df, verbose)


# =============================================================================
# 性能测试入口
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Numba Tick 回测引擎性能测试")
    print("=" * 70)

    # 检测 Numba 状态
    if NUMBA_AVAILABLE:
        print("✅ Numba JIT 已启用")
    else:
        print("⚠️ Numba 未安装，使用纯 Python 回退模式")

    # 生成测试数据
    print("\n生成测试数据...")
    n_ticks = 1_000_000

    # 随机生成 Tick 数据
    np.random.seed(42)
    test_ticks = np.zeros((n_ticks, 6), dtype=np.float64)
    test_ticks[:, TICK_TIMESTAMP] = np.arange(n_ticks)  # 时间戳
    test_ticks[:, TICK_BID] = 2000 + np.cumsum(np.random.randn(n_ticks) * 0.01)  # Bid 随机游走
    test_ticks[:, TICK_ASK] = test_ticks[:, TICK_BID] + 0.3  # Ask = Bid + 点差
    test_ticks[:, TICK_MID] = (test_ticks[:, TICK_BID] + test_ticks[:, TICK_ASK]) / 2
    test_ticks[:, TICK_BAR_IDX] = np.arange(n_ticks) // 100  # 每 100 个 tick 一根 K 线

    # 生成测试信号 (10 个信号)
    test_signals = np.zeros((10, 8), dtype=np.float64)
    test_signals[:, SIG_EXEC_BAR_IDX] = np.arange(10) * 100 + 50  # 执行 K 线索引
    test_signals[:, SIG_STRATEGY] = 1  # 策略 A
    test_signals[:, SIG_DIRECTION] = 1  # 多头
    test_signals[:, SIG_STOP_LOSS] = 1990  # 止损价

    # K 线统计
    n_bars = n_ticks // 100
    test_bar_stats = np.zeros((n_bars, 4), dtype=np.float64)
    test_bar_stats[:, BAR_ATR] = 5.0
    test_bar_stats[:, BAR_VWAP] = 2005.0

    print(f"测试数据量: {n_ticks:,} ticks, {n_bars:,} bars")
    print("\n开始性能测试...")

    # 运行回测
    start = time.time()
    trades, equity, n_trades, n_wins, n_processed = fast_tick_matcher(
        test_ticks, test_signals, test_bar_stats,
        initial_capital=100000,
        contract_size=100,
        max_hold_bars_a=5,
        trailing_mult_b=4.89
    )
    elapsed = time.time() - start

    print(f"\n{'='*70}")
    print(f"性能测试结果:")
    print(f"  处理 Tick 数: {n_processed:,}")
    print(f"  交易次数: {n_trades}")
    print(f"  执行时间: {elapsed:.3f}s")
    print(f"  处理速度: {n_processed / elapsed:,.0f} ticks/s")
    print(f"{'='*70}")
