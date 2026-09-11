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

## 当前优先级

### 1. 真实稳定性验证

- 10 路 24h 连续录像
- 10 路 72h 连续录像
- 主动断网 / 摄像头重启 / RTSP 抖动
- FFmpeg 异常退出恢复
- OpenList/WebDAV 故障期间录像持续性
- 磁盘 critical 自动保护
- 根据真实数据校准稳定性验收阈值

### 2. 回放实机验收

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

### 3. UI 设计系统与交互收敛

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

### 4. 维护面继续收敛

- 逐步删除旧 `status` API 兼容依赖
- 将上传管理 / 事件中心等适合实时展示的页面逐步接入 WebSocket
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
- 第一阶段使用子码流低 FPS 人体检测，检测到 `person` 后由 RecorderManager 启动主码流录像
- 支持连续命中阈值、置信度、最短录像时长、无人延迟停止和冷却时间
- 事件进入事件中心，并关联触发摄像头、目标录像摄像头和录像片段
- 支持外部 Webhook / MQTT / Home Assistant / PIR 等事件源
- 摄像头原生 ONVIF / ISAPI / CGI 人体事件作为低资源触发源进行适配评估
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
- 设备发现 / ONVIF（评估后决定）

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
