"""趋势角度策略优化 - 变体3: 长周期参数"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import run_trend_angle_two_stage as main_module

original_create_is_objective = main_module.create_is_objective

def create_is_objective_v3(is_df, is_tick_df, bar_idx_to_ticks):
    import optuna
    from run_trend_angle_two_stage import calculate_strategy_indicators, run_tick_backtest, calculate_fitness_is
    
    def objective(trial: optuna.Trial) -> float:
        params = {
            'sma_period': trial.suggest_int('sma_period', 30, 50),  # 长周期
            'angle_threshold': trial.suggest_float('angle_threshold', 3.0, 8.0),  # 高阈值
            'risk_reward_ratio': trial.suggest_float('risk_reward_ratio', 1.5, 4.0),
            'breakout_lookback': trial.suggest_int('breakout_lookback', 3, 8),
            'trailing_stop_atr': trial.suggest_float('trailing_stop_atr', 1.5, 4.0),
            'use_fixed_exit': True,
        }
        try:
            df_with_indicators = calculate_strategy_indicators(
                is_df.copy(), sma_period=params['sma_period'], atr_period=14, angle_lookback=5
            )
            result = run_tick_backtest(
                df_with_indicators, is_tick_df, bar_idx_to_ticks, params,
                warmup_bars=max(100, params['sma_period'] + 20)
            )
            fitness = calculate_fitness_is(result)
            trial.set_user_attr('total_trades', result.total_trades)
            trial.set_user_attr('win_rate', result.win_rate)
            trial.set_user_attr('profit_factor', result.profit_factor)
            trial.set_user_attr('total_return', result.total_return)
            trial.set_user_attr('max_drawdown_pct', result.max_drawdown_pct)
            trial.set_user_attr('sharpe_ratio', result.sharpe_ratio)
            trial.set_user_attr('calmar', result.total_return / abs(result.max_drawdown_pct)
                               if result.max_drawdown_pct != 0 else result.total_return)
            return fitness
        except Exception as e:
            print(f"Error in trial {trial.number}: {e}")
            return -1e6
    return objective

main_module.create_is_objective = create_is_objective_v3

if __name__ == '__main__':
    main_module.main()
