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
import CameraDeviceGlyph from './CameraDeviceGlyph.vue'

type CameraFormFactor = 'unknown' | 'bullet' | 'dome' | 'turret' | 'ptz' | 'doorbell' | 'indoor'
type PreviewSource = 'main' | 'sub'
type FilterKey = 'all' | 'online' | 'issue' | 'recording'
type CameraHealth = 'online' | 'offline' | 'unknown' | 'disabled'
type HistoryMode = 'push' | 'replace'

interface Camera {
  id: number
  name: string
  manufacturer?: string | null
  model?: string | null
  form_factor: CameraFormFactor
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
  connectivity_status: string
  recorder_state: string
  schedule_state: string
  last_probe_at?: string | null
  last_online_at?: string | null
}

const emit = defineEmits<{
  (event: 'open-batch'): void
  (event: 'open-preview'): void
}>()

const cameras = ref<Camera[]>([])
const loading = ref(false)
const query = ref('')
const filter = ref<FilterKey>('all')
const drawerVisible = ref(false)
const selectedCamera = ref<Camera | null>(null)
const previewFailed = ref(false)
const previewNonce = ref(Date.now())
const previewSource = ref<PreviewSource>('main')
const previewFallbackUsed = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const actionCameraId = ref<number | null>(null)
let refreshTimer: number | null = null

const form = reactive({
  name: '',
  manufacturer: '',
  model: '',
  form_factor: 'unknown' as CameraFormFactor,
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

const formFactorOptions: Array<{ value: CameraFormFactor; label: string }> = [
  { value: 'unknown', label: '未指定' },
  { value: 'bullet', label: '枪机' },
  { value: 'dome', label: '半球' },
  { value: 'turret', label: '炮塔 / 海螺' },
  { value: 'ptz', label: '云台 PTZ' },
  { value: 'doorbell', label: '门铃' },
  { value: 'indoor', label: '室内桌面机' },
]

function apiError(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    return error.message || fallback
  }
  return fallback
}

function cameraById(cameraId: number) {
  return cameras.value.find((item) => item.id === cameraId)
}

function runtimeState(cameraId: number) {
  return cameraById(cameraId)?.recorder_state || 'STOPPED'
}

function isRecording(cameraId: number) {
  return runtimeState(cameraId) === 'RECORDING'
}

function health(camera: Camera): CameraHealth {
  if (!camera.enabled) return 'disabled'
  if (camera.connectivity_status === 'online') return 'online'
  if (camera.connectivity_status === 'offline') return 'offline'
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
  const state = camera.recorder_state || 'STOPPED'
  if (state === 'RECORDING') return '录像中'
  if (state === 'STARTING') return '启动中'
  if (state === 'RECONNECTING') return '重连中'
  if (state === 'STOPPING') return '停止中'
  return '未录像'
}

function formFactorLabel(value?: CameraFormFactor | null) {
  return formFactorOptions.find((item) => item.value === value)?.label || '未指定'
}

function identitySummary(camera: Camera) {
  const parts = [camera.manufacturer, camera.model, camera.form_factor !== 'unknown' ? formFactorLabel(camera.form_factor) : null]
    .filter((item): item is string => Boolean(item))
  return parts.length ? parts.join(' · ') : '设备信息未补充'
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

function schedulePolicyLabel(camera: Camera) {
  if (!camera.auto_record) return '手动录像'
  if (camera.recording_schedule_enabled) return '按计划录像'
  return '自动录像'
}

function scheduleStateLabel(camera: Camera) {
  const state = camera.schedule_state
  if (state === 'manual_override') return '手动接管'
  if (state === 'manual_paused') return '手动暂停'
  if (state === 'in_window') return '计划时段内'
  if (state === 'scheduled') return '等待计划'
  if (state === 'automatic') return '全天自动'
  if (state === 'global_disabled') return '全局自动关闭'
  if (state === 'probe_required') return '需要检测'
  if (state === 'error') return '计划异常'
  return '未启用'
}

function formatTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function inferSubstreamPath(mainPath: string) {
  if (mainPath.includes('/main')) {
    const index = mainPath.lastIndexOf('/main')
    return `${mainPath.slice(0, index)}/sub${mainPath.slice(index + 5)}`
  }
  if (mainPath.endsWith('main')) return `${mainPath.slice(0, -4)}sub`
  return null
}

function preferredPreviewSource(camera: Camera): PreviewSource {
  return camera.sub_rtsp_path?.trim() || inferSubstreamPath(camera.rtsp_path) ? 'sub' : 'main'
}

function resetPreview(camera: Camera) {
  previewSource.value = preferredPreviewSource(camera)
  previewFallbackUsed.value = false
  previewFailed.value = false
  previewNonce.value = Date.now()
}

function handlePreviewLoad() {
  previewFailed.value = false
}

function handlePreviewError() {
  if (!selectedCamera.value) return
  if (previewSource.value === 'sub') {
    previewSource.value = 'main'
    previewFallbackUsed.value = true
    previewFailed.value = false
    previewNonce.value = Date.now()
    return
  }
  previewFailed.value = true
}

function deepLinkedCameraId() {
  const raw = new URLSearchParams(window.location.search).get('camera_id')
  if (!raw) return null
  const cameraId = Number(raw)
  return Number.isInteger(cameraId) && cameraId > 0 ? cameraId : null
}

function writeCameraDeepLink(cameraId: number | null, mode: HistoryMode) {
  const url = new URL(window.location.href)
  if (cameraId === null) url.searchParams.delete('camera_id')
  else url.searchParams.set('camera_id', String(cameraId))
  const next = `${url.pathname}${url.search}${url.hash}`
  if (mode === 'push') window.history.pushState({}, '', next)
  else window.history.replaceState({}, '', next)
}

function syncDrawerFromLocation(showMissing = false) {
  const cameraId = deepLinkedCameraId()
  if (cameraId === null) {
    if (drawerVisible.value) drawerVisible.value = false
    selectedCamera.value = null
    return
  }
  const camera = cameraById(cameraId)
  if (!camera) {
    if (showMissing) ElMessage.warning(`未找到摄像头 #${cameraId}`)
    writeCameraDeepLink(null, 'replace')
    drawerVisible.value = false
    selectedCamera.value = null
    return
  }
  const openingDifferentCamera = !drawerVisible.value || selectedCamera.value?.id !== camera.id
  selectedCamera.value = camera
  if (openingDifferentCamera) resetPreview(camera)
  drawerVisible.value = true
}

function handleCameraPopState() {
  syncDrawerFromLocation(false)
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
    const matched = !needle || [
      camera.name,
      camera.manufacturer || '',
      camera.model || '',
      camera.ip,
      camera.rtsp_path,
      camera.sub_rtsp_path || '',
    ].some((value) => value.toLowerCase().includes(needle))
    if (!matched) return false
    if (filter.value === 'online') return health(camera) === 'online'
    if (filter.value === 'issue') return ['offline', 'unknown'].includes(health(camera))
    if (filter.value === 'recording') return isRecording(camera.id)
    return true
  })
})

const previewSrc = computed(() => selectedCamera.value
  ? `/api/cameras/${selectedCamera.value.id}/preview.mjpeg?stream=${previewSource.value}&fps=6&width=960&_=${previewNonce.value}`
  : '')

async function loadData(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const { data } = await axios.get<Camera[]>('/api/cameras')
    cameras.value = data
    const requestedId = deepLinkedCameraId()
    if (requestedId !== null) {
      syncDrawerFromLocation(showLoading)
    } else if (selectedCamera.value) {
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
    manufacturer: '',
    model: '',
    form_factor: 'unknown',
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
    manufacturer: camera.manufacturer || '',
    model: camera.model || '',
    form_factor: camera.form_factor || 'unknown',
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
      manufacturer: form.manufacturer.trim() || null,
      model: form.model.trim() || null,
      form_factor: form.form_factor,
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
    if (selectedCamera.value?.id === camera.id) {
      drawerVisible.value = false
      writeCameraDeepLink(null, 'replace')
    }
    await loadData()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiError(error, '删除失败'))
  }
}

function openDetails(camera: Camera, syncUrl = true) {
  selectedCamera.value = camera
  resetPreview(camera)
  drawerVisible.value = true
  if (syncUrl && deepLinkedCameraId() !== camera.id) writeCameraDeepLink(camera.id, 'push')
}

function refreshPreview() {
  if (selectedCamera.value) resetPreview(selectedCamera.value)
}

function closeDrawer() {
  const selectedId = selectedCamera.value?.id || null
  selectedCamera.value = null
  previewFailed.value = false
  previewFallbackUsed.value = false
  if (selectedId !== null && deepLinkedCameraId() === selectedId) writeCameraDeepLink(null, 'replace')
}

onMounted(() => {
  window.addEventListener('popstate', handleCameraPopState)
  void loadData()
  refreshTimer = window.setInterval(() => void loadData(false), 10000)
})

onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
  window.removeEventListener('popstate', handleCameraPopState)
})
</script>

<template>
  <section class="camera-page" v-loading="loading">
    <div class="page-heading">
      <div>
        <h1>摄像头设备</h1>
        <p>集中查看设备身份、连接能力、实时预览与录像运行状态。</p>
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
      <el-input v-model="query" clearable :prefix-icon="Search" placeholder="搜索名称、厂商、型号、IP 或 RTSP 路径" class="search-box" />
      <span class="result-count">显示 {{ filteredCameras.length }} / {{ cameras.length }} 台</span>
    </div>

    <div v-if="filteredCameras.length" class="camera-list">
      <article v-for="camera in filteredCameras" :key="camera.id" class="camera-card" @dblclick="openDetails(camera)">
        <div class="camera-main">
          <div class="camera-icon" :class="health(camera)" :title="formFactorLabel(camera.form_factor)">
            <CameraDeviceGlyph :form-factor="camera.form_factor" />
          </div>
          <div class="camera-copy">
            <div class="camera-name-row">
              <strong>{{ camera.name }}</strong>
              <span class="health-badge" :class="health(camera)"><i></i>{{ healthLabel(camera) }}</span>
              <span class="record-badge" :class="{ active: isRecording(camera.id) }"><i></i>{{ runtimeLabel(camera) }}</span>
            </div>
            <div class="camera-identity">{{ identitySummary(camera) }}</div>
            <div class="camera-address">{{ camera.ip }}:{{ camera.rtsp_port }} · {{ camera.rtsp_path }}</div>
            <div class="camera-video">{{ videoSummary(camera) }}</div>
          </div>
        </div>

        <div class="camera-signals">
          <div><span>计划状态</span><b>{{ scheduleStateLabel(camera) }}</b></div>
          <div><span>子码流</span><b>{{ camera.sub_rtsp_path ? '已配置' : inferSubstreamPath(camera.rtsp_path) ? '可推测' : '未配置' }}</b></div>
          <div><span>时间戳</span><b>{{ camera.timestamp_mode }}</b></div>
        </div>

        <div class="camera-actions" @dblclick.stop>
          <el-button size="small" @click="openDetails(camera)">详情 / 预览</el-button>
          <el-button size="small" :icon="Connection" :loading="actionCameraId === camera.id" @click="runAction(camera, 'probe')">检测</el-button>
          <el-button v-if="!isRecording(camera.id)" size="small" type="primary" plain :icon="VideoPlay" :loading="actionCameraId === camera.id" @click="runAction(camera, 'start')">录像</el-button>
          <el-button v-else size="small" type="danger" plain :icon="VideoPause" :loading="actionCameraId === camera.id" @click="runAction(camera, 'stop')">停止</el-button>
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

    <el-drawer v-model="drawerVisible" size="600px" class="camera-detail-drawer" @closed="closeDrawer">
      <template #header>
        <div v-if="selectedCamera" class="drawer-title">
          <div>
            <strong>{{ selectedCamera.name }}</strong>
            <span>{{ identitySummary(selectedCamera) }}</span>
            <span>{{ selectedCamera.ip }}:{{ selectedCamera.rtsp_port }}</span>
          </div>
          <span class="health-badge" :class="health(selectedCamera)"><i></i>{{ healthLabel(selectedCamera) }}</span>
        </div>
      </template>

      <div v-if="selectedCamera" class="drawer-body">
        <div class="device-hero">
          <div class="device-hero-visual" :class="health(selectedCamera)">
            <CameraDeviceGlyph :form-factor="selectedCamera.form_factor" />
          </div>
          <div class="device-hero-copy">
            <span>DEVICE</span>
            <strong>{{ selectedCamera.manufacturer || '通用 RTSP 摄像头' }}</strong>
            <b>{{ selectedCamera.model || formFactorLabel(selectedCamera.form_factor) }}</b>
            <small>{{ formFactorLabel(selectedCamera.form_factor) }} · #{{ selectedCamera.id }}</small>
          </div>
        </div>

        <div class="preview-panel">
          <img
            v-if="selectedCamera.enabled && !previewFailed"
            :key="previewNonce"
            class="preview-image"
            :src="previewSrc"
            :alt="`${selectedCamera.name} 实时预览`"
            @load="handlePreviewLoad"
            @error="handlePreviewError"
          />
          <div v-else class="preview-empty">
            <VideoCamera />
            <strong>{{ selectedCamera.enabled ? '实时预览暂不可用' : '摄像头已禁用' }}</strong>
            <span v-if="selectedCamera.enabled">子码流与主码流均无法打开，可执行连接检测后重试。</span>
          </div>
          <div class="preview-overlay">
            <div class="preview-overlay-status">
              <span><i :class="{ active: isRecording(selectedCamera.id) }"></i>{{ runtimeLabel(selectedCamera) }}</span>
              <span class="preview-stream-chip">策略：AUTO</span>
              <span class="preview-stream-chip" :class="{ fallback: previewFallbackUsed }">
                实际：{{ previewSource === 'sub' ? '子码流' : '主码流' }}<template v-if="previewFallbackUsed"> · 回退</template>
              </span>
            </div>
            <button @click="refreshPreview">重新加载</button>
          </div>
        </div>

        <div class="detail-section">
          <div class="detail-heading"><strong>设备信息</strong><el-button link type="primary" @click="openEdit(selectedCamera)">编辑</el-button></div>
          <dl class="detail-grid">
            <div><dt>厂商</dt><dd>{{ selectedCamera.manufacturer || '未填写' }}</dd></div>
            <div><dt>型号</dt><dd>{{ selectedCamera.model || '未填写' }}</dd></div>
            <div><dt>外形</dt><dd>{{ formFactorLabel(selectedCamera.form_factor) }}</dd></div>
            <div><dt>设备 ID</dt><dd>#{{ selectedCamera.id }}</dd></div>
          </dl>
        </div>

        <div class="detail-section">
          <div class="detail-heading"><strong>连接信息</strong></div>
          <dl class="detail-grid">
            <div><dt>IP 地址</dt><dd>{{ selectedCamera.ip }}</dd></div>
            <div><dt>RTSP 端口</dt><dd>{{ selectedCamera.rtsp_port }}</dd></div>
            <div><dt>用户名</dt><dd>{{ selectedCamera.username || '-' }}</dd></div>
            <div><dt>主码流</dt><dd>{{ selectedCamera.rtsp_path }}</dd></div>
            <div class="wide"><dt>子码流</dt><dd>{{ selectedCamera.sub_rtsp_path || inferSubstreamPath(selectedCamera.rtsp_path) || '未配置' }}</dd></div>
          </dl>
        </div>

        <div class="detail-section">
          <div class="detail-heading"><strong>视频与录像</strong></div>
          <dl class="detail-grid">
            <div><dt>编码</dt><dd>{{ selectedCamera.video_codec?.toUpperCase() || '-' }}</dd></div>
            <div><dt>分辨率</dt><dd>{{ selectedCamera.width && selectedCamera.height ? `${selectedCamera.width}×${selectedCamera.height}` : '-' }}</dd></div>
            <div><dt>帧率</dt><dd>{{ fps(selectedCamera) ? `${fps(selectedCamera)} FPS` : '-' }}</dd></div>
            <div><dt>音频</dt><dd>{{ selectedCamera.audio_codec?.toUpperCase() || '-' }}</dd></div>
            <div><dt>录像策略</dt><dd>{{ schedulePolicyLabel(selectedCamera) }}</dd></div>
            <div><dt>时间戳模式</dt><dd>{{ selectedCamera.timestamp_mode }}</dd></div>
          </dl>
        </div>

        <div class="detail-section">
          <div class="detail-heading"><strong>状态</strong></div>
          <dl class="detail-grid">
            <div><dt>连接状态</dt><dd>{{ healthLabel(selectedCamera) }}</dd></div>
            <div><dt>录像状态</dt><dd>{{ runtimeLabel(selectedCamera) }}</dd></div>
            <div><dt>计划状态</dt><dd>{{ scheduleStateLabel(selectedCamera) }}</dd></div>
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

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '添加 RTSP 摄像头' : '编辑摄像头'" width="680px" destroy-on-close>
      <el-form label-width="88px" class="camera-form" @submit.prevent="saveCamera">
        <div class="form-grid">
          <el-form-item label="名称" class="wide"><el-input v-model="form.name" placeholder="例如：门口摄像头" /></el-form-item>
          <el-form-item label="厂商"><el-input v-model="form.manufacturer" placeholder="例如 Hikvision" /></el-form-item>
          <el-form-item label="型号"><el-input v-model="form.model" placeholder="例如 DS-2CD..." /></el-form-item>
          <el-form-item label="外形" class="wide">
            <el-select v-model="form.form_factor" style="width: 100%">
              <el-option v-for="item in formFactorOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="IP 地址"><el-input v-model="form.ip" placeholder="192.168.1.101" /></el-form-item>
          <el-form-item label="RTSP 端口"><el-input-number v-model="form.rtsp_port" :min="1" :max="65535" controls-position="right" /></el-form-item>
          <el-form-item label="用户名"><el-input v-model="form.username" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password :placeholder="editingId === null ? '必填' : '留空保持原密码'" /></el-form-item>
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
.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}.summary-card{appearance:none;position:relative;min-height:94px;padding:14px 16px;text-align:left;color:var(--nvr-text);background:var(--nvr-surface);border:1px solid var(--nvr-border);border-radius:10px;cursor:pointer;overflow:hidden;transition:.16s}.summary-card:hover{border-color:var(--nvr-border-strong);background:var(--nvr-surface-2)}.summary-card.active{border-color:rgba(76,141,255,.58);box-shadow:0 0 0 1px rgba(76,141,255,.08) inset}.summary-card:after{content:'';position:absolute;left:0;top:14px;bottom:14px;width:2px;background:var(--nvr-subtle);border-radius:2px}.summary-card.online:after{background:var(--nvr-green)}.summary-card.issue:after{background:var(--nvr-yellow)}.summary-card.recording:after{background:var(--nvr-red)}.summary-card span{display:block;color:var(--nvr-muted);font-size:11px}.summary-card strong{display:block;margin:7px 0 5px;font-size:25px;line-height:1}.summary-card small{color:var(--nvr-subtle);font-size:10px}
.toolbar{min-height:56px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:10px 12px;margin-bottom:10px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.search-box{width:min(470px,100%)}.result-count{color:var(--nvr-muted);font-size:11px;white-space:nowrap}
.camera-list{display:flex;flex-direction:column;gap:8px}.camera-card{display:grid;grid-template-columns:minmax(390px,1.65fr) minmax(300px,1fr) auto;align-items:center;gap:16px;padding:14px 15px;border:1px solid var(--nvr-border);border-radius:12px;background:var(--nvr-surface);transition:border-color .15s ease,background-color .15s ease,transform .15s ease}.camera-card:hover{border-color:var(--nvr-border-strong);background:var(--nvr-surface-2);transform:translateY(-1px)}.camera-main{min-width:0;display:flex;align-items:center;gap:14px}.camera-icon{flex:0 0 62px;width:62px;height:62px;display:grid;place-items:center;padding:9px;border-radius:14px;color:var(--nvr-muted);background:linear-gradient(145deg,var(--nvr-input),var(--nvr-surface-2));border:1px solid var(--nvr-border)}.camera-icon.online{color:var(--nvr-green);background:linear-gradient(145deg,rgba(46,204,138,.09),var(--nvr-surface-2))}.camera-icon.offline{color:var(--nvr-red);background:linear-gradient(145deg,rgba(240,93,94,.09),var(--nvr-surface-2))}.camera-icon.unknown{color:var(--nvr-yellow);background:linear-gradient(145deg,rgba(245,185,66,.08),var(--nvr-surface-2))}.camera-icon.disabled{opacity:.62}.camera-copy{min-width:0;flex:1}.camera-name-row{display:flex;align-items:center;flex-wrap:wrap;gap:6px 7px;min-width:0}.camera-name-row strong{min-width:0;max-width:100%;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere;font-size:13px;line-height:1.35}.health-badge,.record-badge{display:inline-flex;align-items:center;gap:5px;height:22px;padding:0 7px;border:1px solid var(--nvr-border);border-radius:5px;color:var(--nvr-muted);background:var(--nvr-input);font-size:10px;white-space:nowrap}.health-badge i,.record-badge i{width:6px;height:6px;border-radius:50%;background:var(--nvr-subtle)}.health-badge.online i{background:var(--nvr-green);box-shadow:0 0 0 3px rgba(46,204,138,.08)}.health-badge.offline i{background:var(--nvr-red)}.health-badge.unknown i{background:var(--nvr-yellow)}.record-badge.active{color:var(--nvr-red);border-color:rgba(240,93,94,.18);background:rgba(240,93,94,.055)}.record-badge.active i{background:var(--nvr-red);box-shadow:0 0 0 3px rgba(240,93,94,.08)}.camera-identity{margin-top:5px;color:var(--nvr-text-soft);font-size:10px}.camera-address{margin-top:5px;color:var(--nvr-muted);font-size:11px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.camera-video{margin-top:4px;color:var(--nvr-subtle);font-size:10px}.camera-signals{display:grid;grid-template-columns:repeat(3,minmax(80px,1fr));gap:8px}.camera-signals div{min-width:0}.camera-signals span,.camera-signals b{display:block}.camera-signals span{margin-bottom:4px;color:var(--nvr-subtle);font-size:9px}.camera-signals b{color:var(--nvr-text-soft);font-size:10px;font-weight:550;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.camera-actions{display:flex;align-items:center;justify-content:flex-end;gap:5px;white-space:nowrap}
.empty-state{min-height:330px;display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px dashed var(--nvr-border-strong);border-radius:11px;color:var(--nvr-muted);background:var(--nvr-surface)}.empty-state :deep(svg){width:34px;margin-bottom:12px;color:var(--nvr-subtle)}.empty-state strong{color:var(--nvr-text-soft);font-size:13px}.empty-state span{margin:6px 0 16px;font-size:11px}
.drawer-title{width:100%;display:flex;align-items:center;justify-content:space-between;gap:16px;padding-right:12px}.drawer-title>div{display:flex;min-width:0;flex-direction:column}.drawer-title strong{font-size:15px;white-space:normal;overflow-wrap:anywhere}.drawer-title span:not(.health-badge){margin-top:3px;color:var(--nvr-muted);font-size:10px}.drawer-body{display:flex;flex-direction:column;gap:13px}.device-hero{display:flex;align-items:center;gap:16px;padding:16px;border:1px solid var(--nvr-border);border-radius:12px;background:linear-gradient(135deg,var(--nvr-surface-2),var(--nvr-surface))}.device-hero-visual{flex:0 0 108px;width:108px;height:82px;display:grid;place-items:center;padding:13px;border:1px solid var(--nvr-border);border-radius:14px;color:var(--nvr-muted);background:var(--nvr-input)}.device-hero-visual.online{color:var(--nvr-green)}.device-hero-visual.offline{color:var(--nvr-red)}.device-hero-visual.unknown{color:var(--nvr-yellow)}.device-hero-visual.disabled{opacity:.6}.device-hero-copy{min-width:0;display:flex;flex-direction:column}.device-hero-copy>span{color:var(--nvr-subtle);font-size:8px;font-weight:800;letter-spacing:.16em}.device-hero-copy strong{margin-top:5px;font-size:15px;font-weight:680;overflow-wrap:anywhere}.device-hero-copy b{margin-top:3px;color:var(--nvr-text-soft);font-size:11px;font-weight:560;overflow-wrap:anywhere}.device-hero-copy small{margin-top:7px;color:var(--nvr-muted);font-size:9px}.preview-panel{position:relative;aspect-ratio:16/9;border:1px solid var(--nvr-border);border-radius:9px;background:#05080c;overflow:hidden}.preview-image{display:block;width:100%;height:100%;object-fit:contain;background:#05080c}.preview-empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#617083}.preview-empty :deep(svg){width:34px;margin-bottom:9px}.preview-empty strong{color:#9aa7b7;font-size:12px}.preview-empty span{margin-top:5px;font-size:10px}.preview-overlay{position:absolute;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:space-between;padding:26px 10px 8px;color:#c4ced8;background:linear-gradient(transparent,rgba(0,0,0,.72));font-size:10px}.preview-overlay-status{display:flex;align-items:center;gap:6px;min-width:0}.preview-overlay span{display:flex;align-items:center;gap:6px}.preview-overlay i{width:6px;height:6px;border-radius:50%;background:#6a7787}.preview-overlay i.active{background:var(--nvr-red)}.preview-stream-chip{height:20px;padding:0 6px;border:1px solid rgba(255,255,255,.14);border-radius:5px;background:rgba(5,8,12,.42);white-space:nowrap}.preview-stream-chip.fallback{color:#f4c563;border-color:rgba(244,197,99,.32)}.preview-overlay button{appearance:none;border:0;color:#c4ced8;background:transparent;cursor:pointer;font-size:10px;white-space:nowrap}.detail-section{padding:13px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.detail-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px}.detail-heading strong{font-size:11px}.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px 16px;margin:0}.detail-grid div{min-width:0}.detail-grid .wide{grid-column:1/-1}.detail-grid dt{margin-bottom:3px;color:var(--nvr-subtle);font-size:9px}.detail-grid dd{margin:0;color:var(--nvr-text-soft);font-size:10px;overflow-wrap:anywhere}.drawer-actions{position:sticky;bottom:0;display:flex;gap:7px;flex-wrap:wrap;padding:11px 0 2px;background:linear-gradient(transparent 0,var(--nvr-bg) 18px)}
.camera-form{padding-top:4px}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 14px}.form-grid .wide{grid-column:1/-1}.form-grid :deep(.el-input-number){width:100%}.switch-group{display:flex;align-items:center;gap:20px;min-height:32px;padding:0 0 18px 88px}.switch-group label{display:flex;align-items:center;gap:9px;color:var(--nvr-muted);font-size:11px}
@media (max-width:1180px){.camera-card{grid-template-columns:minmax(300px,1fr) auto}.camera-signals{display:none}.summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:760px){.camera-page{padding:14px}.page-heading{flex-direction:column}.heading-actions{width:100%}.summary-grid{grid-template-columns:1fr 1fr}.camera-card{grid-template-columns:1fr}.camera-actions{justify-content:flex-start;flex-wrap:wrap}.toolbar{align-items:stretch;flex-direction:column}.search-box{width:100%}.detail-grid{grid-template-columns:1fr}.detail-grid .wide{grid-column:auto}.form-grid{grid-template-columns:1fr}.form-grid .wide{grid-column:auto}.switch-group{padding-left:0}.camera-detail-drawer{width:100%!important}.device-hero-visual{flex-basis:88px;width:88px;height:70px}.preview-overlay-status{gap:4px}.preview-stream-chip{padding:0 5px;font-size:9px}}
</style>
