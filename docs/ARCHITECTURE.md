# 系统架构

## 总览

```text
Browser (Vue 3)
      │
 REST / WebSocket
      │
  FastAPI
      │
      ├── RecorderManager ── CameraWorker × N ── FFmpeg ── RTSP/TCP Cameras
      │
      ├── SegmentProcessor ── ffprobe / remux / health check
      │
      ├── StorageManager ── disk thresholds / cleanup
      │
      ├── UploadManager ── Provider ── 115 / OpenList / future backends
      │
      └── EventBus ── WebSocket / event persistence

SQLite 保存元数据、状态、事件和任务；媒体文件只保存在文件系统。
```

## 进程模型

每台摄像头一个长期 FFmpeg 子进程。Web API 不直接承担 FFmpeg 生命周期，所有操作统一通过 `RecorderManager`。

```text
RecorderManager
  ├── CameraWorker(camera=1)
  ├── CameraWorker(camera=2)
  └── ...
```

CameraWorker 负责：

- 生成安全的 FFmpeg 参数
- 启动/停止/重启子进程
- 采集 stderr 并分类 warning
- 自动重连
- 上报状态和事件

## 媒体链路

```text
RTSP/TCP
  ↓
FFmpeg stream copy
  ↓
Timestamp strategy
  ├── native
  ├── reconstruct(setts)
  └── wallclock(special-case only)
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
Upload Queue
```

## 并发策略

- Recorder：每路独立 FFmpeg，数量等于启用摄像头数。
- Remux：默认并发 2～4，避免抢占录像磁盘 IO。
- Upload：默认并发 2，避免抢占录像网络与磁盘。

## 故障域

必须隔离以下故障：

- 单摄像头离线
- 单 FFmpeg 崩溃
- 单 MKV Remux 失败
- 115 暂时不可用
- 网络瞬断

这些故障均不能导致其他录像 Worker 停止。

## 文件生命周期

```text
active .mkv
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

任何阶段失败均保留足够信息用于恢复和排障。

## 数据库

SQLite 开启 WAL。数据库仅保存元数据：Camera、Recording、UploadTask、Event、Settings。

媒体绝不存入数据库。

## 实时事件

WebSocket `/ws/events` 推送：

```text
camera.online
camera.offline
recorder.started
recorder.stopped
recorder.reconnecting
segment.completed
segment.warning
segment.failed
upload.started
upload.completed
upload.failed
storage.warning
storage.critical
```

## 部署

开发环境：macOS，直接运行 FastAPI/Vite，系统 FFmpeg。

V1 macOS 守护：launchd。

Linux：systemd。

Docker Compose 后续提供，但核心程序不得依赖 Docker 才能工作。
