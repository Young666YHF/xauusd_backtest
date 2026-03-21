"""
技术指标计算模块
================
包含: VWAP, Bollinger Bands, Keltner Channels, ATR, RSI, EMA等
"""

import pandas as pd
import numpy as np
from typing import Tuple


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """
    计算VWAP (成交量加权平均价)
    每日重置
    """
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    dates = df.index.date
    vwap = pd.Series(index=df.index, dtype=float)

    unique_dates = np.unique(dates)
    for date in unique_dates:
        mask = dates == date
        tp_day = typical_price[mask]
        vol_day = df.loc[mask, 'Volume']
        cumulative_tp_vol = (tp_day * vol_day).cumsum()
        cumulative_vol = vol_day.cumsum()
        vwap[mask] = cumulative_tp_vol / cumulative_vol

    return vwap


def calculate_bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std_dev: float = 2.5
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    计算布林带
    Returns: (中轨, 上轨, 下轨, 带宽)
    """
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    bandwidth = (upper - lower) / middle
    return middle, upper, lower, bandwidth


def calculate_keltner_channels(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 20,
    atr_mult: float = 1.5
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    计算肯特纳通道
    Returns: (中轨, 上轨, 下轨, 带宽)
    """
    middle = close.ewm(span=period, adjust=False).mean()
    atr = calculate_atr(high, low, close, period)
    upper = middle + atr_mult * atr
    lower = middle - atr_mult * atr
    bandwidth = (upper - lower) / middle
    return middle, upper, lower, bandwidth


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> pd.Series:
    """
    计算ATR (真实波动幅度)
    """
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    计算RSI (相对强弱指标)
    Returns: RSI序列 (0-100)
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_ema(close: pd.Series, period: int) -> pd.Series:
    """
    计算EMA (指数移动平均)
    """
    return close.ewm(span=period, adjust=False).mean()


def calculate_squeeze_indicator(
    bb_upper: pd.Series,
    bb_lower: pd.Series,
    bb_middle: pd.Series,
    kc_upper: pd.Series,
    kc_lower: pd.Series
) -> Tuple[pd.Series, pd.Series]:
    """
    计算波动率挤压指标
    Returns: (squeeze_ratio, squeeze_release)
    """
    bb_width = (bb_upper - bb_lower) / bb_middle
    kc_width = (kc_upper - kc_lower) / bb_middle
    squeeze_ratio = bb_width / kc_width

    squeeze_release_up = (bb_upper > kc_upper) & (bb_upper.shift(1) <= kc_upper.shift(1))
    squeeze_release_down = (bb_lower < kc_lower) & (bb_lower.shift(1) >= kc_lower.shift(1))
    squeeze_release = squeeze_release_up | squeeze_release_down

    return squeeze_ratio, squeeze_release


def calculate_session_filter(
    df: pd.DataFrame,
    asian_start: int = 6,
    asian_end: int = 14,
    european_start: int = 15,
    european_end: int = 24
) -> Tuple[pd.Series, pd.Series]:
    """
    计算交易时段过滤器

    Args:
        df: 带时区感知时间索引的DataFrame
        asian_start, asian_end: 亚盘时段（北京时间）
        european_start, european_end: 欧美盘时段（北京时间）

    Returns:
        (is_asian_session, is_european_session)
    """
    hour = df.index.hour
    is_asian = (hour >= asian_start) & (hour < asian_end)
    is_european = (hour >= european_start) | (hour < (european_end - 24) % 24)
    return is_asian, is_european


def add_all_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    添加所有技术指标到DataFrame
    """
    df = df.copy()

    # VWAP
    df['VWAP'] = calculate_vwap(df)

    # 布林带
    bb_middle, bb_upper, bb_lower, bb_bandwidth = calculate_bollinger_bands(
        df['Close'],
        period=params.get('bb_period', 20),
        std_dev=params.get('bb_std', 2.5)
    )
    df['BB_Middle'] = bb_middle
    df['BB_Upper'] = bb_upper
    df['BB_Lower'] = bb_lower
    df['BB_Width'] = bb_bandwidth

    # 肯特纳通道
    kc_middle, kc_upper, kc_lower, kc_bandwidth = calculate_keltner_channels(
        df['High'], df['Low'], df['Close'],
        period=params.get('kc_period', 20),
        atr_mult=params.get('kc_atr_mult', 1.5)
    )
    df['KC_Middle'] = kc_middle
    df['KC_Upper'] = kc_upper
    df['KC_Lower'] = kc_lower
    df['KC_Width'] = kc_bandwidth

    # ATR
    df['ATR'] = calculate_atr(
        df['High'], df['Low'], df['Close'],
        period=params.get('atr_period', 14)
    )

    # RSI
    df['RSI'] = calculate_rsi(
        df['Close'],
        period=params.get('rsi_period', 14)
    )

    # EMA
    df['EMA_Fast'] = calculate_ema(
        df['Close'],
        period=params.get('ema_fast', 20)
    )
    df['EMA_Slow'] = calculate_ema(
        df['Close'],
        period=params.get('ema_slow', 50)
    )

    # 波动率挤压指标
    squeeze_ratio, squeeze_release = calculate_squeeze_indicator(
        df['BB_Upper'], df['BB_Lower'], df['BB_Middle'],
        df['KC_Upper'], df['KC_Lower']
    )
    df['Squeeze_Ratio'] = squeeze_ratio
    df['Squeeze_Release'] = squeeze_release

    # 交易时段
    is_asian, is_european = calculate_session_filter(df)
    df['Is_Asian'] = is_asian
    df['Is_European'] = is_european

    return df
