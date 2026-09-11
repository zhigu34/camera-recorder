# 本地开发

## 前置条件

- macOS / Linux
- Python 3.12+
- `uv`
- Node.js 20+
- FFmpeg，且 `ffmpeg -h bsf=setts` 中应支持 `prescale`

## 后端

```bash
cd backend
uv sync --dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

验证：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/system/status
```

## 前端

```bash
cd frontend
npm install
npm run dev
```

打开：`http://127.0.0.1:5173`

Vite 已将 `/api`、`/health` 和 `/ws` 代理到本地 FastAPI。

## 环境变量

```bash
cp .env.example .env
```

不要将 `.env`、数据库、密钥、实际 RTSP 地址或摄像头密码提交到 Git。

## 当前 V0.1 入口

启动后首页会请求 `/api/system/status`，检查：

- FFmpeg 是否存在
- ffprobe 是否存在
- `setts` 是否支持 `prescale`
- 当前默认切片时长

后续开发按 `docs/ROADMAP.md` 中 V0.1 顺序进行。
