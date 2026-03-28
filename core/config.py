"""
配置管理模块
============
使用 Pydantic 进行配置验证和管理
"""

from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Optional, Tuple, Any, Literal
from pathlib import Path
import json
import yaml


class TradingConfig(BaseModel):
    """交易配置"""
    # 品种配置
    symbol: str = Field(default="XAUUSD", description="交易品种代码")
    contract_size: int = Field(default=100, description="合约大小（盎司/手）")
    tick_size: float = Field(default=0.01, description="最小价格变动")

    # 成本配置
    spread_per_ounce: float = Field(default=0.6, description="每盎司点差（美元）- 使得每0.01手往返成本=0.6美元")
    commission_per_lot: float = Field(default=0.0, description="每手单边佣金（已包含在点差中）")

    # 资金配置
    initial_capital: float = Field(default=100000.0, description="初始资金")
    leverage: int = Field(default=1000, description="杠杆倍数（1000倍杠杆）")
    margin_call_ratio: float = Field(default=0.5, description="爆仓保证金比例")

    # 交易时段配置（北京时间 UTC+8）
    asian_session_start: int = Field(default=6, description="亚盘开始小时")
    asian_session_end: int = Field(default=14, description="亚盘结束小时")
    european_session_start: int = Field(default=15, description="欧美盘开始小时")
    european_session_end: int = Field(default=24, description="欧美盘结束小时")

    # 滑点配置
    base_slippage: float = Field(default=0.15, description="基础滑点（美元）")
    atr_slippage_ratio: float = Field(default=0.03, description="ATR滑点比例")

    # 非对称滑点模型
    stop_loss_slippage_mult: float = Field(default=2.0, description="止损滑点倍数")
    take_profit_slippage_mult: float = Field(default=0.0, description="止盈滑点倍数")


class StrategyConfig(BaseModel):
    """策略参数配置"""
    # 基础指标参数
    bb_period: int = Field(default=20, ge=5, le=50, description="布林带周期")
    bb_std: float = Field(default=2.0, ge=0.5, le=5.0, description="布林带标准差")
    kc_period: int = Field(default=20, ge=5, le=50, description="肯特纳通道周期")
    kc_atr_mult: float = Field(default=1.5, ge=0.5, le=5.0, description="肯特纳ATR倍数")
    atr_period: int = Field(default=14, ge=5, le=50, description="ATR周期")
    rsi_period: int = Field(default=14, ge=5, le=50, description="RSI周期")

    # 策略A参数（均值回归）
    rsi_oversold: int = Field(default=25, ge=5, le=50, description="RSI超卖阈值")
    rsi_overbought: int = Field(default=75, ge=50, le=95, description="RSI超买阈值")
    stop_loss_atr_mult_a: float = Field(default=1.0, ge=0.1, le=5.0, description="策略A止损ATR倍数")
    max_hold_bars_a: int = Field(default=5, ge=1, le=50, description="策略A最大持仓K线数")

    # 策略B参数（动量突破）
    ema_fast: int = Field(default=20, ge=5, le=100, description="快速EMA周期")
    ema_slow: int = Field(default=50, ge=10, le=200, description="慢速EMA周期")
    stop_loss_atr_mult_b: float = Field(default=1.2, ge=0.1, le=5.0, description="策略B止损ATR倍数")
    trailing_stop_atr_mult: float = Field(default=2.5, ge=0.5, le=10.0, description="追踪止损ATR倍数")

    # 波动率过滤
    squeeze_threshold: float = Field(default=0.8, ge=0.1, le=2.0, description="挤压阈值")
    volatility_filter_period: int = Field(default=20, ge=5, le=100, description="波动率过滤周期")
    volatility_filter_mult: float = Field(default=1.5, ge=0.5, le=5.0, description="波动率过滤倍数")

    # ATR自适应时间止损
    atr_time_stop_base: float = Field(default=4.0, ge=1.0, le=20.0, description="时间止损基础K线数")
    atr_time_stop_mult: float = Field(default=0.5, ge=0.1, le=2.0, description="时间止损ATR倍数")

    # 假突破过滤
    pullback_confirmation_bars: int = Field(default=2, ge=0, le=10, description="回踩确认K线数")
    ema_momentum_threshold: float = Field(default=0.0005, ge=0.0001, le=0.01, description="EMA动量阈值")

    # 策略B入场模式
    strategy_b_mode: Literal[0, 1] = Field(default=0, description="策略B入场模式：0=自动，1=强制回踩")

    @field_validator('ema_slow')
    @classmethod
    def validate_ema_slow(cls, v: int, info) -> int:
        """验证EMA慢线大于快线"""
        if 'ema_fast' in info.data and v <= info.data['ema_fast']:
            raise ValueError('ema_slow must be greater than ema_fast')
        return v

    @field_validator('rsi_overbought')
    @classmethod
    def validate_rsi(cls, v: int, info) -> int:
        """验证RSI超买大于超卖"""
        if 'rsi_oversold' in info.data and v <= info.data['rsi_oversold']:
            raise ValueError('rsi_overbought must be greater than rsi_oversold')
        return v

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump()

    def to_optimized_params(self) -> Dict[str, Tuple[float, float]]:
        """获取可优化参数范围"""
        return {
            'bb_period': (15, 25),
            'bb_std': (1.8, 2.5),
            'kc_period': (15, 25),
            'kc_atr_mult': (1.2, 2.0),
            'atr_period': (10, 18),
            'rsi_period': (10, 18),
            'rsi_oversold': (15, 35),
            'rsi_overbought': (65, 85),
            'stop_loss_atr_mult_a': (0.8, 1.5),
            'max_hold_bars_a': (3, 10),
            'ema_fast': (12, 30),
            'ema_slow': (35, 70),
            'stop_loss_atr_mult_b': (1.0, 2.0),
            'trailing_stop_atr_mult': (2.0, 4.0),
            'squeeze_threshold': (0.6, 1.0),
            'atr_time_stop_base': (2.0, 6.0),
            'atr_time_stop_mult': (0.3, 0.8),
            'volatility_filter_period': (15, 30),
            'volatility_filter_mult': (1.2, 2.0),
            'pullback_confirmation_bars': (1, 4),
            'ema_momentum_threshold': (0.0003, 0.001),
        }


class DataConfig(BaseModel):
    """数据配置"""
    # 数据源配置
    data_dir: str = Field(default="/home/ctyun/xauusd_data", description="数据目录")
    interval: str = Field(default="15min", description="K线周期")

    # 时区配置
    timezone: str = Field(default="Asia/Shanghai", description="目标时区")
    data_timezone: str = Field(default="UTC", description="数据时区")

    # VWAP锚定时间（美东时间17:00）
    vwap_reset_hour_et: int = Field(default=17, description="VWAP重置小时（美东时间）")


class OptimizationConfig(BaseModel):
    """优化配置"""
    # Optuna配置
    n_trials: int = Field(default=300, ge=10, le=10000, description="优化试验次数")
    timeout: Optional[int] = Field(default=None, description="超时时间（秒）")
    n_jobs: int = Field(default=-1, description="并行作业数（-1表示使用所有CPU）")

    # 早停配置
    early_stopping: bool = Field(default=True, description="是否启用早停")
    patience: int = Field(default=50, ge=10, le=500, description="早停耐心值")

    # 优化目标
    optimization_target: Literal['sharpe', 'calmar', 'profit_factor', 'win_rate', 'custom'] = \
        Field(default='calmar', description="优化目标")

    # 约束条件
    min_trades: int = Field(default=30, ge=5, le=1000, description="最小交易次数")
    min_win_rate: float = Field(default=0.3, ge=0.1, le=0.9, description="最低胜率")

    # Walk-Forward配置
    use_walk_forward: bool = Field(default=True, description="是否使用Walk-Forward验证")
    train_ratio: float = Field(default=0.8, ge=0.5, le=0.9, description="训练集比例")


class Config(BaseModel):
    """全局配置"""
    trading: TradingConfig = Field(default_factory=TradingConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)

    # 版本信息
    version: str = Field(default="2.0.0", description="配置版本")

    @classmethod
    def from_file(cls, filepath: str) -> "Config":
        """从文件加载配置"""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {filepath}")

        with open(path, 'r', encoding='utf-8') as f:
            if path.suffix in ['.yaml', '.yml']:
                data = yaml.safe_load(f)
            elif path.suffix == '.json':
                data = json.load(f)
            else:
                raise ValueError(f"Unsupported config format: {path.suffix}")

        return cls(**data)

    def save(self, filepath: str):
        """保存配置到文件"""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w', encoding='utf-8') as f:
            if path.suffix == '.json':
                json.dump(self.model_dump(), f, indent=2, ensure_ascii=False)
            else:
                yaml.dump(self.model_dump(), f, allow_unicode=True, default_flow_style=False)

    def get_param_bounds(self) -> Dict[str, Tuple[float, float]]:
        """获取参数优化范围"""
        return self.strategy.to_optimized_params()

    def copy(self) -> "Config":
        """复制配置"""
        return Config(**self.model_dump())


# 全局配置实例
_global_config: Optional[Config] = None


def get_config() -> Config:
    """获取全局配置"""
    global _global_config
    if _global_config is None:
        _global_config = Config()
    return _global_config


def set_config(config: Config):
    """设置全局配置"""
    global _global_config
    _global_config = config


def reset_config():
    """重置全局配置"""
    global _global_config
    _global_config = Config()
