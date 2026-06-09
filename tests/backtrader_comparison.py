"""
Backtrader 对比验证脚本
======================
使用相同数据和策略参数，对比 Backtrader 与自定义框架的回测结果
"""

import sys

sys.path.insert(0, "/home/ctyun/xauusd_backtest")

import backtrader as bt
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ============================================
# Backtrader 策略实现
# ============================================


class BBWMartingaleStrategy(bt.Strategy):
    """
    BBW 过滤 + SMA 趋势跟踪 + 阶梯式马丁格尔

    与 Python 自定义框架完全一致的逻辑
    """

    params = (
        ("sma_short", 20),
        ("sma_medium", 50),
        ("sma_long", 200),
        ("bb_period", 36),
        ("bb_std", 2.0),
        ("bbw_ma_period", 84),
        ("position_size", 0.01),
        ("martingale_multiplier", 2.0),
        ("max_martingale_steps", 5),
        ("enable_overshoot", True),
        ("enable_undershoot", True),
        ("spread_per_ounce", 0.6),
        ("contract_size", 100),
        ("warmup_bars", 250),
        ("debug", False),  # 调试开关
    )

    def __init__(self):
        # SMA 指标
        self.sma_short = bt.indicators.SMA(self.data.close, period=self.p.sma_short)
        self.sma_medium = bt.indicators.SMA(self.data.close, period=self.p.sma_medium)
        self.sma_long = bt.indicators.SMA(self.data.close, period=self.p.sma_long)

        # 布林带
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_std
        )

        # BBW = (Upper - Lower) / Middle * 100
        self.bbw = (self.bb.top - self.bb.bot) / self.bb.mid * 100
        self.bbw_ma = bt.indicators.SMA(self.bbw, period=self.p.bbw_ma_period)

        # 马丁格尔状态
        self.martingale_step = 0
        self.loss_count_in_step = 0
        self.overshoot_count = 0
        self.undershoot_count = 0

        # 持仓状态追踪
        self.position_direction = None  # 'long' or 'short'

        # 前一根K线的指标值 (用于信号判断)
        self.prev_sma_s = None
        self.prev_sma_m = None
        self.prev_sma_l = None
        self.prev_close = None
        self.prev_bbw = None
        self.prev_bbw_ma = None

        # 前两根K线的 SMA (用于交叉判断)
        self.prev2_sma_s = None
        self.prev2_sma_m = None

        # 交易记录
        self.trades = []
        self.order = None

    def next(self):
        # 预热期
        if len(self.data) < self.p.warmup_bars:
            return

        # Backtrader 索引说明:
        # [0] = 当前K线
        # [-1] = 上一根K线
        # 这与 Python 列表索引相反！

        # 使用上一根K线判断信号 (避免未来函数)
        prev_close = self.data.close[-1]
        prev_sma_s = self.sma_short[-1]
        prev_sma_m = self.sma_medium[-1]
        prev_sma_l = self.sma_long[-1]
        prev_bbw = self.bbw[-1]
        prev_bbw_ma = self.bbw_ma[-1]

        # 前两根K线的 SMA (用于交叉判断)
        prev2_sma_s = self.sma_short[-2]
        prev2_sma_m = self.sma_medium[-2]

        # 检查指标有效性
        if np.isnan(prev_sma_s) or np.isnan(prev_sma_m) or np.isnan(prev_sma_l):
            return
        if np.isnan(prev_bbw) or np.isnan(prev_bbw_ma):
            return

        # 趋势判断 (基于上一根K线)
        is_bullish = (
            prev_close > prev_sma_s
            and prev_sma_s > prev_sma_m
            and prev_sma_m > prev_sma_l
        )

        is_bearish = (
            prev_close < prev_sma_s
            and prev_sma_s < prev_sma_m
            and prev_sma_m < prev_sma_l
        )

        # SMA 交叉判断
        sma_bearish_cross = (prev2_sma_s >= prev2_sma_m) and (prev_sma_s < prev_sma_m)
        sma_bullish_cross = (prev2_sma_s <= prev2_sma_m) and (prev_sma_s > prev_sma_m)

        # BBW 过滤
        bbw_allow = prev_bbw > prev_bbw_ma

        # 计算当前仓位大小
        current_position_size = self.p.position_size * (
            self.p.martingale_multiplier**self.martingale_step
        )

        # ============================================
        # 出场逻辑
        # ============================================
        if self.position:
            if self.position_direction == "long" and sma_bearish_cross:
                # 多头出场
                self.close()
                if is_bearish and bbw_allow:
                    # 反向开空
                    self.sell(size=current_position_size)
                    self.position_direction = "short"
                else:
                    self.position_direction = None

            elif self.position_direction == "short" and sma_bullish_cross:
                # 空头出场
                self.close()
                if is_bullish and bbw_allow:
                    # 反向开多
                    self.buy(size=current_position_size)
                    self.position_direction = "long"
                else:
                    self.position_direction = None

        # ============================================
        # 入场逻辑 (无持仓时)
        # ============================================
        else:
            if is_bullish and bbw_allow:
                self.buy(size=current_position_size)
                self.position_direction = "long"

            elif is_bearish and bbw_allow:
                self.sell(size=current_position_size)
                self.position_direction = "short"

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.order = None
            elif order.issell():
                self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            # 更新马丁格尔状态
            pnl = trade.pnl

            if pnl < 0:
                # 亏损
                self.loss_count_in_step += 1

                if self.loss_count_in_step >= 2:
                    if self.martingale_step < self.p.max_martingale_steps:
                        self.martingale_step += 1
                        self.loss_count_in_step = 0
                        if self.p.enable_undershoot and self.undershoot_count > 0:
                            self.undershoot_count -= 1
                    else:
                        if self.p.enable_overshoot:
                            self.overshoot_count += 1
                            self.loss_count_in_step = 0
            else:
                # 盈利
                self.loss_count_in_step = 0

                if self.p.enable_overshoot and self.overshoot_count > 0:
                    self.overshoot_count -= 1
                elif self.martingale_step > 0:
                    self.martingale_step -= 1
                else:
                    if self.p.enable_undershoot:
                        self.undershoot_count += 1

            # 记录交易
            self.trades.append(
                {
                    "entry_time": bt.num2date(trade.dtopen),
                    "exit_time": bt.num2date(trade.dtclose),
                    "direction": "long" if trade.size > 0 else "short",
                    "entry_price": trade.price,
                    "exit_price": (
                        trade.price + (trade.pnl / trade.size / self.p.contract_size)
                        if abs(trade.size) > 0
                        else 0
                    ),
                    "size": abs(trade.size),
                    "pnl": trade.pnl,
                }
            )


class SpreadCommission(bt.CommInfoBase):
    """点差成本模型"""

    params = (
        ("spread_per_ounce", 0.6),
        ("contract_size", 100),
        ("stocklike", False),
        ("commtype", bt.CommInfoBase.COMM_FIXED),
    )

    def _getcommission(self, size, price, pseudoexec):
        # 点差成本 = spread_per_ounce * contract_size * size
        return self.p.spread_per_ounce * self.p.contract_size * abs(size)


def run_backtrader_backtest(df, params):
    """运行 Backtrader 回测"""

    cerebro = bt.Cerebro()

    # 创建数据源
    data = bt.feeds.PandasData(
        dataname=df,
        datetime=None,  # 使用索引
        open="Open",
        high="High",
        low="Low",
        close="Close",
        volume="Volume",
        openinterest=-1,
    )
    cerebro.adddata(data)

    # 添加策略
    cerebro.addstrategy(BBWMartingaleStrategy, **params)

    # 设置资金
    cerebro.broker.setcash(100000)

    # 设置点差成本
    comminfo = SpreadCommission(
        spread_per_ounce=params.get("spread_per_ounce", 0.6),
        contract_size=params.get("contract_size", 100),
    )
    cerebro.broker.addcommissioninfo(comminfo)

    # 运行
    results = cerebro.run()
    strategy = results[0]

    return {
        "final_value": cerebro.broker.getvalue(),
        "trades": strategy.trades,
        "total_trades": len(strategy.trades),
        "martingale_step": strategy.martingale_step,
    }


if __name__ == "__main__":
    from dateutil.relativedelta import relativedelta

    # 加载数据
    print("=" * 70)
    print("Backtrader vs 自定义框架 对比验证")
    print("=" * 70)

    data_path = Path("/home/ctyun/xauusd_data/kline/30m")

    # 加载 2017-10 到 2018-01 的数据
    dfs = []
    for month in ["201710", "201711", "201712", "201801"]:
        filepath = data_path / f"XAUUSD_BID_30m_{month}.csv"
        if filepath.exists():
            df = pd.read_csv(filepath, index_col=0)
            df.index = pd.to_datetime(df.index, unit="ms")
            df.columns = [col.capitalize() for col in df.columns]
            dfs.append(df)

    df = pd.concat(dfs).sort_index()
    df = df[~df.index.duplicated(keep="first")]

    print(f"\n数据范围: {df.index[0]} ~ {df.index[-1]}")
    print(f"K线数量: {len(df)}")

    # 参数设置
    params = {
        "sma_short": 20,
        "sma_medium": 50,
        "sma_long": 200,
        "bb_period": 36,
        "bb_std": 2.0,
        "bbw_ma_period": 84,
        "position_size": 0.01,
        "martingale_multiplier": 2.0,
        "max_martingale_steps": 5,
        "enable_overshoot": True,
        "enable_undershoot": True,
        "spread_per_ounce": 0.6,
        "contract_size": 100,
    }

    print(f"\n策略参数:")
    print(f"  SMA: {params['sma_short']}/{params['sma_medium']}/{params['sma_long']}")
    print(f"  BB周期: {params['bb_period']}, BBW_MA周期: {params['bbw_ma_period']}")
    print(f"  基础仓位: {params['position_size']}")

    # ============================================
    # 运行 Backtrader 回测
    # ============================================
    print("\n" + "-" * 70)
    print("Backtrader 回测:")
    print("-" * 70)

    bt_result = run_backtrader_backtest(df, params)

    print(f"  总交易次数: {bt_result['total_trades']}")
    print(f"  最终权益: ${bt_result['final_value']:,.2f}")
    print(f"  总收益率: {(bt_result['final_value'] - 100000) / 100000 * 100:.2f}%")
    print(f"  最终马丁阶梯: {bt_result['martingale_step']}")

    if bt_result["trades"]:
        print(f"\n  前5笔交易:")
        for i, t in enumerate(bt_result["trades"][:5]):
            print(
                f"    {i+1}. {t['entry_time'].strftime('%Y/%m/%d %H:%M')} | {t['direction']} | "
                f"入场: {t['entry_price']:.2f} | PnL: ${t['pnl']:.2f}"
            )

    # ============================================
    # 运行自定义框架回测
    # ============================================
    print("\n" + "-" * 70)
    print("自定义框架回测:")
    print("-" * 70)

    from strategies.dollar_trader_martingale_adx import (
        DollarTraderMartingaleBBWStepStrategy,
        calculate_dollar_trader_martingale_bbw_indicators,
    )
    from engines.dollar_trader_engine import DollarTraderBacktestEngine
    from core.config import TradingConfig

    # 计算指标
    df_indicators = calculate_dollar_trader_martingale_bbw_indicators(
        df.copy(),
        sma_short=params["sma_short"],
        sma_medium=params["sma_medium"],
        sma_long=params["sma_long"],
        bb_period=params["bb_period"],
        bb_std=params["bb_std"],
        bbw_ma_period=params["bbw_ma_period"],
    )

    config = TradingConfig(
        symbol="XAUUSD",
        spread_per_ounce=params["spread_per_ounce"],
        initial_capital=100000,
    )

    strategy = DollarTraderMartingaleBBWStepStrategy(
        params={
            "sma_short": params["sma_short"],
            "sma_medium": params["sma_medium"],
            "sma_long": params["sma_long"],
            "position_size": params["position_size"],
            "martingale_multiplier": params["martingale_multiplier"],
            "max_martingale_steps": params["max_martingale_steps"],
            "bb_period": params["bb_period"],
            "bb_std": params["bb_std"],
            "bbw_ma_period": params["bbw_ma_period"],
            "enable_overshoot": params["enable_overshoot"],
            "enable_undershoot": params["enable_undershoot"],
        },
        strategy_id="DT_BBW_Compare",
    )

    engine = DollarTraderBacktestEngine(config)
    result = engine.run(df_indicators, signals=None, strategy=strategy)

    print(f"  总交易次数: {result.total_trades}")
    print(f"  最终权益: ${result.equity_curve[-1]:,.2f}")
    print(f"  总收益率: {result.total_return * 100:.2f}%")
    print(f"  最终马丁阶梯: {strategy.martingale_step}")

    if result.trades:
        print(f"\n  前5笔交易:")
        for i, t in enumerate(result.trades[:5]):
            print(
                f"    {i+1}. {t.entry_time.strftime('%Y/%m/%d %H:%M')} | {t.direction.name} | "
                f"入场: {t.entry_price:.2f} | PnL: ${t.pnl:.2f}"
            )

    # ============================================
    # 对比总结
    # ============================================
    print("\n" + "=" * 70)
    print("对比总结")
    print("=" * 70)
    print(f"{'指标':<20} {'Backtrader':>15} {'自定义框架':>15} {'差异':>10}")
    print("-" * 70)
    print(
        f"{'交易次数':<20} {bt_result['total_trades']:>15} {result.total_trades:>15} {bt_result['total_trades'] - result.total_trades:>10}"
    )
    print(
        f"{'总收益率':<20} {(bt_result['final_value']-100000)/1000:>14.2f}% {result.total_return*100:>14.2f}% {((bt_result['final_value']-100000)/1000 - result.total_return*100):>9.2f}%"
    )
    print(
        f"{'最终马丁阶梯':<20} {bt_result['martingale_step']:>15} {strategy.martingale_step:>15}"
    )
