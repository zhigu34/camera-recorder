<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft,
  ArrowRight,
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
import { useCameraStore } from './stores/cameras'
import { formatDateTime } from './utils/dateTime'

type CameraFormFactor = 'unknown' | 'bullet' | 'dome' | 'turret' | 'ptz' | 'doorbell' | 'indoor' | 'panoramic'
type PreviewSource = 'main' | 'sub'
type FilterKey = 'all' | 'online' | 'issue' | 'recording' | 'disabled'
type SortKey = 'attention' | 'name' | 'ip' | 'status'
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

const route = useRoute()
const router = useRouter()
const cameraStore = useCameraStore()
const { cameras: sharedCameras, loading: cameraLoading } = storeToRefs(cameraStore)
const cameras = computed(() => sharedCameras.value as Camera[])
const localLoading = ref(false)
const loading = computed(() => localLoading.value || cameraLoading.value)

const CAMERA_PREFERENCES_KEY = 'camera-recorder:camera-device-preferences:v1'
const validFilters = new Set<FilterKey>(['all', 'online', 'issue', 'recording', 'disabled'])
const validSortKeys = new Set<SortKey>(['attention', 'name', 'ip', 'status'])

const query = ref('')
const filter = ref<FilterKey>('all')
const sortKey = ref<SortKey>('attention')
const selectedCamera = ref<Camera | null>(null)
const mobileListVisible = ref(false)
const previewPlaying = ref(false)
const previewFailed = ref(false)
const previewNonce = ref(Date.now())
const previewSource = ref<PreviewSource>('main')
const previewFallbackUsed = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const actionCameraId = ref<number | null>(null)
const batchProbeRunning = ref(false)
const batchProbeFailedNames = ref<string[]>([])
const batchProbeProgress = reactive({ current: 0, total: 0, success: 0, failed: 0 })
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
  { value: 'panoramic', label: '全景 / 鱼眼' },
]
const sortOptions: Array<{ value: SortKey; label: string }> = [
  { value: 'attention', label: '异常优先' },
  { value: 'name', label: '按名称' },
  { value: 'ip', label: '按 IP' },
  { value: 'status', label: '按状态' },
]

function apiError(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    return error.message || fallback
  }
  return fallback
}
function loadPreferences() {
  try {
    const raw = window.localStorage.getItem(CAMERA_PREFERENCES_KEY)
    if (!raw) return
    const stored = JSON.parse(raw) as { filter?: string; sortKey?: string }
    if (stored.filter && validFilters.has(stored.filter as FilterKey)) filter.value = stored.filter as FilterKey
    if (stored.sortKey && validSortKeys.has(stored.sortKey as SortKey)) sortKey.value = stored.sortKey as SortKey
  } catch { /* keep defaults */ }
}
function savePreferences() {
  try { window.localStorage.setItem(CAMERA_PREFERENCES_KEY, JSON.stringify({ filter: filter.value, sortKey: sortKey.value })) }
  catch { /* storage restrictions must not block management */ }
}
function setFilter(value: FilterKey) { filter.value = value; savePreferences() }
function cameraById(cameraId: number) { return cameras.value.find((item) => item.id === cameraId) }
function runtimeState(cameraId: number) { return cameraById(cameraId)?.recorder_state || 'STOPPED' }
function isRecording(cameraId: number) { return runtimeState(cameraId) === 'RECORDING' }
function isCameraBusy(cameraId: number) { return actionCameraId.value === cameraId }
function health(camera: Camera): CameraHealth {
  if (!camera.enabled) return 'disabled'
  if (camera.connectivity_status === 'online') return 'online'
  if (camera.connectivity_status === 'offline') return 'offline'
  return 'unknown'
}
function canQuickProbe(camera: Camera) { return camera.enabled && ['offline', 'unknown'].includes(health(camera)) }
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
function formFactorLabel(value?: CameraFormFactor | null) { return formFactorOptions.find((item) => item.value === value)?.label || '未指定' }
function identitySummary(camera: Camera) {
  const parts = [camera.manufacturer, camera.model, camera.form_factor !== 'unknown' ? formFactorLabel(camera.form_factor) : null].filter((item): item is string => Boolean(item))
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
function formatTime(value?: string | null) { return formatDateTime(value) }
function compareCameraNames(left: Camera, right: Camera) { return left.name.localeCompare(right.name, 'zh-CN', { numeric: true, sensitivity: 'base' }) || left.id - right.id }
function ipParts(camera: Camera) { return camera.ip.split('.').map((part) => { const value = Number(part); return Number.isInteger(value) && value >= 0 && value <= 255 ? value : null }) }
function compareCameraIps(left: Camera, right: Camera) {
  const leftParts = ipParts(left)
  const rightParts = ipParts(right)
  if (leftParts.length === 4 && rightParts.length === 4 && leftParts.every((part) => part !== null) && rightParts.every((part) => part !== null)) {
    for (let index = 0; index < 4; index += 1) {
      const difference = (leftParts[index] as number) - (rightParts[index] as number)
      if (difference !== 0) return difference
    }
  } else {
    const difference = left.ip.localeCompare(right.ip, undefined, { numeric: true, sensitivity: 'base' })
    if (difference !== 0) return difference
  }
  return left.rtsp_port - right.rtsp_port || compareCameraNames(left, right)
}
function statusRank(camera: Camera) {
  const state = health(camera)
  if (state === 'offline') return 0
  if (state === 'unknown') return 1
  if (state === 'online') return 2
  return 3
}
function attentionRank(camera: Camera) {
  const state = health(camera)
  if (state === 'offline') return 0
  if (state === 'unknown') return 1
  if (camera.schedule_state === 'error' || camera.schedule_state === 'probe_required' || camera.recorder_state === 'RECONNECTING') return 2
  if (camera.recorder_state === 'RECORDING') return 3
  if (state === 'online') return 4
  return 5
}
function compareCameras(left: Camera, right: Camera) {
  if (sortKey.value === 'name') return compareCameraNames(left, right)
  if (sortKey.value === 'ip') return compareCameraIps(left, right)
  if (sortKey.value === 'status') return statusRank(left) - statusRank(right) || Number(right.recorder_state === 'RECORDING') - Number(left.recorder_state === 'RECORDING') || compareCameraNames(left, right)
  return attentionRank(left) - attentionRank(right) || compareCameraNames(left, right)
}
function inferSubstreamPath(mainPath: string) {
  if (mainPath.includes('/main')) { const index = mainPath.lastIndexOf('/main'); return `${mainPath.slice(0, index)}/sub${mainPath.slice(index + 5)}` }
  if (mainPath.endsWith('main')) return `${mainPath.slice(0, -4)}sub`
  return null
}
function preferredPreviewSource(camera: Camera): PreviewSource { return camera.sub_rtsp_path?.trim() || inferSubstreamPath(camera.rtsp_path) ? 'sub' : 'main' }
function preparePreview(camera: Camera) {
  previewPlaying.value = false
  previewSource.value = preferredPreviewSource(camera)
  previewFallbackUsed.value = false
  previewFailed.value = false
  previewNonce.value = Date.now()
}
function startPreview() {
  if (!selectedCamera.value?.enabled) return
  previewSource.value = preferredPreviewSource(selectedCamera.value)
  previewFallbackUsed.value = false
  previewFailed.value = false
  previewNonce.value = Date.now()
  previewPlaying.value = true
}
function stopPreview() { previewPlaying.value = false; previewFailed.value = false; previewFallbackUsed.value = false }
function refreshPreview() {
  if (!selectedCamera.value?.enabled) return
  previewSource.value = preferredPreviewSource(selectedCamera.value)
  previewFallbackUsed.value = false
  previewFailed.value = false
  previewNonce.value = Date.now()
  previewPlaying.value = true
}
function handlePreviewLoad() { previewFailed.value = false }
function handlePreviewError() {
  if (!selectedCamera.value || !previewPlaying.value) return
  if (previewSource.value === 'sub') {
    previewSource.value = 'main'
    previewFallbackUsed.value = true
    previewFailed.value = false
    previewNonce.value = Date.now()
    return
  }
  previewFailed.value = true
  previewPlaying.value = false
}
function deepLinkedCameraId() {
  const value = Array.isArray(route.query.camera_id) ? route.query.camera_id[0] : route.query.camera_id
  const cameraId = Number(value || 0)
  return Number.isInteger(cameraId) && cameraId > 0 ? cameraId : null
}
function writeCameraDeepLink(cameraId: number | null, mode: HistoryMode) {
  const nextQuery = { ...route.query }
  if (cameraId === null) delete nextQuery.camera_id
  else nextQuery.camera_id = String(cameraId)
  const target = { path: '/cameras', query: nextQuery, hash: route.hash }
  if (mode === 'push') void router.push(target)
  else void router.replace(target)
}

const summary = computed(() => ({
  total: cameras.value.length,
  online: cameras.value.filter((camera) => health(camera) === 'online').length,
  issue: cameras.value.filter((camera) => camera.enabled && ['offline', 'unknown'].includes(health(camera))).length,
  recording: cameras.value.filter((camera) => isRecording(camera.id)).length,
  disabled: cameras.value.filter((camera) => health(camera) === 'disabled').length,
}))
const sortedCameras = computed(() => [...cameras.value].sort(compareCameras))
const issueCameras = computed(() => sortedCameras.value.filter(canQuickProbe))
const batchProbeLabel = computed(() => batchProbeRunning.value ? `检测中 ${batchProbeProgress.current}/${batchProbeProgress.total}` : `检测异常 ${issueCameras.value.length}`)
const filteredCameras = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return sortedCameras.value.filter((camera) => {
    const matched = !needle || [camera.name, camera.manufacturer || '', camera.model || '', camera.ip, camera.rtsp_path, camera.sub_rtsp_path || ''].some((value) => value.toLowerCase().includes(needle))
    if (!matched) return false
    if (filter.value === 'online') return health(camera) === 'online'
    if (filter.value === 'issue') return camera.enabled && ['offline', 'unknown'].includes(health(camera))
    if (filter.value === 'recording') return isRecording(camera.id)
    if (filter.value === 'disabled') return health(camera) === 'disabled'
    return true
  })
})
const selectedInFilteredCameras = computed(() => Boolean(selectedCamera.value && filteredCameras.value.some((camera) => camera.id === selectedCamera.value?.id)))
const navigationCameras = computed(() => (!selectedCamera.value || selectedInFilteredCameras.value) ? filteredCameras.value : sortedCameras.value)
const selectedNavigationIndex = computed(() => selectedCamera.value ? navigationCameras.value.findIndex((camera) => camera.id === selectedCamera.value?.id) : -1)
const previousCamera = computed<Camera | null>(() => selectedNavigationIndex.value > 0 ? navigationCameras.value[selectedNavigationIndex.value - 1] : null)
const nextCamera = computed<Camera | null>(() => selectedNavigationIndex.value >= 0 && selectedNavigationIndex.value < navigationCameras.value.length - 1 ? navigationCameras.value[selectedNavigationIndex.value + 1] : null)
const navigationScopeLabel = computed(() => !selectedInFilteredCameras.value ? '全部设备' : query.value.trim() || filter.value !== 'all' ? '当前筛选' : '全部设备')
const previewSrc = computed(() => selectedCamera.value && previewPlaying.value ? `/api/cameras/${selectedCamera.value.id}/preview.mjpeg?stream=${previewSource.value}&fps=6&width=960&_=${previewNonce.value}` : '')

function selectCamera(camera: Camera, syncUrl: HistoryMode | null) {
  const openingDifferentCamera = selectedCamera.value?.id !== camera.id
  selectedCamera.value = camera
  if (openingDifferentCamera) preparePreview(camera)
  if (!camera.enabled) previewPlaying.value = false
  mobileListVisible.value = false
  if (syncUrl && deepLinkedCameraId() !== camera.id) writeCameraDeepLink(camera.id, syncUrl)
}
function syncSelectionFromLocation(showMissing = false) {
  const cameraId = deepLinkedCameraId()
  if (cameraId !== null) {
    const camera = cameraById(cameraId)
    if (camera) { selectCamera(camera, null); return }
    if (showMissing) ElMessage.warning(`未找到摄像头 #${cameraId}`)
  }
  const firstCamera = filteredCameras.value[0] || sortedCameras.value[0]
  if (firstCamera) {
    selectCamera(firstCamera, null)
    writeCameraDeepLink(firstCamera.id, 'replace')
    return
  }
  selectedCamera.value = null
  previewPlaying.value = false
  if (cameraId !== null) writeCameraDeepLink(null, 'replace')
}

async function loadData(showLoading = true, force = true) {
  if (showLoading) localLoading.value = true
  try {
    await cameraStore.load(force)
    const selectedId = selectedCamera.value?.id || deepLinkedCameraId()
    if (selectedId) selectedCamera.value = cameraById(selectedId) || null
    syncSelectionFromLocation(showLoading)
  } catch (error) {
    if (showLoading) ElMessage.error(apiError(error, '摄像头数据加载失败'))
  } finally { if (showLoading) localLoading.value = false }
}
function resetForm() {
  editingId.value = null
  Object.assign(form, { name: '', manufacturer: '', model: '', form_factor: 'unknown', ip: '', rtsp_port: 554, username: 'admin', password: '', rtsp_path: '/ch1/main', sub_rtsp_path: '', timestamp_mode: 'reconstruct', enabled: true, auto_record: false })
}
function openCreate() { resetForm(); dialogVisible.value = true }
function openEdit(camera: Camera) {
  editingId.value = camera.id
  Object.assign(form, { name: camera.name, manufacturer: camera.manufacturer || '', model: camera.model || '', form_factor: camera.form_factor || 'unknown', ip: camera.ip, rtsp_port: camera.rtsp_port, username: camera.username, password: '', rtsp_path: camera.rtsp_path, sub_rtsp_path: camera.sub_rtsp_path || '', timestamp_mode: camera.timestamp_mode, enabled: camera.enabled, auto_record: camera.auto_record })
  dialogVisible.value = true
}
async function saveCamera() {
  if (!form.name.trim() || !form.ip.trim() || !form.rtsp_path.trim()) { ElMessage.warning('请填写摄像头名称、IP 和主码流路径'); return }
  if (editingId.value === null && !form.password) { ElMessage.warning('新增摄像头时必须填写密码'); return }
  saving.value = true
  try {
    const payload: Record<string, unknown> = { name: form.name.trim(), manufacturer: form.manufacturer.trim() || null, model: form.model.trim() || null, form_factor: form.form_factor, ip: form.ip.trim(), rtsp_port: form.rtsp_port, username: form.username.trim(), rtsp_path: form.rtsp_path.trim(), sub_rtsp_path: form.sub_rtsp_path.trim() || null, timestamp_mode: form.timestamp_mode, enabled: form.enabled, auto_record: form.auto_record }
    if (form.password) payload.password = form.password
    if (editingId.value === null) await axios.post('/api/cameras', payload)
    else await axios.put(`/api/cameras/${editingId.value}`, payload)
    ElMessage.success(editingId.value === null ? '摄像头已添加' : '摄像头配置已保存')
    dialogVisible.value = false
    resetForm()
    cameraStore.invalidate()
    await loadData(true, true)
  } catch (error) { ElMessage.error(apiError(error, '保存失败')) }
  finally { saving.value = false }
}
async function runAction(camera: Camera, action: 'probe' | 'start' | 'stop') {
  if (batchProbeRunning.value || actionCameraId.value !== null) return
  actionCameraId.value = camera.id
  try {
    if (action === 'probe') {
      const { data } = await axios.post(`/api/cameras/${camera.id}/probe`)
      const detectedFps = typeof data.fps === 'number' ? `${data.fps.toFixed(2)} FPS` : 'FPS -'
      ElMessage.success(`${camera.name}：${data.video_codec || '-'} ${data.width || '-'}×${data.height || '-'} · ${detectedFps}`)
    } else if (action === 'start') { await axios.post(`/api/cameras/${camera.id}/start`); ElMessage.success(`${camera.name} 已开始录像`) }
    else { await axios.post(`/api/cameras/${camera.id}/stop`); ElMessage.success(`${camera.name} 已停止录像`) }
    cameraStore.invalidate()
    await loadData(false, true)
  } catch (error) { ElMessage.error(apiError(error, action === 'probe' ? '连接检测失败' : '操作失败')) }
  finally { actionCameraId.value = null }
}
async function runBatchProbe() {
  if (batchProbeRunning.value || actionCameraId.value !== null) return
  const targets = [...issueCameras.value]
  if (!targets.length) { ElMessage.info('当前没有需要检测的异常设备'); return }
  batchProbeRunning.value = true
  batchProbeFailedNames.value = []
  Object.assign(batchProbeProgress, { current: 0, total: targets.length, success: 0, failed: 0 })
  try {
    for (const camera of targets) {
      actionCameraId.value = camera.id
      try { await axios.post(`/api/cameras/${camera.id}/probe`); batchProbeProgress.success += 1 }
      catch { batchProbeProgress.failed += 1; batchProbeFailedNames.value.push(camera.name) }
      finally { batchProbeProgress.current += 1 }
    }
    actionCameraId.value = null
    cameraStore.invalidate()
    await loadData(false, true)
    if (batchProbeProgress.failed === 0) ElMessage.success(`异常设备检测完成：成功 ${batchProbeProgress.success} 台`)
    else {
      const names = batchProbeFailedNames.value.slice(0, 3).join('、')
      const extra = batchProbeFailedNames.value.length > 3 ? ` 等 ${batchProbeFailedNames.value.length} 台` : ''
      ElMessage.warning(`异常设备检测完成：成功 ${batchProbeProgress.success} 台，失败 ${batchProbeProgress.failed} 台（${names}${extra}）`)
    }
  } finally { actionCameraId.value = null; batchProbeRunning.value = false }
}
async function removeCamera(camera: Camera) {
  if (batchProbeRunning.value || actionCameraId.value !== null) return
  try {
    await ElMessageBox.confirm(`确认删除“${camera.name}”？正在录像时会先停止录像。`, '删除摄像头', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await axios.delete(`/api/cameras/${camera.id}`)
    cameraStore.remove(camera.id)
    ElMessage.success('摄像头已删除')
    if (selectedCamera.value?.id === camera.id) selectedCamera.value = null
    cameraStore.invalidate()
    await loadData(false, true)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiError(error, '删除失败'))
  }
}
function openDetails(camera: Camera, syncUrl = true) {
  const openingDifferentCamera = selectedCamera.value?.id !== camera.id
  selectedCamera.value = camera
  if (openingDifferentCamera) preparePreview(camera)
  mobileListVisible.value = false
  if (syncUrl && deepLinkedCameraId() !== camera.id) writeCameraDeepLink(camera.id, 'push')
}
function switchDetails(camera: Camera | null) {
  if (!camera || batchProbeRunning.value || actionCameraId.value !== null) return
  openDetails(camera, false)
  writeCameraDeepLink(camera.id, 'replace')
}
function showCameraList() { mobileListVisible.value = true; previewPlaying.value = false }
function handleDetailKeyboard(event: KeyboardEvent) {
  if (!selectedCamera.value || mobileListVisible.value || dialogVisible.value || batchProbeRunning.value || actionCameraId.value !== null) return
  const target = event.target as HTMLElement | null
  if (target?.closest('input, textarea, select, button, [contenteditable="true"], .el-input, .el-select')) return
  if (event.key === 'ArrowLeft' && previousCamera.value) { event.preventDefault(); switchDetails(previousCamera.value) }
  else if (event.key === 'ArrowRight' && nextCamera.value) { event.preventDefault(); switchDetails(nextCamera.value) }
}

watch(() => route.query.camera_id, () => syncSelectionFromLocation(false))
watch([filter, query], () => { if (!selectedCamera.value && filteredCameras.value.length) syncSelectionFromLocation(false) })
onMounted(() => {
  loadPreferences()
  window.addEventListener('keydown', handleDetailKeyboard)
  void loadData(true, false)
  refreshTimer = window.setInterval(() => void loadData(false, true), 10000)
})
onBeforeUnmount(() => {
  previewPlaying.value = false
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
  window.removeEventListener('keydown', handleDetailKeyboard)
})
</script>

<template>
  <section class="camera-page" v-loading="loading">
    <div class="page-heading">
      <div><h1>摄像头设备</h1><p>集中查看设备身份、连接能力、实时预览与录像运行状态。</p></div>
      <div class="heading-actions"><el-button :icon="Refresh" :disabled="batchProbeRunning" @click="loadData(true, true)">刷新</el-button><el-button :disabled="batchProbeRunning" @click="emit('open-batch')">批量添加</el-button><el-button type="primary" :icon="Plus" :disabled="batchProbeRunning" @click="openCreate">添加摄像头</el-button></div>
    </div>

    <div class="camera-split-layout" :class="{ 'detail-active': Boolean(selectedCamera) && !mobileListVisible }">
      <aside class="camera-list-pane">
        <div class="summary-grid camera-summary-grid">
          <button class="summary-card" :class="{ active: filter === 'all' }" @click="setFilter('all')"><span>全部</span><strong>{{ summary.total }}</strong><small>已配置</small></button>
          <button class="summary-card online" :class="{ active: filter === 'online' }" @click="setFilter('online')"><span>在线</span><strong>{{ summary.online }}</strong><small>连接正常</small></button>
          <button class="summary-card issue" :class="{ active: filter === 'issue' }" @click="setFilter('issue')"><span>异常</span><strong>{{ summary.issue }}</strong><small>离线 / 未检测</small></button>
          <button class="summary-card recording" :class="{ active: filter === 'recording' }" @click="setFilter('recording')"><span>录像中</span><strong>{{ summary.recording }}</strong><small>当前任务</small></button>
          <button class="summary-card disabled" :class="{ active: filter === 'disabled' }" @click="setFilter('disabled')"><span>已禁用</span><strong>{{ summary.disabled }}</strong><small>主动停用</small></button>
        </div>
        <div class="toolbar camera-split-toolbar">
          <el-input v-model="query" clearable :prefix-icon="Search" placeholder="搜索名称、型号、IP" class="search-box" />
          <div class="camera-toolbar-actions"><el-select v-model="sortKey" class="camera-sort-select" aria-label="设备排序" title="设备排序" @change="savePreferences"><el-option v-for="item in sortOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select><el-button v-if="issueCameras.length || batchProbeRunning" class="batch-probe-button" :icon="Connection" :loading="batchProbeRunning" @click="runBatchProbe">{{ batchProbeLabel }}</el-button></div>
          <span class="result-count">{{ filteredCameras.length }} / {{ cameras.length }} 台</span>
        </div>
        <div v-if="filteredCameras.length" class="camera-list">
          <article v-for="camera in filteredCameras" :key="camera.id" class="camera-card" :class="{ selected: selectedCamera?.id === camera.id, 'needs-probe': canQuickProbe(camera), busy: isCameraBusy(camera.id) }" role="button" tabindex="0" :aria-label="`查看 ${camera.name} 详情`" @click="openDetails(camera)" @keydown.enter.prevent="openDetails(camera)" @keydown.space.prevent="openDetails(camera)">
            <div class="camera-card-topline"><div class="camera-icon" :class="health(camera)" :title="formFactorLabel(camera.form_factor)"><CameraDeviceGlyph :form-factor="camera.form_factor" /></div><span class="camera-card-id">#{{ camera.id }}</span></div>
            <div class="camera-copy"><div class="camera-name-row"><strong :title="camera.name">{{ camera.name }}</strong><span class="health-badge" :class="health(camera)"><i></i>{{ healthLabel(camera) }}</span><span class="record-badge" :class="{ active: isRecording(camera.id) }"><i></i>{{ runtimeLabel(camera) }}</span></div><div class="camera-identity">{{ identitySummary(camera) }}</div><div class="camera-video">{{ videoSummary(camera) }}</div><div class="camera-address">{{ camera.ip }}:{{ camera.rtsp_port }} · {{ camera.rtsp_path }}</div></div>
            <div class="camera-signals"><div><span>录像策略</span><b>{{ schedulePolicyLabel(camera) }}</b></div><div><span>计划状态</span><b>{{ scheduleStateLabel(camera) }}</b></div><div><span>子码流</span><b>{{ camera.sub_rtsp_path ? '已配置' : inferSubstreamPath(camera.rtsp_path) ? '可推测' : '未配置' }}</b></div></div>
            <div class="camera-card-footer" :class="{ 'quick-probe-footer': canQuickProbe(camera) }"><template v-if="canQuickProbe(camera)"><span>{{ health(camera) === 'offline' ? '设备离线，可重新检测连接' : '设备尚未检测连接状态' }}</span><div class="camera-card-quick-action" @click.stop><el-button size="small" plain :icon="Connection" :loading="isCameraBusy(camera.id)" @click="runAction(camera, 'probe')">连接检测</el-button></div></template><template v-else><span>点击查看设备工作区</span><b>查看详情 →</b></template></div>
          </article>
        </div>
        <div v-else class="empty-state"><VideoCamera /><strong>{{ cameras.length ? '没有符合条件的摄像头' : '还没有摄像头' }}</strong><span>{{ cameras.length ? '调整搜索词或筛选条件。' : '添加第一台 RTSP 摄像头开始录像。' }}</span><el-button v-if="!cameras.length" type="primary" :icon="Plus" @click="openCreate">添加摄像头</el-button></div>
      </aside>

      <section class="camera-detail-pane" aria-label="摄像头详情">
        <template v-if="selectedCamera">
          <header class="camera-detail-header">
            <button type="button" class="camera-detail-back" @click="showCameraList"><ArrowLeft />返回设备列表</button>
            <div class="drawer-title"><div class="drawer-title-copy"><strong>{{ selectedCamera.name }}</strong><span>{{ identitySummary(selectedCamera) }}</span></div><div class="drawer-title-states"><span class="health-badge" :class="health(selectedCamera)"><i></i>{{ healthLabel(selectedCamera) }}</span><span class="record-badge" :class="{ active: isRecording(selectedCamera.id) }"><i></i>{{ runtimeLabel(selectedCamera) }}</span></div></div>
          </header>
          <div class="camera-detail-body drawer-body drawer-body-v2">
            <nav v-if="navigationCameras.length > 1" class="drawer-device-nav" aria-label="摄像头切换"><el-button text :icon="ArrowLeft" :disabled="!previousCamera || batchProbeRunning || actionCameraId !== null" @click="switchDetails(previousCamera)">上一台</el-button><div class="drawer-device-nav-position"><strong>{{ selectedNavigationIndex + 1 }} / {{ navigationCameras.length }}</strong><span>{{ navigationScopeLabel }} · ← →</span></div><el-button text :icon="ArrowRight" :disabled="!nextCamera || batchProbeRunning || actionCameraId !== null" @click="switchDetails(nextCamera)">下一台</el-button></nav>
            <section class="device-overview"><div class="device-overview-visual" :class="health(selectedCamera)"><CameraDeviceGlyph :form-factor="selectedCamera.form_factor" /></div><div class="device-overview-main"><div class="device-overview-heading"><div><strong>{{ selectedCamera.manufacturer || '通用 RTSP 摄像头' }}</strong><span>{{ selectedCamera.model || formFactorLabel(selectedCamera.form_factor) }} · #{{ selectedCamera.id }}</span></div><span class="device-overview-type">{{ formFactorLabel(selectedCamera.form_factor) }}</span></div><dl class="device-overview-facts"><div><dt>地址</dt><dd>{{ selectedCamera.ip }}:{{ selectedCamera.rtsp_port }}</dd></div><div><dt>视频</dt><dd>{{ videoSummary(selectedCamera) }}</dd></div><div><dt>最近在线</dt><dd>{{ formatTime(selectedCamera.last_online_at) }}</dd></div></dl></div></section>
            <section class="preview-section"><div class="preview-section-heading"><div><strong>实时预览</strong><span>按需播放，打开详情不会自动拉取摄像头码流。</span></div><span v-if="previewPlaying" class="preview-live-badge"><i></i>预览中</span></div><div class="preview-panel preview-panel-v2" :class="{ idle: !previewPlaying && !previewFailed, failed: previewFailed }"><img v-if="selectedCamera.enabled && previewPlaying && !previewFailed" :key="previewNonce" class="preview-image" :src="previewSrc" :alt="`${selectedCamera.name} 实时预览`" @load="handlePreviewLoad" @error="handlePreviewError" /><div v-else-if="!selectedCamera.enabled" class="preview-empty preview-state-panel"><VideoCamera /><strong>摄像头已禁用</strong><span>启用设备后才能播放实时画面。</span></div><div v-else-if="previewFailed" class="preview-empty preview-state-panel"><VideoCamera /><strong>实时预览暂不可用</strong><span>子码流与主码流均无法打开，可先执行连接检测。</span><el-button size="small" :icon="Refresh" @click="startPreview">重新尝试</el-button></div><button v-else type="button" class="preview-play-control" @click="startPreview"><span class="preview-play-icon"><VideoPlay /></span><strong>播放实时画面</strong><small>点击后才开始拉取 {{ preferredPreviewSource(selectedCamera) === 'sub' ? '子码流' : '主码流' }}</small></button><div v-if="previewPlaying && !previewFailed" class="preview-overlay preview-overlay-v2"><div class="preview-overlay-status"><span><i :class="{ active: isRecording(selectedCamera.id) }"></i>{{ runtimeLabel(selectedCamera) }}</span><span class="preview-stream-chip" :class="{ fallback: previewFallbackUsed }">{{ previewSource === 'sub' ? '子码流' : '主码流' }}<template v-if="previewFallbackUsed"> · 已回退</template></span></div><div class="preview-overlay-actions"><button type="button" @click="refreshPreview">重新加载</button><button type="button" class="stop" @click="stopPreview">停止预览</button></div></div></div></section>
            <div class="camera-detail-extension-slot"></div>
            <section class="drawer-operation-panel drawer-operation-panel-v2"><div class="drawer-operation-copy"><strong>设备操作</strong><span>检测连接、控制录像、调整配置或进入多画面实时监控。</span></div><div class="drawer-actions drawer-actions-v2"><el-button :icon="Connection" :loading="isCameraBusy(selectedCamera.id)" :disabled="batchProbeRunning || (actionCameraId !== null && !isCameraBusy(selectedCamera.id))" @click="runAction(selectedCamera, 'probe')">连接检测</el-button><el-button v-if="!isRecording(selectedCamera.id)" type="primary" :icon="VideoPlay" :loading="isCameraBusy(selectedCamera.id)" :disabled="!selectedCamera.enabled || batchProbeRunning || (actionCameraId !== null && !isCameraBusy(selectedCamera.id))" @click="runAction(selectedCamera, 'start')">开始录像</el-button><el-button v-else type="danger" plain :icon="VideoPause" :loading="isCameraBusy(selectedCamera.id)" @click="runAction(selectedCamera, 'stop')">停止录像</el-button><el-button :icon="Edit" :disabled="batchProbeRunning || actionCameraId !== null" @click="openEdit(selectedCamera)">编辑配置</el-button><el-button :disabled="batchProbeRunning" @click="emit('open-preview')">实时监控</el-button></div></section>
            <div class="detail-columns"><section class="detail-section detail-section-v2"><div class="detail-heading"><strong>连接信息</strong></div><dl class="detail-grid detail-grid-v2"><div><dt>IP 地址</dt><dd>{{ selectedCamera.ip }}</dd></div><div><dt>RTSP 端口</dt><dd>{{ selectedCamera.rtsp_port }}</dd></div><div><dt>用户名</dt><dd>{{ selectedCamera.username || '-' }}</dd></div><div><dt>主码流</dt><dd>{{ selectedCamera.rtsp_path }}</dd></div><div class="wide"><dt>子码流</dt><dd>{{ selectedCamera.sub_rtsp_path || inferSubstreamPath(selectedCamera.rtsp_path) || '未配置' }}</dd></div></dl></section><section class="detail-section detail-section-v2"><div class="detail-heading"><strong>视频与录像</strong></div><dl class="detail-grid detail-grid-v2"><div><dt>编码</dt><dd>{{ selectedCamera.video_codec?.toUpperCase() || '-' }}</dd></div><div><dt>分辨率</dt><dd>{{ selectedCamera.width && selectedCamera.height ? `${selectedCamera.width}×${selectedCamera.height}` : '-' }}</dd></div><div><dt>帧率</dt><dd>{{ fps(selectedCamera) ? `${fps(selectedCamera)} FPS` : '-' }}</dd></div><div><dt>音频</dt><dd>{{ selectedCamera.audio_codec?.toUpperCase() || '-' }}</dd></div><div><dt>录像策略</dt><dd>{{ schedulePolicyLabel(selectedCamera) }}</dd></div><div><dt>计划状态</dt><dd>{{ scheduleStateLabel(selectedCamera) }}</dd></div></dl></section></div>
            <section class="detail-section detail-section-v2 runtime-section"><div class="detail-heading"><strong>运行状态</strong></div><dl class="detail-grid runtime-grid"><div><dt>连接状态</dt><dd>{{ healthLabel(selectedCamera) }}</dd></div><div><dt>录像状态</dt><dd>{{ runtimeLabel(selectedCamera) }}</dd></div><div><dt>最近检测</dt><dd>{{ formatTime(selectedCamera.last_probe_at) }}</dd></div><div><dt>最近在线</dt><dd>{{ formatTime(selectedCamera.last_online_at) }}</dd></div><div><dt>时间戳模式</dt><dd>{{ selectedCamera.timestamp_mode }}</dd></div><div><dt>设备类型</dt><dd>{{ formFactorLabel(selectedCamera.form_factor) }}</dd></div></dl></section>
            <section class="drawer-danger-zone"><div><strong>删除摄像头</strong><span>删除设备配置；若正在录像，会先停止当前录像任务。</span></div><el-button type="danger" plain :icon="Delete" :disabled="batchProbeRunning || actionCameraId !== null" @click="removeCamera(selectedCamera)">删除</el-button></section>
          </div>
        </template>
        <div v-else class="camera-detail-empty empty-state"><VideoCamera /><strong>还没有可显示的摄像头</strong><span>添加第一台摄像头后，这里会成为持续可见的设备工作区。</span><el-button type="primary" :icon="Plus" @click="openCreate">添加摄像头</el-button></div>
      </section>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '添加 RTSP 摄像头' : '编辑摄像头'" width="680px" destroy-on-close>
      <el-form label-width="88px" class="camera-form" @submit.prevent="saveCamera">
        <div class="form-grid">
          <el-form-item label="名称" class="wide"><el-input v-model="form.name" placeholder="例如：门口摄像头" /></el-form-item>
          <el-form-item label="厂商"><el-input v-model="form.manufacturer" placeholder="例如 Hikvision" /></el-form-item>
          <el-form-item label="型号"><el-input v-model="form.model" placeholder="例如 DS-2CD..." /></el-form-item>
          <el-form-item label="外形" class="wide"><el-select v-model="form.form_factor" style="width: 100%"><el-option v-for="item in formFactorOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <el-form-item label="IP 地址"><el-input v-model="form.ip" placeholder="192.168.1.101" /></el-form-item>
          <el-form-item label="RTSP 端口"><el-input-number v-model="form.rtsp_port" :min="1" :max="65535" controls-position="right" /></el-form-item>
          <el-form-item label="用户名"><el-input v-model="form.username" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password :placeholder="editingId === null ? '必填' : '留空保持原密码'" /></el-form-item>
          <el-form-item label="主码流" class="wide"><el-input v-model="form.rtsp_path" placeholder="/ch1/main" /></el-form-item>
          <el-form-item label="子码流" class="wide"><el-input v-model="form.sub_rtsp_path" placeholder="可选，例如 /ch1/sub" /></el-form-item>
          <el-form-item label="时间戳"><el-select v-model="form.timestamp_mode" style="width: 100%"><el-option label="重建时间戳（推荐）" value="reconstruct" /><el-option label="使用原始时间戳" value="native" /><el-option label="使用系统时间" value="wallclock" /></el-select></el-form-item>
          <el-form-item label="自动录像"><el-switch v-model="form.auto_record" /></el-form-item>
          <el-form-item label="启用设备"><el-switch v-model="form.enabled" /></el-form-item>
        </div>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveCamera">保存</el-button></template>
    </el-dialog>
  </section>
</template>
