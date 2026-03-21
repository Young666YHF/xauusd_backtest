"""
Optimization API endpoints with Optuna - 重构版本
使用TPE贝叶斯优化替代遗传算法
"""

import asyncio
import uuid
import sys
import os
from datetime import datetime
from typing import Dict, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

# Import models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from models.schemas import (
        OptimizationRequest,
        OptimizationResponse,
        OptimizationProgress,
        OptimizationResult,
        SavePresetRequest,
        SavePresetResponse,
        PresetResponse
    )
except ImportError:
    # 如果模型不存在，创建简化版本
    from pydantic import BaseModel

    class OptimizationRequest(BaseModel):
        start_date: str = "2025-08-01"
        end_date: str = "2026-02-28"
        interval: str = "15m"
        n_trials: int = 100
        min_trades: int = 100
        use_wfo: bool = False
        n_splits: int = 3

    class OptimizationResponse(BaseModel):
        success: bool
        optimization_id: str
        message: str

    class OptimizationProgress(BaseModel):
        generation: int
        total_generations: int
        best_fitness: float
        avg_fitness: float
        global_best: float
        best_params: Optional[Dict] = None

    class OptimizationResult(BaseModel):
        best_params: Dict
        best_fitness: float
        history: List[Dict]

    class SavePresetRequest(BaseModel):
        name: str
        description: str = ""

    class SavePresetResponse(BaseModel):
        success: bool
        message: str
        preset: Optional[Dict] = None

    class PresetResponse(BaseModel):
        params: Dict
        description: str
        created_at: str
        updated_at: str


from services.backtest_service import (
    save_preset,
    get_preset,
    DATA_DIR,
    backtest_service,
    REFACTORED_DEFAULT_PARAMS,
    REFACTORED_PARAM_BOUNDS
)

router = APIRouter(prefix="/api", tags=["optimization"])

# Store active optimizations
active_optimizations: Dict[str, dict] = {}


class OptimizationManager:
    """Manages optimization runs with WebSocket broadcasting - Optuna版本"""

    def __init__(self, optimization_id: str, websocket: WebSocket):
        self.optimization_id = optimization_id
        self.websocket = websocket
        self.is_running = True
        self.best_params = None
        self.best_fitness = float('-inf')
        self.history = []
        self.study = None

    async def send_progress(self, progress: OptimizationProgress):
        """Send progress update via WebSocket"""
        try:
            await self.websocket.send_json(progress.model_dump())
        except Exception:
            pass

    def stop(self):
        """Stop the optimization"""
        self.is_running = False


def create_optuna_callback(manager: OptimizationManager, n_trials: int):
    """创建Optuna回调函数用于发送进度"""
    def callback(study, trial):
        if not manager.is_running:
            study.stop()
            return

        # 每10个trial或最后一个发送进度
        if trial.number % 10 == 0 or trial.number == n_trials - 1:
            progress = OptimizationProgress(
                generation=trial.number + 1,
                total_generations=n_trials,
                best_fitness=round(study.best_value, 4) if study.best_value else 0,
                avg_fitness=round(study.trials_dataframe()['value'].mean(), 4) if len(study.trials) > 0 else 0,
                global_best=round(study.best_value, 4) if study.best_value else 0,
                best_params=study.best_params if trial.number % 20 == 0 else None
            )

            # 使用asyncio创建任务发送
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(manager.send_progress(progress))
            except Exception:
                pass

        # 记录历史
        manager.history.append({
            "trial": trial.number + 1,
            "value": trial.value if trial.value else 0,
            "best_value": study.best_value if study.best_value else 0
        })

    return callback


async def run_optuna_optimization_with_progress(
    manager: OptimizationManager,
    request: OptimizationRequest
):
    """Run Optuna optimization with WebSocket broadcasting"""

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

    import optuna
    from optuna_optimizer import create_optuna_objective, calculate_custom_fitness
    from data_loader import load_data_range
    from indicators import add_all_indicators
    from strategy import TradingStrategy
    from backtest import BacktestEngine

    print(f"[Optimization] Loading data from {request.start_date} to {request.end_date}...")

    # Load data
    try:
        ohlcv_df = load_data_range(DATA_DIR, request.start_date, request.end_date, request.interval)
        print(f"[Optimization] Loaded {len(ohlcv_df)} OHLCV bars")
    except Exception as e:
        print(f"[Optimization] Failed to load data: {e}")
        await manager.websocket.send_json({
            "type": "error",
            "message": f"Failed to load data: {e}"
        })
        return

    # Create Optuna study
    manager.study = optuna.create_study(
        direction='maximize',
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner()
    )

    # Create objective function
    def objective(trial):
        params = REFACTORED_DEFAULT_PARAMS.copy()

        # Sample parameters
        for param_name, (low, high) in REFACTORED_PARAM_BOUNDS.items():
            if isinstance(low, int) and isinstance(high, int):
                params[param_name] = trial.suggest_int(param_name, low, high)
            else:
                params[param_name] = trial.suggest_float(param_name, low, high)

        # Validate constraints
        if params['ema_fast'] >= params['ema_slow']:
            return -1e6
        if params['rsi_oversold'] >= params['rsi_overbought']:
            return -1e6

        try:
            # Add indicators
            df_ind = add_all_indicators(ohlcv_df, params)
            strategy = TradingStrategy(params)

            # Run backtest
            engine = BacktestEngine(
                initial_capital=100000,
                position_size=1.0,
                spread_per_ounce=0.6
            )

            stats = engine.run_backtest(df_ind, strategy, verbose=False)

            # Calculate fitness
            fitness = calculate_custom_fitness(stats, request.min_trades, verbose=False)

            # Store trial attributes
            trial.set_user_attr('total_trades', stats.get('total_trades', 0))
            trial.set_user_attr('total_return', stats.get('total_return', 0))
            trial.set_user_attr('max_drawdown', stats.get('max_drawdown', 0))
            trial.set_user_attr('win_rate', stats.get('win_rate', 0))

            return fitness

        except Exception as e:
            print(f"[Optimization] Trial error: {e}")
            return -1e6

    # Create callback
    callback = create_optuna_callback(manager, request.n_trials)

    print(f"[Optimization] Starting Optuna optimization with {request.n_trials} trials...")

    # Run optimization
    manager.study.optimize(
        objective,
        n_trials=request.n_trials,
        callbacks=[callback],
        show_progress_bar=False
    )

    # Store results
    manager.best_params = manager.study.best_params
    manager.best_fitness = manager.study.best_value

    print(f"[Optimization] Complete. Best fitness: {manager.best_fitness:.4f}")


async def run_wfo_optimization_with_progress(
    manager: OptimizationManager,
    request: OptimizationRequest
):
    """Run Walk-Forward optimization with WebSocket broadcasting"""

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

    from optuna_optimizer import run_walk_forward_optimization, calculate_custom_fitness
    from data_loader import load_data_range

    print(f"[WFO] Loading data from {request.start_date} to {request.end_date}...")

    # Load data
    try:
        ohlcv_df = load_data_range(DATA_DIR, request.start_date, request.end_date, request.interval)
        print(f"[WFO] Loaded {len(ohlcv_df)} OHLCV bars")
    except Exception as e:
        print(f"[WFO] Failed to load data: {e}")
        await manager.websocket.send_json({
            "type": "error",
            "message": f"Failed to load data: {e}"
        })
        return

    print(f"[WFO] Starting Walk-Forward Optimization...")

    # Run WFO
    result = run_walk_forward_optimization(
        ohlcv_df,
        n_splits=request.n_splits,
        n_trials=request.n_trials,
        min_trades=request.min_trades,
        verbose=True
    )

    # Store results
    manager.best_params = result['best_params']
    manager.best_fitness = result['best_oos_fitness']

    # Build history
    for split_result in result['all_results']:
        manager.history.append({
            "split": split_result['split'],
            "is_fitness": split_result['is_fitness'],
            "oos_fitness": split_result['oos_fitness']
        })

    print(f"[WFO] Complete. Best OOS fitness: {manager.best_fitness:.4f}")


@router.post("/optimize/start", response_model=OptimizationResponse)
async def start_optimization(request: OptimizationRequest):
    """Start an optimization run"""
    optimization_id = str(uuid.uuid4())[:8]

    mode_str = "WFO" if request.use_wfo else "Optuna TPE"

    return OptimizationResponse(
        success=True,
        optimization_id=optimization_id,
        message=f"{mode_str} optimization started. Connect to /ws/optimize/{optimization_id} for progress updates."
    )


@router.websocket("/ws/optimize/{optimization_id}")
async def optimization_websocket(websocket: WebSocket, optimization_id: str):
    """WebSocket endpoint for optimization progress"""

    await websocket.accept()

    # Get request parameters from query
    start_date = websocket.query_params.get("start_date", "2025-08-01")
    end_date = websocket.query_params.get("end_date", "2026-02-28")
    interval = websocket.query_params.get("interval", "15m")
    n_trials = int(websocket.query_params.get("n_trials", 100))
    min_trades = int(websocket.query_params.get("min_trades", 100))
    use_wfo = websocket.query_params.get("use_wfo", "false").lower() == "true"
    n_splits = int(websocket.query_params.get("n_splits", 3))

    request = OptimizationRequest(
        start_date=start_date,
        end_date=end_date,
        interval=interval,
        n_trials=n_trials,
        min_trades=min_trades,
        use_wfo=use_wfo,
        n_splits=n_splits
    )

    manager = OptimizationManager(optimization_id, websocket)
    active_optimizations[optimization_id] = manager

    try:
        # Send initial message
        await websocket.send_json({
            "type": "started",
            "message": f"Starting {'WFO' if use_wfo else 'Optuna'} optimization",
            "n_trials": n_trials,
            "use_wfo": use_wfo
        })

        # Run optimization
        if use_wfo:
            await run_wfo_optimization_with_progress(manager, request)
        else:
            await run_optuna_optimization_with_progress(manager, request)

        # Send final result
        if manager.best_params:
            await websocket.send_json({
                "type": "complete",
                "best_params": manager.best_params,
                "best_fitness": manager.best_fitness,
                "history": manager.history,
                "refactored_version": True
            })

    except WebSocketDisconnect:
        manager.stop()
    except Exception as e:
        import traceback
        print(f"[Optimization Error] {e}")
        traceback.print_exc()
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })
    finally:
        if optimization_id in active_optimizations:
            del active_optimizations[optimization_id]


@router.get("/optimize/{optimization_id}/result")
async def get_optimization_result(optimization_id: str):
    """Get final optimization result"""

    if optimization_id not in active_optimizations:
        raise HTTPException(status_code=404, detail="Optimization not found")

    manager = active_optimizations[optimization_id]

    if manager.best_params is None:
        raise HTTPException(status_code=400, detail="Optimization not complete")

    return OptimizationResult(
        best_params=manager.best_params,
        best_fitness=manager.best_fitness,
        history=manager.history
    )


@router.post("/optimize/{optimization_id}/save-preset", response_model=SavePresetResponse)
async def save_optimization_preset(
    optimization_id: str,
    preset_name: str,
    description: str = ""
):
    """Save optimization result as a preset"""

    if optimization_id not in active_optimizations:
        raise HTTPException(status_code=404, detail="Optimization not found or expired")

    manager = active_optimizations[optimization_id]

    if manager.best_params is None:
        raise HTTPException(status_code=400, detail="Optimization not complete")

    try:
        # Add fitness info to description
        full_description = f"{description}\nOptimized fitness: {manager.best_fitness:.4f}\nRefactored version with Optuna"

        success = save_preset(
            name=preset_name,
            params=manager.best_params,
            description=full_description.strip()
        )

        preset = get_preset(preset_name)
        return SavePresetResponse(
            success=success,
            message=f"Optimization result saved as preset '{preset_name}'",
            preset=PresetResponse(**preset) if preset else None
        )
    except Exception as e:
        return SavePresetResponse(
            success=False,
            message="Failed to save preset",
            error=str(e)
        )


@router.get("/optimization/info")
async def get_optimization_info():
    """Get information about the optimization system"""
    return {
        "optimizer": "Optuna TPE (Tree-structured Parzen Estimator)",
        "previous_optimizer": "Genetic Algorithm (deprecated)",
        "fitness_function": "Calmar Ratio (Return/Max Drawdown)",
        "features": [
            "Bayesian optimization with TPE sampler",
            "Calmar ratio as primary objective",
            "Trade count penalty for statistical significance",
            "Walk-Forward Optimization (WFO) support",
            "Median pruner for early stopping"
        ],
        "refactored_version": True,
        "improvements": {
            "module1": "Fixed look-ahead bias, dynamic VWAP exit, ATR-adaptive time stop",
            "module2": "Volatility filter for strategy A, pullback confirmation for strategy B",
            "module3": "Optuna TPE optimization, Calmar ratio fitness, WFO validation"
        }
    }
