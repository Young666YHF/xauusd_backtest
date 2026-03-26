"""
Optuna贝叶斯优化器
==================
使用TPE算法进行超参数优化
"""

from typing import Dict, List, Optional, Any, Callable
import pandas as pd
import numpy as np
from datetime import datetime
import warnings

from .base import BaseOptimizer, OptimizationCallback
from core.types import OptimizationResult

try:
    import optuna
    from optuna.samplers import TPESampler
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False
    warnings.warn("Optuna not installed. OptunaOptimizer will not work.")


class OptunaOptimizer(BaseOptimizer):
    """
    Optuna贝叶斯优化器

    使用TPE (Tree-structured Parzen Estimator) 算法
    支持早停、并行优化
    """

    def __init__(
        self,
        param_bounds: Dict[str, tuple],
        n_trials: int = 300,
        timeout: Optional[int] = None,
        n_jobs: int = -1,
        min_trades: int = 30,
        optimization_target: str = 'calmar',
        early_stopping: bool = True,
        patience: int = 50,
        seed: Optional[int] = None
    ):
        super().__init__(
            param_bounds, n_trials, timeout, n_jobs,
            min_trades, optimization_target
        )
        self.early_stopping = early_stopping
        self.patience = patience
        self.seed = seed

        if not OPTUNA_AVAILABLE:
            raise ImportError("Optuna is required for OptunaOptimizer")

    def suggest_params(self, trial) -> Dict[str, Any]:
        """
        建议参数

        Args:
            trial: Optuna trial对象

        Returns:
            参数字典
        """
        params = {}

        for param_name, (min_val, max_val) in self.param_bounds.items():
            # 判断参数类型
            if isinstance(min_val, int) and isinstance(max_val, int):
                # 整数参数
                params[param_name] = trial.suggest_int(
                    param_name, min_val, max_val
                )
            elif param_name.endswith('_mode') or param_name.startswith('use_'):
                # 分类参数
                choices = list(range(int(min_val), int(max_val) + 1))
                params[param_name] = trial.suggest_categorical(param_name, choices)
            else:
                # 浮点参数
                params[param_name] = trial.suggest_float(
                    param_name, min_val, max_val
                )

        return params

    def optimize(
        self,
        objective_func: Callable[[Dict[str, Any]], float],
        callback: Optional[OptimizationCallback] = None
    ) -> OptimizationResult:
        """
        执行优化

        Args:
            objective_func: 目标函数
            callback: 回调对象

        Returns:
            OptimizationResult
        """
        self.callback = callback
        start_time = datetime.now()

        # 创建Optuna study
        sampler = TPESampler(seed=self.seed) if self.seed else TPESampler()

        study = optuna.create_study(
            direction='maximize',
            sampler=sampler
        )

        # 早停计数器
        best_value = -float('inf')
        no_improvement_count = 0

        def optuna_objective(trial) -> float:
            nonlocal best_value, no_improvement_count

            # 获取参数
            params = self.suggest_params(trial)

            # 评估
            try:
                fitness = objective_func(params)
            except Exception as e:
                # 如果评估失败，返回很大的负数
                return -1e10

            # 早停检查
            if self.early_stopping:
                if fitness > best_value:
                    best_value = fitness
                    no_improvement_count = 0
                else:
                    no_improvement_count += 1

                if no_improvement_count >= self.patience:
                    trial.study.stop()

            # 回调
            if callback and callback.on_trial_complete:
                callback.on_trial_complete(trial.number, params, fitness)

            return fitness

        # 执行优化
        study.optimize(
            optuna_objective,
            n_trials=self.n_trials,
            timeout=self.timeout,
            n_jobs=self.n_jobs,
            show_progress_bar=True
        )

        # 构建结果
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        self.best_params = study.best_params
        self.best_fitness = study.best_value

        result = OptimizationResult(
            best_params=study.best_params,
            best_fitness=study.best_value,
            total_trials=len(study.trials),
            completed_trials=len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]),
            pruned_trials=len([t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED]),
            failed_trials=len([t for t in study.trials if t.state == optuna.trial.TrialState.FAIL]),
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration
        )

        # 回调
        if callback and callback.on_optimization_end:
            callback.on_optimization_end(result)

        return result

    def optimize_with_walk_forward(
        self,
        train_func: Callable[[Dict[str, Any]], Dict[str, Any]],
        test_func: Callable[[Dict[str, Any]], Dict[str, Any]],
        callback: Optional[OptimizationCallback] = None
    ) -> OptimizationResult:
        """
        使用Walk-Forward验证进行优化

        Args:
            train_func: 训练集评估函数
            test_func: 测试集评估函数
            callback: 回调对象

        Returns:
            OptimizationResult
        """
        def objective(params: Dict[str, Any]) -> float:
            # 训练集评估
            train_result = train_func(params)
            train_fitness = self.calculate_fitness(train_result)

            # 如果训练集表现不好，直接返回
            if train_fitness < 0:
                return train_fitness

            # 测试集评估
            test_result = test_func(params)
            test_fitness = self.calculate_fitness(test_result)

            # 综合评分：训练集70% + 测试集30%
            combined_fitness = train_fitness * 0.7 + test_fitness * 0.3

            # 如果测试集表现明显差于训练集（过拟合），降低评分
            if test_fitness < train_fitness * 0.5:
                combined_fitness *= 0.5

            return combined_fitness

        return self.optimize(objective, callback)
