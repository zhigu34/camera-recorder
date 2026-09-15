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
- 建立 Device Adapter 与 Stream Resolver 边界，让录像、预览、检测按用途获取流，而不是各自直接读取 `camera.rtsp_path`。
- 为 Camera 落库 `connection_type`，现有摄像头统一迁移为 `manual_rtsp`，未来 ONVIF 使用 `onvif`。
- 保留现有移动检测数据库、API、事件和时间轴兼容，避免为架构重组做高风险事件数据迁移。
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
- 持久化 preferred source；V1 只有 `local.motion` 一个真实事件源，多源选择在第二个真实 provider 接入时再落库。

## 4. 总体架构

```text
Camera
  |
  +-- Device Adapter
  |     +-- Manual RTSP        (V1)
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

## 5. Device Adapter 与 Camera 连接来源

### 5.1 connection_type

V1 为 `cameras` 表新增：

```text
connection_type = manual_rtsp | onvif
```

实现要求：

- 数据库字段非空，默认值和 server default 都是 `manual_rtsp`。
- Alembic 迁移把所有历史 Camera 视为 `manual_rtsp`。
- `CameraCreate` V1 只接受/默认 `manual_rtsp`；`onvif` 在协议实现前不得通过普通创建接口伪造为已支持设备。
- `CameraRead` 暴露 `connection_type`。
- 现有手工 RTSP 添加流程不改变。

### 5.2 Device Adapter

V1 建立稳定接口并实现：

```text
ManualRtspDeviceAdapter
```

未来新增：

```text
OnvifDeviceAdapter
```

Device Adapter 负责设备级能力和流来源，不负责事件中心展示。ONVIF 专属元数据未来使用独立表/模型保存，不把 Profile Token、Service URL、PTZ capability 等全部塞入 `cameras` 表。

未来 ONVIF 元数据至少包括：

- Device UUID / endpoint reference。
- Device service URL。
- Media / Media2 / Events / PTZ capabilities。
- Profile Token 与流角色映射。
- Snapshot URI 能力。
- 固件、厂商、型号等发现信息。

## 6. Stream Resolver

V1 提供统一入口：

```text
resolve_stream(camera, purpose)

purpose:
  recording
  preview
  detection
```

Manual RTSP 行为：

- `recording`：主码流。
- `preview`：优先子码流，没有则主码流。
- `detection`：优先子码流，没有则主码流。

V1 必须让以下三条链路通过 resolver 获取流：

1. Recorder / FFmpeg 录像输入。
2. 实时预览。
3. 本地移动检测。

这样未来 `OnvifDeviceAdapter` 只需要把 ONVIF Profile 映射成 recording / preview / detection 三种用途，上述三条业务链路不需要再次重构。

Resolver 输出的是业务可消费的流描述，不要求上层知道 Profile Token。V1 Manual RTSP 可最终解析成当前 RTSP URL/路径；未来 ONVIF 可解析成设备返回的 Stream URI。

## 7. Event Source 抽象

### 7.1 Event Source Descriptor

后端统一返回：

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

前端根据 descriptor 渲染能力，不根据品牌或未来 provider 写死业务判断。

### 7.2 Detector Registry

V1 registry 注册：

```text
local.motion
```

后续直接增加：

```text
local.ai
camera.onvif
```

每个 adapter 至少承担：

- capability discovery：当前摄像头可以提供哪些事件。
- configuration bridge：读取/更新该 source 的配置。
- runtime status：报告运行状态和错误原因。

事件产生或订阅机制由 adapter 内部实现，上层只消费规范化事件。

## 8. 统一 Detection Event

事件检测平台定义统一事件 DTO。V1 数据库仍使用现有 `MotionEvent`，通过 compatibility adapter 输出通用结构：

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

V1 `MotionEvent` 映射固定为：

```text
source_kind = local
provider    = motion
event_type  = motion
```

后续 ONVIF 和本地 AI 也输出 DetectionEvent，因此新的事件消费者只依赖统一结构。现有依赖 `/api/motion-events` 的消费者在 V1 保持兼容，不要求一次性切换。

## 9. 事件来源优先级与重复控制

系统默认不能同时对同一种逻辑能力开启多个 provider，否则会产生重复事件并浪费服务器资源。

未来默认优先级：

```text
camera_native
    -> 不支持时 local_ai
    -> 对 motion 能力可回退 local.motion
```

`local.motion` 只能生成 motion，不能伪装成人形、车辆或越界事件。

V1 只有 `local.motion` 一个真实 source，因此不持久化 preferred source。AI 和 ONVIF 在 UI 中只作为 capability slot 显示为“待接入/未安装”，不可开启。第二个真实 provider 接入时，再新增 preferred source 配置与跨 provider 去重策略。

## 10. ONVIF Native Events 扩展契约

未来 `camera.onvif` Event Source 负责：

- 查询 Events capability。
- 建立 PullPointSubscription 或其他受支持订阅。
- 解析 ONVIF Topic / Message。
- 把标准 topic 和已识别厂商 topic 映射为系统 event_type。
- 维护订阅续期、断线重连和设备时钟偏差处理。
- 无法识别的 vendor event 仍保留原始 topic 与 metadata，不静默丢弃。

ONVIF 原生事件与本地事件进入同一 DetectionEvent 管线。

连接状态与事件订阅状态必须独立：ONVIF Events 订阅断线表现为 source `error/reconnecting`，不能把整个 Camera 判为 offline。

## 11. 前端信息架构

### 11.1 主导航与路由

主导航新增一级：

```text
事件检测
```

路由固定为：

```text
/event-detection
/event-detection?camera_id=12
```

与摄像头、录像、事件中心、系统设置同级。

### 11.2 页面布局

采用已确认效果图结构：

- 顶部：标题与真实统计。
- 左栏：摄像头搜索、状态过滤、摄像头列表。
- 中栏：当前摄像头、实时画面、检测区域编辑。
- 右栏：Event Source / capability、灵敏度和当前 source 参数。
- 底部：重置与保存普通配置。

不显示虚假的 AI 模型数量或已启用状态。

### 11.3 capability 呈现

普通 RTSP 摄像头 V1：

```text
移动检测    可用 · 本地
人形识别    未安装 AI Provider
车辆识别    未安装 AI Provider
越界检测    暂不可用
```

未来 ONVIF AI 摄像头：

```text
移动检测    摄像头原生 ONVIF
人形识别    摄像头原生 ONVIF
车辆识别    摄像头原生 ONVIF
本地 AI     可选
```

前端只消费 capability descriptor，不根据厂商硬编码。

## 12. 摄像头详情调整

现有摄像头抽屉移除完整 `MotionDetectionPanel`。

替换为“事件检测”摘要卡：

- 当前是否存在启用的事件源。
- 主要事件源，例如“本地移动检测”。
- 当前运行状态。
- “前往配置”按钮跳转 `/event-detection?camera_id=<id>`。

摄像头页面负责设备管理；事件检测工作区负责检测规则和来源配置。

## 13. 检测区域

V1 继续使用现有 `MotionZone` 与 `MotionZoneEditor`，不迁移通用区域表。

规则：

- 普通检测参数使用页面草稿 + 保存按钮。
- 区域创建、重绘、启停、删除保持即时提交。
- UI 明确提示区域操作立即生效，普通参数保存后生效。

未来 AI 或 ONVIF 出现不同区域语义时，再设计通用 DetectionRule / DetectionZone；不在 V1 预建空表。

## 14. API 契约

### 14.1 保留兼容 API

```text
GET/PUT /api/cameras/{id}/motion-detection
POST/PUT/DELETE /api/cameras/{id}/motion-zones/...
GET /api/motion-events
```

### 14.2 V1 新增聚合 API

```text
GET /api/cameras/{id}/event-detection
```

返回该摄像头事件检测 overview：Camera 摘要、所有 Event Source descriptors、当前启用 source、运行状态和 capability 汇总。

```text
GET /api/cameras/{id}/event-detection/sources/{source_id}
PUT /api/cameras/{id}/event-detection/sources/{source_id}
```

读取/更新指定 source 配置。V1 只支持 `source_id=local.motion`，内部桥接现有 motion service，不复制第二套配置逻辑。

```text
GET /api/detection-events?start=...&end=...&camera_id=...&event_type=...&provider=...
```

返回统一 DetectionEvent。V1 由 MotionEvent adapter 提供数据；原 `/api/motion-events` 保持兼容。

对于尚未实现的 `local.ai` / `camera.onvif`，overview 可以返回 unavailable/unsupported descriptor，但 source detail/update 不得伪装成功，应返回明确的不可用错误。

## 15. 数据迁移策略

V1 数据库迁移只增加 Camera `connection_type`：

- 非空字符串字段。
- default/server default：`manual_rtsp`。
- 历史数据全部保持 `manual_rtsp`。

不修改：

- `motion_detection_settings`
- `motion_zones`
- `motion_events`
- 录像关联和现有事件 ID

新的聚合层负责把 legacy motion 数据映射成统一 DTO。未来若需要通用事件表，单独设计和迁移，不与本轮 UI/设备边界调整混合。

## 16. 错误与状态模型

Event Source 状态至少区分：

- `available`：能力可正常使用。
- `unavailable`：能力存在于平台设计中，但依赖未安装/未配置。
- `unsupported`：当前摄像头或 adapter 不具备该能力。
- `error`：已经配置但运行失败。

Runtime state 可以进一步表示 `disabled / starting / running / reconnecting / error`。

前端不能把 unsupported、unavailable、error 都显示成“关闭”。

## 17. 测试要求

### 后端

- registry 正确注册并查询 `local.motion`。
- event-detection overview 对普通 RTSP Camera 返回正确 descriptor。
- legacy motion config 能通过 source API 读取和保存。
- legacy MotionEvent 正确映射成 DetectionEvent。
- 未实现 AI/ONVIF 时返回 unavailable/unsupported，不伪造功能。
- `connection_type` 迁移后历史数据为 `manual_rtsp`。
- Manual RTSP Stream Resolver 对 recording/preview/detection 行为正确。
- Recorder、Preview、Motion Detection 三条链路均通过 resolver，行为与改造前兼容。

### 前端

- `/event-detection` 主导航和路由正确。
- `camera_id` 深链正确选择摄像头。
- 摄像头切换不会污染其他摄像头的未保存草稿。
- 现有移动检测全部参数可以读取、修改、保存。
- MotionZone CRUD 与区域编辑保持兼容。
- AI / ONVIF 未实现能力明确禁用并说明原因。
- 摄像头详情只显示检测摘要并正确跳转事件检测页面。

### 回归

- 原 `/api/motion-events` 保持可用。
- 回放时间轴移动事件保持可用。
- 事件中心与通知系统不会因为聚合 API 出现重复事件。
- 前端 lint/test/build、后端 pytest、Docker smoke 全部通过后才允许合并。

## 18. 分阶段路线

### V1：事件检测平台骨架

- `connection_type` migration。
- ManualRtspDeviceAdapter。
- Stream Resolver，并接管 recording / preview / detection 三条流用途。
- Event Source registry。
- `local.motion` adapter 与兼容桥。
- DetectionEvent adapter + `/api/detection-events`。
- 新主导航与事件检测工作区。
- 摄像头详情改为事件检测摘要入口。

### V2：ONVIF Device

- WS-Discovery。
- ONVIF 登录和设备身份发现。
- Media/Media2 Profiles。
- 主/子/检测流自动解析。
- ONVIF 设备自动添加。

### V3：ONVIF Native Events

- Events capability discovery。
- PullPoint 订阅、续期与重连。
- 标准 Topic 与 vendor Topic 映射。
- motion/tamper/digital input 等统一事件。
- 设备原生 AI topic 可识别时映射 person/vehicle/intrusion 等。
- 引入 preferred source 和必要的跨 provider 去重策略。

### V4：Local AI

- `local.ai` provider。
- 模型生命周期和资源调度。
- person/vehicle 等检测能力。
- 与 camera_native 的来源选择与 fallback。

## 19. 成功标准

本轮完成后必须达到：

1. 用户从主导航进入独立“事件检测”工作区即可配置现有移动检测。
2. 摄像头详情不再承担完整检测配置。
3. UI 和新的聚合接口围绕 Event Source / capability 工作，而不是继续扩大 motion 特例。
4. 现有移动检测数据、事件、回放时间轴完全兼容。
5. Camera 已有明确的 `connection_type`，但 ONVIF 未实现时不会伪装可用。
6. Recorder、Preview、Detection 都通过统一 Stream Resolver 获取流。
7. 未来加入 `OnvifDeviceAdapter` 和 `camera.onvif` 时，不需要再次重构 Recorder、Preview、事件中心、录像时间轴和事件检测页面主体。
8. 未来加入 `local.ai` 时，不需要重新设计事件来源模型。
