"""
优化器基类
==========
定义优化器的抽象接口
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
import pandas as pd
from datetime import datetime

from core.types import OptimizationResult


@dataclass
class OptimizationCallback:
    """优化回调"""
    on_trial_complete: Optional[Callable[[int, Dict, float], None]] = None
    on_best_updated: Optional[Callable[[Dict, float], None]] = None
    on_optimization_end: Optional[Callable[[OptimizationResult], None]] = None


class BaseOptimizer(ABC):
    """
    优化器抽象基类

    子类必须实现:
    - optimize: 执行优化
    """

    def __init__(
        self,
        param_bounds: Dict[str, tuple],
        n_trials: int = 100,
        timeout: Optional[int] = None,
        n_jobs: int = -1,
        min_trades: int = 30,
        optimization_target: str = 'calmar'
    ):
        """
        初始化优化器

        Args:
            param_bounds: 参数优化范围 {参数名: (最小值, 最大值)}
            n_trials: 优化次数
            timeout: 超时时间（秒）
            n_jobs: 并行作业数
            min_trades: 最小交易次数
            optimization_target: 优化目标
        """
        self.param_bounds = param_bounds
        self.n_trials = n_trials
        self.timeout = timeout
        self.n_jobs = n_jobs
        self.min_trades = min_trades
        self.optimization_target = optimization_target

        # 回调
        self.callback: Optional[OptimizationCallback] = None

        # 结果
        self.best_params: Optional[Dict[str, Any]] = None
        self.best_fitness: float = 0.0
        self.trials_history: List[Dict[str, Any]] = []

    @abstractmethod
    def optimize(
        self,
        objective_func: Callable[[Dict[str, Any]], float],
        callback: Optional[OptimizationCallback] = None
    ) -> OptimizationResult:
        """
        执行优化

        Args:
            objective_func: 目标函数，接收参数字典，返回适应度值
            callback: 优化回调

        Returns:
            OptimizationResult
        """
        pass

    def calculate_fitness(self, result: Dict[str, Any]) -> float:
        """
        计算适应度值

        Args:
            result: 回测结果字典

        Returns:
            适应度值（越高越好）
        """
        # 检查最小交易次数
        if result.get('total_trades', 0) < self.min_trades:
            return -float('inf')

        target = self.optimization_target

        if target == 'sharpe':
            return result.get('sharpe_ratio', 0)
        elif target == 'calmar':
            return result.get('calmar_ratio', 0)
        elif target == 'profit_factor':
            return result.get('profit_factor', 0)
        elif target == 'win_rate':
            return result.get('win_rate', 0)
        elif target == 'total_return':
            return result.get('total_return', 0)
        else:
            # 综合评分
            sharpe = result.get('sharpe_ratio', 0)
            calmar = result.get('calmar_ratio', 0)
            pf = result.get('profit_factor', 0)
            win_rate = result.get('win_rate', 0)

            # 加权综合
            score = (
                sharpe * 0.3 +
                calmar * 0.3 +
                min(pf, 3.0) * 0.2 +
                win_rate * 0.2
            )
            return score

    def suggest_params(self, trial) -> Dict[str, Any]:
        """
        建议参数（供子类实现）

        Args:
            trial: 优化框架的trial对象

        Returns:
            参数字典
        """
        raise NotImplementedError

    def _expand_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        展开简化参数为完整参数

        Args:
            params: 简化参数

        Returns:
            完整参数
        """
        # 默认直接返回，子类可重写
        return params

    def get_best_params(self) -> Optional[Dict[str, Any]]:
        """获取最优参数"""
        return self.best_params

    def get_optimization_history(self) -> List[Dict[str, Any]]:
        """获取优化历史"""
        return self.trials_history.copy()
