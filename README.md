# XAUUSD 量化交易系统 v2.0

重构后的模块化量化交易系统，支持多种策略的tick级别回测和贝叶斯优化。

## 系统架构

```
xauusd_backtest/
├── core/                   # 核心组件
│   ├── config.py          # 配置管理
│   ├── types.py           # 数据类型定义
│   ├── events.py          # 事件系统
│   ├── risk_manager.py    # 风险管理
│   ├── indicators.py      # 技术指标
│   └── data_loader.py     # 数据加载
├── strategies/            # 策略模块
│   ├── base.py           # 策略基类
│   ├── mean_reversion.py # 均值回归策略
│   └── momentum_breakout.py # 动量突破策略
├── engines/              # 回测引擎
│   ├── base.py          # 引擎基类
│   ├── candle_engine.py # K线级引擎
│   └── tick_engine.py   # Tick级引擎
├── optimizers/          # 优化器
│   ├── base.py         # 优化器基类
│   └── optuna_optimizer.py # Optuna贝叶斯优化
├── web/                # Web界面
├── tests/              # 测试
├── examples/           # 示例
└── logs/               # 日志
```

## 特性

### 策略系统
- **策略基类**: 所有策略继承统一的接口
- **内置策略**:
  - 均值回归策略（亚盘时段，布林带+RSI）
  - 动量突破策略（欧美盘时段，EMA+布林带突破）
- **策略注册**: 支持动态加载和扩展

### 回测引擎
- **K线级引擎**: 快速回测，适合参数搜索
- **Tick级引擎**: 高精度回测，适合精确验证
- **非对称滑点**: 区分止损/止盈滑点模型
- **前视偏差防护**: 确保信号执行在下一根K线

### 优化系统
- **贝叶斯优化**: 使用Optuna TPE算法
- **Walk-Forward**: 支持训练/测试集分离验证
- **早停机制**: 避免无效优化
- **多目标**: 支持夏普比率、Calmar比率等多种目标

### 风险管理
- **动态仓位**: 基于ATR和账户风险计算
- **追踪止损**: ATR自适应追踪止损
- **保证金检测**: 模拟真实爆仓机制
- **波动率过滤**: 自动识别异常波动

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行回测

```bash
# K线级回测 - 均值回归策略
python run_backtest.py \
  --strategy mean_reversion \
  --start-date 2025-01-01 \
  --end-date 2025-03-31

# Tick级回测 - 动量突破策略
python run_backtest.py \
  --strategy momentum_breakout \
  --engine tick \
  --start-date 2025-01-01 \
  --end-date 2025-03-31 \
  --tick-data /path/to/ticks.csv
```

### 运行优化

```bash
# 基础优化
python run_optimization.py \
  --strategy mean_reversion \
  --train-start 2025-01-01 \
  --train-end 2025-10-31 \
  --n-trials 300

# Walk-Forward优化
python run_optimization.py \
  --strategy momentum_breakout \
  --train-start 2025-01-01 \
  --train-end 2025-10-31 \
  --test-start 2025-11-01 \
  --test-end 2025-12-31 \
  --target calmar
```

### 程序化使用

```python
from core.config import Config
from core.data_loader import DataLoader
from core.indicators import add_all_indicators
from strategies import StrategyRegistry
from engines import CandleBacktestEngine

# 加载配置
config = Config()

# 加载数据
loader = DataLoader(config.data.data_dir)
df = loader.load_monthly_data(2025, 1, '15min')

# 添加指标
df = add_all_indicators(df)

# 创建策略
strategy = StrategyRegistry.create(
    'mean_reversion',
    config.strategy.to_dict()
)

# 运行回测
engine = CandleBacktestEngine(config.trading)
result = engine.run_with_strategy(df, strategy)

# 查看结果
print(f"Total Trades: {result.total_trades}")
print(f"Win Rate: {result.win_rate:.2%}")
print(f"Sharpe: {result.sharpe_ratio:.2f}")
```

## 自定义策略

继承 `BaseStrategy` 实现自己的策略：

```python
from strategies.base import BaseStrategy
from core.types import TradeSignal, TradeDirection

class MyStrategy(BaseStrategy):
    def get_default_params(self):
        return {'period': 20, 'threshold': 0.01}

    def get_param_bounds(self):
        return {'period': (10, 50), 'threshold': (0.001, 0.1)}

    def generate_signal(self, df, current_idx, **kwargs):
        # 实现信号逻辑
        if current_idx < self.params['period']:
            return None

        # ... 信号计算 ...

        return self._create_signal(
            timestamp=df.index[current_idx],
            direction=TradeDirection.LONG,
            entry_price=df.iloc[current_idx]['Close'],
            stop_loss=df.iloc[current_idx]['Close'] * 0.99,
            reason="MySignal"
        )

# 注册策略
from strategies.base import StrategyRegistry
StrategyRegistry.register('my_strategy', MyStrategy)
```

## 配置说明

配置文件支持 YAML 或 JSON 格式：

```yaml
# config.yaml
trading:
  symbol: "XAUUSD"
  initial_capital: 100000.0
  spread_per_ounce: 0.2

strategy:
  bb_period: 20
  rsi_oversold: 25
  rsi_overbought: 75

optimization:
  n_trials: 300
  target: "calmar"
  min_trades: 30
```

## 测试

运行测试：

```bash
python -m pytest tests/
# 或
python tests/test_core.py
```

## Web界面

启动Web服务：

```bash
cd web/backend
python main.py
```

访问 http://localhost:8000

## 项目改进

### 相比旧版本

1. **模块化架构**: 清晰的模块划分，易于扩展
2. **类型安全**: 使用Pydantic进行配置验证
3. **策略抽象**: 统一的策略接口，支持动态加载
4. **引擎统一**: K线和Tick引擎共享基类
5. **优化集成**: 内置Optuna贝叶斯优化
6. **事件系统**: 支持组件间通信
7. **风险管理**: 完善的风险控制模块
8. **测试覆盖**: 核心模块单元测试

## 注意事项

1. 时区处理: 数据源为UTC，策略判断使用北京时间
2. VWAP锚定: 按美东时间17:00重置
3. 滑点模型: 策略B突破入场滑点更大
4. 双引擎同步: 修改策略时需同步更新两个引擎

## License

MIT
