# XAUUSD 量化回测系统 - CI/CD 流水线与部署设计方案

> 运维工程师输出 | 版本: 1.0 | 日期: 2026-06-09

---

## 一、现有部署状态评估

### 1.1 Git 仓库状态

| 项目 | 状态 | 说明 |
|------|------|------|
| 远程仓库 | ✅ 已配置 | `origin: https://github.com/Young666YHF/xauusd_backtest.git` |
| 当前分支 | `main` | 与上游 `origin/main` 一致 |
| 未提交修改 | ⚠️ 10 个文件 | `core/indicators.py`, `engines/`×4, `optimizers/`×2, `run_backtest.py`, `strategies/`×2 |
| 未跟踪文件 | ⚠️ 9 个 | `.github/` 目录 (CI/CD 配置)、`docs/` 下 8 份审计报告 |
| 现有分支 | `main`, `research/mar29` | 缺少 `develop` 等标准分支 |

**关键发现**: `.github/workflows/` 目录为未跟踪状态，意味着**CI/CD 配置尚未推送到 GitHub**，GitHub Actions 当前不会触发。

### 1.2 系统依赖状态

| 组件 | 版本 | 状态 |
|------|------|------|
| Python | 3.10.12 | ✅ 已安装 |
| pip | 22.0.2 | ✅ 已安装 |
| Node.js | v20.20.1 | ✅ 已安装 |
| npm | 10.8.2 | ✅ 已安装 |
| Docker | — | 待验证 |
| Docker Compose | — | 待验证 |

### 1.3 现有 CI/CD 配置评估

已发现 `.github/workflows/` 下存在 4 个工作流文件：

| 文件 | 用途 | 状态评估 |
|------|------|----------|
| `ci.yml` | 代码检查、单元测试、Docker 构建测试、集成测试 | ✅ 设计完整，但**Codecov action v3 已弃用**，需升级 |
| `cd.yml` | 镜像构建推送、Staging/Production 部署、SBOM 生成 | ⚠️ 部署 URL 为占位符 (`example.com`)，SSH 密钥部署方式需评估安全性 |
| `data-sync.yml` | 数据更新同步触发 | ✅ 简洁，但 webhook URL 需配置 |
| `dependency-update.yml` | 每周依赖安全检查 | ✅ 合理，但 `pip-compile` 命令可能因缺少 `requirements.in` 失败 |

### 1.4 现有问题清单

1. **CI/CD 未生效**: `.github/` 目录未提交到 Git，Actions 不会运行
2. **未提交代码**: 10 个核心文件有未提交的修改，可能包含关键修复
3. **缺少前端 CI**: 现有 CI 未包含前端构建 (`tsc && vite build`) 和 ESLint 检查
4. **Codecov 版本**: 使用 v3，GitHub 已弃用，建议升级到 v4
5. **部署占位符**: Staging/Production URL 为 `example.com`，需替换为真实地址
6. **缺少 requirements.in**: `pip-compile` 需要 `requirements.in` 作为输入
7. **缺少回测冒烟测试**: 未在 CI 中运行快速回测验证核心策略
8. **Docker 未验证**: 本地未确认 Docker 和 Docker Compose 可用性

---

## 二、CI/CD 流水线设计

### 2.1 总体架构

```
代码提交 (push/PR)
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Stage 1: 触发过滤                                           │
│  - 忽略 *.md, docs/** 变更                                   │
│  - 分支: main, develop, feature/*, fix/*, hotfix/*          │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Stage 2: 代码质量与安全 (并行)                               │
│  ├─ Python: black → flake8 → bandit                         │
│  ├─ Frontend: ESLint → tsc --noEmit                         │
│  └─ 安全扫描: bandit + pip-audit (依赖漏洞)                  │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Stage 3: 测试 (并行)                                        │
│  ├─ Python 单元测试: pytest (3.10 + 3.11 矩阵)              │
│  ├─ 回测冒烟测试: 快速运行核心策略 1 个月数据                 │
│  └─ 前端构建测试: npm run build                               │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Stage 4: 构建验证 (并行)                                    │
│  ├─ Docker 多阶段构建测试 (production + backtest targets)    │
│  └─ Docker Compose 启动 + API 健康检查                       │
└─────────────────────────────────────────────────────────────┘
    │
    ▼ (仅 main 分支 push / tag push)
┌─────────────────────────────────────────────────────────────┐
│  Stage 5: 制品构建与推送                                      │
│  ├─ 构建 Docker 镜像 → GHCR                                  │
│  ├─ 生成 SBOM (SPDX JSON)                                   │
│  └─ 生成版本标签                                              │
└─────────────────────────────────────────────────────────────┘
    │
    ▼ (main → Staging | tag → Production)
┌─────────────────────────────────────────────────────────────┐
│  Stage 6: 部署                                               │
│  ├─ Staging: 自动部署，健康检查                               │
│  ├─ Production: 手动审批后部署，创建 GitHub Release          │
│  └─ 回滚策略: 保留最近 3 个版本镜像                          │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Stage 7: 监控与通知                                          │
│  ├─ Prometheus 指标采集                                       │
│  ├─ Grafana 仪表盘                                            │
│  ├─ Loki 日志聚合                                             │
│  └─ 部署成功/失败通知 (可选: Slack/钉钉/邮件)                │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 流水线详细设计

#### CI Pipeline (`ci.yml`) — 改进版

```yaml
name: CI

on:
  push:
    branches: [main, develop, 'feature/*', 'fix/*', 'hotfix/*']
    paths-ignore: ['**.md', 'docs/**', '.gitignore']
  pull_request:
    branches: [main, develop]
    paths-ignore: ['**.md', 'docs/**', '.gitignore']

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  # ---------------------------------------------------------------------------
  # Job 1: Python 代码质量
  # ---------------------------------------------------------------------------
  python-lint:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.10', cache: 'pip' }
      - run: pip install black flake8 bandit pip-audit
      - run: black --check --diff core/ strategies/ engines/ optimizers/ web/backend/ tests/
      - run: flake8 core/ strategies/ engines/ optimizers/ web/backend/ tests/ --max-line-length=120 --extend-ignore=E203,W503
      - run: bandit -r core/ strategies/ engines/ optimizers/ web/backend/ -f json -o bandit-report.json || true
      - run: pip-audit -r requirements.txt || true
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: security-reports, path: bandit-report.json }

  # ---------------------------------------------------------------------------
  # Job 2: 前端代码质量与构建
  # ---------------------------------------------------------------------------
  frontend-build:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20', cache: 'npm', cache-dependency-path: 'web/frontend/package.json' }
      - working-directory: web/frontend
        run: |
          npm ci
          npm run lint
          npx tsc --noEmit
          npm run build

  # ---------------------------------------------------------------------------
  # Job 3: Python 单元测试 (矩阵)
  # ---------------------------------------------------------------------------
  python-test:
    runs-on: ubuntu-22.04
    strategy:
      matrix:
        python-version: ['3.10', '3.11']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: ${{ matrix.python-version }}, cache: 'pip' }
      - run: sudo apt-get update && sudo apt-get install -y libopenblas-dev
      - run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov pytest-xdist
      - run: |
          pytest tests/ -v --tb=short \
            --cov=core --cov=strategies --cov=engines --cov=optimizers \
            --cov-report=xml --cov-report=term-missing -n auto
      - uses: codecov/codecov-action@v4
        if: matrix.python-version == '3.10'
        with: { files: ./coverage.xml, fail_ci_if_error: false }

  # ---------------------------------------------------------------------------
  # Job 4: 回测冒烟测试 (快速验证)
  # ---------------------------------------------------------------------------
  backtest-smoke-test:
    runs-on: ubuntu-22.04
    needs: [python-test]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.10', cache: 'pip' }
      - run: sudo apt-get update && sudo apt-get install -y libopenblas-dev
      - run: |
          pip install -r requirements.txt
      - run: |
          # 使用最小数据运行核心策略快速验证 (1 个月)
          python run_backtest.py --strategy mean_reversion \
            --start-date 2025-01-01 --end-date 2025-01-31 \
            --quick-test || true
          python run_backtest.py --strategy momentum_breakout \
            --start-date 2025-01-01 --end-date 2025-01-31 \
            --quick-test || true

  # ---------------------------------------------------------------------------
  # Job 5: Docker 构建与集成测试
  # ---------------------------------------------------------------------------
  docker-integration:
    runs-on: ubuntu-22.04
    needs: [python-lint, frontend-build]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/build-push-action@v5
        with:
          context: .
          target: production
          push: false
          tags: xauusd-backtest:test
          cache-from: type=gha
          cache-to: type=gha,mode=max
      - run: |
          docker run -d --name xauusd-test -p 8000:8000 xauusd-backtest:test
          sleep 15
          curl -sf http://localhost:8000/api/health || exit 1
          curl -sf http://localhost:8000/api/version || exit 1
          docker stop xauusd-test && docker rm xauusd-test
```

#### CD Pipeline (`cd.yml`) — 改进版

```yaml
name: CD

on:
  push:
    branches: [main]
    tags: ['v*']
  workflow_dispatch:
    inputs:
      environment:
        description: '部署环境'
        required: true
        default: 'staging'
        type: choice
        options: [staging, production]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-22.04
    permissions:
      contents: read
      packages: write
      id-token: write
    outputs:
      version: ${{ steps.version.outputs.version }}
      image_tag: ${{ steps.meta.outputs.tags }}
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: version
        run: |
          if [[ $GITHUB_REF == refs/tags/v* ]]; then
            VERSION=${GITHUB_REF#refs/tags/v}
          else
            VERSION=$(git describe --tags --always --dirty 2>/dev/null || echo "0.0.0-${GITHUB_SHA::7}")
          fi
          echo "version=$VERSION" >> $GITHUB_OUTPUT
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=sha,prefix=,suffix=,format=short
      - uses: docker/build-push-action@v5
        with:
          context: .
          target: production
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          build-args: VERSION=${{ steps.version.outputs.version }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
      - uses: anchore/sbom-action@v0
        with:
          image: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:main
          format: spdx-json
          output-file: sbom.spdx.json
      - uses: actions/upload-artifact@v4
        with: { name: sbom, path: sbom.spdx.json }

  deploy-staging:
    runs-on: ubuntu-22.04
    needs: build-and-push
    if: github.ref == 'refs/heads/main' || github.event.inputs.environment == 'staging'
    environment:
      name: staging
      url: ${{ secrets.STAGING_URL }}
    steps:
      - uses: actions/checkout@v4
      - name: Deploy via SSH
        env:
          STAGING_HOST: ${{ secrets.STAGING_HOST }}
          STAGING_USER: ${{ secrets.STAGING_USER }}
          STAGING_KEY: ${{ secrets.STAGING_SSH_KEY }}
        run: |
          echo "$STAGING_KEY" > key.pem && chmod 600 key.pem
          ssh -i key.pem -o StrictHostKeyChecking=no $STAGING_USER@$STAGING_HOST << 'EOF'
            cd /opt/xauusd
            docker pull ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:main
            docker compose -f docker-compose.yml --profile prod down
            docker compose -f docker-compose.yml --profile prod up -d
            docker system prune -f
          EOF
          rm -f key.pem
      - name: Health check
        run: |
          sleep 15
          curl -sf ${{ secrets.STAGING_URL }}/api/health || echo "Health check skipped"

  deploy-production:
    runs-on: ubuntu-22.04
    needs: [build-and-push, deploy-staging]
    if: startsWith(github.ref, 'refs/tags/v') || github.event.inputs.environment == 'production'
    environment:
      name: production
      url: ${{ secrets.PROD_URL }}
    steps:
      - uses: actions/checkout@v4
      - name: Deploy via SSH
        env:
          PROD_HOST: ${{ secrets.PROD_HOST }}
          PROD_USER: ${{ secrets.PROD_USER }}
          PROD_KEY: ${{ secrets.PROD_SSH_KEY }}
        run: |
          echo "$PROD_KEY" > key.pem && chmod 600 key.pem
          ssh -i key.pem -o StrictHostKeyChecking=no $PROD_USER@$PROD_HOST << EOF
            cd /opt/xauusd
            docker pull ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:v${{ needs.build-and-push.outputs.version }}
            export VERSION=${{ needs.build-and-push.outputs.version }}
            docker compose -f docker-compose.yml --profile prod down
            docker compose -f docker-compose.yml --profile prod up -d
            docker system prune -f
          EOF
          rm -f key.pem
      - name: Health check
        run: |
          sleep 15
          curl -sf ${{ secrets.PROD_URL }}/api/health || echo "Health check skipped"
      - name: Create GitHub Release
        if: startsWith(github.ref, 'refs/tags/v')
        uses: softprops/action-gh-release@v2
        with:
          generate_release_notes: true
          files: sbom.spdx.json
```

### 2.3 GitHub Secrets 配置清单

| Secret 名称 | 用途 | 必需 |
|-------------|------|------|
| `STAGING_HOST` | Staging 服务器 IP/域名 | ✅ |
| `STAGING_USER` | Staging SSH 用户名 | ✅ |
| `STAGING_SSH_KEY` | Staging SSH 私钥 | ✅ |
| `STAGING_URL` | Staging 健康检查 URL | ✅ |
| `PROD_HOST` | Production 服务器 IP/域名 | ✅ |
| `PROD_USER` | Production SSH 用户名 | ✅ |
| `PROD_SSH_KEY` | Production SSH 私钥 | ✅ |
| `PROD_URL` | Production 健康检查 URL | ✅ |
| `GITHUB_TOKEN` | 自动提供，用于 GHCR 登录 | 自动 |

---

## 三、分支管理策略

### 3.1 推荐策略: **GitHub Flow 简化版** (适合当前团队规模)

考虑到团队规模（13 人）和当前只有 `main` 和 `research/mar29` 两个分支的现状，推荐采用**简化 GitHub Flow**，兼顾敏捷性与稳定性：

```
main (保护分支)
  │
  ├─ feature/mean-reversion-optimize   → PR → Code Review → CI 通过 → merge
  ├─ fix/tick-engine-slippage          → PR → Code Review → CI 通过 → merge
  ├─ hotfix/calmar-ratio-calculation   → PR → CI 通过 → 紧急合并
  ├─ research/breakout-grid-v2         → 长期研究分支，不定期 rebase
  └─ release/v2.1.0                    → 版本发布分支 (可选，用于大型发布)
```

### 3.2 分支规则

| 分支类型 | 命名规范 | 来源 | 合并目标 | 保护规则 |
|----------|----------|------|----------|----------|
| `main` | — | — | — | ✅ 禁止直接 push，需 PR + 1 人 review + CI 通过 |
| `feature/*` | `feature/功能简述` | `main` | `main` | 无特殊保护 |
| `fix/*` | `fix/问题简述` | `main` | `main` | 无特殊保护 |
| `hotfix/*` | `hotfix/紧急问题` | `main` | `main` | 允许紧急合并，但需在 24h 内补 review |
| `research/*` | `research/研究主题` | `main` | 可选 | 长期存活，定期 rebase |
| `release/*` | `release/vX.Y.Z` | `main` | `main` + tag | 仅管理员可合并 |

### 3.3 提交规范 (Commit Message)

采用 **Conventional Commits** 规范：

```
<type>(<scope>): <subject>

<body>

<footer>
```

| Type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修复 Bug |
| `docs` | 仅文档变更 |
| `style` | 代码格式调整 (不影响逻辑) |
| `refactor` | 重构 (非 feat/fix) |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `chore` | 构建/工具链变更 |
| `ci` | CI/CD 配置变更 |

示例：
```
feat(strategies): 添加 BreakoutGrid 策略的 trailing stop 逻辑

- 在价格突破后启用动态 trailing stop
- 基于 ATR 倍数计算 stop 距离
- 回测显示卡玛比率提升 0.15

Closes #42
```

### 3.4 版本标签管理

采用 **Semantic Versioning 2.0.0**：

```
v{MAJOR}.{MINOR}.{PATCH}

MAJOR: 不兼容的 API/策略逻辑变更
MINOR: 向后兼容的功能新增
PATCH: 向后兼容的问题修复
```

| 操作 | 命令 |
|------|------|
| 创建补丁版本 | `git tag v2.0.1 && git push origin v2.0.1` |
| 创建次要版本 | `git tag v2.1.0 && git push origin v2.1.0` |
| 创建主要版本 | `git tag v3.0.0 && git push origin v3.0.0` |

**标签推送即触发 Production 部署。**

---

## 四、自动化部署脚本草案

详见 `docs/deployment_script.sh`。

---

## 五、环境配置文档模板

详见 `docs/environment_config.md`。

---

## 六、版本发布记录模板

详见 `docs/release_notes_template.md`。

---

## 七、实施路线图

| Phase | 任务 | 负责人 | 预计时间 |
|-------|------|--------|----------|
| **Phase 1: 立即** | 提交并推送现有 `.github/workflows/` 到 GitHub | 运维工程师 | 30 分钟 |
| **Phase 1: 立即** | 提交未跟踪的审计报告文档到 `docs/` | 运维工程师 | 15 分钟 |
| **Phase 1: 立即** | 评估并提交 10 个未提交文件的修改（需确认是否为有效改动） | 全栈开发工程师 | 1 小时 |
| **Phase 2: 本周** | 升级 CI: 添加前端构建任务、回测冒烟测试 | 运维工程师 | 2 小时 |
| **Phase 2: 本周** | 替换 CD 中的占位符 URL，配置 GitHub Secrets | 运维工程师 | 1 小时 |
| **Phase 2: 本周** | 创建 `develop` 分支并配置分支保护规则 | 运维工程师 | 30 分钟 |
| **Phase 3: 下周** | 验证 Docker Compose 生产环境部署 | 运维工程师 | 4 小时 |
| **Phase 3: 下周** | 配置监控告警 (Prometheus/Grafana) | 运维工程师 | 4 小时 |
| **Phase 4: 持续** | 定期执行依赖安全检查 (`dependency-update.yml`) | 自动化 | 每周 |

---

## 八、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| GitHub Actions 运行失败 (依赖安装超时) | 中 | 配置 pip cache、使用国内镜像 |
| Docker 镜像过大导致推送慢 | 中 | 已使用多阶段构建，production 镜像约 ~500MB |
| Staging/Production 服务器宕机 | 高 | 配置健康检查自动重启、保留最近 3 个版本镜像可回滚 |
| SSH 密钥泄露 | 高 | 使用 GitHub Secrets 管理、定期轮换密钥、考虑迁移到 Docker Swarm/K8s |
| 回测数据量过大导致 CI 超时 | 中 | 冒烟测试使用 1 个月最小数据集 |
| 前端与后端 API 版本不匹配 | 中 | CI 中同时构建前后端、集成测试验证 API 契约 |

---

*文档结束。如有问题请联系运维工程师。*
