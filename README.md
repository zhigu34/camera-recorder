# Camera Recorder

轻量级 RTSP 摄像头录像、管理与云端归档平台。

## 目标

- 多路 RTSP TCP 长连接录像
- H.265 / AAC 原码流保存，不重新编码主录像
- 异常时间戳重建（`setts`）
- 默认 10 分钟 MKV 切片，后台无损 Remux 为 MP4
- 录像健康检查、断线自动重连、磁盘管理
- Vue 3 Web 管理界面
- 后续接入 115 云端归档

## 技术栈

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2, SQLite, Alembic
- Frontend: Vue 3, TypeScript, Vite, Pinia, Element Plus
- Media: FFmpeg / ffprobe
- Realtime: WebSocket

## 文档

- [开发设计](docs/DEVELOPMENT.md)
- [系统架构](docs/ARCHITECTURE.md)
- [版本路线](docs/ROADMAP.md)

## 当前阶段

当前目标为 V0.1：完成摄像头 CRUD、RTSP Probe、单路录像 Worker、时间戳重建、10 分钟切片、MKV → MP4 和基础健康检查。

> 安全说明：仓库中禁止提交真实摄像头密码、RTSP URL、115 Token、数据库密钥或本地录像文件。
