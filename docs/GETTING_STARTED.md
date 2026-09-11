# 启动与开发

## 推荐部署：Docker Compose

前置条件：Docker Engine / Docker Desktop + Compose。

### 首次部署

准备环境文件：

```bash
cp .env.example .env
```

至少修改：

```text
CAMREC_SECRET_KEY
OPENLIST_ADMIN_PASSWORD
```

然后运行：

```bash
./deploy.sh
```

`deploy.sh` 会自动：

- 检查 Docker / Compose / Buildx
- 使用 default builder
- 校验 Compose 配置
- 检查本地 FFmpeg 包
- 构建 backend / frontend
- 启动服务
- 等待 backend / frontend 健康
- 在 Docker 网络资源异常时尝试清理未使用网络后重试

完整构建日志位于：

```text
logs/deploy-build.log
```

### 后续升级

统一使用：

```bash
git pull && ./deploy.sh
```

常用参数：

```bash
./deploy.sh --no-build
./deploy.sh --check-only
./deploy.sh --no-ffmpeg-download
```

服务默认地址：

```text
Web       http://127.0.0.1:8080
API       http://127.0.0.1:8000
OpenList  http://127.0.0.1:5244
```

查看服务：

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f openlist
```

停止：

```bash
docker compose down
```

`down` 不删除宿主机持久化数据。

## FFmpeg 本地包

后端 Dockerfile 不在构建过程中直接从 GitHub 下载 FFmpeg。`deploy.sh` 会在宿主机准备并校验本地压缩包。

也可以手动执行：

```bash
bash scripts/download-ffmpeg.sh
bash scripts/download-ffmpeg.sh amd64
bash scripts/download-ffmpeg.sh arm64
bash scripts/download-ffmpeg.sh all
```

文件位置：

```text
vendor/ffmpeg/ffmpeg-linux64.tar.xz
vendor/ffmpeg/ffmpeg-linuxarm64.tar.xz
```

脚本会先校验现有压缩包，有效文件会直接复用。

如果部署服务器访问上游困难，可以在其他机器准备好对应架构文件后复制到 `vendor/ffmpeg/`。

构建阶段还会确认 FFmpeg `setts` bitstream filter 支持 `prescale`；不满足时直接终止构建。

## 构建依赖源

Dockerfile 默认使用适合中国大陆网络的构建源：

- Debian APT：清华 TUNA
- Python / uv：清华 TUNA PyPI
- npm：npmmirror
- FFmpeg：宿主机本地包

如需临时切回官方源，可通过 Docker build args 覆盖。

## 摄像头网络

backend 容器必须能够访问摄像头 LAN IP 的 RTSP 端口，通常为 TCP/554。

如果存在 VLAN、防火墙或 Docker 网络策略，需要允许容器主动访问摄像头网段。

## 首次配置

1. 打开 Web → `摄像头` → `添加摄像头`。
2. 保存后执行 `检测`。
3. 确认编码、分辨率、FPS、音频参数正确。
4. 对存在时间戳问题的设备优先尝试 `reconstruct`。
5. 手动开始录像，或进入 `录制计划` 配置自动录像。
6. 在 `系统设置` 配置切片、RTSP 超时、磁盘阈值、OpenList/WebDAV、上传和本地保留策略。
7. 在 `告警设置` 配置 SMTP 与通知策略。
8. 在 `系统健康` 查看连接、Recorder、Schedule、磁盘、上传和稳定性数据。

### 状态说明

摄像头有三个独立状态：

```text
连接状态 connectivity_status
录像状态 recorder_state
计划状态 schedule_state
```

不要根据“录像中”推断网络一定在线，也不要根据“计划时段”推断 Recorder 一定已经启动。

## OpenList / WebDAV

Camera Recorder 只依赖标准 WebDAV，不绑定具体存储品牌。

在 OpenList 添加任意可写存储后，可在 `系统设置` 使用：

```text
WebDAV URL: http://openlist:5244/dav/<挂载名>
远端根目录: 监控录像
```

或：

```text
WebDAV URL: http://openlist:5244/dav
远端根目录: <挂载名>/监控录像
```

详见 `docs/OPENLIST.md`。

## 24h / 72h 稳定性验收

系统健康采样会持续记录 Recorder 可用率、录像完整率、FFmpeg 失败和断流信息。部署持续运行后，可直接在项目根目录执行：

```bash
bash scripts/stability-check.sh 24
bash scripts/stability-check.sh 72
```

脚本会从正在运行的 backend 主进程读取 `/api/health/stability`，输出：

- 监控摄像头数量与 PASS / FAIL / COLLECTING
- 录像可用率
- 录像完整率
- FFmpeg 失败与连续失败
- 断流次数、累计时长和最长单次断流
- 每台失败/采集中摄像头的具体原因

退出码：

```text
0  PASS
1  FAIL
2  COLLECTING（采样时间或覆盖率尚不足）
3  无法读取报告
```

如果刚部署不久就执行 24h / 72h 验收，出现 `COLLECTING` 是正常的；应让服务持续运行到对应观察窗口后再次执行。验收期间不要清空 SQLite 数据库或健康采样记录。

也可以直接查看原始 JSON：

```bash
docker compose exec -T backend \
  python -m app.cli.stability_check --hours 24 --json
```

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
curl http://127.0.0.1:8000/api/health/summary
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

Vite 会代理 API 与 WebSocket 到本地 FastAPI。

### 测试

```bash
cd backend
uv run pytest

cd ../frontend
npm run build
```

## 数据目录

```text
data/camera.db          SQLite 元数据与运行时配置
recordings/             完成的 MP4
staging/camera-{id}/    FFmpeg 正在写入/待处理 MKV
failed/camera-{id}/     Remux 或健康检查失败的 MKV
logs/camera-{id}.log    单路 FFmpeg 日志
logs/deploy-build.log   部署构建日志
openlist-data/          OpenList 配置与数据库
```

不要把 `.env`、数据库、实际 RTSP 地址、密码、Token 或录像提交到 Git。
