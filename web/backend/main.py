"""
FastAPI main application for XAUUSD Backtest Web Interface
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from contextlib import asynccontextmanager
import os

# Import API routers (support both direct run and module import)
import sys
backend_dir = os.path.dirname(__file__)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from api.backtest import router as backtest_router
from api.optimize import router as optimize_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    # Startup
    print("Starting XAUUSD Backtest Server...")
    yield
    # Shutdown
    print("Shutting down...")


app = FastAPI(
    title="XAUUSD Backtest System",
    description="Web interface for XAUUSD dual-strategy backtesting and optimization",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers FIRST (before static files)
app.include_router(backtest_router)
app.include_router(optimize_router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "xauusd-backtest"}


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
        }
    }


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
        # Return HTML with cache-busting headers
        return HTMLResponse(
            content=html_content,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"error": "Frontend not built. Run 'npm run build' in frontend directory."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
