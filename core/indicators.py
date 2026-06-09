"""
技术指标计算模块
================
提供完整的技术指标计算功能
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple

# Numba并行支持
try:
    from numba import njit, prange

    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False

    # 创建虚拟装饰器
    def njit(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    prange = range


@njit(parallel=True, cache=True, fastmath=True)
def _sma_numba_parallel(data: np.ndarray, period: int) -> np.ndarray:
    """Numba并行版SMA计算"""
    n = len(data)
    result = np.full(n, np.nan)

    # 使用并行计算每个点的SMA
    for i in prange(period - 1, n):
        s = 0.0
        for j in range(i - period + 1, i + 1):
            s += data[j]
        result[i] = s / period

    return result


@njit(parallel=True, cache=True, fastmath=True)
def _atr_numba_parallel(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int
) -> np.ndarray:
    """Numba并行版ATR计算"""
    n = len(highs)
    tr = np.zeros(n)

    # 第一个TR用High-Low
    tr[0] = highs[0] - lows[0]

    # 计算TR
    for i in range(1, n):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i - 1])
        tr3 = abs(lows[i] - closes[i - 1])
        tr[i] = max(tr1, max(tr2, tr3))

    # 计算ATR (Wilder平滑)
    atr = np.full(n, np.nan)
    atr[period - 1] = np.mean(tr[:period])

    alpha = 1.0 / period
    for i in range(period, n):
        atr[i] = tr[i] * alpha + atr[i - 1] * (1 - alpha)

    return atr


def calculate_sma(series: pd.Series, period: int, use_numba: bool = False) -> pd.Series:
    """计算简单移动平均线

    Args:
        series: 价格序列
        period: 周期
        use_numba: 是否使用Numba并行加速（大数据集时推荐）
    """
    if use_numba and NUMBA_AVAILABLE and len(series) > 10000:
        result = _sma_numba_parallel(series.values, period)
        return pd.Series(result, index=series.index)
    return series.rolling(window=period, min_periods=period).mean()


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """计算指数移动平均线"""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    计算平均真实波幅 (ATR)

    Args:
        df: DataFrame包含High, Low, Close列
        period: ATR周期

    Returns:
        ATR序列
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # 真实波幅
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # ATR - 使用 Wilder 平滑
    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()

    return atr


def calculate_sma_angle(
    sma_series: pd.Series, atr_series: pd.Series, lookback: int = 5
) -> pd.Series:
    """
    计算SMA均线的倾斜角度（量纲标准化版本）

    【核心公式】角度 = atan( (SMA[t] - SMA[t-n]) / (ATR[t] × n) ) × (180/π)

    通过ATR标准化，将价格变化转换为与波动率相对的无量纲比率，
    使得角度计算在不同市场条件下具有可比性。

    Args:
        sma_series: SMA序列
        atr_series: ATR序列（用于标准化）
        lookback: 回看K线数（默认5根）

    Returns:
        角度序列（0-90度，正值表示向上，负值表示向下）
    """
    # 计算SMA变化量
    sma_change = sma_series - sma_series.shift(lookback)

    # ATR标准化：将bars转换为"等效美元波动"
    atr_normalized = atr_series * lookback

    # 避免除以零
    atr_normalized = atr_normalized.replace(0, np.nan)

    # 计算无量纲比率
    ratio = sma_change / atr_normalized

    # 计算角度（弧度转度数）
    angle = np.arctan(ratio) * (180 / np.pi)

    return angle


def calculate_bollinger_bands(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    计算布林带

    Args:
        series: 价格序列
        period: 周期
        std_dev: 标准差倍数

    Returns:
        (上轨, 中轨, 下轨)
    """
    middle = calculate_sma(series, period)
    std = series.rolling(window=period, min_periods=period).std()

    upper = middle + std * std_dev
    lower = middle - std * std_dev

    return upper, middle, lower


def calculate_bbw(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> pd.Series:
    """计算Bollinger Band Width (BBW) = (Upper - Lower) / Middle × 100"""
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(series, period, std_dev)
    return (bb_upper - bb_lower) / bb_middle * 100


def calculate_keltner_channels(
    df: pd.DataFrame, period: int = 20, atr_mult: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    计算肯特纳通道

    Args:
        df: DataFrame包含High, Low, Close列
        period: EMA周期
        atr_mult: ATR倍数

    Returns:
        (上轨, 中轨, 下轨)
    """
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    middle = calculate_ema(typical_price, period)
    atr = calculate_atr(df, period)

    upper = middle + atr * atr_mult
    lower = middle - atr * atr_mult

    return upper, middle, lower


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    计算相对强弱指标 (RSI) - 使用 Wilder 平滑（RMA）

    标准 RSI 采用 Wilder 的平滑移动平均（alpha = 1/period），
    而非简单移动平均，以确保与主流图表软件一致。

    Args:
        series: 价格序列
        period: RSI周期

    Returns:
        RSI序列 (0-100)
    """
    delta = series.diff()

    # 分离上涨和下跌
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    # 使用 Wilder 平滑（RMA）：alpha = 1 / period
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    # 计算RS和RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_vwap(df: pd.DataFrame, reset_hour_et: int = 17) -> pd.Series:
    """
    计算VWAP (成交量加权平均价)

    【重要】VWAP 锚定于美东时间 17:00（外汇日线重置时间）

    Args:
        df: DataFrame包含High, Low, Close, Volume列
        reset_hour_et: VWAP重置小时（美东时间）

    Returns:
        VWAP序列
    """
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3

    # 获取"交易日"
    if df.index.tz is not None:
        # 转换为美东时间
        try:
            import pytz

            et_tz = pytz.timezone("America/New_York")
            index_et = df.index.tz_convert(et_tz)

            # 计算交易日
            trading_day = pd.Series(index_et.date, index=df.index)
            hour_et = index_et.hour

            # 17:00之前的数据属于前一天
            mask_before_reset = hour_et < reset_hour_et
            trading_day.loc[mask_before_reset] = trading_day.loc[
                mask_before_reset
            ] - pd.Timedelta(days=1)
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                f"VWAP timezone conversion failed: {e}, falling back to local date"
            )
            trading_day = pd.Series(df.index.date, index=df.index)
    else:
        trading_day = pd.Series(df.index.date, index=df.index)

    # 计算VWAP
    tp_volume = typical_price * df["Volume"]

    vwap = pd.Series(index=df.index, dtype=float)

    for day in trading_day.unique():
        mask = trading_day == day
        cumulative_tp_vol = tp_volume[mask].cumsum()
        cumulative_vol = df.loc[mask, "Volume"].cumsum()
        vwap.loc[mask] = cumulative_tp_vol / cumulative_vol

    return vwap


def calculate_macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    计算MACD

    Args:
        series: 价格序列
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期

    Returns:
        (MACD线, 信号线, 柱状图)
    """
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)

    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def calculate_stochastic(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3
) -> Tuple[pd.Series, pd.Series]:
    """
    计算随机指标 (Stochastic Oscillator)

    Args:
        df: DataFrame包含High, Low, Close列
        k_period: %K周期
        d_period: %D周期

    Returns:
        (%K, %D)
    """
    lowest_low = df["Low"].rolling(window=k_period, min_periods=k_period).min()
    highest_high = df["High"].rolling(window=k_period, min_periods=k_period).max()

    k = 100 * (df["Close"] - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(window=d_period, min_periods=d_period).mean()

    return k, d


def calculate_adx(
    df: pd.DataFrame, period: int = 14
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    计算ADX (平均趋向指数)

    Args:
        df: DataFrame包含High, Low, Close列
        period: ADX周期

    Returns:
        (ADX, +DI, -DI)
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # 真实波幅
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # 方向移动
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    # 平滑
    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr

    # DX和ADX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()

    return adx, plus_di, minus_di


def add_all_indicators(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    kc_period: int = 20,
    kc_atr_mult: float = 1.5,
    atr_period: int = 14,
    rsi_period: int = 14,
    ema_fast: int = 20,
    ema_slow: int = 50,
    vwap_reset_hour: int = 17,
) -> pd.DataFrame:
    """
    添加所有指标到DataFrame

    Args:
        df: 原始OHLCV数据
        **kwargs: 指标参数

    Returns:
        添加指标后的DataFrame
    """
    result = df.copy()

    # 移动平均线
    result[f"EMA_{ema_fast}"] = calculate_ema(result["Close"], ema_fast)
    result[f"EMA_{ema_slow}"] = calculate_ema(result["Close"], ema_slow)

    # 布林带
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(
        result["Close"], bb_period, bb_std
    )
    result["BB_Upper"] = bb_upper
    result["BB_Middle"] = bb_middle
    result["BB_Lower"] = bb_lower
    result["BB_Width"] = (bb_upper - bb_lower) / bb_middle

    # 肯特纳通道
    kc_upper, kc_middle, kc_lower = calculate_keltner_channels(
        result, kc_period, kc_atr_mult
    )
    result["KC_Upper"] = kc_upper
    result["KC_Middle"] = kc_middle
    result["KC_Lower"] = kc_lower

    # 挤压指标（布林带在肯特纳通道内）
    result["Squeeze_On"] = (bb_upper < kc_upper) & (bb_lower > kc_lower)

    # ATR
    result["ATR"] = calculate_atr(result, atr_period)

    # RSI
    result["RSI"] = calculate_rsi(result["Close"], rsi_period)

    # VWAP
    if "Volume" in result.columns:
        result["VWAP"] = calculate_vwap(result, vwap_reset_hour)

    # MACD
    macd, signal, hist = calculate_macd(result["Close"])
    result["MACD"] = macd
    result["MACD_Signal"] = signal
    result["MACD_Hist"] = hist

    # ADX
    adx, plus_di, minus_di = calculate_adx(result, atr_period)
    result["ADX"] = adx
    result["Plus_DI"] = plus_di
    result["Minus_DI"] = minus_di

    return result
