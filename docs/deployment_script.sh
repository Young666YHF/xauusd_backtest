#!/bin/bash
# =============================================================================
# XAUUSD 量化回测系统 - 自动化部署脚本
# 用途: Staging / Production 环境一键部署
# 用法: ./deploy.sh [staging|production] [版本标签]
# 示例:
#   ./deploy.sh staging          # 部署 main 分支最新镜像
#   ./deploy.sh production v2.1.0 # 部署 v2.1.0 标签镜像
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# 配置变量 (根据环境修改)
# -----------------------------------------------------------------------------
ENVIRONMENT="${1:-staging}"
VERSION="${2:-main}"
REGISTRY="ghcr.io"
IMAGE_NAME="young666yhf/xauusd_backtest"
COMPOSE_FILE="/opt/xauusd/docker-compose.yml"
DEPLOY_DIR="/opt/xauusd"
BACKUP_DIR="/opt/xauusd/backups"
RETAIN_BACKUPS=3

# 日志颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# -----------------------------------------------------------------------------
# 前置检查
# -----------------------------------------------------------------------------
check_prerequisites() {
    log_info "检查前置条件..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose 未安装"
        exit 1
    fi

    if [ "$EUID" -ne 0 ] && [ "$ENVIRONMENT" == "production" ]; then
        log_warn "Production 部署建议以 root 或具有 docker 权限的用户执行"
    fi

    log_info "前置条件检查通过"
}

# -----------------------------------------------------------------------------
# 登录容器仓库
# -----------------------------------------------------------------------------
registry_login() {
    log_info "登录容器仓库 ${REGISTRY}..."
    # 需要在服务器上预先配置 ~/.docker/config.json 或使用 docker login
    # GHCR 使用 PAT (Personal Access Token):
    #   echo $GITHUB_PAT | docker login ghcr.io -u USERNAME --password-stdin
    if ! docker pull "${REGISTRY}/${IMAGE_NAME}:${VERSION}" &> /dev/null; then
        log_warn "无法拉取镜像，尝试登录..."
        if [ -z "${GITHUB_PAT:-}" ]; then
            log_error "环境变量 GITHUB_PAT 未设置，无法登录 GHCR"
            exit 1
        fi
        echo "$GITHUB_PAT" | docker login ghcr.io -u "${GITHUB_USER:-}" --password-stdin
    fi
}

# -----------------------------------------------------------------------------
# 备份当前运行状态
# -----------------------------------------------------------------------------
backup_current() {
    log_info "备份当前部署状态..."
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_NAME="backup_${ENVIRONMENT}_${TIMESTAMP}"

    # 导出当前 compose 配置
    if [ -f "$COMPOSE_FILE" ]; then
        cp "$COMPOSE_FILE" "${BACKUP_DIR}/${BACKUP_NAME}_compose.yml"
    fi

    # 备份当前运行的镜像标签
    CURRENT_IMAGE=$(docker ps --filter "name=backtest-${ENVIRONMENT}" --format "{{.Image}}" || true)
    if [ -n "$CURRENT_IMAGE" ]; then
        echo "$CURRENT_IMAGE" > "${BACKUP_DIR}/${BACKUP_NAME}_image.txt"
    fi

    # 清理旧备份
    ls -t "$BACKUP_DIR" | tail -n +$((RETAIN_BACKUPS + 1)) | xargs -r rm -rf

    log_info "备份完成: ${BACKUP_NAME}"
}

# -----------------------------------------------------------------------------
# 拉取并部署新镜像
# -----------------------------------------------------------------------------
deploy_new_version() {
    log_info "部署 ${ENVIRONMENT} 环境，版本: ${VERSION}..."

    cd "$DEPLOY_DIR"

    # 拉取新镜像
    docker pull "${REGISTRY}/${IMAGE_NAME}:${VERSION}"

    # 设置环境变量
    export BACKTEST_PORT="${BACKTEST_PORT:-8000}"
    export GRAFANA_PORT="${GRAFANA_PORT:-3000}"
    export GRAFANA_USER="${GRAFANA_USER:-admin}"
    export GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-change_me}"
    export UVICORN_WORKERS="${UVICORN_WORKERS:-4}"
    export IMAGE_TAG="${VERSION}"

    # 停止当前服务
    log_info "停止当前服务..."
    if docker compose version &> /dev/null; then
        docker compose -f "$COMPOSE_FILE" --profile prod down
    else
        docker-compose -f "$COMPOSE_FILE" --profile prod down
    fi

    # 启动新服务
    log_info "启动新服务..."
    if docker compose version &> /dev/null; then
        docker compose -f "$COMPOSE_FILE" --profile prod up -d
    else
        docker-compose -f "$COMPOSE_FILE" --profile prod up -d
    fi

    # 清理旧镜像
    docker system prune -f

    log_info "部署命令执行完成"
}

# -----------------------------------------------------------------------------
# 健康检查
# -----------------------------------------------------------------------------
health_check() {
    log_info "执行健康检查..."

    HEALTH_URL="http://localhost:${BACKTEST_PORT:-8000}/api/health"
    MAX_RETRIES=12
    RETRY_DELAY=5

    for i in $(seq 1 $MAX_RETRIES); do
        if curl -sf "$HEALTH_URL" &> /dev/null; then
            log_info "健康检查通过 ✅"
            return 0
        fi
        log_warn "健康检查第 ${i}/${MAX_RETRIES} 次重试..."
        sleep $RETRY_DELAY
    done

    log_error "健康检查失败 ❌"
    return 1
}

# -----------------------------------------------------------------------------
# 回滚到上一版本
# -----------------------------------------------------------------------------
rollback() {
    log_warn "执行回滚..."

    LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/*_image.txt 2>/dev/null | head -1)
    if [ -z "$LATEST_BACKUP" ]; then
        log_error "未找到可用备份，无法回滚"
        exit 1
    fi

    PREV_IMAGE=$(cat "$LATEST_BACKUP")
    PREV_VERSION="${PREV_IMAGE##*:}"

    log_info "回滚到版本: ${PREV_VERSION}"
    VERSION="$PREV_VERSION"
    deploy_new_version
    health_check || log_error "回滚后健康检查仍失败，请手动介入"
}

# -----------------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------------
main() {
    echo "========================================"
    echo "  XAUUSD 回测系统部署脚本"
    echo "  环境: ${ENVIRONMENT}"
    echo "  版本: ${VERSION}"
    echo "========================================"

    check_prerequisites
    backup_current

    if [ "${SKIP_REGISTRY_LOGIN:-false}" != "true" ]; then
        registry_login
    fi

    deploy_new_version

    if ! health_check; then
        log_error "部署后健康检查失败，准备回滚..."
        rollback
        exit 1
    fi

    log_info "部署成功完成! 🚀"
    echo ""
    echo "访问地址:"
    echo "  API:      http://localhost:${BACKTEST_PORT:-8000}"
    echo "  Grafana:  http://localhost:${GRAFANA_PORT:-3000}"
    echo "========================================"
}

# 如果直接执行脚本（非 source）
if [ "${BASH_SOURCE[0]}" == "${0}" ]; then
    main "$@"
fi
