"""
FastAPI main application for XAUUSD Backtest Web Interface
简化版本 - 通过命令行接口提供服务
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from contextlib import asynccontextmanager
import os
import sys

# 添加项目根目录到路径
backend_dir = os.path.dirname(__file__)
project_root = os.path.dirname(os.path.dirname(backend_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.config import get_config
from strategies import StrategyRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    print("Starting XAUUSD Backtest Server v2.0...")
    yield
    print("Shutting down...")


app = FastAPI(
    title="XAUUSD Backtest System",
    description="Web interface for XAUUSD dual-strategy backtesting and optimization",
    version="2.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "xauusd-backtest", "version": "2.0.0"}


@app.get("/api/version")
async def version_info():
    """Get system version information"""
    return {
        "version": "2.0.0",
        "name": "XAUUSD Backtest System",
        "optimizer": "Optuna TPE",
        "features": {
            "lookahead_bias_fixed": True,
            "dynamic_vwap_exit": True,
            "atr_adaptive_time_stop": True,
            "volatility_filter": True,
            "pullback_confirmation": True,
            "bayesian_optimization": True,
            "walk_forward_validation": True,
            "dollar_trader_strategy": True,
        }
    }


@app.get("/api/strategies")
async def list_strategies():
    """List available strategies"""
    strategies = StrategyRegistry.list_strategies()
    info = {}
    for name in strategies:
        info[name] = StrategyRegistry.get_info(name)
    return {
        "strategies": strategies,
        "info": info
    }


@app.get("/api/config")
async def get_default_config():
    """Get default configuration"""
    config = get_config()
    return {
        "strategy": config.strategy.to_dict(),
        "trading": config.trading.model_dump(),
        "optimization": config.optimization.model_dump()
    }


# Import and include dollar trader routes
from api.dollar_trader import router as dollar_trader_router
app.include_router(dollar_trader_router)


# Mount static files for frontend (production build) - AFTER API routes
frontend_dist = os.path.join(os.path.dirname(__file__), "../frontend/dist")
frontend_assets = os.path.join(frontend_dist, "assets")

# Mount assets directory
if os.path.exists(frontend_assets):
    app.mount("/assets", StaticFiles(directory=frontend_assets), name="assets")


# Serve index.html for all other routes (SPA support)
@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    """Serve the SPA index.html for all non-API routes with no-cache headers"""
    index_file = os.path.join(frontend_dist, "index.html")
    if os.path.exists(index_file):
        with open(index_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(
            content=html_content,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {
        "error": "Frontend not built",
        "message": "Web API is available. Use /api/health and /api/version for status."
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
