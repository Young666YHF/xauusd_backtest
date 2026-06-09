# XAUUSD 量化回测系统 - 版本发布记录

> 使用此模板创建每次版本发布的记录。复制到 `docs/releases/vX.Y.Z.md` 并同步更新 `CHANGELOG.md`。

---

## 版本信息

| 字段 | 值 |
|------|-----|
| **版本号** | v2.X.Y |
| **发布日期** | YYYY-MM-DD |
| **发布人** | @username |
| **Git 标签** | `v2.X.Y` |
| **Docker 镜像** | `ghcr.io/young666yhf/xauusd_backtest:v2.X.Y` |
| **SBOM** | `sbom-v2.X.Y.spdx.json` |

---

## 发布摘要

<!-- 用 2-3 句话概括本次发布的核心内容 -->

本次发布主要包含 [功能/修复/优化]：
- 新增 XX 策略的 YY 特性
- 修复了 ZZ 模块的致命 Bug
- 性能优化，回测速度提升 XX%

---

## 变更详情

### ✅ 新增 (Added)

- [ ] 功能 A 的描述和用途
- [ ] 功能 B 的描述和用途

### 🔧 变更 (Changed)

- [ ] 行为/性能改进描述
- [ ] 配置项变更说明

### 🐛 修复 (Fixed)

- [ ] Bug 描述及影响范围
- [ ] 关联 Issue: #123

### ⚠️ 弃用 (Deprecated)

- [ ] 即将弃用的功能/接口
- [ ] 迁移建议

### 🔒 安全 (Security)

- [ ] 安全修复描述
- [ ] CVE 编号 (如有)

---

## 策略变更

| 策略 | 变更类型 | 说明 | 回测验证 |
|------|----------|------|----------|
| MeanReversion | 无 / 参数调整 / 逻辑变更 | 具体说明 | ✅ 通过 |
| MomentumBreakout | 无 / 参数调整 / 逻辑变更 | 具体说明 | ✅ 通过 |
| BreakoutGrid | 无 / 参数调整 / 逻辑变更 | 具体说明 | ✅ 通过 |
| DollarTrader | 无 / 参数调整 / 逻辑变更 | 具体说明 | ✅ 通过 |

> ⚠️ **策略逻辑变更必须附带回测对比数据**

---

## 回测验证报告

### 核心指标对比

| 指标 | 上一版本 | 当前版本 | 变化 |
|------|----------|----------|------|
| 总收益率 | X% | Y% | ±Z% |
| 夏普比率 | X | Y | ±Z |
| 卡玛比率 | X | Y | ±Z |
| 最大回撤 | X% | Y% | ±Z% |
| 胜率 | X% | Y% | ±Z% |
| 交易次数 | X | Y | ±Z |

### 验证环境

- 数据区间: 2023-01-01 ~ 2024-12-31
- 数据频率: Tick / 1min / 15min
- 测试机: Ubuntu 22.04, 4C8G
- Python: 3.10.12

---

## 部署检查清单

### 发布前检查

- [ ] 所有 CI 检查通过 (lint, test, build)
- [ ] 代码审查完成 (至少 1 人 approve)
- [ ] CHANGELOG.md 已更新
- [ ] 版本号已更新 (`config.yaml`, `package.json`)
- [ ] Git 标签已创建并推送
- [ ] Docker 镜像构建成功

### 发布后检查

- [ ] Staging 环境部署成功
- [ ] Staging 健康检查通过
- [ ] Production 环境部署成功
- [ ] Production 健康检查通过
- [ ] 监控仪表盘无异常告警
- [ ] 回测冒烟测试通过

---

## 回滚方案

若发布后出现严重问题，按以下步骤回滚：

```bash
# 1. 记录当前状态
docker ps > /opt/xauusd/rollback_$(date +%Y%m%d_%H%M%S).log

# 2. 回滚到上一版本
./docs/deployment_script.sh production v2.X.Y-1

# 3. 验证回滚
curl -sf https://xauusd.example.com/api/health

# 4. 通知团队
```

**上一稳定版本**: `v2.X.Y-1`
**预计回滚时间**: < 5 分钟

---

## 已知问题

| 问题 | 影响 | 计划修复版本 |
|------|------|--------------|
| 问题 A 描述 | 低/中/高 | v2.X.Z |

---

## 相关文档

- [PRD v1.0](team-xauusd-prd-v1.md)
- [架构设计文档](architecture.md)
- [API 文档](api.md)
- [部署文档](environment_config.md)

---

*发布记录结束。*
