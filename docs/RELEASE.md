# Camera Recorder V1 发布、升级与回滚指南

本文用于 V1.0 代码收敛后的发布准备、日常升级和故障回退。它不替代真实摄像头、浏览器和存储环境的 V1.0 验收；外部验收状态以 [V1_STATUS.md](V1_STATUS.md) 为准。

## 1. 两类备份不要混用

### 运维页 JSON 配置备份

在 `系统设置 → 运维工具 → 配置备份` 中可以导出 JSON。

它适合：

- 保存系统运行参数；
- 保存通知策略和 SMTP 非敏感字段；
- 保存现有摄像头的非敏感配置；
- 在同一实例或仍保留本地凭据的实例上恢复配置。

它**故意不包含**：

- 摄像头密码；
- WebDAV 密码；
- SMTP 密码；
- `CAMREC_SECRET_KEY`；
- OpenList 管理员密码。

恢复时只更新已经存在的同名摄像头，不会凭空创建一个没有密码的设备，也不会覆盖或清空已有密钥。

因此，这个 JSON 不是完整灾备。

### 完整灾备

进行版本升级、主机迁移或高风险维护前，至少保留：

```text
.env             部署密钥与端口配置
 data/            SQLite 数据库等持久化数据
 openlist-data/   OpenList 配置与数据库（使用内置 OpenList 时）
```

如果需要保留本地录像本身，还需要另外保护：

```text
recordings/
staging/          仅在需要保留尚未 finalize 的片段时
failed/           仅在需要后续排查/修复失败片段时
```

建议在维护窗口中停止会写入这些目录的服务后再做文件级快照或归档，避免复制到一半时文件仍在变化。停止 backend 会短暂中断录像，因此应按现场可接受的维护窗口执行。

**`CAMREC_SECRET_KEY` 一旦投入使用必须保持稳定。** 丢失或改变它会导致已有摄像头、SMTP、WebDAV 密文无法解密。

## 2. 正常升级

标准升级入口保持不变：

```bash
git pull && ./deploy.sh
```

推荐顺序：

1. 在运维页导出一份脱敏 JSON 配置备份。
2. 对 `.env`、`data/` 和需要的 OpenList 数据做完整备份或快照。
3. 执行 `git pull && ./deploy.sh`。
4. 检查部署脚本最终健康检查结果。
5. 打开 `系统设置 → 运维工具`，检查 Recorder、连接监控、磁盘、归档状态。
6. 检查事件/审计记录与关键摄像头状态。
7. 需要验证实时画面或回放时，由用户显式点击播放；升级本身不会改变“进入页面不自动拉流/播放”的产品规则。

`deploy.sh` 会根据变更文件决定需要构建和更新哪些服务。普通前端改动不会为了部署而重启录像 backend；如果 backend 本身需要更新，容器重建/重启期间正在录像会有短暂中断，脚本会在执行前明确提示。

## 3. 数据库迁移

backend 启动流程会在应用初始化前执行 Alembic：

```text
upgrade_database()
  -> alembic upgrade head
```

迁移文件位于：

```text
backend/migrations/versions/
```

发布要求：

- 新 schema 变化必须通过 Alembic migration 交付；
- 升级前必须有可恢复的 SQLite 备份；
- CI 通过不等于现场数据升级一定可回退，重要实例仍应先做备份；
- 不要把删除数据库文件或手工重建表作为常规升级步骤。

## 4. 回滚

### 仅代码/UI 回滚，且数据库 schema 兼容

可以切到已知可用提交，再使用同一部署脚本：

```bash
git switch --detach <known-good-commit>
./deploy.sh
```

确认恢复后，再按你的 Git 分支流程回到 `main`。

### 涉及数据库迁移的回滚

不要默认假设旧代码可以直接读取已经升级后的数据库，也不要在没有验证 migration `downgrade` 的情况下盲目执行降级。

更稳妥的流程是：

1. 停止会写数据库的 backend。
2. 恢复升级前的 `data/` / SQLite 备份。
3. 保持升级前相同的 `.env`，尤其 `CAMREC_SECRET_KEY`。
4. 切回已知可用代码提交。
5. 执行 `./deploy.sh`。
6. 重新检查健康状态、摄像头配置、Recorder 与归档队列。

如果同时升级/调整过 OpenList，并且其持久化格式发生变化，也应恢复匹配的 `openlist-data/` 备份。

## 5. 日志与审计

运维页只读取 `logs/` 直属普通文件，不递归目录、不跟随符号链接，也拒绝路径穿越。

日志保留策略：

- `camera-<id>.log`：按 **20 MiB** 轮转；
- 每路摄像头保留 **5 份历史轮转文件**（`.1` 到 `.5`），外加当前日志；
- `deploy-build.log` / `deploy-up.log`：每次部署开始时重置，因此天然只保存本次部署输出；
- 当前策略可在 `系统设置 → 运维工具 → 运行日志` 查看，也可通过 `/api/operations/log-policy` 读取。

操作审计复用 Event 表，覆盖配置备份/恢复、系统设置、通知设置以及摄像头管理等高价值管理动作。审计元数据不得保存密码、完整 RTSP 凭据或其他密钥。

## 6. Prometheus 基础指标

`/metrics` 以 Prometheus text format 暴露基础运行指标，包括：

- 摄像头总数与 online/offline/unknown 数量；
- 当前 Recorder 进程数；
- 连接监控错误计数；
- 录像盘 total/used/free bytes；
- 每路摄像头连接失败 streak。

该接口不包含 RTSP 地址、用户名或密码。V1 只提供指标端点，不内置 Prometheus/Grafana/ELK 服务栈。

## 7. V1.0 发布检查清单

### 代码与发布准备

- [x] 四批 V1 code-convergence 代码已实现。
- [x] Live / Playback / Recording Management 保持手动媒体启动规则。
- [x] 配置备份/恢复具备秘密字段保护。
- [x] 运维日志访问受目录边界保护。
- [x] 摄像头日志有界轮转且策略可见。
- [x] 高价值管理动作进入 audit 流。
- [x] `/metrics` 提供基础 Prometheus 指标。
- [x] Alembic migration chain 已建立并在 backend 启动时升级到 head。
- [x] 升级、完整备份和回滚流程已文档化。
- [ ] 发布候选提交的最终 CI 全绿。

### 外部实机验收

这些项目不能用单元测试或 Docker smoke 代替：

- [ ] 10 路摄像头连续录像 24 小时。
- [ ] 10 路摄像头连续录像 72 小时。
- [ ] 断网、摄像头重启、RTSP 抖动、FFmpeg kill 后可恢复。
- [ ] OpenList/WebDAV 故障期间本地录像不中断，恢复后上传队列继续处理。
- [ ] 真实录像盘达到 critical 阈值时保护逻辑符合预期。
- [ ] Chrome / Edge / Safari 完成本地与云端 H.264 / HEVC、seek、跨片段、跨天回放矩阵。

只有外部实机验收也完成后，才应把 V1.0 标记为正式发布；代码收敛完成不等于现场验收完成。
