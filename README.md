# Camera Recorder

轻量级 RTSP 摄像头录像、管理、健康监控与 OpenList/WebDAV 云端归档平台。

项目优先保证持续录像和故障隔离：单路摄像头、FFmpeg、Remux、上传或云端存储异常都不应影响其他录像 Worker。

## 核心能力

- 多路 RTSP/TCP 长连接录像，每台摄像头独立 FFmpeg Worker
- 摄像头 CRUD、单会话 Probe、动态识别编码 / 分辨率 / FPS / 音频参数
- H.264 / H.265 与音频原码流保存，主录像不重新编码
- `native` / `reconstruct` / `wallclock` 三种时间戳策略
- 长连接 MKV 切片，后台无损 Remux 为 MP4
- ffprobe 成品健康检查、断线自动重连、异常文件保留
- 周录制计划、手动开始/暂停与自动恢复
- 摄像头连接状态、Recorder 状态、Schedule 状态三线独立
- SQLite 元数据、运行时设置、事件、上传任务持久化
- OpenList WebDAV 上传队列，可挂载任意 OpenList 支持的可写存储
- 上传失败自动退避，上传成功后按本地保留策略自动清理
- 本地与 OpenList 云端录像统一时间轴回放
- 1 / 4 / 9 宫格实时预览
- 事件中心、邮件告警、系统健康、24h/72h 稳定性验收
- 运维日志、脱敏配置备份/恢复、操作审计与 Prometheus 基础指标
- Vue 3 + TypeScript + Vue Router + Pinia 管理界面
- Docker Compose 一键部署，支持 amd64 / arm64

## 摄像头状态模型

三个维度互不覆盖：

```text
connectivity_status
  unknown / online / offline

recorder_state
  STOPPED / STARTING / RECORDING / RECONNECTING / STOPPING

schedule_state
  disabled / global_disabled / automatic / scheduled / in_window
  manual_override / manual_paused / probe_required / error
```

`status` 仅作为旧 API / 数据库兼容别名保留；新代码应使用上面三个明确字段。

## 部署

前置条件：Docker Engine / Docker Desktop + Compose。

首次部署：

```bash
git clone git@github.com:zhigu34/camera-recorder.git
cd camera-recorder
cp .env.example .env
# 修改 CAMREC_SECRET_KEY 和 OPENLIST_ADMIN_PASSWORD
./deploy.sh
```

以后升级统一使用：

```bash
git pull && ./deploy.sh
```

`deploy.sh` 会检查 Docker/Compose/Buildx、FFmpeg 本地包、Compose 配置、镜像构建和服务健康状态。已有且有效的 FFmpeg 包与 Docker 层会直接复用；普通前端改动只重建前端，不重启录像 backend。

Hikvision HCNetSDK 支持**默认关闭**。普通 RTSP / ONVIF 部署不需要下载或放置任何厂商 SDK，核心 backend/frontend/OpenList 也不依赖 `hik-bridge`。需要启用 HIK SDK 时，在 `.env` 中设置：

```dotenv
CAMREC_HIK_ENABLED=1
HIK_SDK_DIR=./hik-sdk-runtime
```

并把 Linux64 HCNetSDK runtime 放到对应目录，然后仍然执行普通的：

```bash
./deploy.sh
```

不需要手工传 `docker compose --profile hik`；部署脚本会先完成核心服务，再单独处理可选 HIK 阶段。关闭 HIK 时设置 `CAMREC_HIK_ENABLED=0`，下一次部署会移除旧 `hik-bridge`，不会影响核心录像服务。详细说明见：[Hikvision HCNetSDK runtime](docs/HIK_SDK_RUNTIME.md)。

涉及正式升级、数据库迁移或回滚前，先阅读：[V1 发布、升级与回滚](docs/RELEASE.md)。运维页导出的 JSON 是脱敏配置备份，不替代 `.env`、SQLite 和 OpenList 持久化数据的完整灾备。

服务默认地址：

```text
Camera Recorder  http://127.0.0.1:8080
FastAPI          backend:8000（仅 Docker 内部网络，通过前端 /api、/ws 和 /health 代理）
OpenList         http://127.0.0.1:5244
HIK Bridge       默认不启动；启用后 hik-bridge:8100（仅 Docker 内部网络）
```

宿主机持久化目录：

```text
data/           SQLite
recordings/     最终 MP4
staging/        正在录像 / 待处理 MKV
failed/         处理失败的 MKV
logs/           FFmpeg 与部署日志
openlist-data/  OpenList 配置与数据库
```

## 首次使用

1. 打开 `摄像头` → `添加摄像头`。
2. 填写名称、IP、账号密码和 RTSP Path。
3. 保存后执行 `检测`，让系统读取真实媒体参数。
4. 根据设备情况选择时间戳模式；已验证存在时间戳问题的设备优先使用 `reconstruct`。
5. 手动开始录像，或在 `录制计划` 中启用自动录像。
6. 在 `实时监控` 查看预览，在 `录像回放` 查看时间轴和云端归档录像。
7. 在 `系统设置` 配置切片、磁盘阈值、OpenList/WebDAV 和本地保留策略。
8. 在 `通知与告警` 配置 SMTP 与通知策略。
9. 在 `系统设置 → 运维工具` 查看日志、审计、配置备份和 Prometheus 指标。

## OpenList / WebDAV 归档

Camera Recorder 只依赖标准 WebDAV，不直接依赖具体云盘 API。实际存储由 OpenList 管理，可以是任意 OpenList 支持且允许写入的后端。

两种常见配置都支持：

```text
WebDAV URL: http://openlist:5244/dav/archive
远端根目录: 监控录像
```

或：

```text
WebDAV URL: http://openlist:5244/dav
远端根目录: archive/监控录像
```

最终目录类似：

```text
监控录像/
└── 摄像头名称/
    └── YYYY-MM-DD/
        └── 摄像头名称_YYYY-MM-DD_HH-MM-SS.mp4
```

详见：[OpenList / WebDAV 配置](docs/OPENLIST.md)。

## 技术栈

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2, SQLite, asyncio
- Frontend: Vue 3, TypeScript, Vue Router, Pinia, Vite, Element Plus, Axios
- Media: FFmpeg / ffprobe
- Archive bridge: OpenList / WebDAV
- Runtime: Docker Compose + Nginx

## 文档

- [启动与开发](docs/GETTING_STARTED.md)
- [系统架构](docs/ARCHITECTURE.md)
- [开发设计](docs/DEVELOPMENT.md)
- [Hikvision HCNetSDK runtime](docs/HIK_SDK_RUNTIME.md)
- [OpenList / WebDAV](docs/OPENLIST.md)
- [V1 当前状态](docs/V1_STATUS.md)
- [V1 发布、升级与回滚](docs/RELEASE.md)
- [版本路线](docs/ROADMAP.md)

## 安全

- 不要提交 `.env`、数据库、摄像头密码、完整 RTSP URL、WebDAV 密码、Token 或录像文件。
- 摄像头、SMTP、WebDAV 密码使用 `CAMREC_SECRET_KEY` 派生密钥加密后保存到 SQLite，API 不回显明文。
- `CAMREC_SECRET_KEY` 开始使用后应保持稳定，否则旧密文无法解密。
- OpenList 默认定位于可信 LAN 内使用；如暴露到公网，应放在 HTTPS、认证与访问控制之后。

## 当前重点

- 完成 V1.0 外部实机验收：10 路 24h / 72h、故障恢复、磁盘保护与 OpenList 中断恢复
- 完成 Chrome / Safari / Edge 本地与云端 H.264 / HEVC 回放矩阵
- 根据真实长期运行数据继续校准录像健康、连接监控和告警阈值
- V1.0 验收通过前不扩展 ONVIF、事件录像、人物检测等 Post-V1 功能
