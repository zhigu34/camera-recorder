# OpenList / WebDAV 归档配置

Camera Recorder 通过 OpenList 的标准 WebDAV 接口上传最终 MP4。应用只感知 WebDAV，不直接调用具体云盘或对象存储 API，因此 OpenList 后端可以替换为任意受支持且允许写入的存储。

录像链路与上传链路相互独立：OpenList、外网或云端存储异常不会停止 RTSP Recorder。

## 1. 启动服务

首次部署：

```bash
cp .env.example .env
# 修改 CAMREC_SECRET_KEY 和 OPENLIST_ADMIN_PASSWORD
./deploy.sh
```

默认服务地址：

```text
Camera Recorder  http://127.0.0.1:8080
FastAPI          http://127.0.0.1:8000
OpenList         http://127.0.0.1:5244
```

OpenList 初始管理员密码来自 `.env` 的 `OPENLIST_ADMIN_PASSWORD`。

## 2. 在 OpenList 添加存储

登录 OpenList 管理页面后：

1. 进入 `存储` → `添加存储`。
2. 选择实际要使用的驱动。
3. 按该驱动要求完成账号授权、Token 或密钥配置。
4. 设置清晰的挂载路径，例如 `archive`、`aliyun`、`nas`。
5. 保存后确认该挂载目录可以创建目录和上传文件。

具体驱动的授权方式由 OpenList 管理，与 Camera Recorder 无关。

凭证、Token、Cookie、密钥等都属于敏感信息，不要提交到 GitHub、聊天记录或公开日志。

## 3. WebDAV 地址

OpenList 标准 WebDAV 入口：

```text
http[s]://host:port/dav/
```

如果存储挂载名为 `archive`，可以直接把挂载路径放进 URL：

```text
http://openlist:5244/dav/archive
```

然后 Camera Recorder 中的远端根目录填写：

```text
监控录像
```

也可以使用 WebDAV 根入口：

```text
http://openlist:5244/dav
```

远端根目录填写：

```text
archive/监控录像
```

两种方式都有效，选择一种保持一致即可。

## 4. Camera Recorder 上传设置

打开 `系统设置`，配置：

- 自动上传：开启
- 上传并发数：默认 2
- 最大重试次数：默认 8
- 本地保留时间：默认 48 小时
- WebDAV URL：按上节填写
- 远端根目录：例如 `监控录像`
- WebDAV 用户名：OpenList 用户名
- WebDAV 密码：OpenList 登录密码或专用 WebDAV 用户密码

保存后写入 SQLite 并立即生效，无需重启 Docker。WebDAV 密码使用 `CAMREC_SECRET_KEY` 派生密钥加密保存，API 不回显明文。

远端目录结构示例：

```text
监控录像/
├── 门口摄像头/
│   └── 2026-09-12/
│       └── 门口摄像头_2026-09-12_12-00-00.mp4
└── 大厅摄像头/
    └── 2026-09-12/
        └── 大厅摄像头_2026-09-12_12-00-00.mp4
```

## 5. 上传与清理策略

上传链路：

```text
RTSP Recorder
  ↓
完成 MKV
  ↓
Remux MP4
  ↓
ffprobe 健康检查
  ↓
UploadTask
  ↓
OpenList WebDAV
  ↓
实际存储后端
```

规则：

- 只上传已经完成并通过基础健康检查的 MP4。
- 正在写入的 MKV 不会上传。
- 上传任务持久化到 SQLite，应用重启后继续。
- 网络 / OpenList / 存储端错误按指数退避自动重试。
- PUT 后通过 WebDAV 再验证远端文件。
- 只有上传成功的录像才有资格进入本地自动清理。
- 本地保留时间可配置；`-1` 表示永不自动删除。
- 上传失败不影响 Recorder、Remux 或其他摄像头。

## 6. 云端回放

已经上传且本地文件被清理的录像仍会保留元数据，并继续出现在录像时间轴中。

回放优先级：

1. 本地文件存在时直接本地播放。
2. 本地文件不存在但上传成功时，通过 OpenList WebDAV 获取云端流。
3. OpenList 返回可用外部直链时直接重定向浏览器。
4. 不支持直链时由 Camera Recorder 保留 HTTP Range 代理。
5. 浏览器不支持 HEVC 时可从远端源实时生成 H.264 Proxy。

WebDAV 凭据只保留在后端，不发送给浏览器。

## 7. WebDAV 权限

如果不用 OpenList 管理员账号，专用账号至少需要：

- WebDAV 读取
- WebDAV 写入 / 管理
- 创建目录
- 上传文件
- 云端回放所需的文件读取权限

建议为 Camera Recorder 使用权限最小化的专用账号。

## 8. 排障

查看上传状态：

```bash
curl http://127.0.0.1:8000/api/uploads
```

查看上传任务：

```bash
curl http://127.0.0.1:8000/api/uploads/tasks
```

后端日志：

```bash
docker compose logs -f backend
```

OpenList 日志：

```bash
docker compose logs -f openlist
```

Web 页面 `上传管理` 会显示：

```text
pending
uploading
retry_wait
success
failed
```

失败任务可以手动重试，也会按配置进行自动重试。
