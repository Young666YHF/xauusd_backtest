# XAUUSD 量化回测系统 - 环境配置文档

> 运维工程师输出 | 版本: 1.0 | 日期: 2026-06-09

---

## 一、环境概述

| 环境 | 用途 | 服务器规格 | 访问方式 |
|------|------|------------|----------|
| **开发环境 (Dev)** | 本地开发调试 | 开发者本地机器 | `http://localhost:8000` |
| **测试环境 (Test)** | CI/CD 自动化测试 | GitHub Actions Runner | 临时容器 |
| **预发布环境 (Staging)** | 预生产验证 | 云服务器 2C4G | `https://staging.xauusd.example.com` |
| **生产环境 (Production)** | 正式运行 | 云服务器 4C8G+ | `https://xauusd.example.com` |

---

## 二、服务器基础配置

### 2.1 操作系统要求

```bash
# 推荐 Ubuntu 22.04 LTS
lsb_release -a
# No LSB modules are available.
# Distributor ID: Ubuntu
# Description:    Ubuntu 22.04.4 LTS
# Release:        22.04
# Codename:       jammy
```

### 2.2 Docker 安装与配置

```bash
# 安装 Docker
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 验证安装
docker --version
docker compose version

# 配置 Docker 日志轮转
sudo tee /etc/docker/daemon.json > /dev/null << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}
EOF
sudo systemctl restart docker
```

### 2.3 目录结构

```bash
# 创建部署目录
sudo mkdir -p /opt/xauusd
sudo chown $USER:$USER /opt/xauusd

cd /opt/xauusd

# 目录结构
/opt/xauusd/
├── docker-compose.yml          # Docker Compose 配置
├── .env                        # 环境变量 (不提交到 Git)
├── data/                       # 数据挂载点 (外部卷)
│   └── xauusd_data/            # 指向 ../xauusd_data 的符号链接
├── logs/                       # 日志目录
├── results/                    # 回测结果
├── backups/                    # 部署备份
└── docker/                     # 监控配置
    ├── prometheus.yml
    ├── loki.yml
    ├── promtail.yml
    └── grafana/
        ├── dashboards/
        └── datasources/
```

---

## 三、环境变量配置

### 3.1 创建 `.env` 文件

复制 `.env.example` 并根据环境修改：

```bash
cp /opt/xauusd/.env.example /opt/xauusd/.env
chmod 600 /opt/xauusd/.env
```

### 3.2 Staging 环境 `.env` 示例

```bash
# =============================================================================
# Staging Environment Configuration
# =============================================================================

APP_ENV=staging
APP_PORT=8000
LOG_LEVEL=info

# 数据配置
DATA_DIR=/opt/xauusd_data
DATA_MOUNT_PATH=/data

# 交易配置 (Staging 使用保守参数)
INITIAL_CAPITAL=100000.0
LEVERAGE=100
SPREAD_PER_OUNCE=0.6
COMMISSION_PER_LOT=0.0

# Web 服务器
UVICORN_WORKERS=2
UVICORN_HOST=0.0.0.0
UVICORN_PORT=8000
CORS_ORIGINS=http://localhost:5173,https://staging.xauusd.example.com

# 监控
GRAFANA_PORT=3000
GRAFANA_USER=admin
GRAFANA_PASSWORD=<强密码>
PROMETHEUS_PORT=9090

# 回测资源限制
BACKTEST_MAX_WORKERS=2
BACKTEST_MEMORY_LIMIT=4G
```

### 3.3 Production 环境 `.env` 示例

```bash
# =============================================================================
# Production Environment Configuration
# =============================================================================

APP_ENV=production
APP_PORT=8000
LOG_LEVEL=warning

# 数据配置
DATA_DIR=/opt/xauusd_data
DATA_MOUNT_PATH=/data

# 交易配置
INITIAL_CAPITAL=100000.0
LEVERAGE=1000
SPREAD_PER_OUNCE=0.6
COMMISSION_PER_LOT=0.0

# Web 服务器 (Production 使用更多 worker)
UVICORN_WORKERS=4
UVICORN_HOST=0.0.0.0
UVICORN_PORT=8000
CORS_ORIGINS=https://xauusd.example.com

# 监控 (强密码必须修改)
GRAFANA_PORT=3000
GRAFANA_USER=admin
GRAFANA_PASSWORD=<16位以上强密码>
PROMETHEUS_PORT=9090

# 通知 (可选)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx
TELEGRAM_BOT_TOKEN=<bot_token>
TELEGRAM_CHAT_ID=<chat_id>

# 回测资源限制
BACKTEST_MAX_WORKERS=4
BACKTEST_MEMORY_LIMIT=8G
```

---

## 四、数据目录挂载

### 4.1 数据卷准备

```bash
# 方式 1: 使用 Docker Volume (推荐)
docker volume create xauusd_data

# 方式 2: 使用主机目录绑定 (开发/Staging 适用)
mkdir -p /opt/xauusd_data
# 将 xauusd_data 仓库的数据复制到此目录
```

### 4.2 权限设置

```bash
# 确保容器内的 xauusd 用户 (UID/GID 可能为 999) 可以读取数据
sudo chown -R 999:999 /opt/xauusd_data
sudo chmod -R 755 /opt/xauusd_data
```

---

## 五、防火墙与安全配置

### 5.1 UFW 防火墙规则

```bash
# 安装并启用 UFW
sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 允许必要端口
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80/tcp      # HTTP (如果前面有 Nginx)
sudo ufw allow 443/tcp     # HTTPS
sudo ufw allow 8000/tcp    # FastAPI (内部访问，建议不暴露公网)
sudo ufw allow 3000/tcp    # Grafana (建议限制 IP)
sudo ufw allow 9090/tcp    # Prometheus (仅限内网)

# 启用防火墙
sudo ufw enable
```

### 5.2 SSH 安全配置

```bash
# 编辑 /etc/ssh/sshd_config
sudo sed -i 's/#PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd
```

### 5.3 容器安全

- 生产容器以非 root 用户 (`xauusd`) 运行
- 仅暴露必要的端口
- 使用只读卷挂载数据 (`:ro`)
- 定期扫描镜像漏洞: `docker scan` 或 `trivy image`

---

## 六、监控配置

### 6.1 Prometheus 配置 (`docker/prometheus.yml`)

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'xauusd-backtest'
    static_configs:
      - targets: ['backtest-prod:8000']
    metrics_path: /metrics

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
```

### 6.2 关键监控指标

| 指标 | 告警阈值 | 说明 |
|------|----------|------|
| `up{job="xauusd-backtest"}` | == 0 | 服务宕机 |
| `container_cpu_usage_seconds_total` | > 80% 持续 5m | CPU 过高 |
| `container_memory_usage_bytes` | > 90% 持续 5m | 内存不足 |
| `disk_free` | < 10GB | 磁盘空间不足 |
| `api_request_duration_seconds` | p99 > 5s | API 响应过慢 |

---

## 七、维护操作手册

### 7.1 查看日志

```bash
# 查看所有服务日志
docker compose -f /opt/xauusd/docker-compose.yml --profile prod logs -f

# 查看特定服务日志
docker compose -f /opt/xauusd/docker-compose.yml --profile prod logs -f backtest-prod

# 查看最近 100 行
docker compose -f /opt/xauusd/docker-compose.yml --profile prod logs --tail=100 backtest-prod
```

### 7.2 重启服务

```bash
# 重启单个服务
docker compose -f /opt/xauusd/docker-compose.yml --profile prod restart backtest-prod

# 重启所有服务
docker compose -f /opt/xauusd/docker-compose.yml --profile prod restart
```

### 7.3 更新数据

```bash
# 进入数据服务容器
docker compose -f /opt/xauusd/docker-compose.yml --profile prod exec data-prod bash

# 在容器内运行数据验证
python3 verify_all_1m_data.py
```

### 7.4 备份数据

```bash
#!/bin/bash
# backup.sh - 数据备份脚本

BACKUP_DIR="/opt/backups/xauusd"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

# 备份数据目录
tar czf "${BACKUP_DIR}/data_${DATE}.tar.gz" -C /opt xauusd_data

# 备份结果
tar czf "${BACKUP_DIR}/results_${DATE}.tar.gz" -C /opt/xauusd results

# 保留最近 30 天的备份
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete

echo "备份完成: ${BACKUP_DIR}/data_${DATE}.tar.gz"
```

---

*文档结束。配置修改后需重启服务生效。*
