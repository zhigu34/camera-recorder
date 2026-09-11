# Camera Recorder 开发设计

## 1. 项目定位

Camera Recorder 是一个轻量级多路 RTSP 摄像头录像、管理、健康监控与云端归档平台。第一目标是可靠录像，其次才是在线播放和高级 NVR 功能。

核心原则：

1. 主录像不转码，优先 `-c:v copy -c:a copy`。
2. 单摄像头故障隔离，一路异常不能影响其他摄像头。
3. 录像、Remux、上传三条链路解耦。
4. RTSP 使用 TCP，降低 UDP 丢包带来的录像损坏。
5. 不直接写云盘；先完成本地文件，再进入上传队列。
6. 最终文件原子落盘，Web 和上传器永远不读取半成品。
7. 不写死 15fps / 16000Hz，参数必须来自 Probe。
8. 不信任异常摄像头时间戳，支持 `native` / `reconstruct` / `wallclock` 三种策略。

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
- psutil
- cryptography（摄像头凭据加密）

依赖管理使用 `uv`。

### 前端

- Vue 3
- TypeScript
- Vite
- Vue Router
- Pinia
- Element Plus
- Axios
- ECharts
- WebSocket

### 媒体处理

- FFmpeg
- ffprobe
- Matroska (MKV) 中间文件
- MP4 最终文件

## 3. 已验证媒体特性

当前测试设备主要为：

- 视频：H.265 / HEVC Main
- 音频：AAC-LC
- 音频：16000 Hz / mono
- 当前探测帧率：15fps
- `has_b_frames = 0`

部分设备 RTSP 原始时间戳存在异常，直接 stream copy 可能出现：

- `Timestamps are unset`
- `Starting new cluster due to timestamp`
- `Non-monotonic DTS`

已验证可行的无转码时间戳重建方式：

```bash
-bsf:v 'setts=ts=N:duration=1:time_base=1/15:prescale=1'
-bsf:a 'setts=ts=N*1024:duration=1024:time_base=1/16000:prescale=1'
```

该参数只是当前设备的实例。正式程序必须根据 Probe 动态生成视频 FPS 与音频采样参数。

## 4. 时间戳模式

Camera 模型提供：

- `native`：保留摄像头原始 PTS/DTS。
- `reconstruct`：通过 `setts` 在 packet 层重建时间轴，仍保持 stream copy。
- `wallclock`：仅作为特殊兼容模式，不作为默认值。

当前萤石设备优先使用 `reconstruct`。

### reconstruct 约束

视频重建假设输入是稳定 CFR。FPS 必须使用有理数存储：

```text
fps_num
fps_den
```

例如：

- 15fps = 15/1 → time_base 1/15
- 20fps = 20/1 → time_base 1/20
- 29.97fps = 30000/1001 → time_base 1001/30000

如果 Probe 发现复杂 B-frame/VFR 流，不应自动套用 CFR 重建策略，应进入人工验证状态。

## 5. RTSP Probe

每次 Probe 必须使用一次 RTSP 会话同时读取音视频流，禁止分别建立两次会话后比较 `start_time`。

探测字段：

```text
codec_name
profile
width
height
pix_fmt
r_frame_rate
avg_frame_rate
time_base
has_b_frames
sample_rate
channels
channel_layout
```

RTSP/RTP 音视频 `stream.start_time` 不作为实际音画同步判断依据。

## 6. RecorderManager

每台摄像头对应独立 `CameraWorker`：

```text
STOPPED
STARTING
RECORDING
RECONNECTING
ERROR
STOPPING
```

一台摄像头对应一个长期 FFmpeg 进程。不要每 10 分钟主动断开 RTSP 并重连。

目标结构：

```text
Camera
  ↓ RTSP/TCP
FFmpeg 长连接
  ↓ setts（按模式）
10min MKV segment
  ↓
SegmentProcessor
  ↓ stream-copy remux
MP4
```

断线时 Worker 自动重启，指数退避：3s、5s、10s、20s、30s、60s，上限 60s；恢复后重置重试计数。

## 7. 录像切片

默认切片：600 秒。

使用 FFmpeg Segment Muxer 或等价长连接切片机制。实际切点可能靠近关键帧，因此健康检查不要求严格等于 600.000 秒。

Staging：

```text
staging/
└── camera-{id}/
    ├── ...mkv
    └── ...mkv
```

只处理已经关闭的 MKV。可结合：当前 active 文件、文件 mtime、文件大小是否稳定判断完成状态。

## 8. Remux

完成的 MKV 后台无损 Remux：

```bash
ffmpeg \
  -hide_banner \
  -loglevel warning \
  -i input.mkv \
  -map 0:v:0 \
  -map '0:a?' \
  -c:v copy \
  -c:a copy \
  -tag:v hvc1 \
  -movflags +faststart \
  -y output.part.mp4
```

成功后原子 rename：

```text
output.part.mp4 → output.mp4
```

最终目录：

```text
recordings/
└── 摄像头名称/
    └── YYYY-MM-DD/
        └── 摄像头名称_YYYY-MM-DD_HH-MM-SS.mp4
```

## 9. 健康检查

最终 MP4 至少检查：

- 文件存在且非空
- ffprobe 成功
- 有视频流
- 期望有音频时存在音频流
- codec 与预期一致
- 分辨率合理
- duration 合理

健康级别：

- `healthy`
- `warning`
- `failed`

FFmpeg stderr 分类统计：

- `Non-monotonic DTS`
- `Timestamps are unset`
- `corrupt`
- `Connection timed out`
- `Connection reset`
- `Invalid data`

少量 warning 不自动删除文件；ffprobe 失败或缺失视频流才直接判定 failed。

## 10. 数据模型

### Camera

```text
id
name
ip
rtsp_port
username
password_encrypted
rtsp_path
enabled
auto_record
video_codec
video_profile
width
height
fps_num
fps_den
pixel_format
has_b_frames
video_time_base
audio_codec
audio_profile
sample_rate
channels
audio_frame_samples
timestamp_mode
status
last_probe_at
last_online_at
created_at
updated_at
```

### Recording

```text
id
camera_id
started_at
ended_at
duration
source_mkv_path
mp4_path
file_size
video_codec
audio_codec
width
height
fps_num
fps_den
status
health_status
ffprobe_ok
has_video
has_audio
warning_count
timestamp_warning_count
network_warning_count
upload_status
created_at
updated_at
```

### UploadTask

```text
id
recording_id
provider
remote_path
status
retry_count
last_error
started_at
completed_at
created_at
updated_at
```

### Event

```text
id
camera_id
recording_id
level
category
code
message
metadata_json
created_at
```

## 11. REST API

```text
GET    /api/cameras
POST   /api/cameras
GET    /api/cameras/{id}
PUT    /api/cameras/{id}
DELETE /api/cameras/{id}
POST   /api/cameras/{id}/probe
POST   /api/cameras/{id}/start
POST   /api/cameras/{id}/stop
POST   /api/cameras/{id}/restart

POST   /api/recorder/start-all
POST   /api/recorder/stop-all
GET    /api/recorder/status

GET    /api/recordings
GET    /api/recordings/{id}
DELETE /api/recordings/{id}
POST   /api/recordings/{id}/probe
POST   /api/recordings/{id}/remux

GET    /api/uploads
POST   /api/uploads/{id}/retry

GET    /api/events
GET    /api/system/status
GET    /api/system/storage
GET    /api/settings
PUT    /api/settings
```

WebSocket：`/ws/events`。

## 12. 安全

- 摄像头密码使用 Fernet 加密后写 SQLite。
- 密钥独立保存在 `data/secret.key`，权限 600。
- API 永不返回真实密码，只返回 `password_set: true/false`。
- 日志禁止记录完整 RTSP URL、密码、115 Token。
- `.env`、数据库、录像、staging、密钥必须在 `.gitignore` 中。

## 13. 115 上传

Uploader 使用 Provider 抽象：

```python
class UploadProvider:
    async def upload(...): ...
    async def exists(...): ...
    async def verify(...): ...
```

后续可支持 115/OpenList/WebDAV/S3/NAS。录像完成并健康检查后才进入上传队列；上传失败不影响录像。

远端保持本地目录结构。

## 14. 启动与恢复

应用启动顺序：

```text
数据库迁移
→ FFmpeg/ffprobe能力检测
→ 扫描 staging
→ 恢复未完成任务
→ 初始化 RecorderManager
→ 初始化 SegmentProcessor
→ 初始化 UploadManager
→ 根据配置启动自动录像
→ Web Ready
```

收到 SIGTERM/SIGINT 时优雅停止：通知 CameraWorker、结束 FFmpeg、封尾当前 MKV、加入处理队列、停止后台任务、关闭数据库。

## 15. 测试要求

必须包含：Unit、Integration、Long-running、Failure Injection。

V1 发布前进行至少 72 小时 10 路并发长稳测试，重点记录：录像缺失时间、FFmpeg 重启、网络异常、MP4 失败、时间戳 warning、CPU、RAM、磁盘 IO、网络吞吐。

开发优先级始终是：

```text
可靠录像 > 正确切片 > 异常恢复 > 文件完整 > 上传 > UI > 高级功能
```
