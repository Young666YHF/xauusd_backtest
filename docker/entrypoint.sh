#!/bin/sh
# XAUUSD Backtest System - Docker Entrypoint
# Supports multiple execution modes

set -e

# Default to web server if no command specified
if [ $# -eq 0 ]; then
    echo "Starting XAUUSD Backtest Web Server..."
    exec uvicorn web.backend.main:app \
        --host "${UVICORN_HOST:-0.0.0.0}" \
        --port "${UVICORN_PORT:-8000}" \
        --workers "${UVICORN_WORKERS:-1}"
fi

# Mode selection via environment variable
MODE="${MODE:-$1}"

case "$MODE" in
    web|server)
        echo "Starting Web Server..."
        shift || true
        exec uvicorn web.backend.main:app \
            --host "${UVICORN_HOST:-0.0.0.0}" \
            --port "${UVICORN_PORT:-8000}" \
            --workers "${UVICORN_WORKERS:-1}" "$@"
        ;;

    backtest)
        echo "Running Backtest..."
        shift || true
        exec python run_backtest.py "$@"
        ;;

    optimize)
        echo "Running Optimization..."
        shift || true
        exec python run_optimization.py "$@"
        ;;

    test|pytest)
        echo "Running Tests..."
        shift || true
        exec pytest tests/ -v --tb=short "$@"
        ;;

    shell|bash|sh)
        echo "Starting shell..."
        exec /bin/sh
        ;;

    *)
        # Pass through any other command
        exec "$@"
        ;;
esac
