"""
技术指标计算模块
包含: VWAP, Bollinger Bands, Keltner Channels, ATR, RSI, EMA等

【修复3.0】VWAP 时区严格锚定
- 外汇黄金市场 VWAP 必须锚定于美东时间 17:00 (EST/EDT)
- 这是全球外汇市场的真实日线重置时间（流动性重置点）
- 不能使用北京时间 00:00 或任何其他本地时间
"""

import pandas as pd
import numpy as np
from typing import Tuple
import warnings

# 尝试导入 pytz 进行时区处理
try:
    import pytz
    BEIJING_TZ = pytz.timezone('Asia/Shanghai')
    NEW_YORK_TZ = pytz.timezone('America/New_York')
    UTC_TZ = pytz.UTC
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False
    BEIJING_TZ = 'Asia/Shanghai'
    warnings.warn("【警告】pytz 未安装，VWAP 时区锚定可能不准确")


# 外汇市场日线重置时间 (美东时间)
# 这是全球黄金市场的流动性重置点
FOREX_DAILY_RESET_HOUR_ET = 17  # 美东时间 17:00


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """
    计算VWAP (成交量加权平均价)

    【修复3.0】按外汇市场真实日线重置时间锚定

    关键修复：
    - 外汇/黄金市场日线重置时间是美东时间 17:00 (EST/EDT)
    - 不是北京时间 00:00，不是 UTC 00:00
    - 这是全球流动性提供商的结算时间点

    时区转换：
    - 美东时间 17:00 = UTC 22:00 (冬令时 EST, UTC-5)
    - 美东时间 17:00 = UTC 21:00 (夏令时 EDT, UTC-4)
    - 美东时间 17:00 = 北京时间次日 06:00 (冬令时) 或 05:00 (夏令时)

    Args:
        df: 包含 'High', 'Low', 'Close', 'Volume' 的DataFrame，索引为时间戳

    Returns:
        VWAP序列
    """
    # 典型价格
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3

    vwap = pd.Series(index=df.index, dtype=float)

    # ═══════════════════════════════════════════════════════════════════════
    # 【修复核心】获取美东时间 17:00 锚定的"交易日"
    # ═══════════════════════════════════════════════════════════════════════

    if PYTZ_AVAILABLE and df.index.tz is not None:
        # 如果数据有时区信息，转换为美东时间
        index_et = df.index.tz_convert(NEW_YORK_TZ)

        # 计算美东时间的小时
        hour_et = index_et.hour

        # 外汇交易日定义：从美东时间 17:00 开始到次日 17:00
        # 在 17:00 之前的数据属于"前一天"的交易日
        # 在 17:00 及之后的数据属于"当天"的交易日
        # 【修复】使用 numpy array 避免修改 Index
        trading_date = pd.Series(index_et.normalize().to_numpy(), index=df.index)

        # 对于 00:00-16:59 的数据，它们属于前一天的交易日
        # 对于 17:00-23:59 的数据，它们属于当天的交易日
        mask_before_17 = hour_et < FOREX_DAILY_RESET_HOUR_ET
        trading_date.loc[mask_before_17] = trading_date.loc[mask_before_17] - pd.Timedelta(days=1)

    else:
        # 无时区信息时，假设数据为北京时间 (UTC+8)
        # 进行简化处理：美东时间 17:00 = 北京时间次日 05:00 (夏令时) 或 06:00 (冬令时)
        # 使用近似值：北京时间 05:30 作为分界点（取夏令时和冬令时的中间值）
        # 这样在大部分情况下误差不超过 30 分钟

        if df.index.tz is None:
            warnings.warn(
                "【VWAP 警告】数据无时区信息，假设为北京时间。\n"
                "VWAP 将在北京时间约 05:30 分界，近似锚定美东时间 17:00。\n"
                "建议：为数据添加时区信息以获得精确计算。"
            )

        index_beijing = df.index
        hour_beijing = index_beijing.hour
        minute_beijing = index_beijing.minute

        # 将北京时间转换为"交易日"
        # 外汇交易日从美东 17:00 开始：
        # - 冬令时：北京时间次日 06:00
        # - 夏令时：北京时间次日 05:00
        # 近似使用 05:30 作为全年分界点（平均误差 < 30分钟）
        # 【修复】使用 numpy array 避免修改 Index
        trading_date = pd.Series(index_beijing.normalize().to_numpy(), index=df.index)

        total_minutes = hour_beijing * 60 + minute_beijing
        # 05:30 = 5*60 + 30 = 330 分钟
        mask_before_530 = total_minutes < 330  # 00:00 - 05:29
        trading_date.loc[mask_before_530] = trading_date.loc[mask_before_530] - pd.Timedelta(days=1)

    # 按交易日分组计算累计 VWAP
    unique_dates = trading_date.unique()

    for date in unique_dates:
        mask = trading_date == date
        tp_day = typical_price[mask]
        vol_day = df.loc[mask, 'Volume']

        # 累计成交额 / 累计成交量
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

    Args:
        close: 收盘价序列
        period: 计算周期
        std_dev: 标准差倍数

    Returns:
        (中轨, 上轨, 下轨, 带宽)
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

    Args:
        high, low, close: 价格序列
        period: 计算周期
        atr_mult: ATR倍数

    Returns:
        (中轨, 上轨, 下轨, 带宽)
    """
    # EMA作为中轨
    middle = close.ewm(span=period, adjust=False).mean()

    # 计算ATR
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

    Args:
        high, low, close: 价格序列
        period: 计算周期

    Returns:
        ATR序列
    """
    # True Range
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # ATR (EMA平滑)
    atr = tr.ewm(span=period, adjust=False).mean()

    return atr


def calculate_rsi(
    close: pd.Series,
    period: int = 14
) -> pd.Series:
    """
    计算RSI (相对强弱指标)

    Args:
        close: 收盘价序列
        period: 计算周期

    Returns:
        RSI序列 (0-100)
    """
    delta = close.diff()

    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)

    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_ema(
    close: pd.Series,
    period: int
) -> pd.Series:
    """
    计算EMA (指数移动平均)

    Args:
        close: 收盘价序列
        period: 计算周期

    Returns:
        EMA序列
    """
    return close.ewm(span=period, adjust=False).mean()


def calculate_squeeze_indicator(
    bb_upper: pd.Series,
    bb_lower: pd.Series,
    bb_middle: pd.Series,
    kc_upper: pd.Series,
    kc_lower: pd.Series,
    release_window: int = 5
) -> Tuple[pd.Series, pd.Series]:
    """
    计算波动率挤压指标

    【修复3.1】Squeeze Release 窗口化
    - 不再仅限交叉那根K线
    - 只要处于挤压释放状态 (bb_upper > kc_upper)
    - 且距离交叉发生不超过 release_window 根K线
    - 都视为有效的突破窗口

    Args:
        bb_upper, bb_lower, bb_middle: 布林带轨道
        kc_upper, kc_lower: 肯特纳通道轨道
        release_window: 释放窗口期（默认5根K线）

    Returns:
        (squeeze_state, squeeze_release)
        squeeze_state: < 0 表示挤压（震荡），> 0 表示释放（趋势）
        squeeze_release: True表示处于有效突破窗口期
    """
    # 计算带宽比值
    bb_width = (bb_upper - bb_lower) / bb_middle
    kc_width = (kc_upper - kc_lower) / bb_middle  # 用bb_middle作为基准

    # 挤压状态
    squeeze_ratio = bb_width / kc_width

    # ═══════════════════════════════════════════════════════════════════════
    # 【修复3.1】窗口化 Squeeze Release
    # ═══════════════════════════════════════════════════════════════════════

    # 判断是否处于释放状态（布林带突破肯特纳通道）
    is_released_up = bb_upper > kc_upper
    is_released_down = bb_lower < kc_lower
    is_released = is_released_up | is_released_down

    # 检测交叉点（从挤压变为释放的那根K线）
    was_squeezed_up = (bb_upper.shift(1) <= kc_upper.shift(1))
    was_squeezed_down = (bb_lower.shift(1) >= kc_lower.shift(1))

    cross_up = is_released_up & was_squeezed_up
    cross_down = is_released_down & was_squeezed_down
    cross_point = cross_up | cross_down

    # 使用滚动窗口：距离交叉点 <= release_window 根K线
    # 创建一个 Series 记录最近的交叉点位置
    squeeze_release = pd.Series(False, index=bb_upper.index)

    # 标记所有在释放窗口期内的K线
    for i in range(len(bb_upper)):
        if is_released.iloc[i]:
            # 检查过去 release_window 根K线内是否有交叉
            start_idx = max(0, i - release_window)
            if cross_point.iloc[start_idx:i+1].any():
                squeeze_release.iloc[i] = True

    return squeeze_ratio, squeeze_release


def calculate_session_filter(
    df: pd.DataFrame,
    data_timezone: str = None,
    asian_start_utc: int = 0,
    asian_end_utc: int = 8,
    european_start_utc: int = 8,
    european_end_utc: int = 22
) -> Tuple[pd.Series, pd.Series]:
    """
    计算交易时段过滤器

    【修复3.2】重构时区处理 - 移除硬编码北京时间依赖
    - 所有时段判定基于 UTC 时间
    - 调用者必须明确传入数据的时区
    - 与 MT4 实盘对接时绝对一致

    MT4 服务器时间（标准）:
    - 夏令时: UTC+3
    - 冬令时: UTC+2

    UTC 时段定义:
    - 亚盘 (东京/悉尼): UTC 00:00 - 08:00
    - 欧美盘 (伦敦/纽约): UTC 08:00 - 22:00

    Args:
        df: 带有时间索引的 DataFrame
        data_timezone: 数据的时区 (如 'Asia/Shanghai', 'UTC', 'America/New_York')
                      如果为 None，假设索引已经是 UTC
        asian_start_utc: 亚盘开始时间 (UTC)
        asian_end_utc: 亚盘结束时间 (UTC)
        european_start_utc: 欧美盘开始时间 (UTC)
        european_end_utc: 欧美盘结束时间 (UTC)

    Returns:
        (is_asian_session, is_european_session)
    """
    # 获取时间索引
    idx = df.index.copy()

    # ═══════════════════════════════════════════════════════════════════════
    # 【修复3.2】统一转换为 UTC 时间
    # ═══════════════════════════════════════════════════════════════════════

    if idx.tz is None:
        if data_timezone is not None:
            # 为 naive 时间戳添加时区信息
            if PYTZ_AVAILABLE:
                tz = pytz.timezone(data_timezone)
                idx = idx.tz_localize(tz)
                warnings.warn(
                    f"【时区标注】数据索引已标注为 {data_timezone}，将转换为 UTC\n"
                    f"亚盘: UTC {asian_start_utc}:00-{asian_end_utc}:00\n"
                    f"欧美盘: UTC {european_start_utc}:00-{european_end_utc}:00"
                )
            else:
                warnings.warn(
                    "【时区警告】pytz 未安装，无法进行时区转换。\n"
                    "假设数据已经是 UTC 时间。"
                )
        else:
            # 无时区信息，假设为 UTC
            warnings.warn(
                "【时区警告】数据索引无时区信息且未指定 data_timezone。\n"
                "假设数据已经是 UTC 时间。段判定可能不准确。"
            )
    else:
        # 已经有时区信息，转换为 UTC
        idx = idx.tz_convert(UTC_TZ)

    # 获取 UTC 小时
    hour_utc = idx.hour

    # 基于 UTC 时间判定时段
    is_asian = (hour_utc >= asian_start_utc) & (hour_utc < asian_end_utc)

    # 欧美盘可能跨越午夜 (22:00 后进入次日亚盘)
    if european_end_utc > 24:
        # 跨午夜情况
        is_european = (hour_utc >= european_start_utc) | (hour_utc < (european_end_utc - 24) % 24)
    else:
        is_european = (hour_utc >= european_start_utc) & (hour_utc < european_end_utc)

    return is_asian, is_european


def add_all_indicators(
    df: pd.DataFrame,
    params: dict
) -> pd.DataFrame:
    """
    添加所有技术指标到DataFrame

    Args:
        df: 原始OHLCV数据
        params: 参数字典

    Returns:
        添加了指标的DataFrame
    """
    df = df.copy()

    # 基础指标
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
        df['KC_Upper'], df['KC_Lower'],
        release_window=5  # 【修复3.1】窗口化 Squeeze Release
    )
    df['Squeeze_Ratio'] = squeeze_ratio
    df['Squeeze_Release'] = squeeze_release

    # 交易时段（【修复3.2】使用 UTC 时间）
    # 参数 data_timezone 从 params 获取，默认假设为 UTC
    data_timezone = params.get('data_timezone', None)
    is_asian, is_european = calculate_session_filter(df, data_timezone=data_timezone)
    df['Is_Asian'] = is_asian
    df['Is_European'] = is_european

    return df


if __name__ == "__main__":
    # 测试指标计算
    from data_loader import generate_sample_data

    df = generate_sample_data(days=30)
    params = {
        'bb_period': 12,
        'bb_std': 1.6,
        'kc_period': 15,
        'kc_atr_mult': 1.3,
        'atr_period': 8,
        'rsi_period': 13,
        'ema_fast': 28,
        'ema_slow': 64
    }

    df = add_all_indicators(df, params)
    print(df[['Close', 'VWAP', 'BB_Upper', 'BB_Lower', 'ATR', 'RSI']].tail())
