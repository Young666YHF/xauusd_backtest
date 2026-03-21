// API Client - Refactored Version with Optuna Support

import axios from 'axios';
import type {
  BacktestRequest,
  BacktestResponse,
  ConfigResponse,
  OptimizationRequest,
  DataPreviewResponse,
  VersionInfo,
  RefactoringSummary,
  PresetsListResponse,
  PresetResponse,
} from '../types';

const api = axios.create({
  baseURL: '/api',
  timeout: 120000, // 2 minutes for backtest
});

export const backtestApi = {
  /**
   * Get default configuration and parameter bounds
   */
  async getConfig(): Promise<ConfigResponse> {
    const response = await api.get<ConfigResponse>('/config/defaults');
    return response.data;
  },

  /**
   * Run backtest with given parameters
   */
  async runBacktest(request: BacktestRequest): Promise<BacktestResponse> {
    const response = await api.post<BacktestResponse>('/backtest/run', request);
    return response.data;
  },

  /**
   * Get all parameter presets
   */
  async getPresets(): Promise<PresetsListResponse> {
    const response = await api.get<PresetsListResponse>('/presets');
    return response.data;
  },

  /**
   * Get a specific preset by name
   */
  async getPreset(name: string): Promise<PresetResponse> {
    const response = await api.get<PresetResponse>(`/presets/${encodeURIComponent(name)}`);
    return response.data;
  },

  /**
   * Get price data preview
   */
  async getDataPreview(days: number = 30): Promise<DataPreviewResponse> {
    const response = await api.get<DataPreviewResponse>('/data/preview', {
      params: { days },
    });
    return response.data;
  },

  /**
   * Get version information (refactored check)
   */
  async getVersionInfo(): Promise<VersionInfo> {
    try {
      const response = await api.get<VersionInfo>('/version');
      return response.data;
    } catch (e) {
      // Fallback to legacy mode
      return {
        version: '1.0.0',
        name: 'XAUUSD Legacy',
        refactored: false,
        optimizer: 'Genetic Algorithm',
        features: {
          lookahead_bias_fixed: false,
          dynamic_vwap_exit: false,
          atr_adaptive_time_stop: false,
          volatility_filter: false,
          pullback_confirmation: false,
          bayesian_optimization: false,
          walk_forward_validation: false,
        },
      };
    }
  },

  /**
   * Get refactoring summary
   */
  async getRefactoringSummary(): Promise<RefactoringSummary> {
    const response = await api.get<RefactoringSummary>('/refactoring-summary');
    return response.data;
  },
};

export const optimizeApi = {
  /**
   * Start optimization and return optimization ID
   * Supports both legacy GA and refactored Optuna
   */
  async startOptimization(request: OptimizationRequest): Promise<{ optimization_id: string }> {
    const response = await api.post('/optimize/start', request);
    return response.data;
  },

  /**
   * Create WebSocket connection for optimization progress
   * Compatible with both GA and Optuna backends
   */
  createOptimizationSocket(
    optimizationId: string,
    params: OptimizationRequest,
    onProgress: (data: any) => void,
    onComplete: (data: any) => void,
    onError: (error: string) => void
  ): WebSocket {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;

    // Build query params based on optimization type
    const isRefactored = params.n_trials !== undefined;

    let queryParams: string;
    if (isRefactored) {
      // Refactored: Optuna TPE
      queryParams = [
        `start_date=${params.start_date}`,
        `end_date=${params.end_date}`,
        `interval=${params.interval || '15m'}`,
        `n_trials=${params.n_trials}`,
        `min_trades=${params.min_trades || 100}`,
        `use_wfo=${params.use_wfo || false}`,
        params.use_wfo ? `n_splits=${params.n_splits || 3}` : '',
      ]
        .filter(Boolean)
        .join('&');
    } else {
      // Legacy: Genetic Algorithm
      queryParams = [
        `start_date=${params.start_date}`,
        `end_date=${params.end_date}`,
        `interval=${params.interval || '15m'}`,
        `population_size=${params.population_size}`,
        `generations=${params.generations}`,
        `objective=${params.objective}`,
      ].join('&');
    }

    const url = `${protocol}//${host}/ws/optimize/${optimizationId}?${queryParams}`;

    const ws = new WebSocket(url);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'complete') {
        onComplete(data);
      } else if (data.type === 'error') {
        onError(data.message || 'Optimization error');
      } else {
        onProgress(data);
      }
    };

    ws.onerror = () => {
      onError('WebSocket connection error');
    };

    ws.onclose = (event) => {
      if (!event.wasClean) {
        onError('Connection closed unexpectedly');
      }
    };

    return ws;
  },
};

export default api;
