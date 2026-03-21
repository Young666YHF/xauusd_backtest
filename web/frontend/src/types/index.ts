// API Types - Refactored Version with Optuna Support

export interface BacktestParameters {
  bb_period: number;
  bb_std: number;
  kc_period: number;
  kc_atr_mult: number;
  atr_period: number;
  rsi_period: number;
  rsi_oversold: number;
  rsi_overbought: number;
  stop_loss_atr_mult_a: number;
  max_hold_bars_a: number;
  ema_fast: number;
  ema_slow: number;
  stop_loss_atr_mult_b: number;
  trailing_stop_atr_mult: number;
  squeeze_threshold: number;
  // Refactored: Module 1 - ATR adaptive time stop
  atr_time_stop_base: number;
  atr_time_stop_mult: number;
  // Refactored: Module 2 - Volatility filter
  volatility_filter_period: number;
  volatility_filter_mult: number;
  // Refactored: Module 2 - Pullback confirmation
  pullback_confirmation_bars: number;
  ema_momentum_threshold: number;
}

export interface BacktestRequest {
  parameters: BacktestParameters;
  start_date: string;
  end_date: string;
  interval: string;
  initial_capital: number;
  position_size: number;
  use_tick_backtest?: boolean;
}

export interface StrategyStats {
  trades: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
}

export interface BacktestResult {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  total_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  profit_factor: number;
  avg_win: number;
  avg_loss: number;
  max_win: number;
  max_loss: number;
  avg_bars_held: number;
  final_capital: number;
  strategy_stats: Record<string, StrategyStats>;
}

export interface TradeRecord {
  entry_time: string;
  exit_time: string;
  direction: string;
  size: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  pnl_pct: number;
  strategy: string;
  exit_reason: string;
  bars_held: number;
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
}

export interface DataInfo {
  start_date: string;
  end_date: string;
  interval: string;
  total_ticks: number;
  ohlcv_bars: number;
  total_ticks_processed: number;
  using_tick_backtest: boolean;
  data_source: string;
  warning?: string;
}

export interface BacktestResponse {
  success: boolean;
  result: BacktestResult | null;
  equity_curve: EquityPoint[] | null;
  trades: TradeRecord[] | null;
  data_info: DataInfo | null;
  error: string | null;
  refactored_features?: {
    lookahead_bias_fixed: boolean;
    dynamic_vwap_exit: boolean;
    atr_adaptive_time_stop: boolean;
    volatility_filter: boolean;
    pullback_confirmation: boolean;
  };
}

export interface ParameterBounds {
  min: number;
  max: number;
}

export interface ConfigResponse {
  default_params: BacktestParameters;
  param_bounds: Record<string, ParameterBounds>;
  descriptions: Record<string, string>;
  data_source: string;
  data_dir: string;
  available_months: string[];
  refactored_version?: boolean;
  intervals?: string[];
}

// Refactored: Optuna TPE Optimization Request
export interface OptimizationRequest {
  start_date: string;
  end_date: string;
  interval: string;
  // Optuna specific parameters (replacing GA parameters)
  n_trials: number;           // Number of Optuna trials (replaces population_size * generations)
  min_trades: number;         // Minimum trades threshold for statistical significance
  use_wfo: boolean;           // Use Walk-Forward Optimization
  n_splits: number;           // Number of WFO splits (only used when use_wfo=true)
  // Legacy GA parameters (for backward compatibility, will be ignored by refactored backend)
  population_size?: number;
  generations?: number;
  crossover_rate?: number;
  mutation_rate?: number;
  objective?: string;
}

// Refactored: Optuna Optimization Progress
export interface OptimizationProgress {
  // For regular Optuna optimization
  trial?: number;
  total_trials: number;
  best_fitness: number;
  avg_fitness?: number;
  global_best: number;
  best_params: BacktestParameters | null;
  // For WFO mode
  split?: number;
  n_splits?: number;
  is_fitness?: number;
  oos_fitness?: number;
  // Legacy fields (for compatibility)
  generation?: number;
  total_generations?: number;
}

export interface OptimizationResult {
  best_params: BacktestParameters;
  best_fitness: number;
  // WFO results
  avg_oos_fitness?: number;
  best_oos_fitness?: number;
  std_oos_fitness?: number;
  // History
  history: Array<{
    trial?: number;
    generation?: number;
    value?: number;
    best_value?: number;
    // WFO history
    split?: number;
    is_fitness?: number;
    oos_fitness?: number;
  }>;
  // Refactored version info
  refactored_version?: boolean;
  use_wfo?: boolean;
}

export interface DataPreviewResponse {
  timestamps: string[];
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  volume: number[];
  count: number;
}

// Parameter preset
export interface ParameterPreset {
  id: string;
  name: string;
  description: string;
  parameters: BacktestParameters;
  created_at: string;
}

// Backend preset response
export interface PresetResponse {
  params: BacktestParameters;
  description: string;
  created_at: string;
  updated_at: string;
}

// Backend presets list response
export interface PresetsListResponse {
  presets: Record<string, PresetResponse>;
  count: number;
}

// Version info
export interface VersionInfo {
  version: string;
  name: string;
  refactored: boolean;
  optimizer: string;
  features: {
    lookahead_bias_fixed: boolean;
    dynamic_vwap_exit: boolean;
    atr_adaptive_time_stop: boolean;
    volatility_filter: boolean;
    pullback_confirmation: boolean;
    bayesian_optimization: boolean;
    walk_forward_validation: boolean;
  };
}

// Refactoring summary
export interface RefactoringSummary {
  version: string;
  refactoring_date: string;
  modules: {
    module1_critical_fixes: {
      title: string;
      changes: Array<{
        issue: string;
        solution: string;
        impact: string;
      }>;
    };
    module2_market_microstructure: {
      title: string;
      changes: Array<{
        feature: string;
        description: string;
        benefit: string;
      }>;
    };
    module3_optimization: {
      title: string;
      changes: Array<{
        algorithm?: string;
        replaces?: string;
        advantage?: string;
        fitness_function?: string;
        formula?: string;
        penalty?: string;
        validation?: string;
        method?: string;
        purpose?: string;
      }>;
    };
  };
  api_endpoints: Record<string, string>;
}
