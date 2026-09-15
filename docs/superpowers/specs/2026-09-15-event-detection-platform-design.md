# Event Detection Platform V1 设计

状态：已确认设计

日期：2026-09-15

## 1. 背景

当前项目已经具备本地移动检测能力，包括按摄像头配置、运行状态、检测区域、移动事件、快照和回放时间轴消费。但这些能力目前以 `motion_*` 为中心，并通过 `MotionDetectionPanel` 直接嵌入摄像头详情抽屉。

后续项目需要同时支持两类检测能力：

1. 服务器侧检测：现有移动检测，以及后续本地 AI（人形、车辆、越界、徘徊、物品遗留等）。
2. 摄像头原生检测：尤其是未来 ONVIF 摄像头提供的 Motion、Tamper、Digital Input，以及部分厂商通过 ONVIF Topic / PullPoint 暴露的人形、车辆、越界等智能事件。

因此 V1 不再把“移动检测”视为最终产品边界，而是建立统一的“事件检测平台”。现有移动检测作为第一个事件源实现继续工作，未来 ONVIF Native Events 和本地 AI 通过相同接口接入。

## 2. 目标

本轮实现目标：

- 主导航新增一级“事件检测”，路由 `/event-detection`。
- 支持 `?camera_id=<id>` 深链并保持摄像头选择状态。
- 将现有移动检测配置与检测区域从摄像头详情抽离到独立工作区。
- 建立 Event Source / Detector Registry 抽象，让 UI 和上层业务不再直接绑定 `motion`。
- 建立统一事件来源与能力描述，为本地 AI 和 ONVIF Native Events 留出稳定接口。
- 建立 Stream Resolver 边界，让录像、预览、检测逐步从直接读取 `camera.rtsp_path` 过渡到按用途解析流。
- 保留现有移动检测数据库、API、事件和时间轴兼容，避免为架构重组做高风险数据迁移。
- 明确 ONVIF 设备适配、流解析、原生事件订阅的后续扩展点，但本轮不实现 ONVIF 协议。

## 3. 非目标

V1 不实现：

- WS-Discovery 自动发现。
- ONVIF Device / Media / Media2 / PTZ / Events 协议调用。
- PullPointSubscription 或 BaseNotification 订阅。
- 本地 AI 推理模型。
- 人形、车辆、越界、徘徊等真实 AI 检测。
- 将现有 `motion_detection_settings`、`motion_zones`、`motion_events` 表重命名或迁移。
- 对已有录像、移动事件、时间轴数据做破坏性变更。

## 4. 总体架构

```text
Camera
  |
  +-- Device Adapter
  |     +-- Manual RTSP        (当前)
  |     +-- ONVIF              (后续)
  |
  +-- Stream Resolver
  |     +-- recording
  |     +-- preview
  |     +-- detection
  |
  +-- Event Sources
        +-- Local
        |     +-- motion       (V1 实际可用)
        |     +-- local_ai     (后续)
        |
        +-- Camera Native
              +-- onvif        (后续)
```

核心原则：录像、预览、检测、事件中心不需要知道设备底层是手工 RTSP 还是 ONVIF；事件消费者也不需要知道事件来自本地算法还是摄像头原生能力。

## 5. Event Source 抽象

### 5.1 Event Source Descriptor

后端提供统一能力描述，至少包含：

```text
id                  例如 local.motion / camera.onvif
provider            motion / local_ai / onvif
source_kind         local / camera_native
status              available / unavailable / unsupported / error
display_name
capabilities[]      motion / person / vehicle / intrusion / tamper / ...
configurable
runtime_state
reason              不可用时的说明
```

前端只根据 descriptor 渲染能力，而不是写死“移动检测、人形检测、车辆检测”的业务逻辑。

### 5.2 Detector Registry

后端建立 registry，用于注册事件源适配器。

V1 注册：

```text
local.motion
```

后续可直接增加：

```text
local.ai
camera.onvif
```

每个 adapter 至少承担三类职责：

- capability discovery：当前摄像头可以提供哪些事件。
- configuration bridge：获取与更新该 source 的配置。
- runtime status：报告 source 当前是否运行、异常原因等。

事件订阅/产生机制由 adapter 内部实现，上层只消费规范化事件。

## 6. 统一 Detection Event

事件检测平台定义统一事件 DTO。数据库 V1 仍允许现有 `MotionEvent` 继续存储，但新上层接口输出统一结构。

```text
DetectionEvent
  id
  camera_id
  source_kind       local | camera_native
  provider          motion | local_ai | onvif
  event_type        motion | person | vehicle | intrusion | tamper | ...
  started_at
  ended_at
  confidence        optional
  zone_id           optional
  zone_name         optional
  recording_id      optional
  snapshot_url      optional
  metadata          provider-specific metadata
```

V1 的 `MotionEvent` 通过 adapter 映射为：

```text
source_kind = local
provider    = motion
event_type  = motion
```

未来 ONVIF 事件也映射为同一结构，因此事件中心、录像时间轴、通知系统只依赖 DetectionEvent。

## 7. 事件来源优先级与重复控制

系统不能默认同时对同一能力开启多个来源，否则会产生重复事件并浪费服务器资源。

推荐默认优先级：

```text
camera_native
    -> 不支持时 local_ai
    -> 不支持时 local.motion
```

注意：`local.motion` 只能作为 motion 能力的回退，不能伪装成人形/车辆事件。

V1 尚无 ONVIF 与 AI，因此实际只有 `local.motion` 可启用；其他能力在 UI 中显示为“待接入能力”，不可操作。

后续每种逻辑能力允许配置一个 preferred source，也允许高级用户显式启用多个来源进行验证，但多源并行不是默认状态。

## 8. ONVIF 预留边界

### 8.1 Camera 连接来源

Camera 增加轻量连接来源概念：

```text
connection_type = manual_rtsp | onvif
```

V1 现有摄像头默认 `manual_rtsp`，不改变已有使用方式。

ONVIF 专属数据不应全部塞入 `cameras` 表。未来建议新增独立设备元数据结构，保存：

- ONVIF device UUID / endpoint reference。
- Device service URL。
- Media / Media2 / Events / PTZ capabilities。
- Profile Token 与流角色映射。
- Snapshot URI 能力。
- 固件、厂商、型号等发现信息。

### 8.2 Device Adapter

预留：

```text
ManualRtspDeviceAdapter
OnvifDeviceAdapter
```

Device Adapter 负责设备能力发现与设备级操作，不直接负责录像和事件中心展示。

### 8.3 ONVIF Event Source

未来 `camera.onvif` adapter 负责：

- 查询 Events capability。
- 建立 PullPointSubscription 或其他受支持订阅。
- 解析 ONVIF Topic / Message。
- 将摄像头厂商事件映射为系统事件类型。
- 维护订阅续期、断线重连和时钟偏差处理。
- 对无法识别的 vendor event 保留原始 topic 与 metadata，而不是丢弃。

ONVIF 原生事件与本地事件进入同一 DetectionEvent 管线。

## 9. Stream Resolver

当前代码大量直接使用 `camera.rtsp_path`。V1 建立统一解析边界：

```text
resolve_stream(camera, purpose)

purpose:
  recording
  preview
  detection
```

Manual RTSP 默认行为：

- recording -> 主码流。
- preview -> 优先子码流，没有则主码流。
- detection -> 优先子码流，没有则主码流。

未来 ONVIF Adapter 获取 Profiles 后，只需要让 resolver 返回相应 profile 的 RTSP URI，上层 Recorder、Preview、Detector 无需重构。

V1 不要求一次性重写所有录像调用；先建立 resolver 与新事件检测工作区使用它，随后逐步迁移旧调用点。

## 10. 前端信息架构

### 10.1 主导航

新增一级：

```text
事件检测
```

与摄像头、录像、事件中心、系统设置同级。

路由：

```text
/event-detection
/event-detection?camera_id=12
```

### 10.2 页面布局

采用已确认效果图结构：

- 顶部：页面标题与真实统计。
- 左栏：摄像头搜索、状态过滤、摄像头列表。
- 中栏：当前摄像头、实时画面、检测区域编辑。
- 右栏：检测来源/类型、灵敏度及当前 source 参数。
- 底部：重置与保存配置。

不显示虚假的 AI 模型统计。如果 V1 没有 AI provider，就明确显示未安装/待接入。

### 10.3 检测能力呈现

普通 RTSP 摄像头示例：

```text
移动检测    可用 · 本地
人形识别    未安装 AI Provider
车辆识别    未安装 AI Provider
越界检测    暂不可用
```

未来 ONVIF 设备示例：

```text
移动检测    摄像头原生 ONVIF
人形识别    摄像头原生 ONVIF
车辆识别    摄像头原生 ONVIF
本地 AI     可选
```

前端通过 capability descriptor 渲染，不根据品牌硬编码。

## 11. 摄像头详情调整

现有摄像头抽屉不再承载完整 `MotionDetectionPanel`。

替换为简洁“事件检测”摘要卡：

- 是否启用事件检测。
- 当前主要来源，例如“本地移动检测”。
- 当前运行状态。
- “前往配置”按钮，跳转 `/event-detection?camera_id=<id>`。

这样摄像头页面负责设备管理，事件检测工作区负责检测策略，职责分离。

## 12. 检测区域

V1 继续复用现有 `MotionZone` 与区域编辑能力，避免迁移。

区域操作规则：

- 参数表单使用统一草稿保存。
- 区域创建、重绘、启停、删除继续即时提交。
- 页面清晰提示区域变更会立即生效，而普通参数需点击保存。

未来如果 AI/ONVIF 对区域语义有不同要求，再引入通用 DetectionZone / Rule 模型；V1 不提前迁表。

## 13. API 边界

保留现有兼容 API：

```text
GET/PUT /api/cameras/{id}/motion-detection
POST/PUT/DELETE /api/cameras/{id}/motion-zones/...
GET /api/motion-events
```

新增事件检测聚合 API，命名以实现阶段最终路由规范为准，但职责固定为：

```text
GET  camera detection overview
GET  camera event-source capabilities
GET  normalized detection configuration
PUT  normalized detection configuration
GET  normalized detection runtime status
```

V1 聚合层内部调用现有 motion service，不复制第二套业务逻辑。

事件查询逐步增加统一 DetectionEvent 输出；旧 `/api/motion-events` 保持兼容，直到所有消费者迁移完成。

## 14. 数据迁移策略

本轮采用兼容优先策略：

- 不重命名 motion 表。
- 不搬迁现有 MotionEvent 数据。
- 不改变现有录像关联。
- 新的聚合层把 legacy motion 数据映射成统一 DTO。
- `connection_type` 若落库，老数据迁移默认 `manual_rtsp`。

任何未来通用事件表迁移必须独立设计，不与本轮 UI/架构调整混在一起。

## 15. 错误处理

事件源必须能区分：

- unsupported：设备/系统不具备该能力。
- unavailable：能力理论可用，但依赖未安装或尚未配置。
- error：已配置但运行失败。
- available：可正常使用。

前端不能把 unsupported/error 都显示成“关闭”。

未来 ONVIF 订阅断线必须表现为 source runtime error/reconnecting，而不能让整个摄像头被判断为离线。

## 16. 测试要求

### 后端

- registry 能正确注册并查询 `local.motion`。
- legacy motion config 能映射到通用 capability/config DTO。
- legacy MotionEvent 能映射到 DetectionEvent。
- 未支持 AI/ONVIF 时 descriptor 正确返回 unavailable/unsupported，而不是伪造能力。
- connection_type 老数据兼容。
- Stream Resolver 对 recording/preview/detection 的 manual RTSP 行为稳定。

### 前端

- `/event-detection` 主导航与路由正确。
- `camera_id` 深链正确选择摄像头。
- 摄像头列表切换不会污染其他摄像头草稿。
- 移动检测现有配置可完整读取、编辑、保存。
- 检测区域 CRUD 行为保持兼容。
- AI / ONVIF 未实现能力明确禁用并显示原因。
- 摄像头详情只显示摘要并正确跳转事件检测工作区。

### 回归

- 现有移动事件查询保持可用。
- 回放时间轴移动事件保持可用。
- 现有通知/事件中心不因新工作区出现重复事件。
- 前端 lint/test/build、后端 pytest、Docker smoke 全部通过后才可合并。

## 17. 分阶段实现

### V1：事件检测平台骨架

- 主导航与新工作区。
- local.motion adapter / registry。
- capability descriptor。
- legacy motion compatibility bridge。
- Stream Resolver 边界。
- 摄像头详情移除完整移动检测面板，替换摘要入口。

### V2：ONVIF Device

- WS-Discovery。
- ONVIF 登录与设备身份发现。
- Media/Media2 Profiles。
- 主/子/检测流自动解析。
- 自动添加摄像头。

### V3：ONVIF Native Events

- Events capability discovery。
- PullPoint 订阅与续期。
- Topic 映射。
- motion/tamper/digital input 统一事件。
- 支持设备原生 AI topic 时映射 person/vehicle/intrusion 等。

### V4：Local AI

- local.ai provider。
- 模型生命周期与资源调度。
- person/vehicle 等检测能力。
- 与 camera_native 的 preferred source / fallback 策略。

## 18. 成功标准

本轮完成后应达到：

1. 用户从主导航进入独立“事件检测”工作区即可配置现有移动检测。
2. 摄像头详情不再承担复杂检测配置。
3. 前端和事件消费者通过通用 source/capability 概念工作，而不是继续扩大 `motion` 特例。
4. 现有移动检测数据、事件、时间轴完全兼容。
5. 未来增加 `camera.onvif` 时，不需要重构事件中心、录像时间轴和事件检测页面主体。
6. 未来增加 `local.ai` 时，不需要再次重新设计事件来源模型。
