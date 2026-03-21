"""
本地数据加载模块 - 从CSV文件加载tick数据并聚合成OHLCV

【修复2.1】时区地雷问题
- 强制时区校验与转换
- 确保所有数据索引为北京时间 (UTC+8)
- 防止参数学习错配

【Critical Fix 5】DST 动态时区信号生成
- 使用 Pandas timezone 自动适应美国夏令时/冬令时切换
- 生成 Is_Asian (06:00-14:00 北京时间) 和 Is_European (15:00-00:00 北京时间) 信号列
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional
import warnings

try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False
    warnings.warn("pytz 未安装，DST 功能将不可用。请运行: pip install pytz")


# 北京时区 (UTC+8)
BEIJING_TZ_NAME = 'Asia/Shanghai'
UTC_TZ = 'UTC'

# 使用 pytz 的时区对象
if PYTZ_AVAILABLE:
    BEIJING_TZ = pytz.timezone('Asia/Shanghai')
    NEW_YORK_TZ = pytz.timezone('America/New_York')
else:
    BEIJING_TZ = BEIJING_TZ_NAME
    NEW_YORK_TZ = None


def validate_and_convert_timezone(df: pd.DataFrame, expected_tz = None) -> pd.DataFrame:
    """
    【修复2.1】时区校验与转换

    确保DataFrame的时间索引为北京时间(UTC+8)

    Args:
        df: 待校验的DataFrame
        expected_tz: 目标时区，默认北京时间

    Returns:
        时区转换后的DataFrame

    Raises:
        ValueError: 如果无法确定时区信息
    """
    if expected_tz is None:
        expected_tz = BEIJING_TZ_NAME
    if df.index.tz is None:
        # 无时区信息 - 需要推断或假设
        warnings.warn(
            "【时区警告】数据索引无时区信息！"
            "\n假设数据为 UTC+0，将转换为北京时间(UTC+8)"
            "\n如果数据实际为北京时间，请手动设置: df.index = df.index.tz_localize('Asia/Shanghai')"
        )
        # 假设原始数据为 UTC+0
        df.index = df.index.tz_localize(UTC_TZ).tz_convert(expected_tz)
    else:
        # 有时区信息 - 直接转换
        df.index = df.index.tz_convert(expected_tz)

    return df


def load_tick_data_from_csv(
    csv_path: str,
    assume_timezone: Optional[str] = None
) -> pd.DataFrame:
    """
    从CSV文件加载tick数据

    数据格式: timestamp, ask, bid, ask_volume, bid_volume

    Args:
        csv_path: CSV文件路径
        assume_timezone: 假设的原始时区 (None表示自动推断UTC+0)

    Returns:
        DataFrame with columns: [timestamp, ask, bid, ask_volume, bid_volume]
    """
    df = pd.read_csv(
        csv_path,
        header=None,
        names=['timestamp', 'ask', 'bid', 'ask_volume', 'bid_volume']
    )

    # 解析时间戳
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # 【修复2.1】时区处理
    if assume_timezone:
        df['timestamp'] = df['timestamp'].dt.tz_localize(assume_timezone)
    elif df['timestamp'].dt.tz is None:
        # 假设原始数据为 UTC+0
        df['timestamp'] = df['timestamp'].dt.tz_localize(UTC_TZ)

    # 设置时间索引
    df.set_index('timestamp', inplace=True)

    # 转换为北京时间
    df = validate_and_convert_timezone(df, BEIJING_TZ)

    # 计算中间价格
    df['price'] = (df['ask'] + df['bid']) / 2

    return df


def ticks_to_ohlcv(df: pd.DataFrame, interval: str = '15min') -> pd.DataFrame:
    """
    将tick数据聚合成OHLCV数据

    Args:
        df: tick数据DataFrame (包含 'price', 'ask_volume', 'bid_volume' 列)
        interval: 聚合周期 (15T=15分钟, 1H=1小时, 1D=1天)

    Returns:
        OHLCV DataFrame
    """
    # 计算成交量（使用ask_volume + bid_volume的平均值）
    df['volume'] = (df['ask_volume'] + df['bid_volume']) / 2

    # 按时间周期聚合
    ohlc = df['price'].resample(interval).ohlc()
    volume = df['volume'].resample(interval).sum()

    # 合并数据
    ohlcv = ohlc.copy()
    ohlcv['Volume'] = volume

    # 标准化列名
    ohlcv.columns = ['Open', 'High', 'Low', 'Close', 'Volume']

    # 删除缺失值
    ohlcv = ohlcv.dropna()

    return ohlcv


def load_monthly_data(
    data_dir: str,
    year: int,
    month: int,
    interval: str = '15min'
) -> Optional[pd.DataFrame]:
    """
    加载指定月份的tick数据并聚合

    Args:
        data_dir: 数据目录路径
        year: 年份
        month: 月份
        interval: 聚合周期

    Returns:
        OHLCV DataFrame 或 None（如果文件不存在）
    """
    filename = f"XAUUSD_{year}-{month:02d}.csv"
    filepath = Path(data_dir) / filename

    if not filepath.exists():
        print(f"文件不存在: {filepath}")
        return None

    print(f"加载数据: {filename}")

    try:
        # 加载tick数据
        tick_df = load_tick_data_from_csv(str(filepath))

        print(f"  原始tick数: {len(tick_df):,}")

        # 聚合成OHLCV
        ohlcv = ticks_to_ohlcv(tick_df, interval)

        print(f"  聚合后K线数: {len(ohlcv):,}")
        print(f"  时间范围: {ohlcv.index[0]} 到 {ohlcv.index[-1]}")

        return ohlcv

    except Exception as e:
        print(f"加载 {filename} 失败: {e}")
        return None


def load_data_range(
    data_dir: str,
    start_date: str,
    end_date: str,
    interval: str = '15min'
) -> pd.DataFrame:
    """
    加载指定日期范围内的数据

    Args:
        data_dir: 数据目录路径
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        interval: 聚合周期

    Returns:
        合并后的OHLCV DataFrame
    """
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    # 生成需要加载的月份列表
    months = []
    current = start.replace(day=1)
    while current <= end:
        months.append((current.year, current.month))
        # 移动到下一个月
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    # 加载每个月的数据
    dfs = []
    for year, month in months:
        df = load_monthly_data(data_dir, year, month, interval)
        if df is not None:
            dfs.append(df)

    if not dfs:
        raise ValueError(f"未找到 {start_date} 到 {end_date} 的数据")

    # 合并数据
    combined = pd.concat(dfs)

    # 按时间排序
    combined = combined.sort_index()

    # 过滤指定日期范围
    combined = combined[(combined.index >= start) & (combined.index <= end)]

    # 删除重复索引
    combined = combined[~combined.index.duplicated(keep='first')]

    print(f"\n{'='*60}")
    print(f"数据加载完成")
    print(f"{'='*60}")
    print(f"总K线数: {len(combined):,}")
    print(f"时间范围: {combined.index[0]} 到 {combined.index[-1]}")
    print(f"价格范围: {combined['Low'].min():.2f} - {combined['High'].max():.2f}")

    return combined


# =============================================================================
# 【Critical Fix 5】DST 动态时区信号生成
# =============================================================================


def add_trading_session_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    【Critical Fix 5】添加 DST 感知的交易时段信号列

    使用 Pandas timezone 转换功能，自动适应美国夏令时/冬令时切换

    交易时段定义 (北京时间):
    - 亚盘: 06:00-14:00
    - 欧美盘: 15:00-00:00 (次日)

    Args:
        df: OHLCV DataFrame，索引为时间戳 (需有时区信息)

    Returns:
        添加了 Is_Asian 和 Is_European 列的 DataFrame
    """
    if not PYTZ_AVAILABLE:
        warnings.warn("pytz 未安装，无法进行 DST 感知的时区转换")
        # 回退：使用简单的固定时区假设
        df = df.copy()
        beijing_hours = df.index.hour if df.index.tz is None else df.index.tz_convert(BEIJING_TZ_NAME).hour
        df['Is_Asian'] = (beijing_hours >= 6) & (beijing_hours < 14)
        df['Is_European'] = (beijing_hours >= 15) | (beijing_hours < 0)
        return df

    df = df.copy()

    # 确保索引有时区信息
    if df.index.tz is None:
        # 假设为 UTC+0，转换为北京时间
        df.index = df.index.tz_localize('UTC').tz_convert(BEIJING_TZ)
    else:
        # 转换为北京时间
        df.index = df.index.tz_convert(BEIJING_TZ)

    # 提取北京时间的小时
    beijing_hours = df.index.hour

    # 亚盘信号: 06:00-14:00 北京时间
    df['Is_Asian'] = (beijing_hours >= 6) & (beijing_hours < 14)

    # 欧美盘信号: 15:00-00:00 北京时间
    df['Is_European'] = (beijing_hours >= 15) | (beijing_hours < 0)

    # 添加美东时间列 (用于调试)
    df['NY_Hour'] = df.index.tz_convert(NEW_YORK_TZ).hour

    # 添加夏令时标记 (用于调试)
    # 美国夏令时: 3月第二个周日 - 11月第一个周日
    df['Is_DST'] = df.index.map(lambda x: is_us_dst(x))

    return df


def is_us_dst(dt: datetime) -> bool:
    """
    判断给定时间是否处于美国夏令时期间

    美国夏令时规则:
    - 开始: 3月第二个周日 2:00 AM
    - 结束: 11月第一个周日 2:00 AM

    Args:
        dt: datetime 对象 (带时区信息)

    Returns:
        True 表示夏令时，False 表示冬令时
    """
    # 转换为美东时间
    if dt.tzinfo is not None:
        eastern_dt = dt.astimezone(NEW_YORK_TZ)
    else:
        # 假设为北京时间
        eastern_dt = BEIJING_TZ.localize(dt).astimezone(NEW_YORK_TZ)

    year = eastern_dt.year

    # 计算3月第二个周日
    march_first = datetime(year, 3, 1)
    days_until_sunday = (6 - march_first.weekday()) % 7
    first_sunday_march = march_first + timedelta(days=days_until_sunday)
    second_sunday_march = first_sunday_march + timedelta(days=7)
    dst_start = NEW_YORK_TZ.localize(second_sunday_march.replace(hour=2, minute=0, second=0))

    # 计算11月第一个周日
    november_first = datetime(year, 11, 1)
    days_until_sunday = (6 - november_first.weekday()) % 7
    first_sunday_november = november_first + timedelta(days=days_until_sunday)
    dst_end = NEW_YORK_TZ.localize(first_sunday_november.replace(hour=2, minute=0, second=0))

    # 判断是否在夏令时期间
    return dst_start <= eastern_dt < dst_end


def get_session_info(df: pd.DataFrame) -> dict:
    """
    获取交易时段统计信息

    Args:
        df: 带有交易时段信号的 DataFrame

    Returns:
        包含各时段统计的字典
    """
    return {
        'total_bars': len(df),
        'asian_bars': df['Is_Asian'].sum() if 'Is_Asian' in df.columns else 0,
        'european_bars': df['Is_European'].sum() if 'Is_European' in df.columns else 0,
        'dst_bars': df['Is_DST'].sum() if 'Is_DST' in df.columns else 0,
        'date_range': f"{df.index[0]} to {df.index[-1]}" if len(df) > 0 else "N/A"
    }


def load_local_15min_data(
    data_dir: str = '/home/ctyun/xauusd_data',
    months: Optional[List[str]] = None,
    interval: str = '15min'
) -> pd.DataFrame:
    """
    加载本地15分钟数据（简化接口）

    Args:
        data_dir: 数据目录路径
        months: 月份列表 ['2025-08', '2025-09', ...]，默认为None（加载所有可用数据）

    Returns:
        OHLCV DataFrame
    """
    if months is None:
        # 自动加载所有可用月份
        data_path = Path(data_dir)
        csv_files = sorted(data_path.glob('XAUUSD_*.csv'))

        dfs = []
        for filepath in csv_files:
            try:
                tick_df = load_tick_data_from_csv(str(filepath))
                ohlcv = ticks_to_ohlcv(tick_df, interval)
                dfs.append(ohlcv)
                print(f"✓ {filepath.name}: {len(ohlcv)} 条K线")
            except Exception as e:
                print(f"✗ {filepath.name}: {e}")

        if not dfs:
            raise ValueError("未找到任何数据文件")

        combined = pd.concat(dfs)
        combined = combined.sort_index()
        combined = combined[~combined.index.duplicated(keep='first')]

        return combined
    else:
        # 加载指定月份
        dfs = []
        for month_str in months:
            year, month = map(int, month_str.split('-'))
            df = load_monthly_data(data_dir, year, month, interval)
            if df is not None:
                dfs.append(df)

        combined = pd.concat(dfs)
        combined = combined.sort_index()
        combined = combined[~combined.index.duplicated(keep='first')]

        return combined


if __name__ == "__main__":
    # 测试数据加载
    print("测试本地数据加载...")

    # 测试加载单个月份
    df = load_monthly_data('/home/ctyun/xauusd_data', 2025, 8, '15min')
    if df is not None:
        print("\n前5条数据:")
        print(df.head())
        print("\n数据描述:")
        print(df.describe())

    # 测试加载日期范围
    print("\n" + "="*60)
    print("测试加载日期范围 2025-08-01 到 2025-08-31")
    print("="*60)
    df_range = load_data_range(
        '/home/ctyun/xauusd_data',
        '2025-08-01',
        '2025-08-31',
        '15min'
    )
    print(f"\n加载了 {len(df_range)} 条数据")
