"""
XAUUSD 量化交易系统 v2.0
==========================

重构后的模块化交易系统，支持：
- 多种策略（均值回归、动量突破）
- K线级和Tick级回测
- Optuna贝叶斯优化
- Walk-Forward验证

模块结构：
- core: 核心组件（配置、类型、事件、风险管理）
- strategies: 策略模块
- engines: 回测引擎
- optimizers: 优化器
- web: Web界面

用法示例：
    from core.config import Config
    from strategies import StrategyRegistry
    from engines import CandleBacktestEngine
    from optimizers import OptunaOptimizer

    # 加载配置
    config = Config()

    # 创建策略
    strategy = StrategyRegistry.create('mean_reversion', config.strategy.to_dict())

    # 创建引擎并运行回测
    engine = CandleBacktestEngine(config.trading)
    result = engine.run_with_strategy(df, strategy)
"""

__version__ = "2.0.0"
__author__ = "Quant Dev"

from core.config import Config
from core.types import BacktestResult, OptimizationResult

__all__ = [
    'Config',
    'BacktestResult',
    'OptimizationResult',
    '__version__',
]
