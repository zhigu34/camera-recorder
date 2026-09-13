# 按时间范围导出录像设计

## 目标

在回放页允许用户选择一个时间范围，将该范围内同一摄像头的多个 MP4 录像切片导出为一个或多个可下载文件。

设计目标：

- 主入口位于回放页，而不是录像文件管理页。
- 默认使用无转码 `stream copy`，避免重复编码和画质损失。
- 导出前识别录像缺口，并把缺口处理方式交给用户选择。
- 分段输出时，用户可选择分别下载多个 MP4，或打包为无压缩 ZIP。
- 导出任务异步执行，避免长时间占用 HTTP 请求。
- 导出产物与原始录像分离存放、分离建模。
- 不改变现有录像切片、回放进入页不自动播放等既有媒体行为。

## 用户入口与交互

入口放在 `PlaybackWorkspace.vue` 的回放工具区，增加“导出片段”。

`PlaybackTimelineV3.vue` 增加时间范围选择能力：用户可在时间轴拖出开始/结束时间，并显示选中区间与两个边界手柄。现有单点点击/拖动 seek 行为继续保留；范围选择进入独立交互模式，避免与普通 seek 冲突。

点击“导出片段”后先请求后端进行范围分析，不立即启动 FFmpeg。确认框展示：

- 摄像头
- 开始时间
- 结束时间
- 请求时长
- 覆盖到的录像切片数量
- 缺口数量和每个缺口的起止时间

没有缺口时，只展示导出方式：

- `fast`：快速导出，无转码，默认选项
- `exact`：精确导出，严格匹配用户选择时间，必要时允许边界转码

有缺口时增加“缺口处理”：

- `merge`：跳过缺失时间，把实际存在的录像继续合并成一个 MP4
- `split`：按连续录像区间拆分，输出多个 MP4

当且仅当 `gap_policy=split` 时出现“多文件交付方式”：

- `individual`：分别生成多个 MP4，默认选项
- `zip`：多个 MP4 + 导出信息文件打包为一个 ZIP

ZIP 使用 store/no-compression 模式，不对 MP4 再做无意义压缩。

## 范围分析

新增后端范围分析服务，输入：

```json
{
  "camera_id": 3,
  "start_at": "2026-09-14T10:03:20+08:00",
  "end_at": "2026-09-14T10:17:45+08:00"
}
```

查询规则：

```text
recording.started_at < requested_end
AND
recording.ended_at > requested_start
```

结果按 `started_at` 排序，并裁剪到请求范围。分析阶段生成：

- `recordings`：参与导出的录像记录
- `continuous_groups`：按连续性归并后的区间组
- `gaps`：缺失区间
- `covered_duration`
- `requested_duration`

连续性判断需允许很小的时间误差，避免 FFmpeg/容器时间戳的毫秒级偏差被误判为缺口。建议以 1 秒以内作为默认容差；真正大于容差的间隔才计入 gap。

如果整个请求范围没有任何录像，分析接口直接返回不可导出状态，不创建任务。

## API 设计

建议新增独立路由：

`backend/app/api/exports.py`

### 分析范围

`POST /api/exports/analyze`

返回请求范围、切片数、连续区间和缺口。

### 创建导出任务

`POST /api/exports`

示例：

```json
{
  "camera_id": 3,
  "start_at": "2026-09-14T10:03:20+08:00",
  "end_at": "2026-09-14T10:17:45+08:00",
  "export_mode": "fast",
  "gap_policy": "split",
  "package_mode": "individual"
}
```

约束：

- `export_mode`: `fast | exact`
- `gap_policy`: `merge | split`
- `package_mode`: `individual | zip`
- 当 `gap_policy=merge` 时，`package_mode` 必须为 `individual`；`zip` 只允许用于 `split`
- 无缺口时按单文件导出处理，不因为 `package_mode` 人为拆分

### 查询任务

`GET /api/exports/{id}`

状态：

- `pending`
- `processing`
- `ready`
- `failed`
- `expired`

### 获取产物

`GET /api/exports/{id}/artifacts`

返回一个或多个导出产物。单文件可以直接下载；多文件 individual 模式前端分别展示下载按钮；ZIP 模式只展示 ZIP 主产物。

## 数据模型

新增 `ExportJob`，不要把派生导出文件写入 `Recording`。

建议字段：

```text
id
camera_id
requested_start_at
requested_end_at
export_mode
gap_policy
package_mode
status
progress
gap_count
requested_duration
covered_duration
error_message
created_at
started_at
completed_at
expires_at
```

新增 `ExportArtifact`：

```text
id
export_job_id
kind              mp4 | zip | manifest
segment_index
start_at
end_at
path
file_size
created_at
```

`Recording` 继续只代表系统原始录像资产；`ExportJob/ExportArtifact` 代表用户派生结果。

## 后端服务

新增：

`backend/app/services/recording_export.py`

职责：

1. 查询并分析时间范围。
2. 识别缺口与连续分组。
3. 为任务生成工作目录。
4. 构造 concat list。
5. 运行 FFmpeg。
6. 根据 gap policy 输出一个或多个 MP4。
7. 可选生成 store-mode ZIP。
8. 更新 ExportJob / ExportArtifact 状态。
9. 失败时保留错误信息并清理 `.part` 临时文件。

导出任务执行器可以先采用应用内 asyncio worker，与现有 `SegmentProcessor` 风格保持一致；第一版不引入 Celery/Redis。服务重启时，残留 `pending/processing` 任务应重置为可恢复或失败状态，避免永远卡住。

## 快速导出

快速模式优先使用 concat demuxer + `-c copy`。

同一摄像头正常情况下编码参数一致，符合无转码合并条件。创建 concat 文件：

```text
file '/data/recordings/.../10-00.mp4'
file '/data/recordings/.../10-05.mp4'
file '/data/recordings/.../10-10.mp4'
```

然后生成临时合并文件：

```text
ffmpeg -f concat -safe 0 -i list.txt -c copy merged.part.mp4
```

再按请求范围做 stream-copy 边界裁剪。快速模式允许起止位置贴近关键帧，因此 UI 文案必须明确“速度优先，边界可能存在少量偏差”。

如果 concat 因编码参数异常失败，任务应明确失败并给出原因；第一版不静默自动切换为全量转码，避免高 CPU 行为不可预期。

## 精确导出

精确模式保证开始/结束尽量严格匹配用户选择。

第一版实现允许对最终范围进行重新编码以获得稳定、可预测的边界；后续可优化为“仅首尾边界转码，中间 stream copy”。

精确模式在 UI 中标记为 CPU 开销较高，并非默认选项。

## 缺口策略

### merge

所有存在录像按时间顺序合并为一个 MP4，不插黑帧、不补静帧、不人为补足缺失秒数。

例如：

```text
10:03:20 - 10:08:12
[缺 17 秒]
10:08:29 - 10:17:45
```

输出文件会直接从 10:08:12 的最后画面衔接到 10:08:29 的第一画面。导出任务和 UI 必须保留 gap 元数据，不能把产物描述成真实墙钟时间连续。

### split

按照 `continuous_groups` 分别导出：

```text
camera_10-03-20_10-08-12.mp4
camera_10-08-29_10-13-41.mp4
camera_10-14-03_10-17-45.mp4
```

每个 Artifact 记录自己的真实开始/结束时间。

## ZIP 打包

仅用于 `split + zip`。

ZIP 内容：

```text
camera_10-03-20_10-08-12.mp4
camera_10-08-29_10-13-41.mp4
camera_10-14-03_10-17-45.mp4
export-info.json
```

`export-info.json` 记录：

- 摄像头 ID/名称
- 用户请求起止时间
- 实际覆盖时长
- gaps
- 每个输出文件及真实起止时间
- export mode

ZIP 使用 `ZIP_STORED`，避免 CPU 浪费。

## 文件目录

原始录像保持：

```text
/data/recordings/
```

导出文件单独放：

```text
/data/exports/
  camera-3/
    2026-09-14/
      export-<job-id>/
```

工作中的临时文件统一使用 `.part` 或 job 临时目录，只有成功后才暴露为可下载 Artifact。

## 生命周期与清理

导出是派生数据，不应永久占用录像盘。

第一版建议默认保留 24 小时，之后标记 `expired` 并删除产物。保留时长先作为服务常量；若后续需要用户自定义，再加入系统设置，避免本功能首版同时扩大设置模型。

正在下载的文件不应在请求处理中被删除；清理任务只处理超过 `expires_at` 且非 processing 的任务。

## 前端状态

`PlaybackWorkspace.vue` 负责：

- 当前 export range
- 打开/关闭导出确认框
- 调用 analyze API
- 创建 ExportJob
- 展示导出任务进度和完成状态

`PlaybackTimelineV3.vue` 负责：

- 范围选择视觉层
- 范围开始/结束事件
- 不主动启动播放器

第一版任务进度可以采用轮询 `GET /api/exports/{id}`；不新增 WebSocket 协议。轮询只在存在 pending/processing 任务时运行，任务完成后停止。

## 下载体验

- 单 MP4：显示一个“下载 MP4”。
- split + individual：显示每个 MP4 的时间范围和独立下载按钮。
- split + zip：显示一个“下载 ZIP”。
- 浏览器刷新后可通过 ExportJob API 重新获取尚未过期的任务和产物。

第一版不新增独立“导出记录”页面；回放页完成整个工作流。后续若导出需求增长，再增加导出历史页。

## 安全与边界

- 所有输入时间必须规范化为 timezone-aware datetime。
- 强制 `end_at > start_at`。
- 后端限制单次最大导出范围，第一版建议 24 小时，避免误操作产生超大任务。
- 路径完全由服务端根据 Recording 记录构造，客户端不能传文件路径。
- concat list 对路径做安全处理，不接受用户提供的路径。
- 下载接口只能访问归属于 ExportArtifact 的文件。
- 删除/过期清理不能影响 `/data/recordings` 原始录像。

## 测试策略

此功能涉及数据库、FFmpeg 和录像资产，按高风险业务逻辑处理，不走纯 UI 快速流程。

后端重点测试：

- 范围重叠查询
- 无录像范围
- 无缺口连续切片
- 单个/多个缺口识别
- gap tolerance
- merge 分组
- split 分组
- individual / zip 参数校验
- ExportJob 状态迁移
- FFmpeg 命令构造
- ZIP 使用 store 模式
- 任务失败清理
- 过期清理不触碰原始录像

前端重点测试：

- 时间轴范围选择不会自动播放
- analyze 结果无缺口时隐藏 gap controls
- 有缺口时显示 merge/split
- split 时才显示 individual/zip
- 默认 `fast + merge`，split 默认 `individual`
- 任务完成后显示正确下载入口

CI 继续要求 frontend tests/build、backend pytest/compileall 和 docker smoke 全绿后才能合并。

## 非目标

第一版不做：

- 跨摄像头合并
- 多天/超长任务的分布式队列
- 云端直接合并
- 自动转码兜底
- 在视频里插入缺口黑屏
- 永久导出历史页面
- 修改现有正式录像保存格式

## 实施顺序

1. ExportJob / ExportArtifact 数据模型与迁移。
2. 范围分析与缺口识别服务、测试。
3. 导出任务服务与 FFmpeg 快速模式。
4. split / ZIP 产物。
5. 精确模式。
6. API 与下载/过期清理。
7. PlaybackTimelineV3 范围选择。
8. PlaybackWorkspace 导出确认和任务状态 UI。
9. 全量 CI、Docker smoke、端到端自检。
