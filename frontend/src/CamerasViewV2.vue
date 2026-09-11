<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Connection,
  Delete,
  Edit,
  Plus,
  Refresh,
  Search,
  VideoCamera,
  VideoPause,
  VideoPlay,
} from '@element-plus/icons-vue'

interface Camera {
  id: number
  name: string
  ip: string
  rtsp_port: number
  username: string
  rtsp_path: string
  sub_rtsp_path?: string | null
  enabled: boolean
  auto_record: boolean
  recording_schedule_enabled: boolean
  timestamp_mode: 'native' | 'reconstruct' | 'wallclock'
  password_set?: boolean
  video_codec?: string | null
  width?: number | null
  height?: number | null
  fps_num?: number | null
  fps_den?: number | null
  audio_codec?: string | null
  status: string
  last_probe_at?: string | null
  last_online_at?: string | null
}

interface RecorderRuntime {
  camera_id: number
  state: string
  pid?: number | null
  last_error?: string | null
}

interface SystemStatus {
  recorders?: RecorderRuntime[]
}

type FilterKey = 'all' | 'online' | 'issue' | 'recording'
type CameraHealth = 'online' | 'offline' | 'unknown' | 'disabled'

const emit = defineEmits<{
  (event: 'open-batch'): void
  (event: 'open-preview'): void
}>()

const cameras = ref<Camera[]>([])
const systemStatus = ref<SystemStatus | null>(null)
const loading = ref(false)
const query = ref('')
const filter = ref<FilterKey>('all')
const drawerVisible = ref(false)
const selectedCamera = ref<Camera | null>(null)
const previewFailed = ref(false)
const previewNonce = ref(Date.now())
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const actionCameraId = ref<number | null>(null)
let refreshTimer: number | null = null

const form = reactive({
  name: '',
  ip: '',
  rtsp_port: 554,
  username: 'admin',
  password: '',
  rtsp_path: '/ch1/main',
  sub_rtsp_path: '',
  timestamp_mode: 'reconstruct' as Camera['timestamp_mode'],
  enabled: true,
  auto_record: false,
})

function apiError(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    return error.message || fallback
  }
  return fallback
}

function runtime(cameraId: number) {
  return systemStatus.value?.recorders?.find((item) => item.camera_id === cameraId)
}

function runtimeState(cameraId: number) {
  return runtime(cameraId)?.state || 'STOPPED'
}

function isRecording(cameraId: number) {
  return runtimeState(cameraId) === 'RECORDING'
}

function latestProbeSucceeded(camera: Camera): boolean | null {
  if (!camera.last_probe_at) return null
  const probeAt = new Date(camera.last_probe_at).getTime()
  if (Number.isNaN(probeAt)) return null
  if (!camera.last_online_at) return false
  const onlineAt = new Date(camera.last_online_at).getTime()
  if (Number.isNaN(onlineAt)) return false
  return onlineAt >= probeAt
}

function health(camera: Camera): CameraHealth {
  if (!camera.enabled) return 'disabled'
  const state = runtimeState(camera.id)
  if (['RECORDING', 'STARTING', 'RECONNECTING'].includes(state)) return 'online'

  const probeSucceeded = latestProbeSucceeded(camera)
  if (probeSucceeded === true) return 'online'
  if (probeSucceeded === false) return 'offline'

  // Legacy fallback for cameras that pre-date probe timestamps. camera.status is
  // also used by recording scheduling, so values such as "scheduled" must not
  // be interpreted as a connectivity failure.
  if (camera.status === 'probe_failed' || camera.status === 'offline') return 'offline'
  if (camera.status === 'online' || camera.status === 'recording') return 'online'
  return 'unknown'
}

function healthLabel(camera: Camera) {
  const value = health(camera)
  if (value === 'online') return '在线'
  if (value === 'offline') return '离线'
  if (value === 'disabled') return '已禁用'
  return '未检测'
}

function runtimeLabel(camera: Camera) {
  const state = runtimeState(camera.id)
  if (state === 'RECORDING') return '录像中'
  if (state === 'STARTING') return '启动中'
  if (state === 'RECONNECTING') return '重连中'
  return '未录像'
}

function fps(camera: Camera) {
  if (!camera.fps_num || !camera.fps_den) return null
  const value = camera.fps_num / camera.fps_den
  return Number.isInteger(value) ? `${value}` : value.toFixed(2)
}

function videoSummary(camera: Camera) {
  const parts: string[] = []
  if (camera.video_codec) parts.push(camera.video_codec.toUpperCase())
  if (camera.width && camera.height) parts.push(`${camera.width}×${camera.height}`)
  const frameRate = fps(camera)
  if (frameRate) parts.push(`${frameRate} FPS`)
  return parts.length ? parts.join(' · ') : '尚未获取视频参数'
}

function scheduleLabel(camera: Camera) {
  if (!camera.auto_record) return '手动录像'
  if (camera.recording_schedule_enabled) return '按计划录像'
  return '自动录像'
}

function formatTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

const summary = computed(() => ({
  total: cameras.value.length,
  online: cameras.value.filter((camera) => health(camera) === 'online').length,
  issue: cameras.value.filter((camera) => ['offline', 'unknown'].includes(health(camera))).length,
  recording: cameras.value.filter((camera) => isRecording(camera.id)).length,
}))

const filteredCameras = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return cameras.value.filter((camera) => {
    const matched = !needle || [camera.name, camera.ip, camera.rtsp_path, camera.sub_rtsp_path || '']
      .some((value) => value.toLowerCase().includes(needle))
    if (!matched) return false
    if (filter.value === 'online') return health(camera) === 'online'
    if (filter.value === 'issue') return ['offline', 'unknown'].includes(health(camera))
    if (filter.value === 'recording') return isRecording(camera.id)
    return true
  })
})

const previewSrc = computed(() => selectedCamera.value
  ? `/api/cameras/${selectedCamera.value.id}/preview.mjpeg?stream=auto&fps=6&width=960&_=${previewNonce.value}`
  : '')

async function loadData(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const [cameraRes, statusRes] = await Promise.all([
      axios.get<Camera[]>('/api/cameras'),
      axios.get<SystemStatus>('/api/system/status'),
    ])
    cameras.value = cameraRes.data
    systemStatus.value = statusRes.data
    if (selectedCamera.value) {
      selectedCamera.value = cameras.value.find((item) => item.id === selectedCamera.value?.id) || null
      if (!selectedCamera.value) drawerVisible.value = false
    }
  } catch (error) {
    if (showLoading) ElMessage.error(apiError(error, '摄像头数据加载失败'))
  } finally {
    if (showLoading) loading.value = false
  }
}

function resetForm() {
  editingId.value = null
  Object.assign(form, {
    name: '',
    ip: '',
    rtsp_port: 554,
    username: 'admin',
    password: '',
    rtsp_path: '/ch1/main',
    sub_rtsp_path: '',
    timestamp_mode: 'reconstruct',
    enabled: true,
    auto_record: false,
  })
}

function openCreate() {
  resetForm()
  dialogVisible.value = true
}

function openEdit(camera: Camera) {
  editingId.value = camera.id
  Object.assign(form, {
    name: camera.name,
    ip: camera.ip,
    rtsp_port: camera.rtsp_port,
    username: camera.username,
    password: '',
    rtsp_path: camera.rtsp_path,
    sub_rtsp_path: camera.sub_rtsp_path || '',
    timestamp_mode: camera.timestamp_mode,
    enabled: camera.enabled,
    auto_record: camera.auto_record,
  })
  dialogVisible.value = true
}

async function saveCamera() {
  if (!form.name.trim() || !form.ip.trim() || !form.rtsp_path.trim()) {
    ElMessage.warning('请填写摄像头名称、IP 和主码流路径')
    return
  }
  if (editingId.value === null && !form.password) {
    ElMessage.warning('新增摄像头时必须填写密码')
    return
  }

  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      ip: form.ip.trim(),
      rtsp_port: form.rtsp_port,
      username: form.username.trim(),
      rtsp_path: form.rtsp_path.trim(),
      sub_rtsp_path: form.sub_rtsp_path.trim() || null,
      timestamp_mode: form.timestamp_mode,
      enabled: form.enabled,
      auto_record: form.auto_record,
    }
    if (form.password) payload.password = form.password

    if (editingId.value === null) {
      await axios.post('/api/cameras', payload)
      ElMessage.success('摄像头已添加')
    } else {
      await axios.put(`/api/cameras/${editingId.value}`, payload)
      ElMessage.success('摄像头配置已保存')
    }
    dialogVisible.value = false
    resetForm()
    await loadData()
  } catch (error) {
    ElMessage.error(apiError(error, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function runAction(camera: Camera, action: 'probe' | 'start' | 'stop') {
  actionCameraId.value = camera.id
  try {
    if (action === 'probe') {
      const { data } = await axios.post(`/api/cameras/${camera.id}/probe`)
      const detectedFps = typeof data.fps === 'number' ? `${data.fps.toFixed(2)} FPS` : 'FPS -'
      ElMessage.success(`${camera.name}：${data.video_codec || '-'} ${data.width || '-'}×${data.height || '-'} · ${detectedFps}`)
    } else if (action === 'start') {
      await axios.post(`/api/cameras/${camera.id}/start`)
      ElMessage.success(`${camera.name} 已开始录像`)
    } else {
      await axios.post(`/api/cameras/${camera.id}/stop`)
      ElMessage.success(`${camera.name} 已停止录像`)
    }
    await loadData(false)
  } catch (error) {
    ElMessage.error(apiError(error, action === 'probe' ? '连接检测失败' : '操作失败'))
  } finally {
    actionCameraId.value = null
  }
}

async function removeCamera(camera: Camera) {
  try {
    await ElMessageBox.confirm(
      `确认删除“${camera.name}”？正在录像时会先停止录像。`,
      '删除摄像头',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await axios.delete(`/api/cameras/${camera.id}`)
    ElMessage.success('摄像头已删除')
    if (selectedCamera.value?.id === camera.id) drawerVisible.value = false
    await loadData()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiError(error, '删除失败'))
  }
}

function openDetails(camera: Camera) {
  selectedCamera.value = camera
  previewFailed.value = false
  previewNonce.value = Date.now()
  drawerVisible.value = true
}

function refreshPreview() {
  previewFailed.value = false
  previewNonce.value = Date.now()
}

function closeDrawer() {
  selectedCamera.value = null
  previewFailed.value = false
}

onMounted(() => {
  void loadData()
  refreshTimer = window.setInterval(() => void loadData(false), 10000)
})

onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
})
</script>

<template>
  <section class="camera-page" v-loading="loading">
    <div class="page-heading">
      <div>
        <h1>摄像头管理</h1>
        <p>集中查看接入状态、视频参数与录像运行状态。</p>
      </div>
      <div class="heading-actions">
        <el-button :icon="Refresh" @click="loadData()">刷新</el-button>
        <el-button @click="emit('open-batch')">批量添加</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">添加摄像头</el-button>
      </div>
    </div>

    <div class="summary-grid">
      <button class="summary-card" :class="{ active: filter === 'all' }" @click="filter = 'all'">
        <span>全部摄像头</span><strong>{{ summary.total }}</strong><small>已配置设备</small>
      </button>
      <button class="summary-card online" :class="{ active: filter === 'online' }" @click="filter = 'online'">
        <span>在线</span><strong>{{ summary.online }}</strong><small>最近连接正常</small>
      </button>
      <button class="summary-card issue" :class="{ active: filter === 'issue' }" @click="filter = 'issue'">
        <span>异常 / 未检测</span><strong>{{ summary.issue }}</strong><small>建议执行连接检测</small>
      </button>
      <button class="summary-card recording" :class="{ active: filter === 'recording' }" @click="filter = 'recording'">
        <span>录像中</span><strong>{{ summary.recording }}</strong><small>当前录像进程</small>
      </button>
    </div>

    <div class="toolbar">
      <el-input v-model="query" clearable :prefix-icon="Search" placeholder="搜索名称、IP 或 RTSP 路径" class="search-box" />
      <span class="result-count">显示 {{ filteredCameras.length }} / {{ cameras.length }} 台</span>
    </div>

    <div v-if="filteredCameras.length" class="camera-list">
      <article v-for="camera in filteredCameras" :key="camera.id" class="camera-card" @dblclick="openDetails(camera)">
        <div class="camera-main">
          <div class="camera-icon" :class="health(camera)"><VideoCamera /></div>
          <div class="camera-copy">
            <div class="camera-name-row">
              <strong>{{ camera.name }}</strong>
              <span class="health-badge" :class="health(camera)"><i></i>{{ healthLabel(camera) }}</span>
              <span class="record-badge" :class="{ active: isRecording(camera.id) }"><i></i>{{ runtimeLabel(camera) }}</span>
            </div>
            <div class="camera-address">{{ camera.ip }}:{{ camera.rtsp_port }} · {{ camera.rtsp_path }}</div>
            <div class="camera-video">{{ videoSummary(camera) }}</div>
          </div>
        </div>

        <div class="camera-signals">
          <div><span>录像策略</span><b>{{ scheduleLabel(camera) }}</b></div>
          <div><span>子码流</span><b>{{ camera.sub_rtsp_path ? '已配置' : '未配置' }}</b></div>
          <div><span>时间戳</span><b>{{ camera.timestamp_mode }}</b></div>
        </div>

        <div class="camera-actions" @dblclick.stop>
          <el-button size="small" @click="openDetails(camera)">详情 / 预览</el-button>
          <el-button
            size="small"
            :icon="Connection"
            :loading="actionCameraId === camera.id"
            @click="runAction(camera, 'probe')"
          >检测</el-button>
          <el-button
            v-if="!isRecording(camera.id)"
            size="small"
            type="primary"
            plain
            :icon="VideoPlay"
            :loading="actionCameraId === camera.id"
            @click="runAction(camera, 'start')"
          >录像</el-button>
          <el-button
            v-else
            size="small"
            type="danger"
            plain
            :icon="VideoPause"
            :loading="actionCameraId === camera.id"
            @click="runAction(camera, 'stop')"
          >停止</el-button>
          <el-dropdown trigger="click" @command="(command: string) => command === 'edit' ? openEdit(camera) : removeCamera(camera)">
            <el-button size="small">更多</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="edit" :icon="Edit">编辑配置</el-dropdown-item>
                <el-dropdown-item command="delete" :icon="Delete" divided>删除摄像头</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </article>
    </div>

    <div v-else class="empty-state">
      <VideoCamera />
      <strong>{{ cameras.length ? '没有符合条件的摄像头' : '还没有摄像头' }}</strong>
      <span>{{ cameras.length ? '调整搜索词或筛选条件。' : '添加第一台 RTSP 摄像头开始录像。' }}</span>
      <el-button v-if="!cameras.length" type="primary" :icon="Plus" @click="openCreate">添加摄像头</el-button>
    </div>

    <el-drawer v-model="drawerVisible" size="520px" class="camera-detail-drawer" @closed="closeDrawer">
      <template #header>
        <div v-if="selectedCamera" class="drawer-title">
          <div>
            <strong>{{ selectedCamera.name }}</strong>
            <span>{{ selectedCamera.ip }}:{{ selectedCamera.rtsp_port }}</span>
          </div>
          <span class="health-badge" :class="health(selectedCamera)"><i></i>{{ healthLabel(selectedCamera) }}</span>
        </div>
      </template>

      <div v-if="selectedCamera" class="drawer-body">
        <div class="preview-panel">
          <img
            v-if="selectedCamera.enabled && !previewFailed"
            :key="previewNonce"
            class="preview-image"
            :src="previewSrc"
            :alt="`${selectedCamera.name} 实时预览`"
            @error="previewFailed = true"
          />
          <div v-else class="preview-empty">
            <VideoCamera />
            <strong>{{ selectedCamera.enabled ? '实时预览暂不可用' : '摄像头已禁用' }}</strong>
            <span v-if="selectedCamera.enabled">可先执行连接检测，或重新加载预览。</span>
          </div>
          <div class="preview-overlay">
            <span><i :class="{ active: isRecording(selectedCamera.id) }"></i>{{ runtimeLabel(selectedCamera) }}</span>
            <button @click="refreshPreview">重新加载</button>
          </div>
        </div>

        <div class="detail-section">
          <div class="detail-heading"><strong>连接信息</strong><el-button link type="primary" @click="openEdit(selectedCamera)">编辑</el-button></div>
          <dl class="detail-grid">
            <div><dt>IP 地址</dt><dd>{{ selectedCamera.ip }}</dd></div>
            <div><dt>RTSP 端口</dt><dd>{{ selectedCamera.rtsp_port }}</dd></div>
            <div><dt>用户名</dt><dd>{{ selectedCamera.username || '-' }}</dd></div>
            <div><dt>主码流</dt><dd>{{ selectedCamera.rtsp_path }}</dd></div>
            <div class="wide"><dt>子码流</dt><dd>{{ selectedCamera.sub_rtsp_path || '未配置' }}</dd></div>
          </dl>
        </div>

        <div class="detail-section">
          <div class="detail-heading"><strong>视频与录像</strong></div>
          <dl class="detail-grid">
            <div><dt>编码</dt><dd>{{ selectedCamera.video_codec?.toUpperCase() || '-' }}</dd></div>
            <div><dt>分辨率</dt><dd>{{ selectedCamera.width && selectedCamera.height ? `${selectedCamera.width}×${selectedCamera.height}` : '-' }}</dd></div>
            <div><dt>帧率</dt><dd>{{ fps(selectedCamera) ? `${fps(selectedCamera)} FPS` : '-' }}</dd></div>
            <div><dt>音频</dt><dd>{{ selectedCamera.audio_codec?.toUpperCase() || '-' }}</dd></div>
            <div><dt>录像策略</dt><dd>{{ scheduleLabel(selectedCamera) }}</dd></div>
            <div><dt>时间戳模式</dt><dd>{{ selectedCamera.timestamp_mode }}</dd></div>
          </dl>
        </div>

        <div class="detail-section">
          <div class="detail-heading"><strong>状态</strong></div>
          <dl class="detail-grid">
            <div><dt>运行状态</dt><dd>{{ runtimeState(selectedCamera.id) }}</dd></div>
            <div><dt>摄像头状态</dt><dd>{{ selectedCamera.status || '-' }}</dd></div>
            <div><dt>最近检测</dt><dd>{{ formatTime(selectedCamera.last_probe_at) }}</dd></div>
            <div><dt>最近在线</dt><dd>{{ formatTime(selectedCamera.last_online_at) }}</dd></div>
          </dl>
        </div>

        <div class="drawer-actions">
          <el-button :icon="Connection" :loading="actionCameraId === selectedCamera.id" @click="runAction(selectedCamera, 'probe')">连接检测</el-button>
          <el-button v-if="!isRecording(selectedCamera.id)" type="primary" :icon="VideoPlay" :loading="actionCameraId === selectedCamera.id" @click="runAction(selectedCamera, 'start')">开始录像</el-button>
          <el-button v-else type="danger" plain :icon="VideoPause" :loading="actionCameraId === selectedCamera.id" @click="runAction(selectedCamera, 'stop')">停止录像</el-button>
          <el-button @click="emit('open-preview')">进入实时监控</el-button>
        </div>
      </div>
    </el-drawer>

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '添加 RTSP 摄像头' : '编辑摄像头'" width="620px" destroy-on-close>
      <el-form label-width="88px" class="camera-form" @submit.prevent="saveCamera">
        <div class="form-grid">
          <el-form-item label="名称" class="wide"><el-input v-model="form.name" placeholder="例如：门口摄像头" /></el-form-item>
          <el-form-item label="IP 地址"><el-input v-model="form.ip" placeholder="192.168.1.101" /></el-form-item>
          <el-form-item label="RTSP 端口"><el-input-number v-model="form.rtsp_port" :min="1" :max="65535" controls-position="right" /></el-form-item>
          <el-form-item label="用户名"><el-input v-model="form.username" /></el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" type="password" show-password :placeholder="editingId === null ? '必填' : '留空保持原密码'" />
          </el-form-item>
          <el-form-item label="主码流" class="wide"><el-input v-model="form.rtsp_path" placeholder="/ch1/main" /></el-form-item>
          <el-form-item label="子码流" class="wide"><el-input v-model="form.sub_rtsp_path" placeholder="可选，例如 /ch1/sub" /></el-form-item>
          <el-form-item label="时间戳">
            <el-select v-model="form.timestamp_mode" style="width: 100%">
              <el-option label="重建时间戳（推荐）" value="reconstruct" />
              <el-option label="使用原始时间戳" value="native" />
              <el-option label="使用系统时间" value="wallclock" />
            </el-select>
          </el-form-item>
          <div class="switch-group">
            <label><span>启用摄像头</span><el-switch v-model="form.enabled" /></label>
            <label><span>自动录像</span><el-switch v-model="form.auto_record" /></label>
          </div>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveCamera">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.camera-page{padding:22px;min-height:100%;color:var(--nvr-text)}
.page-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:18px}.page-heading h1{margin:0;font-size:20px;font-weight:680;letter-spacing:-.01em}.page-heading p{margin:6px 0 0;color:var(--nvr-muted);font-size:12px}.heading-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}.summary-card{appearance:none;position:relative;min-height:94px;padding:14px 16px;text-align:left;color:var(--nvr-text);background:var(--nvr-surface);border:1px solid var(--nvr-border);border-radius:10px;cursor:pointer;overflow:hidden;transition:.16s}.summary-card:hover{border-color:var(--nvr-border-strong);background:var(--nvr-surface-2)}.summary-card.active{border-color:rgba(76,141,255,.58);box-shadow:0 0 0 1px rgba(76,141,255,.08) inset}.summary-card:after{content:'';position:absolute;left:0;top:14px;bottom:14px;width:2px;background:#637083;border-radius:2px}.summary-card.online:after{background:var(--nvr-green)}.summary-card.issue:after{background:var(--nvr-yellow)}.summary-card.recording:after{background:var(--nvr-red)}.summary-card span{display:block;color:var(--nvr-muted);font-size:11px}.summary-card strong{display:block;margin:7px 0 5px;font-size:25px;line-height:1}.summary-card small{color:#647286;font-size:10px}
.toolbar{min-height:56px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:10px 12px;margin-bottom:10px;border:1px solid var(--nvr-border);border-radius:9px;background:rgba(20,26,34,.72)}.search-box{width:min(390px,100%)}.result-count{color:var(--nvr-muted);font-size:11px;white-space:nowrap}
.camera-list{display:flex;flex-direction:column;gap:8px}.camera-card{display:grid;grid-template-columns:minmax(330px,1.6fr) minmax(310px,1fr) auto;align-items:center;gap:16px;padding:14px 15px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface);transition:.15s}.camera-card:hover{border-color:var(--nvr-border-strong);background:#161d26}.camera-main{min-width:0;display:flex;align-items:center;gap:12px}.camera-icon{flex:0 0 44px;width:44px;height:44px;display:grid;place-items:center;border-radius:10px;color:#6f7c8e;background:#10161e;border:1px solid var(--nvr-border)}.camera-icon :deep(svg){width:21px}.camera-icon.online{color:var(--nvr-green);background:rgba(46,204,138,.07)}.camera-icon.offline{color:var(--nvr-red);background:rgba(240,93,94,.07)}.camera-icon.unknown{color:var(--nvr-yellow);background:rgba(245,185,66,.06)}.camera-copy{min-width:0}.camera-name-row{display:flex;align-items:center;gap:7px;min-width:0}.camera-name-row strong{max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}.health-badge,.record-badge{display:inline-flex;align-items:center;gap:5px;height:22px;padding:0 7px;border:1px solid var(--nvr-border);border-radius:5px;color:var(--nvr-muted);background:#11171f;font-size:10px;white-space:nowrap}.health-badge i,.record-badge i{width:6px;height:6px;border-radius:50%;background:#687688}.health-badge.online i{background:var(--nvr-green);box-shadow:0 0 0 3px rgba(46,204,138,.08)}.health-badge.offline i{background:var(--nvr-red)}.health-badge.unknown i{background:var(--nvr-yellow)}.record-badge.active{color:#efb7b8;border-color:rgba(240,93,94,.18);background:rgba(240,93,94,.055)}.record-badge.active i{background:var(--nvr-red);box-shadow:0 0 0 3px rgba(240,93,94,.08)}.camera-address{margin-top:6px;color:#8290a1;font-size:11px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.camera-video{margin-top:4px;color:#647286;font-size:10px}.camera-signals{display:grid;grid-template-columns:repeat(3,minmax(80px,1fr));gap:8px}.camera-signals div{min-width:0}.camera-signals span,.camera-signals b{display:block}.camera-signals span{margin-bottom:4px;color:#647286;font-size:9px}.camera-signals b{color:#aeb9c5;font-size:10px;font-weight:550;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.camera-actions{display:flex;align-items:center;justify-content:flex-end;gap:5px;white-space:nowrap}
.empty-state{min-height:330px;display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px dashed var(--nvr-border-strong);border-radius:11px;color:var(--nvr-muted);background:rgba(20,26,34,.42)}.empty-state :deep(svg){width:34px;margin-bottom:12px;color:#536173}.empty-state strong{color:#aeb9c5;font-size:13px}.empty-state span{margin:6px 0 16px;font-size:11px}
.drawer-title{width:100%;display:flex;align-items:center;justify-content:space-between;gap:16px;padding-right:12px}.drawer-title>div{display:flex;min-width:0;flex-direction:column}.drawer-title strong{font-size:15px}.drawer-title span:not(.health-badge){margin-top:3px;color:var(--nvr-muted);font-size:10px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.drawer-body{display:flex;flex-direction:column;gap:13px}.preview-panel{position:relative;aspect-ratio:16/9;border:1px solid var(--nvr-border);border-radius:9px;background:#05080c;overflow:hidden}.preview-image{display:block;width:100%;height:100%;object-fit:contain;background:#05080c}.preview-empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#617083}.preview-empty :deep(svg){width:34px;margin-bottom:9px}.preview-empty strong{color:#9aa7b7;font-size:12px}.preview-empty span{margin-top:5px;font-size:10px}.preview-overlay{position:absolute;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:space-between;padding:26px 10px 8px;background:linear-gradient(transparent,rgba(0,0,0,.72));font-size:10px}.preview-overlay span{display:flex;align-items:center;gap:6px}.preview-overlay i{width:6px;height:6px;border-radius:50%;background:#6a7787}.preview-overlay i.active{background:var(--nvr-red)}.preview-overlay button{appearance:none;border:0;color:#c4ced8;background:transparent;cursor:pointer;font-size:10px}.detail-section{padding:13px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.detail-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px}.detail-heading strong{font-size:11px}.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px 16px;margin:0}.detail-grid div{min-width:0}.detail-grid .wide{grid-column:1/-1}.detail-grid dt{margin-bottom:3px;color:#647286;font-size:9px}.detail-grid dd{margin:0;color:#b7c2cd;font-size:10px;overflow-wrap:anywhere}.drawer-actions{position:sticky;bottom:0;display:flex;gap:7px;flex-wrap:wrap;padding:11px 0 2px;background:linear-gradient(transparent 0,var(--nvr-bg) 18px)}
.camera-form{padding-top:4px}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 14px}.form-grid .wide{grid-column:1/-1}.form-grid :deep(.el-input-number){width:100%}.switch-group{display:flex;align-items:center;gap:20px;min-height:32px;padding:0 0 18px 88px}.switch-group label{display:flex;align-items:center;gap:9px;color:var(--nvr-muted);font-size:11px}
@media (max-width:1180px){.camera-card{grid-template-columns:minmax(300px,1fr) auto}.camera-signals{display:none}.summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:760px){.camera-page{padding:14px}.page-heading{flex-direction:column}.heading-actions{width:100%}.summary-grid{grid-template-columns:1fr 1fr}.camera-card{grid-template-columns:1fr}.camera-actions{justify-content:flex-start;flex-wrap:wrap}.toolbar{align-items:stretch;flex-direction:column}.search-box{width:100%}.detail-grid{grid-template-columns:1fr}.detail-grid .wide{grid-column:auto}.form-grid{grid-template-columns:1fr}.form-grid .wide{grid-column:auto}.switch-group{padding-left:0}.camera-detail-drawer{width:100%!important}}
</style>