"""
数据加载模块
============
支持从CSV加载Tick数据并聚合为OHLCV
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Tuple


def load_tick_data_from_csv(filepath: str) -> pd.DataFrame:
    """
    从CSV文件加载Tick数据

    Args:
        filepath: CSV文件路径

    Returns:
        DataFrame with columns: bid, ask, volume
        Index: datetime
    """
    df = pd.read_csv(filepath)

    # 尝试不同的时间列名称
    time_col = None
    for col in ['timestamp', 'time', 'datetime', 'date']:
        if col in df.columns:
            time_col = col
            break

    if time_col is None:
        # 如果没有时间列，尝试使用第一列
        time_col = df.columns[0]

    df[time_col] = pd.to_datetime(df[time_col])
    df = df.set_index(time_col)
    df = df.sort_index()

    # 标准化列名
    column_mapping = {}
    for col in df.columns:
        col_lower = col.lower()
        if 'bid' in col_lower:
            column_mapping[col] = 'bid'
        elif 'ask' in col_lower:
            column_mapping[col] = 'ask'
        elif 'volume' in col_lower or 'vol' in col_lower:
            column_mapping[col] = 'volume'

    if column_mapping:
        df = df.rename(columns=column_mapping)

    # 如果没有volume列，创建一个默认值
    if 'volume' not in df.columns:
        df['volume'] = 1

    # 确保有bid和ask
    if 'bid' not in df.columns or 'ask' not in df.columns:
        # 尝试从其他列推断
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) >= 2:
            df['bid'] = df[numeric_cols[0]]
            df['ask'] = df[numeric_cols[1]]
        elif len(numeric_cols) == 1:
            df['bid'] = df[numeric_cols[0]]
            df['ask'] = df[numeric_cols[0]]

    return df[['bid', 'ask', 'volume']]


def ticks_to_ohlcv(ticks_df: pd.DataFrame, interval: str = '15min') -> pd.DataFrame:
    """
    将Tick数据聚合为OHLCV数据

    Args:
        ticks_df: Tick数据DataFrame
        interval: 聚合间隔

    Returns:
        OHLCV DataFrame
    """
    # 使用中间价计算OHLC
    mid_price = (ticks_df['bid'] + ticks_df['ask']) / 2

    ohlcv = pd.DataFrame()
    ohlcv['Open'] = mid_price.resample(interval).first()
    ohlcv['High'] = mid_price.resample(interval).max()
    ohlcv['Low'] = mid_price.resample(interval).min()
    ohlcv['Close'] = mid_price.resample(interval).last()
    ohlcv['Volume'] = ticks_df['volume'].resample(interval).sum()

    # 删除空值
    ohlcv = ohlcv.dropna()

    return ohlcv


def load_data_range(data_dir: str, start_date: str, end_date: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    加载指定日期范围的数据

    Args:
        data_dir: 数据目录
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        (ticks_df, ohlcv_df)
    """
    from pathlib import Path

    data_path = Path(data_dir)
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    # 生成月份列表
    months = []
    current = start.replace(day=1)
    while current <= end:
        months.append(current.strftime('%Y-%m'))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    all_ticks = []
    for m in months:
        filepath = data_path / f'XAUUSD_{m}.csv'
        if filepath.exists():
            tick_df = load_tick_data_from_csv(str(filepath))
            all_ticks.append(tick_df)

    if not all_ticks:
        raise ValueError(f"No data found for {start_date} to {end_date}")

    ticks_df = pd.concat(all_ticks).sort_index()
    ticks_df = ticks_df[~ticks_df.index.duplicated(keep='first')]

    # 过滤日期范围
    ticks_df = ticks_df[(ticks_df.index >= start) & (ticks_df.index <= end)]

    ohlcv_df = ticks_to_ohlcv(ticks_df, '15min')

    return ticks_df, ohlcv_df


def generate_sample_data(days: int = 60) -> pd.DataFrame:
    """
    生成模拟测试数据

    Args:
        days: 生成的天数

    Returns:
        OHLCV DataFrame
    """
    np.random.seed(42)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    # 生成15分钟K线
    n_bars = days * 24 * 4
    dates = pd.date_range(start=start_date, periods=n_bars, freq='15min')

    # 模拟价格
    base_price = 2000  # XAUUSD 基准价格
    returns = np.random.randn(n_bars) * 0.002
    prices = base_price * np.cumprod(1 + returns)

    # 生成OHLCV
    df = pd.DataFrame(index=dates)
    df['Open'] = prices
    df['High'] = prices * (1 + np.abs(np.random.randn(n_bars)) * 0.001)
    df['Low'] = prices * (1 - np.abs(np.random.randn(n_bars)) * 0.001)
    df['Close'] = prices * (1 + np.random.randn(n_bars) * 0.001)
    df['Volume'] = np.random.randint(100, 1000, n_bars)

    return df
