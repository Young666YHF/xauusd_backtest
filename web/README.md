# XAUUSD 回测系统 Web 界面

基于 FastAPI + React 的黄金量化交易回测系统 Web 界面。

## 功能特性

- **双策略系统**: 均值回归(策略A) + 动量突破(策略B)
- **参数回测**: 实时调整参数，快速验证策略效果
- **遗传算法优化**: WebSocket 实时显示优化进度
- **交互式图表**: ECharts 权益曲线、K线图等
- **交易明细**: 完整的交易记录和分析

## 技术栈

| 层 | 技术 |
|---|---|
| Backend | FastAPI + WebSocket |
| Frontend | React + Vite + TypeScript |
| Charts | ECharts |
| UI | Ant Design |

## 快速开始

### 后端

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python run_server.py

# 开发模式（自动重载）
python run_server.py --reload
```

服务启动后访问:
- Web 界面: http://localhost:8000
- API 文档: http://localhost:8000/docs

### 前端开发

```bash
cd web/frontend

# 安装依赖
npm install

# 开发模式
npm run dev

# 生产构建
npm run build
```

## API 端点

### 回测 API

- `GET /api/config/defaults` - 获取默认参数和范围
- `POST /api/backtest/run` - 执行回测
- `GET /api/data/preview` - 价格数据预览

### 优化 API

- `POST /api/optimize/start` - 启动优化
- `WebSocket /ws/optimize/{id}` - 实时进度推送
- `GET /api/optimize/{id}/result` - 获取最终结果

## 项目结构

```
web/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── api/
│   │   ├── backtest.py      # 回测 API
│   │   └── optimize.py      # 优化 API + WebSocket
│   ├── models/
│   │   └── schemas.py       # Pydantic 模型
│   └── services/
│       └── backtest_service.py
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api/client.ts
│   │   └── pages/
│   └── dist/                # 构建产物
└── README.md
```

## 参数说明

### 策略 A (均值回归)

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| rsi_oversold | 30 | 20-40 | RSI 超卖阈值 |
| rsi_overbought | 70 | 60-80 | RSI 超买阈值 |
| stop_loss_atr_mult_a | 1.5 | 1.0-2.5 | 止损 ATR 倍数 |
| max_hold_bars_a | 12 | 4-20 | 最大持仓 K 线数 |

### 策略 B (动量突破)

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| ema_fast | 20 | 10-30 | 快速 EMA 周期 |
| ema_slow | 50 | 30-70 | 慢速 EMA 周期 |
| stop_loss_atr_mult_b | 1.5 | 1.0-2.5 | 止损 ATR 倍数 |
| trailing_stop_atr_mult | 2.0 | 1.5-3.5 | 追踪止损 ATR 倍数 |

## 部署

生产环境使用 uvicorn:

```bash
uvicorn web.backend.main:app --host 0.0.0.0 --port 8000
```

建议配合 Nginx 反向代理使用。
