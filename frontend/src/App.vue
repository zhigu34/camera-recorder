<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

interface Camera {
  id: number
  name: string
  ip: string
  rtsp_port: number
  username: string
  rtsp_path: string
  enabled: boolean
  auto_record: boolean
  timestamp_mode: string
  video_codec?: string | null
  width?: number | null
  height?: number | null
  fps_num?: number | null
  fps_den?: number | null
  audio_codec?: string | null
  sample_rate?: number | null
  channels?: number | null
  status: string
}

interface Recording {
  id: number
  camera_id: number
  started_at?: string | null
  duration?: number | null
  file_size?: number | null
  health_status: string
  upload_status: string
  mp4_path: string
}

interface UploadTask {
  id: number
  recording_id: number
  provider: string
  remote_path: string
  status: string
  retry_count: number
  last_error?: string | null
  started_at?: string | null
  completed_at?: string | null
  next_retry_at?: string | null
}

interface UploadStatus {
  enabled: boolean
  configured: boolean
  active: boolean
  provider: string
  webdav_url: string
  webdav_root: string
  local_retention_hours: number
  counts: Record<string, number>
}

interface EventItem {
  id: number
  camera_id?: number | null
  recording_id?: number | null
  level: string
  category: string
  code: string
  message: string
  created_at: string
}

interface StorageStatus {
  path: string
  total_bytes: number
  used_bytes: number
  free_bytes: number
  used_percent: number
  state: 'healthy' | 'warning' | 'critical'
  warning_percent: number
  critical_percent: number
}

interface EmailSettings {
  email_enabled: boolean
  offline_alert_seconds: number
  recovery_stable_seconds: number
  notify_recovery: boolean
  smtp_host: string
  smtp_port: number
  smtp_username: string
  smtp_password_set: boolean
  smtp_from: string
  smtp_to: string
  smtp_use_ssl: boolean
  smtp_starttls: boolean
  smtp_timeout_seconds: number
  configured: boolean
}

interface SystemStatus {
  app: string
  segment_duration_seconds: number
  ffmpeg: {
    ffmpeg_available: boolean
    ffprobe_available: boolean
    setts_available: boolean
    ffmpeg_version?: string | null
  }
  recorders: Array<{ camera_id: number; state: string; pid?: number | null }>
  upload?: {
    enabled: boolean
    configured: boolean
    active: boolean
    provider: string
  }
  storage?: StorageStatus
}

const page = ref('dashboard')
const loading = ref(false)
const cameras = ref<Camera[]>([])
const recordings = ref<Recording[]>([])
const uploads = ref<UploadTask[]>([])
const events = ref<EventItem[]>([])
const uploadStatus = ref<UploadStatus | null>(null)
const status = ref<SystemStatus | null>(null)
const dialogVisible = ref(false)
const saving = ref(false)
const savingEmail = ref(false)
const testingEmail = ref(false)

const form = reactive({
  name: '',
  ip: '',
  rtsp_port: 554,
  username: 'admin',
  password: '',
  rtsp_path: '/ch1/main',
  timestamp_mode: 'reconstruct',
  enabled: true,
  auto_record: false,
})

const emailSettings = reactive({
  email_enabled: false,
  offline_alert_seconds: 60,
  recovery_stable_seconds: 10,
  notify_recovery: true,
  smtp_host: '',
  smtp_port: 587,
  smtp_username: '',
  smtp_password: '',
  smtp_password_set: false,
  clear_smtp_password: false,
  smtp_from: '',
  smtp_to: '',
  smtp_use_ssl: false,
  smtp_starttls: true,
  smtp_timeout_seconds: 15,
  configured: false,
})

const recordingCount = computed(() =>
  cameras.value.filter((camera) => runtimeState(camera.id) === 'RECORDING').length,
)

const pendingUploadCount = computed(() =>
  (uploadStatus.value?.counts.pending || 0) +
  (uploadStatus.value?.counts.uploading || 0) +
  (uploadStatus.value?.counts.retry_wait || 0),
)

const pageTitle = computed(() => {
  if (page.value === 'cameras') return '摄像头管理'
  if (page.value === 'recordings') return '录像文件'
  if (page.value === 'uploads') return '115 上传'
  if (page.value === 'events') return '事件中心'
  if (page.value === 'alerts') return '告警设置'
  return '仪表盘'
})

function runtimeState(cameraId: number) {
  return status.value?.recorders.find((item) => item.camera_id === cameraId)?.state || 'STOPPED'
}

function cameraName(cameraId?: number | null) {
  if (!cameraId) return '-'
  return cameras.value.find((camera) => camera.id === cameraId)?.name || `#${cameraId}`
}

function fps(camera: Camera) {
  if (!camera.fps_num || !camera.fps_den) return '-'
  const value = camera.fps_num / camera.fps_den
  return Number.isInteger(value) ? `${value}` : value.toFixed(2)
}

function sizeText(bytes?: number | null) {
  if (!bytes) return '-'
  if (bytes >= 1024 ** 4) return `${(bytes / 1024 ** 4).toFixed(2)} TB`
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

function uploadTagType(value: string) {
  if (value === 'success') return 'success'
  if (value === 'failed') return 'danger'
  if (value === 'uploading') return 'primary'
  if (value === 'retry_wait') return 'warning'
  return 'info'
}

function eventTagType(value: string) {
  if (value === 'critical' || value === 'error') return 'danger'
  if (value === 'warning') return 'warning'
  return 'info'
}

function storageTagType() {
  if (status.value?.storage?.state === 'critical') return 'danger'
  if (status.value?.storage?.state === 'warning') return 'warning'
  return 'success'
}

function applyEmailSettings(data: EmailSettings) {
  Object.assign(emailSettings, data, {
    smtp_password: '',
    clear_smtp_password: false,
  })
}

function enableSmtpSsl(value: boolean) {
  if (value) emailSettings.smtp_starttls = false
}

function enableStarttls(value: boolean) {
  if (value) emailSettings.smtp_use_ssl = false
}

async function loadAll() {
  loading.value = true
  try {
    const [systemRes, cameraRes, recordingRes, uploadStatusRes, uploadTasksRes, eventRes, emailRes] = await Promise.all([
      axios.get<SystemStatus>('/api/system/status'),
      axios.get<Camera[]>('/api/cameras'),
      axios.get<Recording[]>('/api/recordings?limit=100'),
      axios.get<UploadStatus>('/api/uploads'),
      axios.get<UploadTask[]>('/api/uploads/tasks?limit=100'),
      axios.get<EventItem[]>('/api/events?limit=200'),
      axios.get<EmailSettings>('/api/notifications/email'),
    ])
    status.value = systemRes.data
    cameras.value = cameraRes.data
    recordings.value = recordingRes.data
    uploadStatus.value = uploadStatusRes.data
    uploads.value = uploadTasksRes.data
    events.value = eventRes.data
    applyEmailSettings(emailRes.data)
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function createCamera() {
  saving.value = true
  try {
    await axios.post('/api/cameras', form)
    ElMessage.success('摄像头已添加')
    dialogVisible.value = false
    Object.assign(form, {
      name: '', ip: '', rtsp_port: 554, username: 'admin', password: '',
      rtsp_path: '/ch1/main', timestamp_mode: 'reconstruct', enabled: true, auto_record: false,
    })
    await loadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '添加失败')
  } finally {
    saving.value = false
  }
}

async function probe(camera: Camera) {
  try {
    const { data } = await axios.post(`/api/cameras/${camera.id}/probe`)
    const detectedFps = typeof data.fps === 'number' ? data.fps.toFixed(2) : '-'
    ElMessage.success(`${camera.name}: ${data.video_codec || '-'} ${data.width || '-'}×${data.height || '-'} / ${detectedFps}fps`)
    await loadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : 'Probe 失败')
  }
}

async function start(camera: Camera) {
  try {
    await axios.post(`/api/cameras/${camera.id}/start`)
    ElMessage.success(`${camera.name} 已开始录像`)
    await loadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '启动失败')
  }
}

async function stop(camera: Camera) {
  try {
    await axios.post(`/api/cameras/${camera.id}/stop`)
    ElMessage.success(`${camera.name} 已停止`)
    await loadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '停止失败')
  }
}

async function remove(camera: Camera) {
  await ElMessageBox.confirm(`确认删除 ${camera.name}？`, '删除摄像头', { type: 'warning' })
  await axios.delete(`/api/cameras/${camera.id}`)
  ElMessage.success('已删除')
  await loadAll()
}

async function startAll() {
  await axios.post('/api/recorder/start-all')
  ElMessage.success('已启动可录像摄像头')
  await loadAll()
}

async function stopAll() {
  await axios.post('/api/recorder/stop-all')
  ElMessage.success('已停止全部录像')
  await loadAll()
}

async function retryUpload(task: UploadTask) {
  try {
    await axios.post(`/api/uploads/tasks/${task.id}/retry`)
    ElMessage.success(`上传任务 #${task.id} 已重新排队`)
    await loadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '重试失败')
  }
}

async function scanUploads() {
  try {
    await axios.post('/api/uploads/scan')
    ElMessage.success('已触发上传扫描')
    await loadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '上传未启用')
  }
}

async function saveEmailSettings() {
  savingEmail.value = true
  try {
    const payload = {
      email_enabled: emailSettings.email_enabled,
      offline_alert_seconds: emailSettings.offline_alert_seconds,
      recovery_stable_seconds: emailSettings.recovery_stable_seconds,
      notify_recovery: emailSettings.notify_recovery,
      smtp_host: emailSettings.smtp_host,
      smtp_port: emailSettings.smtp_port,
      smtp_username: emailSettings.smtp_username,
      smtp_password: emailSettings.smtp_password || null,
      clear_smtp_password: emailSettings.clear_smtp_password,
      smtp_from: emailSettings.smtp_from,
      smtp_to: emailSettings.smtp_to,
      smtp_use_ssl: emailSettings.smtp_use_ssl,
      smtp_starttls: emailSettings.smtp_starttls,
      smtp_timeout_seconds: emailSettings.smtp_timeout_seconds,
    }
    const { data } = await axios.put<EmailSettings>('/api/notifications/email', payload)
    applyEmailSettings(data)
    ElMessage.success('邮件告警配置已保存，立即生效')
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '保存失败')
  } finally {
    savingEmail.value = false
  }
}

async function testEmail() {
  testingEmail.value = true
  try {
    await axios.post('/api/notifications/email/test')
    ElMessage.success('测试邮件已发送')
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '测试邮件发送失败')
  } finally {
    testingEmail.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="210px" class="sidebar">
      <div class="brand">Camera Recorder</div>
      <el-menu :default-active="page" @select="page = $event">
        <el-menu-item index="dashboard">仪表盘</el-menu-item>
        <el-menu-item index="cameras">摄像头</el-menu-item>
        <el-menu-item index="recordings">录像文件</el-menu-item>
        <el-menu-item index="uploads">115 上传</el-menu-item>
        <el-menu-item index="events">事件中心</el-menu-item>
        <el-menu-item index="alerts">告警设置</el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div>
          <strong>{{ pageTitle }}</strong>
          <span class="subtitle">RTSP 长连接 · H.265/AAC 原码流</span>
        </div>
        <div class="header-actions">
          <el-button @click="loadAll">刷新</el-button>
          <el-button type="success" @click="startAll">全部开始</el-button>
          <el-button type="danger" plain @click="stopAll">全部停止</el-button>
        </div>
      </el-header>

      <el-main v-loading="loading">
        <template v-if="page === 'dashboard'">
          <el-row :gutter="16">
            <el-col :span="4"><el-card><div class="metric">{{ cameras.length }}</div><div class="muted">摄像头</div></el-card></el-col>
            <el-col :span="4"><el-card><div class="metric">{{ recordingCount }}</div><div class="muted">录像中</div></el-card></el-col>
            <el-col :span="4"><el-card><div class="metric">{{ recordings.length }}</div><div class="muted">最近录像</div></el-card></el-col>
            <el-col :span="4"><el-card><div class="metric">{{ pendingUploadCount }}</div><div class="muted">上传队列</div></el-card></el-col>
            <el-col :span="4">
              <el-card>
                <div class="metric">{{ status?.storage?.used_percent ?? '-' }}<span class="metric-unit">%</span></div>
                <div class="muted">磁盘使用</div>
                <el-tag class="top-gap" size="small" :type="storageTagType()">{{ status?.storage?.state || '-' }}</el-tag>
              </el-card>
            </el-col>
            <el-col :span="4">
              <el-card>
                <el-tag :type="status?.ffmpeg.setts_available ? 'success' : 'danger'">
                  {{ status?.ffmpeg.setts_available ? 'setts 可用' : 'setts 不可用' }}
                </el-tag>
                <div class="muted top-gap">切片 {{ status?.segment_duration_seconds || '-' }} 秒</div>
                <div class="muted top-gap">剩余 {{ sizeText(status?.storage?.free_bytes) }}</div>
              </el-card>
            </el-col>
          </el-row>

          <el-card class="section-card">
            <template #header>摄像头状态</template>
            <el-table :data="cameras" empty-text="还没有摄像头">
              <el-table-column prop="name" label="名称" min-width="150" />
              <el-table-column prop="ip" label="IP" width="150" />
              <el-table-column label="参数" min-width="220">
                <template #default="{ row }">
                  {{ row.video_codec || '-' }} · {{ row.width || '-' }}×{{ row.height || '-' }} · {{ fps(row) }}fps
                </template>
              </el-table-column>
              <el-table-column label="运行" width="120">
                <template #default="{ row }">
                  <el-tag :type="runtimeState(row.id) === 'RECORDING' ? 'success' : 'info'">{{ runtimeState(row.id) }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </template>

        <template v-else-if="page === 'cameras'">
          <div class="toolbar"><el-button type="primary" @click="dialogVisible = true">添加摄像头</el-button></div>
          <el-card>
            <el-table :data="cameras" empty-text="点击“添加摄像头”开始">
              <el-table-column prop="name" label="名称" min-width="140" />
              <el-table-column prop="ip" label="IP" width="150" />
              <el-table-column prop="rtsp_path" label="RTSP Path" min-width="130" />
              <el-table-column label="视频" min-width="190">
                <template #default="{ row }">{{ row.video_codec || '-' }} {{ row.width || '-' }}×{{ row.height || '-' }} / {{ fps(row) }}fps</template>
              </el-table-column>
              <el-table-column label="音频" width="150">
                <template #default="{ row }">{{ row.audio_codec || '-' }} {{ row.sample_rate ? `${row.sample_rate}Hz` : '' }}</template>
              </el-table-column>
              <el-table-column label="模式" width="120"><template #default="{ row }"><el-tag>{{ row.timestamp_mode }}</el-tag></template></el-table-column>
              <el-table-column label="操作" width="300" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="probe(row)">Probe</el-button>
                  <el-button v-if="runtimeState(row.id) !== 'RECORDING'" size="small" type="success" @click="start(row)">开始</el-button>
                  <el-button v-else size="small" type="warning" @click="stop(row)">停止</el-button>
                  <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </template>

        <template v-else-if="page === 'recordings'">
          <el-card>
            <el-table :data="recordings" empty-text="暂无已完成录像">
              <el-table-column prop="camera_id" label="Camera ID" width="100" />
              <el-table-column prop="started_at" label="开始时间" min-width="190" />
              <el-table-column label="时长" width="100"><template #default="{ row }">{{ row.duration ? `${row.duration.toFixed(1)}s` : '-' }}</template></el-table-column>
              <el-table-column label="大小" width="110"><template #default="{ row }">{{ sizeText(row.file_size) }}</template></el-table-column>
              <el-table-column label="健康" width="110"><template #default="{ row }"><el-tag :type="row.health_status === 'healthy' ? 'success' : 'warning'">{{ row.health_status }}</el-tag></template></el-table-column>
              <el-table-column label="上传" width="120"><template #default="{ row }"><el-tag :type="uploadTagType(row.upload_status)">{{ row.upload_status }}</el-tag></template></el-table-column>
              <el-table-column prop="mp4_path" label="文件" min-width="320" show-overflow-tooltip />
            </el-table>
          </el-card>
        </template>

        <template v-else-if="page === 'uploads'">
          <el-card class="upload-summary">
            <div class="upload-head">
              <div>
                <el-tag :type="uploadStatus?.active ? 'success' : 'warning'">
                  {{ uploadStatus?.active ? '自动上传运行中' : '自动上传未启用' }}
                </el-tag>
                <span class="muted upload-note">
                  OpenList {{ uploadStatus?.configured ? '已配置' : '未配置' }} · 本地保留 {{ uploadStatus?.local_retention_hours ?? '-' }} 小时
                </span>
              </div>
              <el-button type="primary" plain @click="scanUploads">立即扫描</el-button>
            </div>
            <div class="muted top-gap">远端：{{ uploadStatus?.webdav_url || '-' }}/{{ uploadStatus?.webdav_root || '' }}</div>
          </el-card>

          <el-card class="section-card">
            <el-table :data="uploads" empty-text="暂无上传任务">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column prop="recording_id" label="录像ID" width="90" />
              <el-table-column label="状态" width="120">
                <template #default="{ row }"><el-tag :type="uploadTagType(row.status)">{{ row.status }}</el-tag></template>
              </el-table-column>
              <el-table-column prop="retry_count" label="重试" width="80" />
              <el-table-column prop="remote_path" label="115路径" min-width="320" show-overflow-tooltip />
              <el-table-column prop="last_error" label="最近错误" min-width="240" show-overflow-tooltip />
              <el-table-column label="操作" width="100" fixed="right">
                <template #default="{ row }">
                  <el-button v-if="row.status === 'failed' || row.status === 'retry_wait'" size="small" @click="retryUpload(row)">重试</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </template>

        <template v-else-if="page === 'events'">
          <el-card>
            <el-table :data="events" empty-text="暂无事件">
              <el-table-column prop="created_at" label="时间" min-width="190" />
              <el-table-column label="级别" width="100">
                <template #default="{ row }"><el-tag :type="eventTagType(row.level)">{{ row.level }}</el-tag></template>
              </el-table-column>
              <el-table-column label="摄像头" min-width="140">
                <template #default="{ row }">{{ cameraName(row.camera_id) }}</template>
              </el-table-column>
              <el-table-column prop="category" label="分类" width="110" />
              <el-table-column prop="code" label="代码" min-width="170" />
              <el-table-column prop="message" label="信息" min-width="360" show-overflow-tooltip />
            </el-table>
          </el-card>
        </template>

        <template v-else>
          <el-card class="alert-card">
            <template #header>
              <div class="card-header">
                <span>摄像头掉线邮件告警</span>
                <el-tag :type="emailSettings.email_enabled && emailSettings.configured ? 'success' : 'info'">
                  {{ emailSettings.email_enabled && emailSettings.configured ? '已启用' : '未启用' }}
                </el-tag>
              </div>
            </template>

            <el-form label-width="150px" class="settings-form">
              <el-form-item label="邮件告警开关">
                <el-switch v-model="emailSettings.email_enabled" />
              </el-form-item>
              <el-form-item label="掉线多久后告警">
                <el-input-number v-model="emailSettings.offline_alert_seconds" :min="0" :max="86400" :step="10" />
                <span class="form-hint">秒；默认 60 秒，短暂网络抖动不会立即发邮件</span>
              </el-form-item>
              <el-form-item label="恢复稳定时间">
                <el-input-number v-model="emailSettings.recovery_stable_seconds" :min="0" :max="3600" :step="5" />
                <span class="form-hint">秒；连续稳定后才判定恢复</span>
              </el-form-item>
              <el-form-item label="恢复邮件">
                <el-switch v-model="emailSettings.notify_recovery" />
              </el-form-item>

              <el-divider content-position="left">SMTP</el-divider>

              <el-form-item label="SMTP服务器">
                <el-input v-model="emailSettings.smtp_host" placeholder="smtp.example.com" />
              </el-form-item>
              <el-form-item label="SMTP端口">
                <el-input-number v-model="emailSettings.smtp_port" :min="1" :max="65535" />
              </el-form-item>
              <el-form-item label="SMTP用户名">
                <el-input v-model="emailSettings.smtp_username" autocomplete="off" />
              </el-form-item>
              <el-form-item label="SMTP密码">
                <el-input
                  v-model="emailSettings.smtp_password"
                  type="password"
                  show-password
                  autocomplete="new-password"
                  :placeholder="emailSettings.smtp_password_set ? '已保存；留空保持不变' : '请输入SMTP密码/授权码'"
                />
                <div class="password-row">
                  <el-tag v-if="emailSettings.smtp_password_set" size="small" type="success">已加密保存</el-tag>
                  <el-checkbox v-if="emailSettings.smtp_password_set" v-model="emailSettings.clear_smtp_password">清除已保存密码</el-checkbox>
                </div>
              </el-form-item>
              <el-form-item label="发件人">
                <el-input v-model="emailSettings.smtp_from" placeholder="camera@example.com" />
              </el-form-item>
              <el-form-item label="收件人">
                <el-input v-model="emailSettings.smtp_to" placeholder="ops@example.com,admin@example.com" />
                <span class="form-hint">多个邮箱使用英文逗号分隔</span>
              </el-form-item>
              <el-form-item label="SSL">
                <el-switch v-model="emailSettings.smtp_use_ssl" @change="enableSmtpSsl" />
                <span class="form-hint">常见端口 465</span>
              </el-form-item>
              <el-form-item label="STARTTLS">
                <el-switch v-model="emailSettings.smtp_starttls" @change="enableStarttls" />
                <span class="form-hint">常见端口 587；与 SSL 二选一</span>
              </el-form-item>
              <el-form-item label="连接超时">
                <el-input-number v-model="emailSettings.smtp_timeout_seconds" :min="1" :max="120" />
                <span class="form-hint">秒</span>
              </el-form-item>

              <el-form-item>
                <el-button type="primary" :loading="savingEmail" @click="saveEmailSettings">保存配置</el-button>
                <el-button :loading="testingEmail" :disabled="!emailSettings.email_enabled" @click="testEmail">发送测试邮件</el-button>
              </el-form-item>
            </el-form>
          </el-card>
        </template>
      </el-main>
    </el-container>
  </el-container>

  <el-dialog v-model="dialogVisible" title="添加 RTSP 摄像头" width="520px">
    <el-form label-width="110px">
      <el-form-item label="名称"><el-input v-model="form.name" placeholder="监控-大厅" /></el-form-item>
      <el-form-item label="IP"><el-input v-model="form.ip" placeholder="192.168.1.100" /></el-form-item>
      <el-form-item label="RTSP端口"><el-input-number v-model="form.rtsp_port" :min="1" :max="65535" /></el-form-item>
      <el-form-item label="用户名"><el-input v-model="form.username" /></el-form-item>
      <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password /></el-form-item>
      <el-form-item label="RTSP路径"><el-input v-model="form.rtsp_path" placeholder="/ch1/main" /></el-form-item>
      <el-form-item label="时间戳模式">
        <el-select v-model="form.timestamp_mode" style="width: 100%">
          <el-option label="Reconstruct（推荐）" value="reconstruct" />
          <el-option label="Native" value="native" />
          <el-option label="Wallclock" value="wallclock" />
        </el-select>
      </el-form-item>
      <el-form-item label="自动录像"><el-switch v-model="form.auto_record" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="createCamera">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
:global(body) { margin: 0; background: #f5f7fa; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.app-shell { min-height: 100vh; }
.sidebar { background: #fff; border-right: 1px solid #ebeef5; }
.brand { height: 60px; display: flex; align-items: center; padding: 0 20px; font-weight: 700; border-bottom: 1px solid #ebeef5; }
.header { height: 60px; background: #fff; border-bottom: 1px solid #ebeef5; display: flex; align-items: center; justify-content: space-between; }
.subtitle { color: #909399; font-size: 12px; margin-left: 12px; }
.header-actions { display: flex; gap: 8px; }
.metric { font-size: 30px; font-weight: 700; }
.metric-unit { font-size: 15px; margin-left: 2px; color: #606266; }
.muted { color: #909399; font-size: 13px; }
.top-gap { margin-top: 10px; }
.section-card { margin-top: 16px; }
.toolbar { display: flex; justify-content: flex-end; margin-bottom: 12px; }
.upload-head, .card-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.upload-note { margin-left: 12px; }
.alert-card { max-width: 900px; }
.settings-form { max-width: 760px; }
.form-hint { margin-left: 12px; color: #909399; font-size: 12px; }
.password-row { display: flex; align-items: center; gap: 12px; margin-top: 8px; width: 100%; }
</style>
