# GitHub Actions Workflows

## CI Pipeline (`ci.yml`)

| Job | 触发条件 | 说明 |
|-----|---------|------|
| lint-and-security | push, PR | black 格式检查、flake8 代码检查、bandit 安全扫描 |
| test | push, PR | pytest 单元测试、覆盖率报告 (Python 3.10/3.11) |
| docker-build-test | push, PR | Docker 多阶段构建测试 |
| integration-test | push, PR | 容器启动后 API 健康检查 |

## CD Pipeline (`cd.yml`)

| Job | 触发条件 | 说明 |
|-----|---------|------|
| build-and-push | main push, tag | 构建并推送镜像到 GHCR，生成 SBOM |
| deploy-staging | main push | 部署到 Staging 环境 |
| deploy-production | tag push | 部署到 Production 环境，创建 GitHub Release |

## Required Secrets

在 GitHub Repository Settings > Secrets and variables > Actions 中配置：

- `STAGING_HOST` / `STAGING_USER` / `STAGING_SSH_KEY`
- `PROD_HOST` / `PROD_USER` / `PROD_SSH_KEY`
- `HTTP_PROXY` / `HTTPS_PROXY` (可选)
