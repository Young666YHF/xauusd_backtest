# autoresearch-trading

自动化交易策略研究循环。AI 持续迭代策略代码，运行回测验证，保留改进、丢弃退步，循环直至手动停止。

## Setup

启动新的研究周期前：

1. **确认研究标签**: 基于日期命名，如 `mar29`。分支 `research/<tag>` 必须不存在。
2. **创建分支**: `git checkout -b research/<tag>` 从 main 分支。
3. **阅读核心文件**:
   - `README.md` — 项目概述
   - `config.yaml` — 全局配置
   - `strategies/base.py` — 策略基类接口
   - `strategies/<target_strategy>.py` — 目标策略（你要修改的文件）
   - `engines/candle_backtest.py` — K线回测引擎
4. **确认数据存在**: 检查 `~/.cache/xauusd_data/` 或 `/home/ctyun/xauusd_data/` 有数据文件。
5. **初始化结果文件**: 创建 `research_results.tsv`，包含表头。
6. **确认后开始**: 向用户确认设置完成，开始实验循环。

## Experimentation

每个实验运行一次回测或优化。目标是提升核心指标。

**可以修改的文件：**
- `strategies/<strategy_name>.py` — 策略逻辑、参数范围、信号生成
- `config.yaml` — 全局交易参数（谨慎修改）

**禁止修改的文件：**
- `core/` — 核心模块（类型、指标、数据加载）
- `engines/` — 回测引擎（双引擎需同步，避免不一致）
- `optimizers/` — 优化器框架

**目标指标** (越高越好)：
- **Sharpe Ratio** — 风险调整收益
- **Calmar Ratio** — 收益/最大回撤
- **Profit Factor** — 盈亏比

**约束条件**：
- 最大回撤不超过 30%
- 最少交易次数 30 笔
- Win Rate > 30%

**简洁性原则**: 同等条件下，代码越简单越好。小改进但增加大量复杂度不值得。删除代码并获得相同或更好结果是最佳改进。

**首次运行**: 先运行基准回测，记录初始指标。

## Running Backtest

```bash
# 单次回测
python run_backtest.py --strategy <strategy_name> --start-date 2025-01-01 --end-date 2025-06-30

# 优化
python run_optimization.py --strategy <strategy_name> --train-start 2025-01-01 --train-end 2025-10-31 --test-start 2025-11-01 --test-end 2025-12-31 --n-trials 100
```

## Output Format

回测完成后输出：

```
Total Trades:     150
Winning Trades:   85
Losing Trades:    65
Win Rate:         56.67%

Total P&L:        $12,345.67
Total Return:     12.35%
Max Drawdown:     8.45%
Sharpe Ratio:     1.85
Profit Factor:    1.72
Calmar Ratio:     1.46
```

提取关键指标：
```bash
grep -E "Sharpe Ratio:|Calmar Ratio:|Max Drawdown:|Win Rate:|Profit Factor:|Total Return:" run.log
```

## Logging Results

实验完成后，记录到 `research_results.tsv`（Tab 分隔）：

```
commit	sharpe	calmar	max_dd	win_rate	trades	status	description
```

列说明：
1. git commit hash (7位)
2. Sharpe Ratio (保留2位小数)
3. Calmar Ratio (保留2位小数)
4. Max Drawdown % (如 8.45，不是 0.0845)
5. Win Rate % (如 56.67)
6. 交易次数
7. 状态: `keep`, `discard`, `crash`
8. 简短描述

示例：
```
commit	sharpe	calmar	max_dd	win_rate	trades	status	description
a1b2c3d	1.85	1.46	8.45	56.67	150	keep	baseline
b2c3d4e	2.12	1.68	7.23	58.32	165	keep	add ATR filter
c3d4e5f	1.45	0.92	12.50	51.20	98	discard	remove stop loss
d4e5f6g	0.00	0.00	0.00	0.00	0	crash	parameter error
```

## The Experiment Loop

研究运行在专用分支（如 `research/mar29`）。

LOOP FOREVER:

1. 查看当前 git 状态：分支和 commit
2. 提出实验想法，修改 `strategies/<target>.py`
3. `git commit -m "描述"`
4. 运行回测：`python run_backtest.py ... > run.log 2>&1`
5. 提取结果：`grep -E "Sharpe|Calmar|Max Drawdown|Win Rate" run.log`
6. 如果 grep 为空，运行 `tail -50 run.log` 查看错误。尝试修复，多次失败则跳过。
7. 记录结果到 TSV（不提交 TSV 文件）
8. 如果指标改进（Sharpe 提高、Max DD 降低），保留 commit
9. 如果指标退步或持平，`git reset --hard HEAD~1` 回退
10. 继续下一个实验想法

**超时**: 单次回测应在 2 分钟内完成。优化可运行更长时间。

**崩溃处理**: 如果是简单错误（语法、参数），修复重跑。如果想法根本错误，标记 crash 并继续。

**永不停止**: 实验循环开始后，不要暂停询问用户。用户可能不在，期望你持续工作直到手动中断。如果想法用尽：
- 回顾历史实验，寻找接近成功的想法
- 尝试组合多个小改进
- 阅读策略代码寻找优化点
- 尝试更激进的架构变化
- 研究不同时段的表现差异

## Research Ideas

以下是一些研究方向：

### 策略逻辑
- 添加/移除入场过滤器（ADX、ATR、趋势强度）
- 调整止损止盈逻辑（ATR 倍数、固定点数、追踪止损）
- 修改信号确认条件
- 添加时段过滤（亚盘 vs 欧美盘）

### 参数优化
- 调整指标周期（EMA、BB、RSI）
- 修改阈值（超买超卖、突破确认）
- 调整仓位管理和风险参数

### 风险管理
- 动态仓位调整
- 最大持仓时间限制
- 连续亏损后的冷却期

### 架构改进
- 多时间框架确认
- 信号强度加权
- 多策略组合

## Notes

- 数据时区: UTC
- 亚盘: 00:00-08:00 UTC, 欧美盘: 08:00-22:00 UTC
- 双引擎同步: 修改策略逻辑需确保 K线引擎和 Tick 引擎一致
- 前视偏差: 确保不使用未来数据
- 过拟合风险: 使用 Walk-Forward 验证，关注样本外表现
