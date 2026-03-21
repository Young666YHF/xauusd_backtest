"""
Pydantic models for API request/response validation
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime


# ==================== Backtest Models ====================

class BacktestParameters(BaseModel):
    """Backtest parameters"""
    # Common parameters
    bb_period: int = Field(default=20, ge=5, le=50, description="Bollinger Bands period")
    bb_std: float = Field(default=2.5, ge=1.0, le=5.0, description="Bollinger Bands std dev")
    kc_period: int = Field(default=20, ge=5, le=50, description="Keltner Channel period")
    kc_atr_mult: float = Field(default=1.5, ge=0.5, le=3.0, description="Keltner Channel ATR multiplier")
    atr_period: int = Field(default=14, ge=5, le=30, description="ATR period")
    rsi_period: int = Field(default=14, ge=5, le=30, description="RSI period")

    # Strategy A parameters (Mean Reversion)
    rsi_oversold: int = Field(default=30, ge=10, le=50, description="RSI oversold level")
    rsi_overbought: int = Field(default=70, ge=50, le=90, description="RSI overbought level")
    stop_loss_atr_mult_a: float = Field(default=1.5, ge=0.5, le=4.0, description="Strategy A stop loss ATR multiplier")
    max_hold_bars_a: int = Field(default=12, ge=1, le=50, description="Max holding bars for strategy A")

    # Strategy B parameters (Momentum)
    ema_fast: int = Field(default=20, ge=5, le=50, description="Fast EMA period")
    ema_slow: int = Field(default=50, ge=20, le=100, description="Slow EMA period")
    stop_loss_atr_mult_b: float = Field(default=1.5, ge=0.5, le=4.0, description="Strategy B stop loss ATR multiplier")
    trailing_stop_atr_mult: float = Field(default=2.0, ge=1.0, le=5.0, description="Trailing stop ATR multiplier")

    # Volatility filter
    squeeze_threshold: float = Field(default=1.0, ge=0.3, le=2.0, description="Squeeze threshold")


class BacktestRequest(BaseModel):
    """Backtest API request - using start_date/end_date instead of days"""
    parameters: BacktestParameters = Field(default_factory=BacktestParameters)
    start_date: str = Field(default="2025-08-01", description="Start date (YYYY-MM-DD)")
    end_date: str = Field(default="2026-02-28", description="End date (YYYY-MM-DD)")
    interval: str = Field(default="15m", description="Time interval (15m, 30m, 1h, 1d)")
    initial_capital: float = Field(default=100000, ge=10000, description="Initial capital")
    position_size: float = Field(default=1.0, ge=0.1, description="Position size in lots")
    use_tick_backtest: bool = Field(default=True, description="Use tick-level backtest engine")


class TradeRecord(BaseModel):
    """Single trade record"""
    entry_time: datetime
    exit_time: datetime
    direction: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    strategy: str
    exit_reason: str
    bars_held: int


class StrategyStats(BaseModel):
    """Statistics for a single strategy"""
    trades: int
    win_rate: float
    total_pnl: float
    avg_pnl: float


class BacktestResult(BaseModel):
    """Backtest result"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 1.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_win: float = 0.0
    max_loss: float = 0.0
    avg_bars_held: float = 0.0
    final_capital: float = 100000.0
    strategy_stats: Optional[Dict[str, StrategyStats]] = None


class DataInfo(BaseModel):
    """Data information for backtest"""
    start_date: str
    end_date: str
    interval: str
    total_ticks: int = 0
    ohlcv_bars: int = 0
    total_ticks_processed: int = 0
    using_tick_backtest: bool = True
    data_source: str = "local_tick"


class BacktestResponse(BaseModel):
    """Complete backtest response"""
    success: bool
    result: Optional[BacktestResult] = None
    equity_curve: Optional[List[Dict[str, Any]]] = None
    trades: Optional[List[TradeRecord]] = None
    data_info: Optional[DataInfo] = None
    error: Optional[str] = None


# ==================== Optimization Models ====================

class OptimizationRequest(BaseModel):
    """Optimization API request - using date range"""
    start_date: str = Field(default="2025-08-01", description="Start date (YYYY-MM-DD)")
    end_date: str = Field(default="2026-02-28", description="End date (YYYY-MM-DD)")
    interval: str = Field(default="15m", description="Time interval")
    population_size: int = Field(default=50, ge=10, le=200, description="GA population size")
    generations: int = Field(default=100, ge=10, le=500, description="Number of generations")
    crossover_rate: float = Field(default=0.8, ge=0.1, le=1.0, description="Crossover rate")
    mutation_rate: float = Field(default=0.1, ge=0.01, le=0.5, description="Mutation rate")
    objective: str = Field(default="total_return", description="Optimization objective")


class OptimizationProgress(BaseModel):
    """Optimization progress update"""
    generation: int
    total_generations: int
    best_fitness: float
    avg_fitness: float
    global_best: float
    best_params: Optional[Dict[str, Any]] = None


class OptimizationResult(BaseModel):
    """Final optimization result"""
    best_params: Dict[str, Any]
    best_fitness: float
    history: List[Dict[str, Any]]


class OptimizationResponse(BaseModel):
    """Optimization start response"""
    success: bool
    optimization_id: str
    message: str


# ==================== Preset Models ====================

class SavePresetRequest(BaseModel):
    """Save preset request"""
    name: str = Field(..., description="Preset name")
    params: BacktestParameters = Field(..., description="Parameters to save")
    description: str = Field(default="", description="Optional description")


class PresetResponse(BaseModel):
    """Preset response"""
    name: str
    params: Dict[str, Any]
    description: str
    created_at: str
    updated_at: str


class PresetsListResponse(BaseModel):
    """List of presets response"""
    presets: Dict[str, PresetResponse]
    count: int


class SavePresetResponse(BaseModel):
    """Save preset result"""
    success: bool
    message: str
    preset: Optional[PresetResponse] = None
    error: Optional[str] = None


# ==================== Config Models ====================

class ParameterBounds(BaseModel):
    """Parameter bounds for optimization"""
    min: float
    max: float


class ConfigResponse(BaseModel):
    """Default configuration response"""
    default_params: Dict[str, Any]
    param_bounds: Dict[str, ParameterBounds]
    descriptions: Dict[str, str]
    data_source: str = "local_tick"
    data_dir: str = "/home/ctyun/xauusd_data"
    available_months: List[str] = []


# ==================== Data Models ====================

class DataPreviewResponse(BaseModel):
    """Price data preview response"""
    timestamps: List[str]
    open: List[float]
    high: List[float]
    low: List[float]
    close: List[float]
    volume: List[float]
    count: int
    error: Optional[str] = None


class AvailableDataResponse(BaseModel):
    """Available data info response"""
    interval: str
    available_months: List[str]
    bars_count: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    has_real_data: bool = False
    data_source: str = "local_tick"
    error: Optional[str] = None


# ==================== Version Models ====================

class VersionFeatures(BaseModel):
    """System features flags"""
    lookahead_bias_fixed: bool = False
    dynamic_vwap_exit: bool = False
    atr_adaptive_time_stop: bool = False
    volatility_filter: bool = False
    pullback_confirmation: bool = False
    bayesian_optimization: bool = False
    walk_forward_validation: bool = False


class VersionInfo(BaseModel):
    """System version information"""
    version: str = "2.0.0"
    name: str = "XAUUSD Backtest System"
    refactored: bool = True
    optimizer: str = "Optuna TPE"
    features: VersionFeatures = Field(default_factory=VersionFeatures)
