# Camera Recorder 开发设计

## 1. 项目定位

Camera Recorder 是一个轻量级多路 RTSP 摄像头录像、管理、健康监控与云端归档平台。第一目标是可靠录像，其次才是预览、回放和高级 NVR 能力。

核心原则：

1. 主录像优先 stream copy，不为了 Web 兼容主动转码原始录像。
2. 单摄像头故障隔离，一路异常不能影响其他摄像头。
3. Recorder、Remux、Upload 三条链路解耦。
4. RTSP 默认使用 TCP。
5. 先可靠落地本地文件，再进入上传队列。
6. 最终文件原子落盘，Web 和上传器不读取半成品。
7. FPS、采样率等媒体参数来自 Probe，不写死设备参数。
8. 时间戳策略支持 `native` / `reconstruct` / `wallclock`。
9. 摄像头连接、Recorder、Schedule 三类状态必须由各自模块独立维护。
10. Camera Recorder 只依赖 OpenList WebDAV，不直接绑定云端存储品牌。

## 2. 技术栈

### 后端

- Python 3.12+
- FastAPI
- SQLAlchemy 2
- Alembic
- SQLite + WAL
- Pydantic 2 / pydantic-settings
- asyncio / `asyncio.subprocess`
- WebSocket
- cryptography

依赖管理使用 `uv`。

### 前端

- Vue 3
- TypeScript
- Vite
- Element Plus
- Axios

当前壳层使用轻量 history 路由，不依赖 Vue Router。

### 媒体

- FFmpeg / ffprobe
- MKV 中间切片
- MP4 最终文件
- 浏览器不支持 HEVC 时按需生成 H.264 Proxy

## 3. 时间戳策略

Camera 支持：

```text
native       保留摄像头原始时间戳
reconstruct  使用 setts 在 packet 层重建时间轴，仍保持 stream copy
wallclock    特殊设备兼容模式
```

`reconstruct` 使用 Probe 得到的 `fps_num/fps_den`、音频采样率和 frame samples 动态构造时间基，不写死 15fps 或 16000Hz。

## 4. RTSP Probe

一次 Probe 使用同一 RTSP 会话读取音视频流，主要记录：

```text
codec
profile
width / height
fps_num / fps_den
pixel_format
has_b_frames
time_base
audio codec
sample_rate
channels
audio_frame_samples
```

Probe 同时拥有摄像头连接状态：

```text
connectivity_status = unknown / online / offline
```

数据库 `camera.status` 只为旧数据与旧 API 保留兼容；新代码不得往其中写 `recording`、`stopped`、`scheduled` 等非连接语义。

## 5. RecorderManager

每台摄像头对应一个长期 `CameraWorker`。

Recorder runtime：

```text
STOPPED
STARTING
RECORDING
RECONNECTING
STOPPING
```

RecorderManager 只负责录像进程状态，不写摄像头连接状态，也不决定调度策略。

断流后使用指数退避重连；稳定运行后清空连续失败计数。

## 6. RecordingScheduleManager

调度器负责：

- 全局自动启动开关
- 摄像头 `auto_record`
- 周计划窗口
- 自动启动 / 自动停止 Recorder
- 手动开始 override
- 手动暂停 override

Schedule 状态：

```text
disabled
global_disabled
automatic
scheduled
in_window
manual_override
manual_paused
probe_required
error
```

ScheduleManager 不写 `camera.status`。

## 7. 录像与 Remux

长期 FFmpeg 进程切出 MKV：

```text
RTSP/TCP
  ↓
FFmpeg stream copy
  ↓
MKV segment
```

SegmentProcessor 只处理已经关闭的 MKV：

```text
closed MKV
  ↓
ffprobe
  ↓
stream-copy remux -> .part.mp4
  ↓
atomic rename -> .mp4
  ↓
health check
```

HEVC MP4 使用 `hvc1` tag，并使用 faststart 方便回放。

## 8. Recording 健康检查

最终 MP4 至少检查：

- 文件存在且非空
- ffprobe 成功
- 存在视频流
- 编码、分辨率合理
- duration 合理
- 警告与错误统计可追踪

健康状态：

```text
healthy
warning
failed
```

异常 MKV / MP4 不应静默删除。

## 9. 上传与 OpenList

UploadManager 只面向 WebDAV Provider。

```text
Recording ready
  ↓
UploadTask
  ↓
OpenList WebDAV
  ↓
实际存储后端
```

规则：

- UploadTask 持久化到 SQLite。
- 上传失败自动退避，不影响 Recorder。
- 上传完成后验证远端文件。
- 只有上传成功且达到保留条件的录像才允许本地清理。
- 本地文件删除后 Recording 元数据仍保留，可继续云端回放。
- OpenList 后端可以是任意受支持的可写存储。

## 10. 回放

录像浏览以摄像头 + 日期 + 时间轴为核心。

播放优先级：

```text
本地 H.264/H.265 原片
  ↓ 浏览器实际解码失败
H.264 Proxy fallback

本地已清理 + 上传成功
  ↓
OpenList WebDAV / 外部直链 / Range proxy
  ↓ HEVC 浏览器失败
远程源 H.264 Proxy fallback
```

原始录像不因浏览器兼容性被修改。

相邻录像导航、跨日自动续播、云端预热和播放遥测都以 Recording 元数据为入口。

## 11. 健康与稳定性

实时健康接口：

```text
GET /api/health/summary
WS  /ws/status
```

每台摄像头返回：

```text
connectivity_status
recorder_state
schedule_state
abnormal
```

健康采样每分钟持久化，保留用于 24h / 72h 统计。

注意：历史 `online_rate` 字段实际上是“期望录像时段内 Recorder 可用率”，不是 RTSP Probe 连通率；UI 中应使用“录像可用率”等准确名称。

## 12. 告警

当前告警覆盖：

- 摄像头录像连接中断与恢复
- FFmpeg 连续失败
- 磁盘 critical / 自动清理受阻
- 上传最终失败
- 恢复通知

告警发送失败不能影响主录像链路。

## 13. 数据模型重点

### Camera

关键字段：

```text
id
name
ip
rtsp_port
username
password_encrypted
rtsp_path
sub_rtsp_path
enabled
auto_record
recording_schedule_enabled
recording_schedule
timestamp_mode
media probe fields
status                # 兼容字段，只表示连接状态
last_probe_at
last_online_at
created_at
updated_at
```

运行时派生字段：

```text
connectivity_status
recorder_state
schedule_state
```

### Recording

保存媒体元数据、健康状态、本地路径、上传状态和时间信息。

### UploadTask

保存 provider、远端路径、状态、重试计数和错误信息。

### Event

保存级别、类别、code、message、camera/recording 关联与 metadata。

## 14. API 组织

主要 API 分组：

```text
/api/cameras
/api/recorder
/api/recordings
/api/uploads
/api/events
/api/health
/api/settings
/api/notifications
/api/playback
```

实时通道：

```text
/ws/status
/ws/preview-wall
```

具体接口以 FastAPI OpenAPI 为准，避免在设计文档中维护容易过期的完整 endpoint 清单。

## 15. 安全

- 摄像头、SMTP、WebDAV 密码加密存储。
- API 不回显秘密明文。
- 日志禁止写完整 RTSP 凭据、WebDAV 密码或云端 Token。
- `.env`、数据库、录像、staging、failed、OpenList 数据目录不得提交到 Git。
- `CAMREC_SECRET_KEY` 投产后应保持稳定。

## 16. 启动与恢复

后端启动需要恢复：

```text
数据库迁移
FFmpeg capability 检测
staging 扫描
未完成上传 / 处理任务
Recorder / Schedule / Health / Alert 后台服务
```

关闭时优雅停止后台任务与 Recorder，不让半成品伪装成完成录像。

## 17. 测试原则

必须持续覆盖：

- Unit
- API integration
- Docker smoke
- 多路长稳
- 断流 / FFmpeg failure injection
- 磁盘压力
- OpenList/WebDAV 故障
- 浏览器回放兼容性

开发优先级：

```text
可靠录像 > 状态正确 > 正确切片 > 异常恢复 > 文件完整 > 上传 > 回放 > UI 增强
```
