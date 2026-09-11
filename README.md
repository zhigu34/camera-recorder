# Camera Recorder

轻量级 RTSP 摄像头录像、管理与云端归档平台。

## 已实现核心能力

- 多路 RTSP TCP 长连接录像，每台摄像头独立 FFmpeg Worker
- 摄像头 CRUD、单会话 RTSP Probe、动态识别分辨率/FPS/音频参数
- H.265 / AAC 原码流保存，不重新编码主录像
- `native` / `reconstruct` / `wallclock` 三种时间戳策略
- `reconstruct` 根据实际 FPS 和 AAC 参数动态生成 `setts + prescale=1`
- 默认 10 分钟 MKV 连续切片，不需要每段重新建立 RTSP 连接
- 后台 MKV → MP4 无损 Remux，HEVC MP4 使用 `hvc1`
- ffprobe 成品健康检查、断线自动重连、异常 MKV 保留
- SQLite 元数据持久化、摄像头密码加密保存
- Vue 3 Web 管理界面：添加、Probe、启停摄像头、查看录像
- Docker Compose 一键部署，支持 amd64 / arm64（Apple Silicon）

## Docker Compose 一键启动

前置条件只需要 Docker Desktop / Docker Engine + Compose：

```bash
git clone git@github.com:zhigu34/camera-recorder.git
cd camera-recorder
cp .env.example .env
# 建议至少修改 .env 中的 CAMREC_SECRET_KEY
docker compose up -d --build
```

打开：

```text
http://127.0.0.1:8080
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
data/        SQLite
recordings/  最终 MP4
staging/     正在录像/待处理 MKV
failed/      处理失败的 MKV
logs/        FFmpeg 日志
```

> 后端 Docker 镜像不会使用发行版自带的旧 FFmpeg，而是按构建架构下载当前 BtbN 静态 FFmpeg，并在镜像构建阶段确认 `setts` 支持 `prescale`。

## 首次使用

1. 打开 Web → `摄像头` → `添加摄像头`。
2. 填写名称、IP、账号密码、RTSP Path（例如 `/ch1/main`）。
3. 时间戳模式优先选择 `reconstruct`。
4. 保存后先点 `Probe`，系统会读取真实 FPS、分辨率、音频采样率等。
5. Probe 成功后点击 `开始`，或点击顶部 `全部开始`。
6. 完成的 Segment 会自动从 MKV 无损封装为 MP4 并出现在 `录像文件` 页面。

## 技术栈

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2, SQLite
- Frontend: Vue 3, TypeScript, Vite, Pinia, Element Plus
- Media: FFmpeg / ffprobe
- Runtime: Docker Compose + Nginx

## 文档

- [开发设计](docs/DEVELOPMENT.md)
- [系统架构](docs/ARCHITECTURE.md)
- [版本路线](docs/ROADMAP.md)
- [启动与开发](docs/GETTING_STARTED.md)

## 当前后续计划

下一阶段重点为：更完整的 Segment 健康评分、事件中心、磁盘自动清理、115 上传队列，以及 72 小时多路长稳测试。

> 安全说明：仓库中禁止提交真实摄像头密码、RTSP URL、115 Token、数据库密钥或本地录像文件。摄像头密码只通过 Web/API 写入本地 SQLite，并使用 `CAMREC_SECRET_KEY` 派生的密钥加密。
