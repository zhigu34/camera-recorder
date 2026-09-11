# 启动与开发

## 推荐：Docker Compose

只需要 Docker Desktop / Docker Engine + Compose。

首次构建先准备 FFmpeg 本地包：

```bash
# 自动识别当前宿主机架构
bash scripts/download-ffmpeg.sh

# Linux x86_64 也可以明确指定
bash scripts/download-ffmpeg.sh amd64
```

然后：

```bash
cp .env.example .env
# 至少修改 CAMREC_SECRET_KEY 和 OPENLIST_ADMIN_PASSWORD
docker compose up -d --build
```

`.env` 只保留部署级信息：宿主机端口、时区、系统加密密钥和 OpenList 容器初始化信息。录像参数、磁盘阈值、115 上传、WebDAV 和邮件告警均从 Web 配置并保存到 SQLite。

Web：`http://127.0.0.1:8080`

API：`http://127.0.0.1:8000`

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
```

升级代码后，已经存在且校验正常的 FFmpeg 包不会重复下载：

```bash
git pull
bash scripts/download-ffmpeg.sh
docker compose up -d --build
```

停止服务：

```bash
docker compose down
```

`down` 不会删除 `data/`、`recordings/`、`staging/`、`failed/`、`logs/` 中的宿主机数据。

### FFmpeg 预下载

Dockerfile **不会访问 GitHub 下载 FFmpeg**。FFmpeg 压缩包由宿主机提前准备，构建时只从 Docker build context 复制并解压。

脚本支持：

```bash
bash scripts/download-ffmpeg.sh          # auto，自动识别当前架构
bash scripts/download-ffmpeg.sh amd64    # Linux x86_64
bash scripts/download-ffmpeg.sh arm64    # ARM64 / Apple Silicon Docker target
bash scripts/download-ffmpeg.sh all      # 两种架构都下载
```

下载位置：

```text
vendor/ffmpeg/ffmpeg-linux64.tar.xz       # amd64
vendor/ffmpeg/ffmpeg-linuxarm64.tar.xz    # arm64
```

脚本会先用 `tar -tJf` 校验已有文件：文件存在且有效时直接跳过下载；损坏文件会删除后重新下载。

如果服务器访问 GitHub 不方便，可以在其他能访问 GitHub 的机器下载后把文件复制到服务器。例如 amd64 服务器只需要准备：

```text
vendor/ffmpeg/ffmpeg-linux64.tar.xz
```

对应上游文件为：

```text
https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz
```

ARM64 对应：

```text
https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz
```

复制完成后直接构建即可；Dockerfile 不会再访问 GitHub。

这些大文件被 `.gitignore` 忽略，不会提交到仓库，但不会被 `.dockerignore` 排除，因此本地构建可以正常 `COPY`。

### 中国大陆构建源

Dockerfile 默认针对中国大陆网络优化构建依赖：

- Debian APT：清华 TUNA Debian / Debian Security
- Python pip / uv：清华 TUNA PyPI
- npm：npmmirror
- FFmpeg：宿主机预下载，本次 Docker build 不联网获取

这些镜像地址是 Docker build `ARG`，不会增加 `.env` 复杂度。默认直接构建即可：

```bash
docker compose build --builder default
```

如果某个环境需要临时切回官方源，可以在构建时覆盖，例如：

```bash
docker compose build --builder default backend \
  --build-arg DEBIAN_MIRROR=https://deb.debian.org/debian \
  --build-arg DEBIAN_SECURITY_MIRROR=https://security.debian.org/debian-security \
  --build-arg PYPI_INDEX_URL=https://pypi.org/simple

docker compose build --builder default frontend \
  --build-arg NPM_REGISTRY=https://registry.npmjs.org
```

### Apple Silicon

Compose 使用 Docker 的 `TARGETARCH` 自动选择本地 `linuxarm64` FFmpeg；Intel/AMD 则使用 `linux64`。镜像构建阶段会执行 `ffmpeg -h bsf=setts` 并确认存在 `prescale`，否则直接构建失败。

### 摄像头网络

后端容器必须能访问摄像头 LAN IP 的 TCP/554。Docker Desktop 默认桥接网络通常可以主动访问局域网设备。如果存在 VLAN、防火墙或 Docker 网络策略，需要允许容器到摄像头网段的 TCP/554。

## 首次配置

1. Web 添加摄像头。
2. 保存后点击 `Probe`。
3. 确认视频编码、分辨率、FPS、音频参数正确。
4. 当前已验证的萤石设备优先使用 `reconstruct`。
5. 点击 `开始`。
6. 点击右下角 `系统设置` 配置切片、磁盘和 115 上传。
7. `告警设置` 页面配置 SMTP 和摄像头掉线邮件。
8. 查看 `docker compose logs -f backend` 和宿主机 `logs/`。

`reconstruct` 不写死 15fps：系统使用 Probe 得到的 `fps_num/fps_den` 动态生成视频 `setts`；AAC 使用实际 `sample_rate` 与 `audio_frame_samples` 生成音频时间轴。

### 系统设置生效规则

- 上传开关、上传并发、重试次数、保留时间、WebDAV 和磁盘阈值：保存后直接生效。
- Remux 并发：下一轮 Segment 处理时生效。
- 切片时长、RTSP 超时、整点切片：新启动或重连的摄像头 Worker 生效；对正在录制的摄像头可执行一次重启。
- 启动时自动恢复录像：下次后端启动时生效。

## 本地开发

前置条件：

- macOS / Linux
- Python 3.12+
- `uv`
- Node.js 20+
- FFmpeg / ffprobe，且 `setts` 支持 `prescale`

### 后端

```bash
cp .env.example .env
cd backend
uv sync --dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

验证：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/system/status
curl http://127.0.0.1:8000/api/settings
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。Vite 会代理 `/api`、`/health` 和 `/ws` 到本地 FastAPI。

### 测试

```bash
cd backend
uv run pytest
```

## 数据目录

```text
data/camera.db          SQLite 元数据与运行时配置
recordings/             完成的 MP4
staging/camera-{id}/    FFmpeg 连续写入的 MKV
failed/camera-{id}/     Remux/健康检查失败后保留的 MKV
logs/camera-{id}.log    单路 FFmpeg 日志
```

不要将 `.env`、数据库、实际 RTSP 地址、密码、Token 或录像提交到 Git。
