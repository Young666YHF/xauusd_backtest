"""
Backtest service - 重构版本
使用本地tick数据进行回测，支持新策略的所有修复
"""

import sys
import os
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import json

# Add parent directory to path for imports
# 需要添加 xauusd_backtest 根目录 (4层向上)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from data_loader import load_tick_data_from_csv, ticks_to_ohlcv, load_data_range
from indicators import add_all_indicators
from strategy import TradingStrategy
from tick_engine import TickBacktestEngine
from backtest import BacktestEngine
from config import DEFAULT_PARAMS, PARAM_BOUNDS
from optuna_optimizer import run_optuna_optimization, OPTIMIZATION_BOUNDS

# 数据目录配置
DATA_DIR = '/home/ctyun/xauusd_data'
PRESETS_FILE = Path(__file__).parent.parent / 'data' / 'presets.json'

# 默认参数（来自 config.py，已是tick优化后的最优参数）
REFACTORED_DEFAULT_PARAMS = DEFAULT_PARAMS.copy()

# 参数边界（使用 optuna_optimizer 的完整边界）
REFACTORED_PARAM_BOUNDS = OPTIMIZATION_BOUNDS.copy()


def load_presets() -> Dict[str, Any]:
    """加载保存的参数预设"""
    if PRESETS_FILE.exists():
        with open(PRESETS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_presets(presets: Dict[str, Any]):
    """保存参数预设"""
    PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PRESETS_FILE, 'w') as f:
        json.dump(presets, f, indent=2)


def save_preset(name: str, params: Dict[str, Any], description: str = "") -> bool:
    """保存一个参数预设"""
    presets = load_presets()
    presets[name] = {
        'params': params,
        'description': description,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    save_presets(presets)
    return True


def delete_preset(name: str) -> bool:
    """删除一个参数预设"""
    presets = load_presets()
    if name in presets:
        del presets[name]
        save_presets(presets)
        return True
    return False


def get_preset(name: str) -> Optional[Dict[str, Any]]:
    """获取单个预设"""
    presets = load_presets()
    return presets.get(name)


def list_presets() -> Dict[str, Any]:
    """列出所有预设"""
    return load_presets()


class BacktestService:
    """Service for running tick-level backtests with refactored strategy"""

    def __init__(self):
        self._data_cache: Dict[str, pd.DataFrame] = {}
        self._tick_cache: Dict[str, pd.DataFrame] = {}

    def get_available_data_info(self, interval: str = "15m") -> Dict[str, Any]:
        """获取本地可用数据的信息"""
        data_path = Path(DATA_DIR)
        csv_files = sorted(data_path.glob('XAUUSD_*.csv'))

        if not csv_files:
            return {
                "interval": interval,
                "available_months": [],
                "bars_count": 0,
                "start_date": None,
                "end_date": None,
                "has_real_data": False
            }

        months = []
        for f in csv_files:
            parts = f.stem.split('_')
            if len(parts) == 2:
                months.append(parts[1])

        try:
            first_file = csv_files[0]
            df_sample = load_tick_data_from_csv(str(first_file))
            start_date = df_sample.index[0].strftime("%Y-%m-%d %H:%M")

            last_file = csv_files[-1]
            df_sample = load_tick_data_from_csv(str(last_file))
            end_date = df_sample.index[-1].strftime("%Y-%m-%d %H:%M")

            return {
                "interval": interval,
                "available_months": months,
                "bars_count": len(csv_files),
                "start_date": start_date,
                "end_date": end_date,
                "has_real_data": True,
                "data_source": "local_tick",
                "refactored_version": True  # 标记为重构版本
            }
        except Exception as e:
            return {
                "interval": interval,
                "available_months": months,
                "bars_count": 0,
                "start_date": None,
                "end_date": None,
                "has_real_data": False,
                "error": str(e)
            }

    def get_data(
        self,
        start_date: str,
        end_date: str,
        interval: str = "15m"
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
        """
        Get tick data and OHLCV data for backtest

        Returns:
            (ticks_df, ohlcv_df, info)
        """
        cache_key = f"{start_date}_{end_date}"

        info = {
            "start_date": start_date,
            "end_date": end_date,
            "interval": interval,
            "data_source": "local_tick"
        }

        if cache_key not in self._tick_cache:
            import pandas as pd
            from pathlib import Path

            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)

            months = []
            current = start.replace(day=1)
            while current <= end:
                months.append((current.year, current.month))
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)

            all_ticks = []
            for year, month in months:
                filename = f"XAUUSD_{year}-{month:02d}.csv"
                filepath = Path(DATA_DIR) / filename

                if filepath.exists():
                    tick_df = load_tick_data_from_csv(str(filepath))
                    tick_df = tick_df[(tick_df.index >= start) & (tick_df.index <= end)]
                    if len(tick_df) > 0:
                        all_ticks.append(tick_df)

            if not all_ticks:
                raise ValueError(f"No data found for {start_date} to {end_date}")

            ticks_df = pd.concat(all_ticks)
            ticks_df = ticks_df.sort_index()
            ticks_df = ticks_df[~ticks_df.index.duplicated(keep='first')]

            ohlcv_df = ticks_to_ohlcv(ticks_df, interval)

            self._tick_cache[cache_key] = ticks_df
            self._data_cache[cache_key] = ohlcv_df

            info["total_ticks"] = len(ticks_df)
            info["ohlcv_bars"] = len(ohlcv_df)
        else:
            ticks_df = self._tick_cache[cache_key]
            ohlcv_df = self._data_cache[cache_key]
            info["total_ticks"] = len(ticks_df)
            info["ohlcv_bars"] = len(ohlcv_df)

        return ticks_df.copy(), ohlcv_df.copy(), info

    def run_backtest(
        self,
        parameters: Dict[str, Any],
        start_date: str,
        end_date: str,
        interval: str = "15m",
        initial_capital: float = 100000,
        position_size: float = 1.0,
        use_tick_backtest: bool = True
    ) -> Dict[str, Any]:
        """
        Run a backtest with refactored strategy
        """
        ticks_df, ohlcv_df, data_info = self.get_data(start_date, end_date, interval)

        # 确保参数包含所有必需的默认值
        params = REFACTORED_DEFAULT_PARAMS.copy()
        params.update(parameters)

        # 添加指标
        ohlcv_ind = add_all_indicators(ohlcv_df, params)

        # 创建策略（使用重构版本）
        strategy = TradingStrategy(params)

        if use_tick_backtest:
            # 使用tick级别回测引擎
            # 【Task 1 修复】删除 spread_per_ounce 参数，Tick 引擎已通过 Bid/Ask 差值处理点差
            engine = TickBacktestEngine(
                initial_capital=initial_capital,
                position_size=position_size,
                contract_size=100
            )
            stats = engine.run_tick_backtest(ticks_df, ohlcv_ind, strategy, verbose=False)
        else:
            # 使用K线级别回测引擎
            engine = BacktestEngine(
                initial_capital=initial_capital,
                position_size=position_size,
                spread_per_ounce=0.6,
                contract_size=100
            )
            stats = engine.run_backtest(ohlcv_ind, strategy, verbose=False)

        # 获取权益曲线
        equity_df = engine.get_equity_curve()
        equity_curve = [
            {"timestamp": ts.isoformat(), "equity": eq}
            for ts, eq in zip(equity_df.index, equity_df['equity'])
        ]

        # 获取交易记录
        trades_df = engine.get_trades_df()
        trades = []
        if not trades_df.empty:
            for _, row in trades_df.iterrows():
                trades.append({
                    "entry_time": row['entry_time'].isoformat() if pd.notna(row['entry_time']) else None,
                    "exit_time": row['exit_time'].isoformat() if pd.notna(row['exit_time']) else None,
                    "direction": row['direction'],
                    "size": float(row['size']),
                    "entry_price": float(row['entry_price']),
                    "exit_price": float(row['exit_price']),
                    "pnl": float(row['pnl']),
                    "pnl_pct": float(row['pnl_pct']),
                    "strategy": row['strategy'],
                    "exit_reason": row['exit_reason'],
                    "bars_held": int(row['bars_held'])
                })

        # 准备结果（使用 .get() 避免 KeyError）
        result = {
            "total_trades": stats.get('total_trades', 0),
            "winning_trades": stats.get('winning_trades', 0),
            "losing_trades": stats.get('losing_trades', 0),
            "win_rate": round(stats.get('win_rate', 0), 2),
            "total_pnl": round(stats.get('total_pnl', 0), 2),
            "total_return": round(stats.get('total_return', 0), 2),
            "max_drawdown": round(stats.get('max_drawdown', 0), 2),
            "sharpe_ratio": round(stats.get('sharpe_ratio', 0), 4),
            "profit_factor": round(stats.get('profit_factor', 1), 4),
            "avg_win": round(stats.get('avg_win', 0), 2),
            "avg_loss": round(stats.get('avg_loss', 0), 2),
            "max_win": round(stats.get('max_win', 0), 2),
            "max_loss": round(stats.get('max_loss', 0), 2),
            "avg_bars_held": round(stats.get('avg_bars_held', 0), 2),
            "final_capital": round(stats.get('final_capital', initial_capital), 2),
            "strategy_stats": stats.get('strategy_stats', {}),
            "equity_curve": equity_curve,
            "trades": trades,
            "data_info": {
                **data_info,
                "total_ticks_processed": stats.get('total_ticks_processed', 0),
                "using_tick_backtest": use_tick_backtest
            },
            "refactored_features": {
                "lookahead_bias_fixed": True,  # 前视偏差已修复
                "dynamic_vwap_exit": True,     # 动态VWAP止盈
                "volatility_filter": True,     # 异常波动过滤
                "pullback_confirmation": True, # 回踩确认
                "atr_adaptive_time_stop": True # ATR自适应时间止损
            }
        }

        return result

    def run_optimization(
        self,
        start_date: str,
        end_date: str,
        n_trials: int = 100,
        min_trades: int = 100,
        use_wfo: bool = False,
        n_splits: int = 3,
        interval: str = "15m"
    ) -> Dict[str, Any]:
        """
        运行参数优化（使用Optuna TPE）
        """
        # 加载数据
        _, ohlcv_df, _ = self.get_data(start_date, end_date, interval)

        # 运行优化
        result = run_optuna_optimization(
            ohlcv_df,
            n_trials=n_trials,
            min_trades=min_trades,
            use_wfo=use_wfo,
            n_splits=n_splits,
            verbose=True
        )

        return {
            'best_params': result['best_params'],
            'best_fitness': result['best_fitness'],
            'best_trial_stats': result.get('best_trial_stats', {}),
            'use_wfo': use_wfo,
            'n_trials': n_trials
        }

    def get_default_config(self) -> Dict[str, Any]:
        """获取默认配置和参数边界"""
        descriptions = {
            "bb_period": "布林带周期",
            "bb_std": "布林带标准差倍数",
            "kc_period": "肯特纳通道周期",
            "kc_atr_mult": "肯特纳通道ATR倍数",
            "atr_period": "ATR周期",
            "rsi_period": "RSI周期",
            "rsi_oversold": "RSI超卖阈值 (策略A)",
            "rsi_overbought": "RSI超买阈值 (策略A)",
            "stop_loss_atr_mult_a": "策略A止损ATR倍数 (已收紧至1.0-1.5)",
            "max_hold_bars_a": "策略A最大持仓K线数",
            "ema_fast": "快速EMA周期 (策略B)",
            "ema_slow": "慢速EMA周期 (策略B)",
            "stop_loss_atr_mult_b": "策略B止损ATR倍数",
            "trailing_stop_atr_mult": "追踪止损ATR倍数",
            "squeeze_threshold": "波动率挤压阈值",
            # Module 1新增参数
            "atr_time_stop_base": "ATR自适应时间止损基础K线数",
            "atr_time_stop_mult": "ATR自适应时间止损调整系数",
            # Module 2新增参数
            "volatility_filter_period": "异常波动检测周期",
            "volatility_filter_mult": "异常波动检测倍数 (超过该倍数拦截信号)",
            "pullback_confirmation_bars": "回踩确认K线数",
            "ema_momentum_threshold": "EMA动能阈值",
        }

        bounds = {}
        for key, (min_val, max_val) in REFACTORED_PARAM_BOUNDS.items():
            bounds[key] = {"min": min_val, "max": max_val}

        return {
            "default_params": REFACTORED_DEFAULT_PARAMS,
            "param_bounds": bounds,
            "descriptions": descriptions,
            "data_source": "local_tick",
            "data_dir": DATA_DIR,
            "refactored_version": True,
            "improvements": {
                "module1": [
                    "消除前视偏差：使用下一根K线开盘价入场",
                    "修复静态VWAP：动态检查当前VWAP",
                    "解决止损悖论：ATR自适应时间止损 + 收紧价格止损",
                    "滑点模拟：更精确的价格执行"
                ],
                "module2": [
                    "异常波动过滤：拦截极端波动时的均值回归信号",
                    "假突破过滤：回踩确认机制",
                    "EMA动能验证：防止假突破中的动能衰竭"
                ],
                "module3": [
                    "Optuna TPE优化：替代遗传算法",
                    "Calmar比率适应度：收益/风险比优化",
                    "Walk-Forward验证：防过拟合",
                    "交易次数惩罚：确保统计显著性"
                ]
            }
        }


# Singleton instance
backtest_service = BacktestService()
