# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Docker multi-stage builds for production, development, and backtest runner targets
- docker-compose profiles for dev/test/prod environment isolation
- GitHub Actions CI pipeline with lint, test, security scan, and Docker build
- GitHub Actions CD pipeline with staging and production deployment
- Monitoring stack: Prometheus, Grafana, Loki, Promtail, Node Exporter, cAdvisor
- `.env.example` template for environment variable management
- Comprehensive DevOps operations guide

### Changed
- Optimized Docker image size via multi-stage builds

## [2.0.0] - 2024-03-30

### Added
- Tick-level backtest engine with Numba JIT optimization
- Optuna-based Bayesian optimization with walk-forward validation
- Multi-strategy support: MeanReversion, MomentumBreakout, TrendAngleBreakout, DollarTrader variants
- BreakoutGrid strategy with dedicated documentation
- Web interface (FastAPI + React) for backtesting and optimization
- MT4 EA and Pine Script code generation
- Dynamic VWAP exit and ATR adaptive time stop
- Volatility filter and pullback confirmation

### Fixed
- Lookahead bias protection
- Tick alignment in backtest engine
