# 启动与开发

## 推荐：Docker Compose

只需要 Docker Desktop / Docker Engine + Compose：

```bash
cp .env.example .env
# 修改 CAMREC_SECRET_KEY 后启动
docker compose up -d --build
```

Web：`http://127.0.0.1:8080`

API：`http://127.0.0.1:8000`

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
```

升级代码后：

```bash
git pull
docker compose up -d --build
```

停止服务：

```bash
docker compose down
```

`down` 不会删除 `data/`、`recordings/`、`staging/`、`failed/`、`logs/` 中的宿主机数据。

### Apple Silicon

Compose 使用 Docker 的 `TARGETARCH` 自动选择 BtbN `linuxarm64` FFmpeg；Intel/AMD 则使用 `linux64`。镜像构建阶段会执行 `ffmpeg -h bsf=setts` 并确认存在 `prescale`，否则直接构建失败，避免运行后才发现时间戳修复能力缺失。

### 摄像头网络

后端容器必须能访问摄像头 LAN IP 的 TCP/554。Docker Desktop 默认桥接网络通常可以主动访问局域网设备。如果存在 VLAN、防火墙或 Docker 网络策略，需要允许容器到摄像头网段的 TCP/554。

## 首次配置

1. Web 添加摄像头。
2. 保存后点击 `Probe`。
3. 确认视频编码、分辨率、FPS、音频参数正确。
4. 当前已验证的萤石设备优先使用 `reconstruct`。
5. 点击 `开始`。
6. 查看 `docker compose logs -f backend` 和宿主机 `logs/`。

`reconstruct` 不写死 15fps：系统使用 Probe 得到的 `fps_num/fps_den` 动态生成视频 `setts`；AAC 使用实际 `sample_rate` 与 `audio_frame_samples` 生成音频时间轴。

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
uv run ruff check .
```

## 数据目录

```text
data/camera.db          SQLite 元数据
recordings/             完成的 MP4
staging/camera-{id}/    FFmpeg 连续写入的 MKV
failed/camera-{id}/     Remux/健康检查失败后保留的 MKV
logs/camera-{id}.log    单路 FFmpeg 日志
```

不要将 `.env`、数据库、实际 RTSP 地址、密码、Token 或录像提交到 Git。
