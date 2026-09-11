# Camera Recorder

轻量级 RTSP 摄像头录像、管理与 115 云端归档平台。

## 已实现核心能力

- 多路 RTSP TCP 长连接录像，每台摄像头独立 FFmpeg Worker
- 摄像头 CRUD、单会话 RTSP Probe、动态识别分辨率/FPS/音频参数
- H.265 / AAC 原码流保存，不重新编码主录像
- `native` / `reconstruct` / `wallclock` 三种时间戳策略
- `reconstruct` 根据实际 FPS 和音频参数动态生成 `setts + prescale=1`
- 默认 10 分钟 MKV 连续切片，不需要每段重新建立 RTSP 连接
- 后台 MKV → MP4 无损 Remux，HEVC MP4 使用 `hvc1`
- ffprobe 成品健康检查、断线自动重连、异常 MKV 保留
- SQLite 元数据持久化、摄像头密码加密保存
- OpenList WebDAV 持久化上传队列，可归档到 115 Open Platform
- 上传失败自动退避重试，上传成功后按本地保留时间自动清理
- Vue 3 Web 管理界面：摄像头、录像、115 上传任务
- Docker Compose 一键部署 Web + API + OpenList，支持 amd64 / arm64（Apple Silicon）

## Docker Compose 一键启动

前置条件只需要 Docker Desktop / Docker Engine + Compose：

```bash
git clone git@github.com:zhigu34/camera-recorder.git
cd camera-recorder
cp .env.example .env
# 必须修改 CAMREC_SECRET_KEY 和 OPENLIST_ADMIN_PASSWORD
docker compose up -d --build
```

打开：

```text
Camera Recorder  http://127.0.0.1:8080
FastAPI          http://127.0.0.1:8000
OpenList         http://127.0.0.1:5244
```

查看状态：

```bash
docker compose ps
docker compose logs -f backend
```

停止：

```bash
docker compose down
```

数据库和录像不会因为 `down` 被删除，数据保存在宿主机：

```text
data/           SQLite
recordings/     最终 MP4
staging/        正在录像/待处理 MKV
failed/         处理失败的 MKV
logs/           FFmpeg 日志
openlist-data/  OpenList 配置与数据库
```

> 后端 Docker 镜像按构建架构下载当前 BtbN 静态 FFmpeg，并在镜像构建阶段确认 `setts` 支持 `prescale`；不满足要求时直接停止构建。

## 首次使用

1. 打开 Web → `摄像头` → `添加摄像头`。
2. 填写名称、IP、账号密码、RTSP Path（例如 `/ch1/main`）。
3. 当前已验证的萤石设备优先选择 `reconstruct`。
4. 保存后先点 `Probe`，系统会读取真实 FPS、分辨率、音频采样率等。
5. Probe 成功后点击 `开始`，或点击顶部 `全部开始`。
6. 完成的 Segment 会自动从 MKV 无损封装为 MP4 并出现在 `录像文件` 页面。

## 115 上传

Compose 会一起启动 OpenList，但 **115 OAuth 授权必须由账号持有人完成一次**。

完成下面步骤即可启用自动上传：

1. 打开 `http://127.0.0.1:5244`，用 `admin` + `.env` 中的 `OPENLIST_ADMIN_PASSWORD` 登录。
2. 获取 115 Open 的 Access Token / Refresh Token。
3. 在 OpenList 添加 `115 Open Platform` 存储。
4. 挂载路径填写 **`115`**。
5. 确认 `/115` 能正常访问。
6. 修改 `.env`：

```env
CAMREC_UPLOAD_ENABLED=true
```

7. 应用配置：

```bash
docker compose up -d
```

随后最终 MP4 会自动上传到：

```text
115/监控录像/{摄像头名称}/YYYY-MM-DD/{摄像头名称}_YYYY-MM-DD_HH-MM-SS.mp4
```

完整说明：[115 / OpenList 配置](docs/115_OPENLIST.md)

## 技术栈

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2, SQLite
- Frontend: Vue 3, TypeScript, Vite, Pinia, Element Plus
- Media: FFmpeg / ffprobe
- Cloud bridge: OpenList / WebDAV / 115 Open Platform
- Runtime: Docker Compose + Nginx

## 文档

- [开发设计](docs/DEVELOPMENT.md)
- [系统架构](docs/ARCHITECTURE.md)
- [版本路线](docs/ROADMAP.md)
- [启动与开发](docs/GETTING_STARTED.md)
- [115 / OpenList](docs/115_OPENLIST.md)

## 安全

- 不要提交 `.env`、摄像头密码、完整 RTSP URL、115 Token 或录像文件。
- 摄像头密码只通过 Web/API 写入本地 SQLite，并使用 `CAMREC_SECRET_KEY` 派生的密钥加密。
- **`CAMREC_SECRET_KEY` 在摄像头已经录入后不要随意修改**，否则旧密码无法解密。
- OpenList 不建议直接以明文 HTTP 暴露到公网；本项目默认定位于可信 LAN 内使用。

## 当前下一步

代码层面的录像、Remux、基础健康检查、上传队列和 Compose 已完成。下一阶段重点是：

- 真实摄像头 10 路 72 小时长稳测试
- 更细粒度 Segment 健康评分与事件中心
- 磁盘容量可视化与更主动的空间告警
- WebSocket 实时状态推送
- 数据库正式 Alembic Migration 流程
