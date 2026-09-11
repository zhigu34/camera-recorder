# 版本路线

## V0.1 技术验证版

目标：证明核心录像链路稳定。

- FastAPI / SQLite 基础框架
- Camera CRUD
- 单会话 RTSP Probe
- FFmpegCommandBuilder
- 单路 CameraWorker
- `native` / `reconstruct` 时间戳策略
- 10 分钟 MKV 切片
- MKV → MP4 stream-copy Remux
- 基础 ffprobe 健康检查
- 最小前端：摄像头列表、添加、Probe、开始、停止

验收：单路连续 24 小时，无持续时间戳异常，MP4 可播放且音画同步。

## V0.2 多路录像版

目标：10 路稳定并发。

- RecorderManager
- 10 个独立 CameraWorker
- 自动重连 / 指数退避
- 独立日志
- SegmentProcessor 队列
- WebSocket 状态推送

验收：10 路同时录像 24 小时；任意一路断线不影响其他路，恢复后自动继续录像。

## V1.0 正式可用版

- Dashboard
- 摄像头管理
- 录像状态
- 录像文件管理
- 事件中心
- 健康检查
- 日志查看
- 磁盘统计 / 告警
- 启动恢复
- Graceful Shutdown
- macOS launchd / Linux systemd

## V1.1 稳定性增强

- 录像健康评分
- RTSP 重连统计
- 时间戳异常统计
- 24h 健康趋势
- 磁盘自动清理
- 日志轮转
- 配置导入导出

## V1.2 115 云端归档

- UploadManager
- UploadTask
- 115 Provider
- 自动上传 / 失败重试
- 上传幂等
- 本地保留 24/48h
- 上传成功后自动清理

## V1.3 录像浏览

- 日期浏览
- 摄像头时间线
- 上一段 / 下一段
- 按需 Web 播放
- 必要时生成低码率 H.264 Proxy；主录像仍保留 H.265 原码流

## V1.4 告警

- 摄像头离线
- 连续录像失败
- 磁盘不足
- 上传长期失败
- Webhook / 企业微信 / Telegram / 邮件
- 告警去重、恢复通知、冷却

## V2.0 NVR Lite

- 实时预览
- 完整时间轴
- 多用户 / RBAC
- 摄像头分组
- 多存储 Provider
- 多节点
- Prometheus Metrics
- 远程管理

## 开发顺序

1. Database / Camera
2. RTSP Probe
3. FFmpegCommandBuilder
4. CameraWorker
5. timestamp reconstruct
6. continuous segment
7. SegmentProcessor
8. Remux
9. Health Check
10. RecorderManager
11. Auto Reconnect
12. WebSocket
13. Frontend Camera Management
14. Dashboard
15. Recording Management
16. StorageManager
17. Event Center
18. 115 Upload
19. Cleanup
20. Timeline / Playback
