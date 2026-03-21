"""
Backtest API endpoints - 重构版本
使用重构后的策略和回测引擎
"""

from fastapi import APIRouter, HTTPException
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from models.schemas import (
        BacktestRequest,
        BacktestResponse,
        BacktestResult,
        TradeRecord,
        ConfigResponse,
        ParameterBounds,
        DataPreviewResponse,
        DataInfo,
        AvailableDataResponse,
        SavePresetRequest,
        SavePresetResponse,
        PresetsListResponse,
        PresetResponse,
        VersionInfo,
        VersionFeatures,
    )
except ImportError:
    from pydantic import BaseModel
    from typing import Dict, List, Optional, Any

    # 简化版模型定义
    class ParameterBounds(BaseModel):
        min: float
        max: float

    class BacktestRequest(BaseModel):
        parameters: Dict[str, Any]
        start_date: str
        end_date: str
        interval: str = "15m"
        initial_capital: float = 100000
        position_size: float = 1.0
        use_tick_backtest: bool = True

    class BacktestResult(BaseModel):
        total_trades: int
        winning_trades: int
        losing_trades: int
        win_rate: float
        total_pnl: float
        total_return: float
        max_drawdown: float
        sharpe_ratio: float
        profit_factor: float

    class BacktestResponse(BaseModel):
        success: bool
        result: Optional[BacktestResult] = None
        equity_curve: List[Dict] = []
        trades: List[Dict] = []
        data_info: Optional[Dict] = None
        error: Optional[str] = None
        refactored_features: Optional[Dict] = None

    class ConfigResponse(BaseModel):
        default_params: Dict[str, Any]
        param_bounds: Dict[str, ParameterBounds]
        descriptions: Dict[str, str]
        data_source: str
        data_dir: str
        available_months: List[str]
        refactored_version: bool = True

    class AvailableDataResponse(BaseModel):
        interval: str
        available_months: List[str]
        bars_count: int
        start_date: Optional[str]
        end_date: Optional[str]
        has_real_data: bool
        refactored_version: bool = True

    class DataPreviewResponse(BaseModel):
        timestamps: List[str]
        open: List[float]
        high: List[float]
        low: List[float]
        close: List[float]
        volume: List[float]
        count: int

    class DataInfo(BaseModel):
        start_date: str
        end_date: str
        interval: str
        total_ticks: int = 0
        ohlcv_bars: int = 0

    class SavePresetRequest(BaseModel):
        name: str
        params: Dict[str, Any]
        description: str = ""

    class SavePresetResponse(BaseModel):
        success: bool
        message: str
        preset: Optional[Dict] = None
        error: Optional[str] = None

    class PresetResponse(BaseModel):
        name: str
        params: Dict[str, Any]
        description: str
        created_at: str
        updated_at: str

    class PresetsListResponse(BaseModel):
        presets: Dict[str, PresetResponse]
        count: int

    class VersionInfo(BaseModel):
        version: str
        name: str
        refactored: bool
        optimizer: str
        features: Dict[str, bool]


    class TradeRecord(BaseModel):
        entry_time: str
        exit_time: str
        direction: str
        size: float
        entry_price: float
        exit_price: float
        pnl: float
        pnl_pct: float
        strategy: str
        exit_reason: str
        bars_held: int


# 使用回测服务
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.backtest_service import (
    backtest_service,
    save_preset,
    delete_preset,
    get_preset,
    list_presets,
    REFACTORED_DEFAULT_PARAMS
)

router = APIRouter(prefix="/api", tags=["backtest"])


@router.get("/config/defaults", response_model=ConfigResponse)
async def get_default_config():
    """Get default parameters and parameter bounds (Refactored Version)"""
    config = backtest_service.get_default_config()
    data_info = backtest_service.get_available_data_info()

    return ConfigResponse(
        default_params=config["default_params"],
        param_bounds={
            k: ParameterBounds(min=v["min"], max=v["max"])
            for k, v in config["param_bounds"].items()
        },
        descriptions=config["descriptions"],
        data_source=config["data_source"],
        data_dir=config["data_dir"],
        available_months=data_info.get("available_months", []),
        refactored_version=True
    )


@router.get("/data/info", response_model=AvailableDataResponse)
async def get_data_info(interval: str = "15m"):
    """Get information about available local tick data"""
    info = backtest_service.get_available_data_info(interval)
    return AvailableDataResponse(
        **info,
        refactored_version=True
    )


@router.post("/backtest/run", response_model=BacktestResponse)
async def run_backtest(request: BacktestRequest):
    """
    Run a backtest with refactored strategy

    Improvements:
    - Fixed look-ahead bias (entry on next bar open)
    - Dynamic VWAP exit check
    - ATR-adaptive time stop
    - Volatility filter for Strategy A
    - Pullback confirmation for Strategy B
    """

    try:
        # Convert parameters to dict
        if hasattr(request.parameters, 'model_dump'):
            params = request.parameters.model_dump()
        else:
            params = dict(request.parameters)

        # Validate parameter constraints
        if params.get('ema_fast', 0) >= params.get('ema_slow', 0):
            raise HTTPException(
                status_code=400,
                detail="Fast EMA period must be less than slow EMA period"
            )

        if params.get('rsi_oversold', 0) >= params.get('rsi_overbought', 0):
            raise HTTPException(
                status_code=400,
                detail="RSI oversold must be less than RSI overbought"
            )

        # 确保包含重构版本的默认参数
        full_params = REFACTORED_DEFAULT_PARAMS.copy()
        full_params.update(params)

        # Run backtest with tick-level data
        result = backtest_service.run_backtest(
            parameters=full_params,
            start_date=request.start_date,
            end_date=request.end_date,
            interval=request.interval,
            initial_capital=request.initial_capital,
            position_size=request.position_size,
            use_tick_backtest=request.use_tick_backtest
        )

        # Extract data info
        data_info = result.pop('data_info', None)

        # Extract trades
        trades = result.pop('trades', [])
        equity_curve = result.pop('equity_curve', [])

        # Extract refactored features info
        refactored_features = result.pop('refactored_features', {})

        # Build result object
        result_data = BacktestResult(
            total_trades=result.get('total_trades', 0),
            winning_trades=result.get('winning_trades', 0),
            losing_trades=result.get('losing_trades', 0),
            win_rate=result.get('win_rate', 0),
            total_pnl=result.get('total_pnl', 0),
            total_return=result.get('total_return', 0),
            max_drawdown=result.get('max_drawdown', 0),
            sharpe_ratio=result.get('sharpe_ratio', 0),
            profit_factor=result.get('profit_factor', 0)
        )

        return BacktestResponse(
            success=True,
            result=result_data,
            equity_curve=equity_curve,
            trades=trades,
            data_info=DataInfo(**data_info) if data_info else None,
            refactored_features=refactored_features
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return BacktestResponse(
            success=False,
            error=str(e)
        )


@router.get("/data/preview", response_model=DataPreviewResponse)
async def get_data_preview(days: int = 30, interval: str = "15m"):
    """Get price data preview from local tick data"""
    data = backtest_service.get_data_preview(days, interval)
    return DataPreviewResponse(**data)


# ==================== Preset Endpoints ====================

@router.get("/presets", response_model=PresetsListResponse)
async def get_presets():
    """Get all saved parameter presets"""
    presets = list_presets()
    preset_models = {
        name: PresetResponse(name=name, **preset)
        for name, preset in presets.items()
    }
    return PresetsListResponse(
        presets=preset_models,
        count=len(preset_models)
    )


@router.get("/presets/{name}", response_model=PresetResponse)
async def get_preset_by_name(name: str):
    """Get a specific preset by name"""
    preset = get_preset(name)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
    return PresetResponse(name=name, **preset)


@router.post("/presets", response_model=SavePresetResponse)
async def create_preset(request: SavePresetRequest):
    """Save a new parameter preset"""
    try:
        params = request.params
        if hasattr(params, 'model_dump'):
            params = params.model_dump()

        success = save_preset(
            name=request.name,
            params=params,
            description=request.description
        )

        preset = get_preset(request.name)
        return SavePresetResponse(
            success=success,
            message=f"Preset '{request.name}' saved successfully",
            preset=PresetResponse(**preset) if preset else None
        )
    except Exception as e:
        return SavePresetResponse(
            success=False,
            message="Failed to save preset",
            error=str(e)
        )


@router.delete("/presets/{name}")
async def delete_preset_by_name(name: str):
    """Delete a preset by name"""
    success = delete_preset(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
    return {"success": True, "message": f"Preset '{name}' deleted"}


# ==================== Refactored Version Info ====================

@router.get("/version", response_model=VersionInfo)
async def get_version_info():
    """Get version and refactoring information"""
    return VersionInfo(
        version="2.0.0",
        name="XAUUSD Refactored",
        refactored=True,
        optimizer="Optuna TPE",
        features={
            "lookahead_bias_fixed": True,
            "dynamic_vwap_exit": True,
            "atr_adaptive_time_stop": True,
            "volatility_filter": True,
            "pullback_confirmation": True,
            "bayesian_optimization": True,
            "walk_forward_validation": True
        }
    )
