"""
数据加载模块
============
支持多种数据源的加载和预处理
"""

import pandas as pd
import numpy as np
from typing import Optional, List, Union, Callable
from pathlib import Path
from datetime import datetime, timezone
import warnings


class DataLoader:
    """数据加载器基类"""

    def __init__(self, data_dir: str = "/home/ctyun/xauusd_data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        interval: str = "15min"
    ) -> pd.DataFrame:
        """
        加载数据（子类实现）

        Args:
            symbol: 品种代码
            start_date: 开始日期
            end_date: 结束日期
            interval: 时间周期

        Returns:
            OHLCV DataFrame
        """
        raise NotImplementedError

    def load_tick_data(
        self,
        filepath: Union[str, Path],
        keep_utc: bool = True
    ) -> pd.DataFrame:
        """
        加载Dukascopy格式的Tick数据

        Args:
            filepath: CSV文件路径
            keep_utc: 是否保持UTC时区

        Returns:
            Tick DataFrame (包含Bid, Ask, BidVolume, AskVolume)
        """
        filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(f"数据文件不存在: {filepath}")

        # 尝试读取CSV
        try:
            # 首先尝试带表头的格式
            df = pd.read_csv(filepath)

            # 检查列名
            if 'Gmt time' in df.columns:
                # Dukascopy格式
                df['Timestamp'] = pd.to_datetime(df['Gmt time'], format='%d.%m.%Y %H:%M:%S.%f')
                df = df.rename(columns={
                    'Ask': 'Ask',
                    'Bid': 'Bid',
                    'AskVolume': 'AskVolume',
                    'BidVolume': 'BidVolume'
                })
            elif 'timestamp' in df.columns:
                df['Timestamp'] = pd.to_datetime(df['timestamp'])
                df = df.rename(columns={
                    'ask': 'Ask',
                    'bid': 'Bid',
                    'ask_volume': 'AskVolume',
                    'bid_volume': 'BidVolume'
                })
            else:
                # 尝试无表头格式
                df = pd.read_csv(filepath, header=None)
                if len(df.columns) >= 5:
                    df.columns = ['Timestamp', 'Ask', 'Bid', 'AskVolume', 'BidVolume'] + [f'Col_{i}' for i in range(5, len(df.columns))]
                    df['Timestamp'] = pd.to_datetime(df['Timestamp'])

        except Exception as e:
            raise ValueError(f"无法解析数据文件 {filepath}: {e}")

        # 设置时间索引
        df.set_index('Timestamp', inplace=True)

        # 时区处理
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')

        if not keep_utc:
            df.index = df.index.tz_convert('Asia/Shanghai')

        return df

    def resample_to_ohlcv(
        self,
        tick_df: pd.DataFrame,
        interval: str = "15min",
        price_col: str = "Mid"
    ) -> pd.DataFrame:
        """
        将Tick数据重采样为OHLCV

        Args:
            tick_df: Tick数据
            interval: 目标周期
            price_col: 价格列名（如果为Mid则自动计算）

        Returns:
            OHLCV DataFrame
        """
        df = tick_df.copy()

        # 计算中间价（如果没有）
        if price_col == "Mid" and "Mid" not in df.columns:
            df["Mid"] = (df["Bid"] + df["Ask"]) / 2

        # 重采样
        ohlcv = pd.DataFrame({
            'Open': df[price_col].resample(interval).first(),
            'High': df[price_col].resample(interval).max(),
            'Low': df[price_col].resample(interval).min(),
            'Close': df[price_col].resample(interval).last(),
            'Volume': df.get('AskVolume', pd.Series(0, index=df.index)).resample(interval).sum() +
                      df.get('BidVolume', pd.Series(0, index=df.index)).resample(interval).sum()
        })

        # 删除空值
        ohlcv.dropna(inplace=True)

        return ohlcv

    def load_monthly_data(
        self,
        year: int,
        month: int,
        interval: str = "15min"
    ) -> pd.DataFrame:
        """
        加载单月数据

        Args:
            year: 年份
            month: 月份
            interval: 目标周期

        Returns:
            OHLCV DataFrame
        """
        filename = f"XAUUSD_{year}-{month:02d}.csv"
        filepath = self.data_dir / filename

        if not filepath.exists():
            raise FileNotFoundError(f"数据文件不存在: {filepath}")

        tick_df = self.load_tick_data(filepath)
        return self.resample_to_ohlcv(tick_df, interval)

    def load_range(
        self,
        months: List[str],
        interval: str = "15min"
    ) -> pd.DataFrame:
        """
        加载多个月份的数据

        Args:
            months: 月份列表，格式 ["2025-01", "2025-02", ...]
            interval: 目标周期

        Returns:
            合并后的OHLCV DataFrame
        """
        dfs = []

        for month_str in months:
            try:
                year, month = map(int, month_str.split('-'))
                df = self.load_monthly_data(year, month, interval)
                dfs.append(df)
            except FileNotFoundError:
                warnings.warn(f"跳过不存在的文件: {month_str}")
                continue
            except Exception as e:
                warnings.warn(f"加载 {month_str} 失败: {e}")
                continue

        if not dfs:
            raise ValueError("没有成功加载任何数据")

        combined = pd.concat(dfs)
        combined = combined.sort_index()
        combined = combined[~combined.index.duplicated(keep='first')]

        return combined


class CSVDataLoader(DataLoader):
    """CSV文件数据加载器"""

    def load(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        interval: str = "15min"
    ) -> pd.DataFrame:
        """
        从CSV加载OHLCV数据

        支持格式：
        - 标准OHLCV格式（Open, High, Low, Close, Volume）
        - Yahoo Finance格式
        """
        filepath = self.data_dir / f"{symbol}.csv"

        if not filepath.exists():
            raise FileNotFoundError(f"数据文件不存在: {filepath}")

        df = pd.read_csv(filepath, index_col=0, parse_dates=True)

        # 标准化列名
        column_mapping = {
            'Open': 'Open',
            'High': 'High',
            'Low': 'Low',
            'Close': 'Close',
            'Volume': 'Volume',
            'Adj Close': 'Close'
        }

        df = df.rename(columns=column_mapping)

        # 确保必要列存在
        required_cols = ['Open', 'High', 'Low', 'Close']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"缺少必要列: {missing}")

        # 添加Volume列（如果不存在）
        if 'Volume' not in df.columns:
            df['Volume'] = 0

        # 日期过滤
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]

        return df


class ParquetDataLoader(DataLoader):
    """Parquet格式数据加载器（高性能）"""

    def load(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        interval: str = "15min"
    ) -> pd.DataFrame:
        """从Parquet加载数据"""
        filepath = self.data_dir / f"{symbol}.parquet"

        if not filepath.exists():
            raise FileNotFoundError(f"数据文件不存在: {filepath}")

        df = pd.read_parquet(filepath)

        # 日期过滤
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]

        return df


def create_data_loader(
    data_dir: str = "/home/ctyun/xauusd_data",
    format: str = "auto"
) -> DataLoader:
    """
    创建数据加载器

    Args:
        data_dir: 数据目录
        format: 数据格式 (csv, parquet, auto)

    Returns:
        DataLoader实例
    """
    if format == "csv":
        return CSVDataLoader(data_dir)
    elif format == "parquet":
        return ParquetDataLoader(data_dir)
    else:
        # 自动检测
        path = Path(data_dir)
        if any(path.glob("*.parquet")):
            return ParquetDataLoader(data_dir)
        else:
            return DataLoader(data_dir)
