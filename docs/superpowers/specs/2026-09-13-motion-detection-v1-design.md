# Motion Detection V1 设计规格

## 目标

为 Camera Recorder 增加第一阶段视频事件能力：基于低码流的移动检测、可选多边形检测区域、移动事件合并与快照，并为 Playback V3 提供真实的移动事件时间轴数据。

本阶段不做人员、车辆、动物分类，不引入目标跟踪或 AI 模型。

## 设计原则

1. **录像主链路不受影响**：主码流录像继续由现有 Recorder/FFmpeg 管理；移动检测是独立分析链路。
2. **优先使用子码流**：有 `sub_rtsp_path` 时使用子码流；没有时回退主码流，并主动降分辨率/帧率。
3. **默认整画面检测**：摄像头启用移动检测但没有 Zone 时，整幅画面作为有效检测区域。
4. **Zone 是包含区域**：配置 Zone 后，仅 Zone 内的有效运动用于创建事件。V1 不提供 Mask UI，但数据/算法边界要允许后续加入排除区域。
5. **事件独立存储**：系统运维 `events` 表保持不变，移动事件写入专用 `motion_events`，避免高频检测数据污染系统日志。
6. **时间坐标统一**：所有事件起止时间使用 UTC 存储，前端按浏览器本地时区显示。
7. **坐标归一化**：Zone 多边形使用 0..1 的归一化坐标，避免与检测分辨率绑定。
8. **失败可恢复**：某一路检测异常不得影响其它摄像头和录像；worker 自动退避重连。

## 技术方案

### 分析链路

```text
RTSP Camera
   ├── Main Stream ───────────────> Recorder ──> Recordings
   └── Sub Stream (preferred)
            │
            v
      Motion Worker
            │
      640px wide / 5 FPS
            │
      grayscale + blur
            │
      MOG2 background subtraction
            │
      morphology open/close
            │
      contour area filtering
            │
      Zone intersection test
            │
      duration + merge-gap state machine
            │
      MotionEvent + Snapshot
```

### OpenCV 算法

V1 使用 `opencv-python-headless`：

- `cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=<mapped>, detectShadows=False)`
- 灰度化 + Gaussian blur 预处理。
- `MORPH_OPEN` 去除小噪声，`MORPH_CLOSE` 合并碎片。
- 按轮廓面积占画面比例过滤微小变化。
- 对每个有效轮廓计算中心点/掩码重叠，判断是否落入 Zone。
- 当有效运动连续超过 `min_duration_ms` 才开启事件。
- 运动消失后等待 `merge_gap_ms`；期间再次出现则继续同一事件，否则结束并落库。

### 灵敏度

前端只暴露三级：

- `low`
- `medium`
- `high`

后端负责映射到 MOG2 阈值、最小面积比例等内部参数，避免用户直接操作算法细节。

建议默认：

- sensitivity: `medium`
- analysis_fps: `5`
- analysis_width: `640`
- min_duration_ms: `800`
- merge_gap_ms: `3000`

## 数据模型

### `motion_detection_settings`

每台摄像头最多一条。

- `camera_id` INTEGER PK/FK -> cameras.id, ON DELETE CASCADE
- `enabled` BOOLEAN NOT NULL DEFAULT false
- `sensitivity` VARCHAR(16) NOT NULL DEFAULT 'medium'
- `analysis_fps` INTEGER NOT NULL DEFAULT 5
- `analysis_width` INTEGER NOT NULL DEFAULT 640
- `min_duration_ms` INTEGER NOT NULL DEFAULT 800
- `merge_gap_ms` INTEGER NOT NULL DEFAULT 3000
- `created_at`
- `updated_at`

约束：

- analysis_fps: 1..10
- analysis_width: 320..1280
- min_duration_ms: 100..10000
- merge_gap_ms: 0..30000

### `motion_zones`

- `id` INTEGER PK
- `camera_id` FK -> cameras.id, ON DELETE CASCADE
- `name` VARCHAR(128)
- `enabled` BOOLEAN DEFAULT true
- `polygon_json` JSON NOT NULL
- `created_at`
- `updated_at`

`polygon_json` 示例：

```json
[[0.12, 0.18], [0.78, 0.20], [0.75, 0.82], [0.15, 0.80]]
```

规则：

- 最少 3 个点。
- 每个 x/y 均在 `[0, 1]`。
- V1 允许多个 Zone 重叠。
- 若没有启用中的 Zone，整画面有效。

### `motion_events`

- `id` INTEGER PK
- `camera_id` FK -> cameras.id, ON DELETE CASCADE
- `zone_id` FK -> motion_zones.id, nullable, ON DELETE SET NULL
- `recording_id` FK -> recordings.id, nullable, ON DELETE SET NULL
- `started_at` DATETIME indexed
- `ended_at` DATETIME indexed
- `peak_score` FLOAT nullable
- `snapshot_path` VARCHAR(1024) nullable
- `metadata_json` TEXT nullable
- `created_at`

如果一个事件同时命中多个 Zone，V1 以事件开始时重叠面积最大的 Zone 作为 `zone_id`，其它命中 Zone 记录到 `metadata_json`。

## 录像关联

事件结束落库时，根据 `camera_id` 和 `[started_at, ended_at]` 查找覆盖事件开始时间的录像片段作为 `recording_id`。

若事件发生时对应录像尚未入库，允许 `recording_id = NULL`。后续 Playback 通过时间范围仍可定位；不阻塞事件创建。

## 快照

每个已确认事件保存一张代表帧。

目录结构：

```text
<data_dir>/motion/YYYY/MM/DD/camera-<camera_id>/event-<event_id>.jpg
```

策略：

- 在事件活跃期间保存运动评分最高的候选帧到内存。
- 事件结束并插入数据库得到 ID 后落盘。
- JPEG 质量使用 85。
- 快照失败不应导致事件丢失；`snapshot_path` 保持 NULL 并记录日志。

## Worker 生命周期

新增 `MotionDetectionManager`，职责仅包含 worker 生命周期管理：

- 应用启动时读取 `enabled=true` 的摄像头检测配置并启动 worker。
- 修改某摄像头配置后只重启该摄像头 worker。
- 摄像头禁用、删除或关闭移动检测时停止 worker。
- worker RTSP 连接失败时指数退避：2s、5s、10s、30s，最大 30s。
- 同一路摄像头最多一个 Motion Worker。
- 应用 shutdown 时停止全部 worker。

单个 `MotionWorker` 负责：

- 解析 main/sub stream。
- FFmpeg 输出固定分析 FPS、缩放后的 BGR/rawvideo 帧到 stdout，OpenCV 不直接负责 RTSP 网络连接。
- OpenCV 仅处理解码后的帧，保持 RTSP 行为与现有 FFmpeg 体系一致。
- 执行运动算法、Zone 判断、事件状态机与快照候选选择。

## FFmpeg 分析命令

使用现有 `settings.ffmpeg_bin` 和 RTSP URL 构造逻辑。

概念命令：

```text
ffmpeg -nostdin -hide_banner -loglevel error
  -rtsp_transport tcp
  -timeout <timeout_us>
  -i <rtsp_url>
  -map 0:v:0 -an
  -vf fps=<analysis_fps>,scale='min(<analysis_width>,iw)':-2
  -pix_fmt bgr24
  -f rawvideo pipe:1
```

实现时必须根据 ffprobe/首帧确定输出帧宽高，避免假设 16:9。

## API

统一挂在摄像头资源下。

### GET `/api/cameras/{camera_id}/motion-detection`

返回配置、Zones、运行状态：

```json
{
  "enabled": true,
  "sensitivity": "medium",
  "analysis_fps": 5,
  "analysis_width": 640,
  "min_duration_ms": 800,
  "merge_gap_ms": 3000,
  "runtime": {
    "state": "running",
    "stream": "sub",
    "last_frame_at": "...",
    "last_error": null
  },
  "zones": []
}
```

### PUT `/api/cameras/{camera_id}/motion-detection`

更新检测参数并按需启动/停止/重启该路 worker。

### POST `/api/cameras/{camera_id}/motion-zones`

创建 Zone。

### PUT `/api/cameras/{camera_id}/motion-zones/{zone_id}`

更新名称、启用状态或 polygon。

### DELETE `/api/cameras/{camera_id}/motion-zones/{zone_id}`

删除 Zone。

### GET `/api/motion-events`

参数：

- `camera_id` required
- `start` required
- `end` required
- `zone_id` optional
- `limit` default 500, max 2000

返回时间范围内与查询窗口有重叠的事件。

### GET `/api/motion-events/{event_id}/snapshot`

返回事件快照；没有快照时 404。

## 前端：摄像头详情

在现有摄像头详情 Drawer 增加“移动检测”配置区，不把设置塞入创建摄像头表单。

功能：

- 移动检测总开关。
- 灵敏度：低/中/高。
- 最短移动时间。
- 事件合并间隔。
- 分析 FPS/宽度放在“高级设置”折叠区。
- Zone 列表：名称、启用状态、编辑、删除。
- “添加检测区域”打开 Polygon 编辑器。

## Zone Polygon 编辑器

- 背景使用当前摄像头静态快照，不持续拉实时视频。
- 点击添加顶点，至少 3 点后可闭合。
- 可拖动已存在顶点。
- 支持重置和删除当前区域。
- 保存时把像素坐标转换为归一化坐标。
- 加载时按当前画布尺寸反算像素坐标。
- 摄像头无法获取快照时，允许使用黑色 16:9 占位画布继续编辑，但显示提示。

## Playback V3 接口

Motion Detection V1 完成后，Playback V3 使用 `/api/motion-events` 绘制真实移动轨道：

```text
录像  ████████████████████████████████████
移动  ────████─────██────────██████────────
                         │
                      playhead
```

交互：

- 点击事件块跳转到 `started_at - 2s`。
- Hover 显示 Zone、开始/结束时间、持续时间。
- 有快照时在右侧 Activity 列表显示缩略图。
- V1 只有 `移动` 类型；人员/车辆轨道不显示，直到 AI 检测真正实现。

## 前端状态与文案

- 未开启：`移动检测未启用`
- 启动中：`正在启动检测`
- 正常：`移动检测运行中`
- RTSP 重连：`检测流正在重连`
- 错误：显示最近错误，但录像状态保持独立。

## 依赖

后端新增：

```text
opencv-python-headless
numpy
```

不新增 GPU、YOLO、Torch、ONNX Runtime 依赖。

## 测试要求

### 后端单元测试

- Zone polygon 校验：少于 3 点、越界坐标、合法坐标。
- 无 Zone 时整画面有效。
- 单 Zone/多 Zone 命中判断。
- 事件持续时间门槛。
- merge gap 合并与关闭。
- sensitivity 参数映射。
- worker 配置变化时 restart，关闭时 stop。
- API CRUD 和摄像头隔离。
- 时间范围查询包含跨窗口事件。

### 检测算法测试

使用程序生成的 NumPy 帧，不依赖真实摄像头：

1. 静态黑帧序列不产生事件。
2. 白色矩形进入画面并持续足够时长产生 1 个事件。
3. 运动仅发生在 Zone 外时不产生事件。
4. 短于 `min_duration_ms` 的闪动不产生事件。
5. 小于 `merge_gap_ms` 的两段运动合并为 1 个事件。

### 前端测试

- 设置读取/保存。
- Polygon 归一化转换。
- Zone CRUD。
- 开关移动检测后的状态刷新。
- Playback 时间轴事件定位计算。

## 非目标

V1 明确不包含：

- 人员/车辆/动物分类。
- 人脸识别、车牌识别。
- 目标跟踪与 track_id。
- AI 通知策略。
- Motion Mask 编辑 UI。
- 云端 AI。
- 按事件触发录像；现有录像策略保持不变。

## 验收标准

1. 用户能在任一摄像头详情中开启/关闭移动检测。
2. 用户能创建至少一个任意四边形/多边形 Zone，并在刷新后保持。
3. 无 Zone 时整画面移动能产生事件；有 Zone 时 Zone 外移动不产生事件。
4. 一段持续移动只产生一个有起止时间的事件，而不是逐帧事件。
5. 每个事件尽可能生成代表快照。
6. RTSP 检测链路失败不会中断主录像进程。
7. 重启服务后已启用摄像头自动恢复检测。
8. Playback V3 能按时间范围读取并显示真实移动事件轨道。
9. 现有系统 `events` 页面不会被移动事件刷屏。
