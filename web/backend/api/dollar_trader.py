"""
美元策略回测API路由
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import pandas as pd
from pathlib import Path
import sys
import os
import logging

# 添加项目根目录到路径
backend_dir = os.path.dirname(os.path.dirname(__file__))
project_root = os.path.dirname(backend_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from strategies.dollar_trader import (
    DollarTraderStrategy,
    calculate_dollar_trader_indicators,
)
from core.config import TradingConfig, get_config
from engines.dollar_trader_engine import DollarTraderBacktestEngine
from core.types import TradeDirection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dollar-trader", tags=["dollar-trader"])


class DollarTraderBacktestRequest(BaseModel):
    """美元策略回测请求"""

    sma_short: int = 20
    sma_medium: int = 50
    sma_long: int = 200
    risk_per_trade: float = 0.02
    start_date: str
    end_date: str
    initial_capital: float = 100000.0
    contract_size: int = 100
    spread_per_lot: float = 60.0


class TradeRecord(BaseModel):
    """交易记录"""

    entry_time: str
    exit_time: str
    direction: str
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    bars_held: int
    exit_reason: str


class EquityPoint(BaseModel):
    """权益点"""

    timestamp: str
    equity: float


class BacktestResult(BaseModel):
    """回测结果"""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_return: float
    avg_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    long_trades: int
    short_trades: int
    signal_exits: int
    final_capital: float


class DollarTraderBacktestResponse(BaseModel):
    """美元策略回测响应"""

    success: bool
    result: Optional[BacktestResult] = None
    equity_curve: Optional[List[EquityPoint]] = None
    trades: Optional[List[TradeRecord]] = None
    error: Optional[str] = None


def load_kline_data(data_dir: str, start_date: str, end_date: str) -> pd.DataFrame:
    """从本地K线数据加载OHLCV"""
    kline_dir = Path(data_dir) / "kline" / "15m"

    # 获取月份列表
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    months = []
    current = start_dt.replace(day=1)
    while current <= end_dt:
        months.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    dfs = []
    for month_str in months:
        filepath = kline_dir / f"XAUUSD_BID_15m_{month_str.replace('-', '')}.csv"
        if filepath.exists():
            df = pd.read_csv(filepath, index_col=0, parse_dates=True)
            dfs.append(df)

    if not dfs:
        raise ValueError("没有成功加载任何数据")

    ohlc_df = pd.concat(dfs)
    ohlc_df = ohlc_df.sort_index()
    ohlc_df = ohlc_df[~ohlc_df.index.duplicated(keep="first")]
    ohlc_df = ohlc_df.loc[start_date:end_date]

    return ohlc_df


@router.post("/backtest", response_model=DollarTraderBacktestResponse)
async def run_backtest(request: DollarTraderBacktestRequest):
    """运行美元策略回测"""
    try:
        # 加载数据（使用服务端配置，忽略用户传入的路径）
        data_dir = get_config().data.data_dir
        ohlc_df = load_kline_data(data_dir, request.start_date, request.end_date)

        if len(ohlc_df) == 0:
            return DollarTraderBacktestResponse(
                success=False, error="没有加载到数据，请检查日期范围和data目录"
            )

        # 计算指标
        ohlc_df = calculate_dollar_trader_indicators(
            ohlc_df,
            sma_short=request.sma_short,
            sma_medium=request.sma_medium,
            sma_long=request.sma_long,
        )

        # 创建策略
        strategy_params = {
            "sma_short": request.sma_short,
            "sma_medium": request.sma_medium,
            "sma_long": request.sma_long,
            "position_size": None,
            "risk_per_trade": request.risk_per_trade,
        }
        strategy = DollarTraderStrategy(
            params=strategy_params, strategy_id="DollarTrader"
        )

        # 配置
        config = TradingConfig(
            initial_capital=request.initial_capital,
            contract_size=request.contract_size,
            spread_per_ounce=request.spread_per_lot / request.contract_size,
        )

        # 计算信号
        signals = []
        warmup_bars = strategy.params["sma_long"] + 5
        for i in range(warmup_bars, len(ohlc_df)):
            signal = strategy.generate_signal(ohlc_df, i)
            if signal:
                signals.append(signal)

        # 执行回测
        engine = DollarTraderBacktestEngine(config)
        result = engine.run(ohlc_df, signals)

        # 构建响应
        equity_curve = [
            EquityPoint(timestamp=ts.isoformat(), equity=eq)
            for ts, eq in zip(result.equity_timestamps, result.equity_curve)
        ]

        trades = [
            TradeRecord(
                entry_time=(
                    t.entry_time.isoformat()
                    if hasattr(t.entry_time, "isoformat")
                    else str(t.entry_time)
                ),
                exit_time=(
                    t.exit_time.isoformat()
                    if hasattr(t.exit_time, "isoformat")
                    else str(t.exit_time)
                ),
                direction=t.direction.name,
                entry_price=t.entry_price,
                exit_price=t.exit_price,
                pnl=t.pnl,
                pnl_pct=t.pnl_pct * 100,
                bars_held=t.bars_held,
                exit_reason=t.exit_reason.name,
            )
            for t in result.trades
        ]

        backtest_result = BacktestResult(
            total_trades=result.total_trades,
            winning_trades=result.winning_trades,
            losing_trades=result.losing_trades,
            win_rate=result.win_rate * 100,
            total_pnl=result.total_pnl,
            total_return=result.total_return * 100,
            avg_pnl=result.avg_pnl,
            avg_win=result.avg_win,
            avg_loss=result.avg_loss,
            profit_factor=result.profit_factor,
            max_drawdown=result.max_drawdown,
            max_drawdown_pct=result.max_drawdown_pct * 100,
            sharpe_ratio=result.sharpe_ratio,
            sortino_ratio=result.sortino_ratio,
            calmar_ratio=result.calmar_ratio,
            long_trades=result.strategy_stats.get("long_trades", 0),
            short_trades=result.strategy_stats.get("short_trades", 0),
            signal_exits=result.strategy_stats.get("signal_exits", 0),
            final_capital=result.final_capital,
        )

        return DollarTraderBacktestResponse(
            success=True,
            result=backtest_result,
            equity_curve=equity_curve,
            trades=trades,
        )

    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return DollarTraderBacktestResponse(
            success=False,
            error="Internal server error. Please check your parameters and try again.",
        )


@router.get("/default-params")
async def get_default_params():
    """获取美元策略默认参数"""
    strategy = DollarTraderStrategy()
    return {
        "sma_short": strategy.params.get("sma_short", 20),
        "sma_medium": strategy.params.get("sma_medium", 50),
        "sma_long": strategy.params.get("sma_long", 200),
        "risk_per_trade": strategy.params.get("risk_per_trade", 0.02),
        "position_size": strategy.params.get("position_size", 1.0),
        "param_bounds": strategy.get_param_bounds(),
    }


@router.get("/presets")
async def get_presets():
    """获取美元策略预设配置"""
    return {
        "conservative": {
            "sma_short": 20,
            "sma_medium": 50,
            "sma_long": 200,
            "risk_per_trade": 0.01,
            "description": "保守配置 - 较低风险，较大止损",
        },
        "balanced": {
            "sma_short": 15,
            "sma_medium": 40,
            "sma_long": 150,
            "risk_per_trade": 0.02,
            "description": "平衡配置 - 标准SMA参数",
        },
        "aggressive": {
            "sma_short": 10,
            "sma_medium": 30,
            "sma_long": 100,
            "risk_per_trade": 0.03,
            "description": "激进配置 - 更快响应，更高风险",
        },
    }
