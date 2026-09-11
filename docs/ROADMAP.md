# 版本路线

> 当前阶段：V0.9.x 前端与状态模型收敛。
>
> 录像、回放、OpenList/WebDAV 归档、实时预览、健康中心、事件中心和邮件告警等核心能力已经落地，当前重点从“补页面”转向状态一致性、稳定性验证、智能事件能力和 UI 设计系统收敛。

## 已完成阶段

### V0.1 ～ V0.2：核心录像与多路并发

- FastAPI / SQLite 基础框架
- Camera CRUD
- RTSP Probe
- FFmpeg Command Builder
- 单路与多路 CameraWorker
- `native` / `reconstruct` / `wallclock`
- 长连接切片
- MKV → MP4 stream-copy Remux
- ffprobe 健康检查
- Recorder 自动重连与故障隔离

### V0.7：健康与稳定性

- `GET /api/health/summary`
- `/ws/status`
- 每分钟健康采样
- 24h 趋势
- 24h / 72h 稳定性验收
- Recorder 可用率 / 录像完整率
- FFmpeg 失败、连续失败和断流统计
- 磁盘 warning / critical
- 安全自动清理
- 告警去重与恢复通知

历史接口中的 `online_rate` 表示期望录像时段内 Recorder 可用率；前端统一展示为“录像可用率”，不再与 RTSP 连接状态混淆。

### V0.8：录像浏览与 Web 回放

- `/recordings/browser`
- 摄像头 + 日期查询
- 24 小时时间轴
- 月历聚合
- 录像缺口识别
- 本地 H.264 / HEVC 回放
- HEVC 解码失败后 H.264 Proxy fallback
- Proxy Range / faststart / 缓存
- 上一段 / 下一段与跨日自动续播
- 云端已归档录像重新纳入时间轴
- OpenList WebDAV 云端流式回放
- 外部直链 302 与 Range proxy
- 云端 HEVC 远程源 Proxy fallback
- 相邻录像预热
- 后端和浏览器回放质量遥测

### V0.9：前端与状态架构收敛

已完成：

- 新 NVR Shell
- 左侧可折叠导航
- 顶部统一页面标题
- 移除旧 workspace tabs
- Dashboard
- 摄像头管理
- 录像管理
- 上传管理
- 事件中心
- 告警设置
- 系统健康
- 录制计划页面
- 1 / 4 / 9 宫格实时预览
- 删除 legacy `App.vue` 与旧 Root 代际代码
- OpenList/WebDAV 去存储品牌绑定
- 摄像头连接 / Recorder / Schedule 三状态分离
- Dashboard 与 Health 统一状态口径
- 删除旧回放页面代际与预览透传层
- 清理 `RootV2`、`CamerasViewV2`、`HealthViewV2`、`RecordingBrowserViewV3` 等历史版本后缀
- Shell 状态轮询复用 `/api/system/status`，不再额外拉取 `/api/cameras` 计算总数
- Dashboard 健康状态切换为 `/ws/status` 实时推送，HTTP 仅用于首次加载与断线兜底
- 双主题 token 基础、深浅模式切换与本地偏好持久化
- 摄像头设备身份元数据：`manufacturer` / `model` / `form_factor`
- 实时监控显示实际生效主码流 / 子码流

当前状态模型：

```text
connectivity_status
  unknown / online / offline

recorder_state
  STOPPED / STARTING / RECORDING / RECONNECTING / STOPPING

schedule_state
  disabled / global_disabled / automatic / scheduled / in_window
  manual_override / manual_paused / probe_required / error
```

## 统一待办清单

本节作为所有尚未完成事项的统一入口。新需求优先归入这里，再按版本拆分实施，避免分散在聊天或临时改动中。

### A. 摄像头设备中心与深链接

- [ ] 摄像头页升级为设备中心：设备身份、运行状态、实时预览、录像策略、能力集中展示
- [ ] 根据 `form_factor` 提供枪机 / 半球 / 炮塔 / PTZ / 门铃 / 室内机统一设备轮廓
- [ ] 根据 `manufacturer + model` 建立可扩展的具体型号图片 / 设备资料映射机制；无匹配时自动回退到外形轮廓
- [ ] 支持 `/cameras?camera_id=<id>`，直接打开指定摄像头详情
- [ ] 实时监控“摄像头配置”直接打开对应摄像头，而不是只进入列表
- [ ] 事件中心、Dashboard、Health 可下钻到准确摄像头
- [ ] 摄像头详情增加能力区：主 / 子码流、音频、ONVIF、事件、PTZ 等能力标记

### B. ONVIF 与设备发现

- [ ] ONVIF 基础客户端与认证
- [ ] 局域网设备发现（明确开启后执行，不默认后台扫描）
- [ ] 自动读取 manufacturer / model / firmware / serial / MAC
- [ ] 自动读取 Media Profiles、主码流 / 子码流 URI、编码和分辨率
- [ ] ONVIF 信息与现有手工 RTSP 配置合并，保持 RTSP 为最终录像输入
- [ ] 评估 / 接入 PullPoint / Events，用摄像头原生 motion / person / smart event 作为低资源事件源
- [ ] PTZ 能力识别，后续决定是否提供基础控制

### C. 智能事件录像

- [ ] 新增独立 `recording_policy`，取值 `manual / automatic / scheduled / event`
- [ ] 新增 `event_state`，取值 `disabled / armed / triggered / cooldown`
- [ ] 事件规则支持“触发摄像头 → 一个或多个目标录像摄像头”
- [ ] 优先接入摄像头原生 ONVIF / 厂商 person / motion 事件
- [ ] 无原生智能事件时，使用子码流低 FPS 本地 person detection
- [ ] 支持置信度、连续命中帧数、最短录像时长、无人延迟停止、冷却时间
- [ ] 支持 Webhook / MQTT / Home Assistant / PIR 等外部事件源
- [ ] 事件中心关联触发源、目标摄像头、规则和产生的录像片段
- [ ] 第二阶段增加约 10 秒可配置预录环形缓存
- [ ] 后续扩展 `vehicle / motion / door_open` 等事件类型
- [ ] 多路推理时评估 OpenVINO / NVIDIA / Coral 等硬件加速路径

### D. 精确页面下钻与前端路由

- [ ] `/recordings/browser?recording_id=<id>` 精确打开录像
- [ ] `/recordings/manage?recording_id=<id>` 精确定位录像资产
- [ ] `/uploads?task_id=<id>` 精确定位上传任务
- [ ] `/settings?section=archive` 精确打开归档设置
- [ ] 事件相关操作跳到准确实体，不只跳页面
- [ ] 录像管理“播放”打开准确录像而不是仅进入回放页
- [ ] 上传管理“上传设置”深链到归档设置
- [ ] 引入 Vue Router，替换 Shell 手写 pathname / popstate 路由

### E. 前端状态与组件架构

- [ ] 建立 Pinia `cameraStore` / status store，减少页面各自重复拉取摄像头和系统状态
- [ ] 实时监控 Recorder 状态复用共享 `/ws/status`，移除独立 5 秒 `/api/system/status` 轮询
- [ ] 统一摄像头、录像、上传等共享 API 类型
- [ ] 清理 PlaybackTelemetryBridge 的全局 document listener，改成明确组件 / store 通道
- [ ] 清理回放时间轴 / 月历 legend 的运行时 DOM 插入，改成明确组件挂载位
- [ ] 设置页面增加 dirty-state 离开保护
- [ ] 建立统一 loading / skeleton / empty / error / motion 规范

### F. UI 设计系统继续收敛

- [ ] 深色 / 浅色模式覆盖所有页面，清理剩余写死颜色
- [ ] 摄像头设备中心完成 UniFi Protect 类的设备卡 / 详情层级，但保持 Camera Recorder 自身视觉
- [ ] Dashboard 异常优先并支持准确下钻
- [ ] 实时监控继续“画面优先、控制弱化”，配置型操作全部回设备中心
- [ ] 事件中心升级为时间线 / 活动流，并突出摄像头、事件类型和录像关联
- [ ] 回放强化播放器、24h 时间轴、兼容性、事件和录像片段的视觉连续性
- [ ] 上传 / 录像管理统一筛选器、批量操作与详情结构
- [ ] 响应式断点与窄屏信息密度统一

### G. 运维、发布与长期维护

- [ ] 10 路 24h / 72h 真实稳定性验收
- [ ] 主动断网、摄像头重启、RTSP 抖动、FFmpeg 异常退出恢复测试
- [ ] OpenList/WebDAV 故障期间本地录像持续性验收
- [ ] 磁盘 critical 自动保护实机验收
- [ ] Chrome / Safari / Edge 的 H.264 / HEVC / 云端回放实机矩阵
- [ ] 日志查看 / 下载入口与日志轮转策略
- [ ] 配置导入导出
- [ ] 更完整操作审计
- [ ] 发布版本与数据库迁移说明
- [ ] Prometheus Metrics
- [ ] Webhook / 企业微信 / Telegram 等通知通道
- [ ] 增加 lint / dead-code 检查
- [ ] 逐步删除旧 `status` API 兼容依赖
- [ ] OpenAPI 与文档持续对齐

## 当前优先级

### 1. 摄像头设备中心与准确下钻

先完成统一待办 A，并以 `/cameras?camera_id=<id>` 作为其他实体深链接的第一条标准实现。

### 2. 真实稳定性验证

- 10 路 24h 连续录像
- 10 路 72h 连续录像
- 主动断网 / 摄像头重启 / RTSP 抖动
- FFmpeg 异常退出恢复
- OpenList/WebDAV 故障期间录像持续性
- 磁盘 critical 自动保护
- 根据真实数据校准稳定性验收阈值

### 3. 回放实机验收

使用 Chrome / Safari / Edge 验证：

- 本地 H.264
- 本地 HEVC
- OpenList H.264
- OpenList HEVC
- 跨日自动续播
- Proxy fallback
- 云端预热命中

根据真实首帧耗时和错误数据调整：

- prefetch lead time
- 直链 TTL
- HEVC fallback 条件
- Proxy 缓存策略

### 4. UI 设计系统与交互收敛

目标：达到成熟 NVR 控制台的界面质感，参考 UniFi Protect 一类产品的信息密度与交互层级，但保持 Camera Recorder 自身视觉和功能语义。

- 深色 / 浅色主题完整覆盖，主题偏好本地持久化并支持首次跟随系统
- 所有页面逐步从写死颜色迁移到统一 `--nvr-*` design tokens
- 统一 Shell、导航、顶栏、状态栏、卡片、表格、筛选器、弹窗和空状态
- 减少边框噪音，用层级、留白、弱背景和状态色表达结构
- 实时监控强化画面优先，控制器按需浮现
- Dashboard 改为异常优先与可下钻布局
- 录像回放强化时间轴、播放器、事件与片段之间的视觉连续性
- 响应式断点和窄屏信息密度统一
- 后续增加统一的 motion / hover / loading 规范

### 5. 维护面继续收敛

- 逐步删除旧 `status` API 兼容依赖
- 将适合实时展示的页面统一接入共享 WebSocket / Store，减少重复轮询
- 收敛真正可复用的前端共享类型，避免为了抽象而统一不同语义的状态文案
- 文档与 OpenAPI 保持一致
- 增加 lint / dead-code 检查

## V1.0 正式可用版

目标：家庭 / 小型现场可长期运行和维护。

验收重点：

- 10 路稳定性数据达标
- 启动恢复可靠
- Graceful Shutdown 可验证
- 录像缺失可观测
- 磁盘策略安全
- 上传失败不影响本地录像
- 告警可用
- 本地与云端回放可用
- Docker 部署、升级、回滚流程清晰

计划补齐：

- 日志查看 / 下载入口
- 配置导入导出
- 更完整的操作审计
- 发布版本与迁移说明

## V1.1 智能事件录像与稳定性增强

稳定性：

- 更细粒度录像健康评分
- 长期稳定性趋势
- 日志轮转策略
- 告警冷却与策略细化
- Webhook / 企业微信 / Telegram 等通知通道
- Prometheus Metrics

智能事件录像：

- 新增独立 `recording_policy` / `event_state`，不把事件录像混入 `schedule_state`
- 支持“事件摄像头 → 一个或多个指定摄像头”的录像触发规则
- 优先使用摄像头原生 ONVIF / 厂商事件，无法提供可靠智能事件时再使用子码流低 FPS 人体检测
- 支持连续命中阈值、置信度、最短录像时长、无人延迟停止和冷却时间
- 事件进入事件中心，并关联触发摄像头、目标录像摄像头和录像片段
- 支持外部 Webhook / MQTT / Home Assistant / PIR 等事件源
- 第二阶段增加约 10 秒可配置预录环形缓存，保留事件发生前画面
- 后续扩展 `vehicle`、motion、door_open 等事件类型

建议状态模型：

```text
recording_policy
  manual / automatic / scheduled / event

event_state
  disabled / armed / triggered / cooldown
```

## V1.2 存储与归档增强

OpenList/WebDAV 已作为统一归档层，后续重点：

- 多归档目标
- Provider 级健康状态
- 云端回放链路长期趋势
- 归档一致性校验
- 大规模历史录像索引优化

不在 Camera Recorder 内直接实现具体云盘 SDK；实际存储适配优先交给 OpenList。

## V2.0 NVR Lite

- 多用户 / RBAC
- 摄像头分组
- 多节点
- 多存储目标策略
- 更完整事件规则
- 远程管理
- ONVIF 发现 / 设备资料 / Profiles / Events 完整化

## 长期原则

```text
可靠录像
  > 状态正确
  > 可恢复
  > 文件完整
  > 存储安全
  > 可回放
  > UI 丰富度
```
