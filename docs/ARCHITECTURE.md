# 系统架构

## 总览

```text
Browser / Vue 3
      │
 REST / WebSocket
      │
   FastAPI
      │
      ├── Camera Probe ──────────────── connectivity_status
      ├── RecorderManager ── CameraWorker × N ── FFmpeg ── RTSP/TCP
      ├── RecordingScheduleManager ─── schedule_state
      ├── SegmentProcessor ── ffprobe / remux / health check
      ├── StorageCleanupManager ── disk thresholds / safe cleanup
      ├── UploadManager ── OpenList WebDAV ── storage backend
      ├── HealthSampler / StabilityReport
      └── AlertMonitor / Event persistence

SQLite 保存配置、元数据、事件、健康采样和任务；媒体文件保存在文件系统。
```

## 状态所有权

摄像头状态拆成三个维度，禁止互相覆盖：

```text
Probe
  └── connectivity_status
      unknown / online / offline

RecorderManager
  └── recorder_state
      STOPPED / STARTING / RECORDING / RECONNECTING / STOPPING

RecordingScheduleManager
  └── schedule_state
      disabled / global_disabled / automatic / scheduled / in_window
      manual_override / manual_paused / probe_required / error
```

数据库 `camera.status` 只作为旧数据/API 兼容字段保留，并按连接状态解释。新代码不得再把 Recorder 或 Schedule 状态写入该字段。

## Recorder 进程模型

每台摄像头对应一个独立长期 FFmpeg 子进程：

```text
RecorderManager
  ├── CameraWorker(camera=1)
  ├── CameraWorker(camera=2)
  └── ...
```

CameraWorker 负责：

- 生成 FFmpeg 参数
- 启动 / 停止 / 重连
- stderr 分类统计
- 指数退避
- Recorder runtime 快照
- 录像链路中断与恢复事件

一路摄像头异常不能导致其他 Worker 停止。

## 媒体链路

```text
RTSP/TCP
  ↓
FFmpeg stream copy
  ↓
Timestamp strategy
  ├── native
  ├── reconstruct(setts)
  └── wallclock
  ↓
Long-running segmentation
  ↓
closed MKV
  ↓
SegmentProcessor
  ├── ffprobe
  ├── remux to .part.mp4
  ├── atomic rename
  └── health check
  ↓
recordings/
  ↓
UploadTask
  ↓
OpenList WebDAV
```

主录像不做视频转码。HEVC 浏览器不兼容时，仅回放链路按需生成 H.264 Proxy，不修改原始录像。

## 录制调度

`RecordingScheduleManager` 每隔约 10 秒 reconcile：

- 处理全局自动启动开关
- 处理摄像头自动录像开关
- 处理周计划窗口
- 管理自动启动的 Recorder
- 尊重手动开始和手动暂停 override

计划状态只描述“调度意图”，不表示网络在线，也不表示 FFmpeg 一定正在录像。

## 上传与云端存储

Camera Recorder 只依赖标准 WebDAV。OpenList 负责适配实际存储后端，因此应用本身不绑定具体云盘品牌。

上传与录像完全解耦：

- 上传失败不停止 Recorder
- UploadTask 写入 SQLite
- 自动重试使用退避
- 上传成功后才允许按本地保留策略清理
- 本地文件清理后仍保留 Recording 元数据
- 云端录像继续参与时间轴、相邻录像和自动续播

## 健康与稳定性

实时健康源：

- `GET /api/health/summary`
- `/ws/status`

包含连接、Recorder、Schedule、存储、上传和 24h 录像统计。

健康采样每分钟持久化，用于：

- Recorder 可用率
- 录像完整率
- 24h / 72h 稳定性报告
- FFmpeg 失败与断流统计

历史 `online_rate` 字段实际表示“期望录像时段内 Recorder 可用率”，不是 RTSP Probe 连通率。

## 实时预览

实时监控使用独立 WebSocket 预览墙：

```text
Browser
  ↕ /ws/preview-wall
FastAPI preview wall
  ↕
FFmpeg preview process
  ↕
RTSP Camera
```

预览连接状态与录像状态是两个不同信号：浏览器预览失败不代表 Recorder 一定停止，Recorder 正常也不保证当前浏览器预览链路正常。

## 故障域

以下故障必须彼此隔离：

- 单摄像头离线
- 单 FFmpeg 崩溃
- 单片段 Remux / ffprobe 失败
- 磁盘压力
- OpenList / WebDAV / 云端存储异常
- 浏览器预览断开
- 浏览器回放兼容性问题

## 文件生命周期

```text
active MKV
  ↓ segment closed
staging/*.mkv
  ↓ remux
*.part.mp4
  ↓ atomic rename
recordings/*.mp4
  ↓ health passed
upload queue
  ↓ upload success + retention expired
eligible for local cleanup
```

失败文件保留足够信息用于恢复和排障。

## 数据库

SQLite 使用 WAL，主要实体包括：

```text
Camera
Recording
UploadTask
Event
SystemSettings
NotificationSettings
CameraHealthSample
```

媒体内容不写入数据库。

## 部署

当前标准部署方式为 Docker Compose。

首次部署准备 `.env` 后运行：

```bash
./deploy.sh
```

升级：

```bash
git pull && ./deploy.sh
```

`deploy.sh` 负责环境检查、FFmpeg 包校验、Compose 配置检查、镜像构建、启动和健康检查。
