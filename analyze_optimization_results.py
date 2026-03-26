#!/usr/bin/env python3
"""
Dollar Trader 优化结果分析脚本
对比所有优化实验结果，选择最佳参数组合
"""

import json
import pandas as pd
from pathlib import Path
from typing import Dict, List


def load_results() -> Dict[str, dict]:
    """加载所有优化结果"""
    results_dir = Path('/home/ctyun/xauusd_backtest/results')
    files = {
        'Calmar': 'dt_calmar.json',
        'Sharpe': 'dt_sharpe.json',
        'Profit Factor': 'dt_pf.json',
        'Composite': 'dt_composite.json',
    }

    results = {}
    for name, filename in files.items():
        filepath = results_dir / filename
        if filepath.exists():
            with open(filepath, 'r') as f:
                results[name] = json.load(f)
        else:
            print(f"Warning: {filepath} not found")

    return results


def analyze_results(results: Dict[str, dict]):
    """分析所有优化结果"""
    print("\n" + "="*80)
    print("Dollar Trader 贝叶斯优化 - 结果汇总")
    print("="*80)

    # 创建对比表格
    comparison_data = []
    for target, data in results.items():
        is_metrics = data.get('in_sample', {})
        oos_metrics = data.get('out_of_sample', {})
        params = data.get('best_params', {})

        comparison_data.append({
            'Target': target,
            'SMA_S': params.get('sma_short', 'N/A'),
            'SMA_M': params.get('sma_medium', 'N/A'),
            'SMA_L': params.get('sma_long', 'N/A'),
            'IS_Return': f"{is_metrics.get('total_return', 0)*100:.2f}%",
            'IS_Sharpe': f"{is_metrics.get('sharpe', 0):.2f}",
            'IS_Calmar': f"{is_metrics.get('calmar', 0):.2f}",
            'IS_PF': f"{is_metrics.get('profit_factor', 0):.2f}",
            'IS_Drawdown': f"{is_metrics.get('max_drawdown_pct', 0)*100:.2f}%",
            'OOS_Return': f"{oos_metrics.get('total_return', 0)*100:.2f}%",
            'OOS_Sharpe': f"{oos_metrics.get('sharpe', 0):.2f}",
            'OOS_Calmar': f"{oos_metrics.get('calmar', 0):.2f}",
            'OOS_PF': f"{oos_metrics.get('profit_factor', 0):.2f}",
            'OOS_Drawdown': f"{oos_metrics.get('max_drawdown_pct', 0)*100:.2f}%",
        })

    df = pd.DataFrame(comparison_data)
    print("\n【样本内表现】")
    print(df[['Target', 'SMA_S', 'SMA_M', 'SMA_L', 'IS_Return', 'IS_Sharpe', 'IS_Calmar', 'IS_PF', 'IS_Drawdown']].to_string(index=False))

    print("\n【样本外表现】")
    print(df[['Target', 'OOS_Return', 'OOS_Sharpe', 'OOS_Calmar', 'OOS_PF', 'OOS_Drawdown']].to_string(index=False))

    # 推荐参数
    print("\n" + "="*80)
    print("推荐参数 (基于综合OOS表现)")
    print("="*80)

    # 计算综合评分
    best_score = -1e9
    best_target = None

    for target, data in results.items():
        oos = data.get('out_of_sample', {})
        # 综合评分：收益 + 夏普 + Calmar - 回撤惩罚
        score = (
            oos.get('total_return', 0) * 0.3 +
            oos.get('sharpe', 0) * 0.3 +
            oos.get('calmar', 0) * 0.3 +
            oos.get('profit_factor', 0) * 0.1 -
            abs(oos.get('max_drawdown_pct', 0)) * 0.5
        )
        print(f"\n{target}: 综合评分 = {score:.3f}")
        if score > best_score:
            best_score = score
            best_target = target

    if best_target and best_target in results:
        best_data = results[best_target]
        print(f"\n{'='*80}")
        print(f"最佳优化目标: {best_target}")
        print(f"{'='*80}")
        print(f"\n最优参数:")
        for param, value in best_data['best_params'].items():
            print(f"  {param}: {value}")

        print(f"\n样本内表现:")
        is_m = best_data['in_sample']
        print(f"  收益率: {is_m['total_return']*100:.2f}%")
        print(f"  夏普比率: {is_m['sharpe']:.2f}")
        print(f"  Calmar比率: {is_m['calmar']:.2f}")
        print(f"  盈利因子: {is_m['profit_factor']:.2f}")
        print(f"  最大回撤: {is_m['max_drawdown_pct']*100:.2f}%")

        print(f"\n样本外表现:")
        oos_m = best_data['out_of_sample']
        print(f"  收益率: {oos_m['total_return']*100:.2f}%")
        print(f"  夏普比率: {oos_m['sharpe']:.2f}")
        print(f"  Calmar比率: {oos_m['calmar']:.2f}")
        print(f"  盈利因子: {oos_m['profit_factor']:.2f}")
        print(f"  最大回撤: {oos_m['max_drawdown_pct']*100:.2f}%")

        # 保存推荐参数
        recommendation = {
            'best_target': best_target,
            'best_params': best_data['best_params'],
            'in_sample': best_data['in_sample'],
            'out_of_sample': best_data['out_of_sample'],
            'score': best_score,
        }

        output_path = Path('/home/ctyun/xauusd_backtest/results/dt_recommendation.json')
        with open(output_path, 'w') as f:
            json.dump(recommendation, f, indent=2)
        print(f"\n推荐参数已保存: {output_path}")


def main():
    results = load_results()
    if not results:
        print("No results found. Please run optimization first.")
        return

    analyze_results(results)


if __name__ == '__main__':
    main()
