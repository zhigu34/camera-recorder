# 115 云端归档 / OpenList 配置

Camera Recorder 通过 OpenList 的 WebDAV 接口上传最终 MP4。录像进程不会直接操作 115，因此 OpenList/公网异常不会影响 RTSP 录像。

## 1. 启动全部服务

```bash
cp .env.example .env
# 修改 CAMREC_SECRET_KEY 和 OPENLIST_ADMIN_PASSWORD
docker compose up -d --build
```

服务地址：

- Camera Recorder: `http://127.0.0.1:8080`
- FastAPI: `http://127.0.0.1:8000`
- OpenList: `http://127.0.0.1:5244`

OpenList 用户名为 `admin`，密码为 `.env` 中的 `OPENLIST_ADMIN_PASSWORD`。

## 2. 获取 115 Open Token

OpenList 的 `115 Open` 驱动基于 115 官方开放平台 API。

官方说明：<https://doc.oplist.org/guide/drivers/115_open>

最简单的方式：

1. 打开 <https://api.oplist.org>。
2. 选择 `115 网盘验证`。
3. 如果不使用自己的 115 开放平台应用，勾选“使用 OpenList 提供的参数”。
4. Client ID / Secret 留空。
5. 点击获取 Token。
6. 登录 115 并授权。
7. 保存页面返回的 `Access Token` 与 `Refresh Token`。

Token 属于敏感凭证，不要提交到 GitHub、聊天记录或公开日志。

## 3. 在 OpenList 挂载 115

打开 OpenList 管理页面：

```text
http://127.0.0.1:5244
```

依次操作：

1. `存储` → `添加存储`。
2. 驱动选择 `115 Open Platform` / `115 开放平台`。
3. **挂载路径必须填写：`115`**。
4. 根文件夹 ID：如果要使用 115 根目录，填 `0`；也可以填写指定目录的 cid。
5. 填入 Access Token、Refresh Token。
6. 保存。
7. 在 OpenList 文件页面确认 `/115` 可以正常进入、创建目录和上传文件。

Camera Recorder 的 Compose 默认 WebDAV 地址为：

```text
http://openlist:5244/dav/115
```

因此挂载名称不是 `115` 时，需要同步修改 `docker-compose.yml` 中的 `CAMREC_WEBDAV_URL`。

## 4. 开启自动上传

修改 `.env`：

```env
CAMREC_UPLOAD_ENABLED=true
CAMREC_WEBDAV_ROOT=监控录像
CAMREC_UPLOAD_CONCURRENCY=2
CAMREC_UPLOAD_RETRY_MAX=8
CAMREC_LOCAL_RETENTION_HOURS=48
```

然后：

```bash
docker compose up -d
```

完成后的远端结构：

```text
115/
└── 监控录像/
    ├── 监控-大厅/
    │   └── 2026-09-11/
    │       └── 监控-大厅_2026-09-11_12-00-00.mp4
    └── 监控-全景/
        └── 2026-09-11/
            └── 监控-全景_2026-09-11_12-00-00.mp4
```

## 5. 上传策略

上传流程：

```text
RTSP录像
  ↓
完成MKV
  ↓
Remux MP4
  ↓
ffprobe健康检查
  ↓
UploadTask
  ↓
OpenList WebDAV
  ↓
115 Open Platform
```

上传具有以下规则：

- 只上传已经完成并通过基础健康检查的 MP4。
- 当前正在录像的 MKV 不会上传。
- 上传任务写入 SQLite，应用重启后继续。
- 网络/OpenList/115 错误使用指数退避自动重试。
- PUT 完成后通过 WebDAV HEAD 再次验证文件存在和大小。
- 只有 `upload_status=success` 的录像才有资格被本地自动清理。
- 默认本地保留 48 小时；可通过 `CAMREC_LOCAL_RETENTION_HOURS` 修改。
- 上传失败不会停止 FFmpeg Recorder。

## 6. WebDAV 权限

OpenList WebDAV 官方文档：<https://doc.oplist.org/guide/advanced/webdav>

Camera Recorder 默认使用 OpenList `admin` 用户，因此具备管理权限。如果以后改成专用上传用户，需要至少给予：

- WebDAV Read
- WebDAV Management
- 创建目录或上传

WebDAV 标准入口是：

```text
http[s]://host:port/dav/
```

## 7. 排障

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

Web 页面 `115 上传` 中可以看到：

- pending
- uploading
- retry_wait
- success
- failed

失败任务可以点击“重试”。
