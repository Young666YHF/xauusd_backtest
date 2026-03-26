#!/usr/bin/env python3
"""
核心模块测试
============
测试核心组件的功能
"""

import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from core.types import TradeSignal, TradeDirection, SignalType, Position
from core.config import Config, StrategyConfig
from core.indicators import (
    calculate_sma, calculate_ema, calculate_atr,
    calculate_bollinger_bands, calculate_rsi
)


class TestTypes(unittest.TestCase):
    """测试数据类型"""

    def test_trade_signal_creation(self):
        """测试交易信号创建"""
        signal = TradeSignal(
            timestamp=datetime.now(),
            signal_type=SignalType.LONG,
            strategy_id='test',
            direction=TradeDirection.LONG,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2020.0
        )

        self.assertEqual(signal.direction, TradeDirection.LONG)
        self.assertEqual(signal.entry_price, 2000.0)

    def test_position_creation(self):
        """测试持仓创建"""
        pos = Position(
            entry_time=datetime.now(),
            entry_price=2000.0,
            direction=TradeDirection.LONG,
            size=1.0,
            strategy_id='test',
            stop_loss=1990.0
        )

        self.assertEqual(pos.direction, TradeDirection.LONG)
        self.assertEqual(pos.entry_price, 2000.0)

        # 测试价格更新
        pos.update_price(2010.0)
        self.assertEqual(pos.highest_price, 2010.0)
        self.assertEqual(pos.unrealized_pnl, 10.0 * 100)  # 100是合约大小


class TestIndicators(unittest.TestCase):
    """测试技术指标"""

    def setUp(self):
        """设置测试数据"""
        dates = pd.date_range(start='2025-01-01', periods=100, freq='1H')
        np.random.seed(42)

        self.df = pd.DataFrame({
            'Open': 2000 + np.random.randn(100).cumsum(),
            'High': 2000 + np.random.randn(100).cumsum() + 5,
            'Low': 2000 + np.random.randn(100).cumsum() - 5,
            'Close': 2000 + np.random.randn(100).cumsum(),
            'Volume': np.random.randint(1000, 10000, 100)
        }, index=dates)

        # 确保High >= Low
        self.df['High'] = self.df[['Open', 'High', 'Low', 'Close']].max(axis=1) + 1
        self.df['Low'] = self.df[['Open', 'High', 'Low', 'Close']].min(axis=1) - 1

    def test_sma(self):
        """测试SMA计算"""
        sma = calculate_sma(self.df['Close'], 20)
        self.assertEqual(len(sma), len(self.df))
        self.assertTrue(sma.iloc[19:].notna().all())
        self.assertTrue(sma.iloc[:19].isna().all())

    def test_ema(self):
        """测试EMA计算"""
        ema = calculate_ema(self.df['Close'], 20)
        self.assertEqual(len(ema), len(self.df))
        self.assertTrue(ema.iloc[19:].notna().all())

    def test_atr(self):
        """测试ATR计算"""
        atr = calculate_atr(self.df, 14)
        self.assertEqual(len(atr), len(self.df))
        self.assertTrue((atr.iloc[14:] > 0).all())

    def test_bollinger_bands(self):
        """测试布林带计算"""
        upper, middle, lower = calculate_bollinger_bands(self.df['Close'], 20, 2.0)

        self.assertEqual(len(upper), len(self.df))
        self.assertTrue((upper.iloc[19:] > middle.iloc[19:]).all())
        self.assertTrue((middle.iloc[19:] > lower.iloc[19:]).all())

    def test_rsi(self):
        """测试RSI计算"""
        rsi = calculate_rsi(self.df['Close'], 14)

        self.assertEqual(len(rsi), len(self.df))
        self.assertTrue((rsi.iloc[14:] >= 0).all())
        self.assertTrue((rsi.iloc[14:] <= 100).all())


class TestConfig(unittest.TestCase):
    """测试配置"""

    def test_default_config(self):
        """测试默认配置"""
        config = Config()

        self.assertEqual(config.trading.symbol, 'XAUUSD')
        self.assertEqual(config.trading.initial_capital, 100000.0)
        self.assertEqual(config.strategy.bb_period, 20)

    def test_strategy_config_validation(self):
        """测试策略配置验证"""
        # 有效配置
        valid_config = StrategyConfig(ema_fast=20, ema_slow=50)
        self.assertEqual(valid_config.ema_fast, 20)

        # 无效配置（ema_slow <= ema_fast）
        with self.assertRaises(ValueError):
            StrategyConfig(ema_fast=50, ema_slow=20)


class TestRiskManager(unittest.TestCase):
    """测试风险管理器"""

    def setUp(self):
        from core.risk_manager import RiskManager
        self.rm = RiskManager(
            max_position_size=2.0,
            max_daily_loss_pct=0.02,
            risk_per_trade_pct=0.01
        )

    def test_position_size_calculation(self):
        """测试仓位计算"""
        size = self.rm.calculate_position_size(
            capital=100000,
            entry_price=2000.0,
            stop_loss=1990.0,
            atr=5.0
        )

        self.assertGreater(size, 0)
        self.assertLessEqual(size, 2.0)

    def test_stop_loss_calculation(self):
        """测试止损计算"""
        stop = self.rm.calculate_stop_loss(
            entry_price=2000.0,
            direction=1,
            atr=5.0,
            multiplier=1.5
        )

        self.assertEqual(stop, 2000.0 - 5.0 * 1.5)


if __name__ == '__main__':
    unittest.main()
